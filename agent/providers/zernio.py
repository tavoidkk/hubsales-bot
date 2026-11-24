"""Adaptador para Zernio (WhatsApp Cloud API gestionada).

Solo texto libre, dentro de la ventana de 24 horas que abre el mensaje del
prospecto. No hay plantillas, adjuntos ni envíos proactivos: el bot es reactivo.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

import httpx
from fastapi import Request

from agent.providers.base import MensajeEntrante, ProveedorWhatsApp

logger = logging.getLogger("agentkit")

BASE_URL_POR_DEFECTO = "https://zernio.com/api/v1"


class ProveedorZernio(ProveedorWhatsApp):
    def __init__(self):
        self.api_key = os.getenv("ZERNIO_API_KEY", "")
        self.webhook_secret = os.getenv("ZERNIO_WEBHOOK_SECRET", "")
        self.account_id = os.getenv("ZERNIO_ACCOUNT_ID", "")
        self.base_url = (os.getenv("ZERNIO_BASE_URL") or BASE_URL_POR_DEFECTO).rstrip("/")

        if not self.api_key:
            logger.warning("ZERNIO_API_KEY no está configurada: el bot no va a poder responder")
        if not self.webhook_secret:
            logger.warning(
                "ZERNIO_WEBHOOK_SECRET no está configurado: los webhooks NO se verifican. "
                "Sirve para probar, pero no lo dejes así en producción."
            )

    # ── Entrada ────────────────────────────────────────────────

    async def verificar_firma(self, request: Request) -> bool:
        """Compara X-Zernio-Signature con el HMAC-SHA256 del cuerpo crudo."""
        if not self.webhook_secret:
            return True

        firma_recibida = request.headers.get("X-Zernio-Signature") or request.headers.get(
            "X-Late-Signature"
        )
        if not firma_recibida:
            logger.warning("Webhook sin firma X-Zernio-Signature: rechazado")
            return False

        cuerpo = await request.body()
        firma_esperada = hmac.new(
            self.webhook_secret.encode("utf-8"), cuerpo, hashlib.sha256
        ).hexdigest()

        # compare_digest sobre str exige ASCII puro; un header raro podría tirar
        # TypeError y convertir esto en un 500 (el proveedor reintentaría).
        try:
            iguales = hmac.compare_digest(firma_esperada, firma_recibida)
        except TypeError:
            logger.warning("La firma del webhook trae caracteres inválidos: rechazado")
            return False

        if not iguales:
            logger.warning("Firma de webhook inválida: rechazado")
            return False
        return True

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Normaliza el evento message.received de Zernio."""
        payload = await request.json()

        evento = payload.get("event")
        if evento != "message.received":
            logger.debug("Evento ignorado: %s", evento)
            return []

        mensaje = payload.get("message") or {}
        if mensaje.get("platform") != "whatsapp":
            return []

        # Si otra app tiene el control de la conversación, no respondemos.
        if (payload.get("metadata") or {}).get("standby"):
            logger.info("Mensaje en standby (otra app responde): se ignora")
            return []

        remitente = mensaje.get("sender") or {}
        telefono = (remitente.get("phoneNumber") or "").lstrip("+")
        if not telefono:
            telefono = remitente.get("businessScopedUserId") or remitente.get("id") or ""

        cuenta = payload.get("account") or {}
        account_id = cuenta.get("accountId") or cuenta.get("id") or ""

        # Segunda barrera: aunque el webhook de Zernio viniera sin filtro (o se
        # creara uno nuevo por error), un mensaje del número de Toyota no debe
        # entrar en este bot. El filtro principal sigue siendo accountIds.
        if self.account_id and account_id and account_id != self.account_id:
            logger.info(
                "Mensaje de otra cuenta de WhatsApp (%s), esperaba %s: se ignora",
                account_id,
                self.account_id,
            )
            return []

        return [
            MensajeEntrante(
                telefono=telefono,
                texto=mensaje.get("text") or "",
                mensaje_id=mensaje.get("platformMessageId") or mensaje.get("id") or "",
                es_propio=mensaje.get("direction") != "incoming",
                contexto={
                    "evento_id": payload.get("id")
                    or request.headers.get("X-Zernio-Event-Id")
                    or "",
                    "conversation_id": mensaje.get("conversationId", ""),
                    "account_id": account_id,
                },
            )
        ]

    # ── Salida ─────────────────────────────────────────────────

    async def enviar_mensaje(
        self, telefono: str, mensaje: str, contexto: dict | None = None
    ) -> bool:
        contexto = contexto or {}
        conversation_id = contexto.get("conversation_id")
        account_id = contexto.get("account_id") or self.account_id

        if not self.api_key:
            logger.error("No se puede enviar: falta ZERNIO_API_KEY")
            return False
        if not conversation_id or not account_id:
            logger.error("No se puede enviar: falta conversation_id o account_id")
            return False

        ok, detalle = await self._post(
            f"{self.base_url}/inbox/conversations/{conversation_id}/messages",
            {"accountId": account_id, "message": mensaje},
            evento_id=contexto.get("evento_id"),
        )
        if not ok:
            logger.error("Zernio rechazó el envío: %s", detalle)
        return ok

    async def _post(
        self, url: str, payload: dict, evento_id: str | None = None
    ) -> tuple[bool, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if evento_id:
            headers["Idempotency-Key"] = f"hubsales-{evento_id}"

        try:
            async with httpx.AsyncClient(timeout=30.0) as cliente:
                r = await cliente.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            return False, f"error de red: {exc}"

        if r.status_code in (200, 201):
            return True, "ok"

        detalle = r.text[:500]
        try:
            cuerpo = r.json()
            detalle = (
                f"{cuerpo.get('error')} "
                f"(type={cuerpo.get('type')}, code={cuerpo.get('code')})"
            )
        except ValueError:
            pass
        return False, f"[{r.status_code}] {detalle}"

    # ── Diagnóstico ────────────────────────────────────────────

    async def verificar_conexion(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "Falta ZERNIO_API_KEY"

        try:
            async with httpx.AsyncClient(timeout=15.0) as cliente:
                r = await cliente.get(
                    f"{self.base_url}/phone-numbers",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except httpx.HTTPError as exc:
            return False, f"No se pudo contactar a Zernio: {exc}"

        if r.status_code != 200:
            return False, f"Zernio respondió {r.status_code}: {r.text[:200]}"

        datos = r.json()
        numeros = datos.get("numbers") or []
        sandbox = datos.get("sandbox") or {}
        if numeros:
            principal = numeros[0].get("phoneNumber") or "?"
            return True, f"Número {principal} conectado ({len(numeros)} en la cuenta)"
        if sandbox.get("phoneNumber"):
            return True, (
                f"Solo sandbox {sandbox['phoneNumber']} — sirve para pruebas, "
                "no para clientes reales"
            )
        return False, "La cuenta no tiene números conectados ni sandbox disponible"
