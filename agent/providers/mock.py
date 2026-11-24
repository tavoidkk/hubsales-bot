"""Proveedor mock: captura mensajes sin enviar nada por red."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import Request

from agent.providers.base import MensajeEntrante, ProveedorWhatsApp

ENVIADOS: List[Dict[str, Any]] = []


class ProveedorMock(ProveedorWhatsApp):
    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            return []
        if not isinstance(payload, dict):
            return []

        texto = str(payload.get("texto") or "")
        if not texto:
            return []
        evento = str(payload.get("mensaje_id") or "mock-evento")
        return [
            MensajeEntrante(
                telefono=str(payload.get("telefono") or "mock"),
                texto=texto,
                mensaje_id=evento,
                es_propio=False,
                contexto={"evento_id": evento},
            )
        ]

    async def enviar_mensaje(
        self, telefono: str, mensaje: str, contexto: dict | None = None
    ) -> bool:
        ENVIADOS.append(
            {"telefono": telefono, "mensaje": mensaje, "contexto": contexto or {}}
        )
        return True

    async def verificar_conexion(self) -> tuple[bool, str]:
        return True, "Proveedor mock: no se envía nada por red"


def obtener_enviados() -> List[Dict[str, Any]]:
    return list(ENVIADOS)


def limpiar_enviados() -> None:
    ENVIADOS.clear()
