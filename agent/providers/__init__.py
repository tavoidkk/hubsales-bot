"""Factory de proveedores. `mock` no envía nada por red (tests y chat local)."""

import os

from agent.providers.base import MensajeEntrante, ProveedorWhatsApp

PROVEEDORES_SOPORTADOS = ("zernio", "mock")


def obtener_proveedor() -> ProveedorWhatsApp:
    proveedor = os.getenv("WHATSAPP_PROVIDER", "").strip().lower()

    if not proveedor:
        raise ValueError(
            "WHATSAPP_PROVIDER no está configurado en el .env. "
            f"Valores válidos: {' | '.join(PROVEEDORES_SOPORTADOS)}"
        )
    if proveedor == "zernio":
        from agent.providers.zernio import ProveedorZernio

        return ProveedorZernio()
    if proveedor == "mock":
        from agent.providers.mock import ProveedorMock

        return ProveedorMock()

    raise ValueError(
        f"Proveedor no soportado: '{proveedor}'. "
        f"Valores válidos: {' | '.join(PROVEEDORES_SOPORTADOS)}"
    )


__all__ = [
    "MensajeEntrante",
    "ProveedorWhatsApp",
    "PROVEEDORES_SOPORTADOS",
    "obtener_proveedor",
]
