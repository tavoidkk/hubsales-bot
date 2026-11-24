#!/usr/bin/env python3
"""zernio_setup.py — configurar la cuenta de Zernio sin tocar la API a mano.

Comandos:

    python scripts/zernio_setup.py estado
        Muestra la cuenta: sandbox, números propios y el accountId del .env.

    python scripts/zernio_setup.py activar +13465551234
        Manda la plantilla de verificación al teléfono de prueba. Hay que
        responder ese WhatsApp para activar la sesión (7 días, 50 mensajes/día).

    python scripts/zernio_setup.py sesiones
    python scripts/zernio_setup.py revocar <session_id>

    python scripts/zernio_setup.py webhooks
        Lista TODOS los webhooks de la cuenta. OJO: acá también aparece el del
        bot de Don McGill Toyota. NO lo borrar ni modificar.

    python scripts/zernio_setup.py webhook https://mi-bot.coolify.app
        Crea el webhook de ESTE bot apuntando a <url>/webhook, con el secreto
        del .env y accountIds=[ZERNIO_ACCOUNT_ID]. Así este webhook NO recibe
        los mensajes del número de Don McGill Toyota. Usar secreto distinto.

    python scripts/zernio_setup.py webhook-test <webhook_id>
        Manda un evento de prueba para confirmar que el servidor responde 200.

Este bot es reactivo: no usa plantillas propias ni envía mensajes primero.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# La consola de Windows usa cp1252 por defecto y rompe con acentos.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

try:
    import httpx
    from dotenv import load_dotenv
except ModuleNotFoundError as exc:  # pragma: no cover
    print(f"Falta el paquete '{exc.name}'.")
    print("Instalá las dependencias primero: pip install -r requirements.txt")
    raise SystemExit(1)

load_dotenv(RAIZ / ".env")

BASE_URL = (os.getenv("ZERNIO_BASE_URL") or "https://api.zernio.com/v1").rstrip("/")
API_KEY = (os.getenv("ZERNIO_API_KEY") or "").strip()
WEBHOOK_SECRET = (os.getenv("ZERNIO_WEBHOOK_SECRET") or "").strip()
# Zernio permite limitar un webhook a ciertos números (accounts). Sin esto, un
# webhook nuevo recibiría también los mensajes del bot de Toyota.
ACCOUNT_ID = (os.getenv("ZERNIO_ACCOUNT_ID") or "").strip()
EVENTOS = ["message.received"]
NOMBRE_WEBHOOK = "HubSales Group — Reclutamiento"


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


async def _pedir(metodo: str, ruta: str, payload: dict | None = None) -> tuple[int, dict]:
    async with httpx.AsyncClient(timeout=30.0) as cliente:
        r = await cliente.request(metodo, f"{BASE_URL}{ruta}", headers=_headers(), json=payload)
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = {"raw": r.text[:400]}
    return r.status_code, cuerpo


def _exigir_key() -> bool:
    if API_KEY:
        return True
    print("Falta ZERNIO_API_KEY en el .env.")
    print("  Zernio -> Settings -> API Keys -> Create key (empieza con sk_)")
    return False


def _mostrar_error(codigo: int, cuerpo: dict) -> None:
    print(f"Zernio respondió {codigo}:")
    print(json.dumps(cuerpo, indent=2, ensure_ascii=False)[:1200])


# ── Cuenta ──────────────────────────────────────────────────────


async def estado() -> int:
    codigo, cuerpo = await _pedir("GET", "/phone-numbers")
    if codigo != 200:
        _mostrar_error(codigo, cuerpo)
        return 1

    sandbox = cuerpo.get("sandbox") or {}
    numeros = cuerpo.get("numbers") or []
    print("Cuenta de Zernio (misma cuenta que el bot de Toyota)\n")

    for numero in numeros:
        cuenta = numero.get("account")
        account_id = (
            numero.get("accountId")
            or numero.get("account_id")
            or (cuenta.get("accountId") if isinstance(cuenta, dict) else None)
            or numero.get("id")
            or "?"
        )
        print(
            f"  Número: {numero.get('phoneNumber') or numero.get('display_phone_number')}  "
            f"({numero.get('country') or '?'}, {numero.get('numberType') or numero.get('type') or '?'})"
        )
        print(f"    accountId: {account_id}")
    print(f"  Total de números: {len(numeros)}")

    # OJO: el accountId que usa el webhook NO es el _id del número. Es el _id
    # de la cuenta de WhatsApp que devuelve /accounts. Se listan para poder
    # copiar el correcto sin adivinar.
    codigo, cuentas = await _pedir("GET", "/accounts")
    if codigo == 200:
        print("\n  Cuentas conectadas (usar el _id de la de whatsapp):")
        for cuenta in cuentas.get("accounts") or []:
            if cuenta.get("platform") != "whatsapp":
                continue
            marca = " ← coincide con el .env" if cuenta.get("_id") == ACCOUNT_ID else ""
            print(f"    {cuenta.get('_id')}  {cuenta.get('displayName') or cuenta.get('name') or ''}{marca}")
    else:
        _mostrar_error(codigo, cuentas)

    print(f"\n  ZERNIO_ACCOUNT_ID en .env: {ACCOUNT_ID or '(vacío)'}")

    if sandbox.get("phoneNumber"):
        print(f"  Sandbox: {sandbox['phoneNumber']}  (solo pruebas)")
        print(f"  accountId sandbox: {sandbox.get('accountId')}")
    else:
        print("  Sandbox: no disponible")

    print(
        "\nBuscá el accountId del número NUEVO que vas a usar para este bot "
        "y pegalo en ZERNIO_ACCOUNT_ID del .env."
    )
    return 0


# ── Sandbox ─────────────────────────────────────────────────────


async def activar(telefono: str) -> int:
    codigo, cuerpo = await _pedir("POST", "/whatsapp/sandbox/sessions", {"phone": telefono})
    if codigo != 200:
        _mostrar_error(codigo, cuerpo)
        if codigo == 400:
            print("\nSi dice que ya hay un teléfono activo, revocalo primero:")
            print("  python scripts/zernio_setup.py sesiones")
            print("  python scripts/zernio_setup.py revocar <session_id>")
        return 1

    sesion = cuerpo.get("session") or {}
    print(f"Sesión creada para {sesion.get('phoneE164') or telefono}")
    print(f"  Estado: {sesion.get('status')}")
    print(f"  Vence:  {sesion.get('expiresAt')}")
    print("\nAbrí WhatsApp en ese teléfono y respondé el mensaje que llegó.")
    print("Cualquier respuesta activa la sesión. Después corré:")
    print("  python scripts/zernio_setup.py sesiones")
    return 0


async def sesiones() -> int:
    codigo, cuerpo = await _pedir("GET", "/whatsapp/sandbox/sessions")
    if codigo != 200:
        _mostrar_error(codigo, cuerpo)
        return 1

    lista = cuerpo.get("sessions") or []
    if not lista:
        print("No hay sesiones de sandbox. Creá una con:")
        print("  python scripts/zernio_setup.py activar +13465551234")
        return 0

    for sesion in lista:
        print(
            f"{sesion.get('status'):9} {sesion.get('phoneE164')}  "
            f"vence {sesion.get('expiresAt')}  id={sesion.get('id')}"
        )
    return 0


async def revocar(session_id: str) -> int:
    codigo, cuerpo = await _pedir("DELETE", f"/whatsapp/sandbox/sessions/{session_id}")
    if codigo != 200:
        _mostrar_error(codigo, cuerpo)
        return 1
    print(f"Sesión {session_id} revocada. Ya podés activar otro teléfono.")
    return 0


# ── Webhooks ────────────────────────────────────────────────────


async def webhooks() -> int:
    codigo, cuerpo = await _pedir("GET", "/webhooks/settings")
    if codigo != 200:
        _mostrar_error(codigo, cuerpo)
        return 1

    lista = cuerpo.get("webhooks") or []
    if not lista:
        print("No hay webhooks configurados.")
        return 0

    print("Webhooks de la cuenta (NO toques el de Don McGill Toyota):\n")
    for webhook in lista:
        activo = "activo" if webhook.get("isActive", True) else "PAUSADO"
        print(f"{webhook.get('_id') or webhook.get('webhookId')}")
        print(f"  nombre:  {webhook.get('name')}  ({activo})")
        print(f"  url:     {webhook.get('url')}")
        print(f"  eventos: {', '.join(webhook.get('events') or [])}")
        cuentas = webhook.get("accountIds") or []
        perfiles = webhook.get("profileIds") or []
        # Un webhook sin filtros ve TODOS los números de la cuenta.
        filtro = (
            f"cuentas: {', '.join(cuentas)}"
            if cuentas
            else f"perfiles: {', '.join(perfiles)}" if perfiles else "SIN FILTRO (ve todos los números)"
        )
        print(f"  filtro:  {filtro}")
    return 0


async def crear_webhook(url: str) -> int:
    if not WEBHOOK_SECRET:
        print("Falta ZERNIO_WEBHOOK_SECRET en el .env.")
        print("Elegí cualquier texto largo y aleatorio y ponelo ahí (distinto del de Toyota).")
        return 1
    if not ACCOUNT_ID:
        print("Falta ZERNIO_ACCOUNT_ID en el .env.")
        print("Sin ese id el webhook recibiría los mensajes de TODOS los números,")
        print("incluido el de Don McGill Toyota. Pegá el accountId del número nuevo.")
        return 1

    url = url.rstrip("/")
    if not url.endswith("/webhook"):
        url = f"{url}/webhook"

    payload = {
        "name": NOMBRE_WEBHOOK,
        "url": url,
        "secret": WEBHOOK_SECRET,
        "events": EVENTOS,
        # Clave para compartir cuenta sin cruzar bots: solo este número llega acá.
        "accountIds": [ACCOUNT_ID],
        "isActive": True,
    }

    codigo, cuerpo = await _pedir("POST", "/webhooks/settings", payload)
    if codigo != 200:
        _mostrar_error(codigo, cuerpo)
        return 1

    webhook = cuerpo.get("webhook") or {}
    webhook_id = webhook.get("_id") or webhook.get("webhookId")
    print(f"Webhook creado: {url}")
    print(f"  id:      {webhook_id}")
    print("\nProbá que el bot responde:")
    print(f"  python scripts/zernio_setup.py webhook-test {webhook_id}")
    return 0


async def probar_webhook(webhook_id: str) -> int:
    codigo, cuerpo = await _pedir("POST", "/webhooks/test", {"webhookId": webhook_id})
    if codigo != 200:
        _mostrar_error(codigo, cuerpo)
        return 1
    print(cuerpo.get("message") or "Evento de prueba enviado.")
    print("Revisá el log del servidor: debería registrar la petición.")
    return 0


# ── CLI ──────────────────────────────────────────────────────────


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Configuración de Zernio para el bot de HubSales")
    sub = parser.add_subparsers(dest="comando")

    sub.add_parser("estado", help="ver números, sandbox y accountId")
    p_activar = sub.add_parser("activar", help="activar un teléfono de prueba")
    p_activar.add_argument("telefono", help="teléfono con código de país, ej. +13465551234")
    sub.add_parser("sesiones", help="listar sesiones de sandbox")
    p_revocar = sub.add_parser("revocar", help="liberar un teléfono de prueba")
    p_revocar.add_argument("session_id")
    sub.add_parser("webhooks", help="listar webhooks de la cuenta")
    p_webhook = sub.add_parser("webhook", help="crear el webhook que apunta a este bot")
    p_webhook.add_argument("url", help="URL pública, ej. https://hubsales.up.railway.app")
    p_test = sub.add_parser("webhook-test", help="mandar un evento de prueba")
    p_test.add_argument("webhook_id")

    args = parser.parse_args(argv)
    comando = args.comando or "estado"

    if not _exigir_key():
        return 1

    if comando == "estado":
        return await estado()
    if comando == "activar":
        return await activar(args.telefono)
    if comando == "sesiones":
        return await sesiones()
    if comando == "revocar":
        return await revocar(args.session_id)
    if comando == "webhooks":
        return await webhooks()
    if comando == "webhook":
        return await crear_webhook(args.url)
    if comando == "webhook-test":
        return await probar_webhook(args.webhook_id)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
