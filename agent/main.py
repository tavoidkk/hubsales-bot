"""main.py — servidor FastAPI + webhook de WhatsApp.

Responde 200 al proveedor de inmediato, procesa en segundo plano, deduplica por
id de evento y toma un candado por teléfono. El flujo vive en agent/flow.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections import defaultdict
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from agent.brain import obtener_mensaje_error
from agent.config import cargar_prompts, identidad, link_formulario
from agent.flow import procesar_turno
from agent.memory import (
    guardar_mensaje,
    inicializar_db,
    liberar_evento,
    limpiar_eventos_viejos,
    marcar_evento_procesado,
    obtener_historial,
)
from agent.providers import obtener_proveedor
from agent.providers.base import MensajeEntrante

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# La consola de Windows usa cp1252 y rompe con acentos.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agentkit")
logger.setLevel(logging.DEBUG if ENVIRONMENT == "development" else logging.INFO)

PORT = int(os.getenv("PORT", "8000"))

# Un candado por teléfono: "hola" y la pregunta real no se procesan en paralelo.
_candados: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

proveedor = None
error_configuracion: str | None = None
try:
    proveedor = obtener_proveedor()
except Exception as exc:  # noqa: BLE001
    error_configuracion = str(exc)

estado_proveedor: dict = {"ok": None, "detalle": "sin verificar"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await inicializar_db()
    await limpiar_eventos_viejos()
    logger.info("Base de datos lista")

    global estado_proveedor
    if proveedor is not None:
        logger.info("Proveedor de WhatsApp: %s", proveedor.__class__.__name__)
        ok, detalle = await proveedor.verificar_conexion()
        estado_proveedor = {"ok": ok, "detalle": detalle}
        logger.info("Conexión con el proveedor: %s — %s", "OK" if ok else "ERROR", detalle)
    else:
        logger.error("Proveedor NO configurado: %s", error_configuracion)
    logger.info("Bot de HubSales Group escuchando en el puerto %s", PORT)

    yield


app = FastAPI(
    title="HubSales Group — Reclutamiento",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def health_check():
    if error_configuracion:
        return {"status": "error", "service": "hubsales-reclutamiento", "detalle": error_configuracion}

    nombre, rol, _empresa = identidad()
    return {
        "status": "ok" if estado_proveedor["ok"] else "degradado",
        "service": "hubsales-reclutamiento",
        "commit": (os.getenv("SOURCE_COMMIT") or "")[:7] or None,
        "proveedor": proveedor.__class__.__name__ if proveedor else None,
        "conexion": estado_proveedor,
        "bot": f"{nombre} — {rol}",
        "idioma": "es",
        # No se expone el enlace: solo si está cargado.
        "link_formulario_configurado": bool(link_formulario()),
    }


@app.get("/health")
async def health_check_alias():
    return await health_check()


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    if proveedor is None:
        raise HTTPException(
            status_code=503,
            detail=error_configuracion or "Proveedor no configurado",
        )

    respuesta = await proveedor.validar_webhook(request)
    if respuesta is not None:
        return PlainTextResponse(respuesta)

    if request.query_params.get("hub.mode") == "subscribe":
        raise HTTPException(status_code=403, detail="Verify token incorrecto")

    return {"status": "ok"}


@app.post("/webhook")
async def webhook_handler(request: Request, tareas: BackgroundTasks):
    if proveedor is None:
        raise HTTPException(
            status_code=503,
            detail=error_configuracion or "Proveedor no configurado",
        )

    if not await proveedor.verificar_firma(request):
        raise HTTPException(status_code=401, detail="Firma del webhook inválida")

    try:
        mensajes = await proveedor.parsear_webhook(request)
    except Exception as exc:  # noqa: BLE001
        logger.error("No se pudo leer el webhook: %s", exc)
        return {"status": "ignorado"}

    encolados = 0
    for msg in mensajes:
        if msg.es_propio or not msg.texto.strip():
            continue

        evento_id = msg.contexto.get("evento_id") or msg.mensaje_id
        if evento_id and not await marcar_evento_procesado(evento_id):
            logger.info("Evento repetido, se ignora: %s", evento_id)
            continue

        logger.info("Mensaje de %s: %s", msg.telefono, msg.texto)
        tareas.add_task(procesar_mensaje, msg)
        encolados += 1

    return {"status": "ok", "encolados": encolados}


async def procesar_mensaje(msg: MensajeEntrante):
    evento_id = msg.contexto.get("evento_id") or msg.mensaje_id

    async with _candados[msg.telefono]:
        try:
            historial = await obtener_historial(msg.telefono)
            respuesta, _estado, es_respuesta_real = await procesar_turno(
                msg.telefono, msg.texto, historial
            )

            if not respuesta.strip():
                # Nada que enviar (por ejemplo, un "gracias" final). Igual se
                # recuerda el mensaje para que la IA no pida lo mismo dos veces.
                await guardar_mensaje(msg.telefono, "user", msg.texto)
                await liberar_evento(evento_id)
                return

            enviado = await proveedor.enviar_mensaje(
                msg.telefono, respuesta, msg.contexto
            )
            if not enviado:
                # Si el envío falló, liberamos el evento para que el reintento
                # del proveedor SÍ se procese y el prospecto no quede sin respuesta.
                logger.error(
                    "No se pudo enviar la respuesta a %s; se libera el evento",
                    msg.telefono,
                )
                await liberar_evento(evento_id)
                return

            # Toda la conversación entra al historial: la IA necesita ver también
            # las respuestas de contexto y de "fuera de línea" para no repetirse.
            await guardar_mensaje(msg.telefono, "user", msg.texto)
            await guardar_mensaje(msg.telefono, "assistant", respuesta)

            logger.info("Respuesta enviada a %s: %s", msg.telefono, respuesta)

        except Exception as exc:  # noqa: BLE001
            logger.exception("Error procesando el mensaje de %s: %s", msg.telefono, exc)
            await liberar_evento(evento_id)
            try:
                await proveedor.enviar_mensaje(
                    msg.telefono, obtener_mensaje_error(), msg.contexto
                )
            except Exception:  # noqa: BLE001
                logger.error("Tampoco se pudo avisar del error")
