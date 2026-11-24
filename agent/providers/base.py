"""Interfaz común para proveedores de WhatsApp."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from fastapi import Request


@dataclass
class MensajeEntrante:
    """Mensaje normalizado: el mismo formato sin importar el proveedor."""

    telefono: str
    texto: str
    mensaje_id: str
    es_propio: bool
    contexto: dict = field(default_factory=dict)


class ProveedorWhatsApp(ABC):
    @abstractmethod
    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Extrae y normaliza los mensajes del payload del webhook."""
        ...

    @abstractmethod
    async def enviar_mensaje(
        self, telefono: str, mensaje: str, contexto: dict | None = None
    ) -> bool:
        """Envía un mensaje de texto. Retorna True si salió bien."""
        ...

    async def verificar_firma(self, request: Request) -> bool:
        """Confirma que el webhook viene del proveedor. Por defecto acepta."""
        return True

    async def validar_webhook(self, request: Request) -> str | None:
        """Verificación GET del webhook (la usa Meta, no Zernio)."""
        return None

    async def verificar_conexion(self) -> tuple[bool, str]:
        """Chequea credenciales. Retorna (ok, mensaje legible)."""
        return True, "Este proveedor no expone un chequeo de conexión"
