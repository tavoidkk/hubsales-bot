"""memory.py — historial, estado del prospecto y deduplicación de webhooks.

SQLite en local y PostgreSQL en producción, con SQLAlchemy async. El estado del
prospecto es la autoridad del flujo: el texto del visitante nunca decide por sí
solo qué se responde.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, declarative_base, mapped_column

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

Base = declarative_base()
_DB_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./hubsales.db")
_KWARGS: dict = {"future": True}
if os.environ.get("ENVIRONMENT") == "test":
    from sqlalchemy.pool import NullPool

    _KWARGS["poolclass"] = NullPool

# Railway/Coolify entregan URLs "postgresql://" o "postgres://". El modo async
# necesita el driver explícito.
if _DB_URL.startswith("postgresql://"):
    _DB_URL = _DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _DB_URL.startswith("postgres://"):
    _DB_URL = _DB_URL.replace("postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(_DB_URL, **_KWARGS)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    created_at: Mapped[str] = mapped_column(default=_ahora)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(nullable=False, index=True)
    role: Mapped[str] = mapped_column(nullable=False)
    content: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[str] = mapped_column(default=_ahora)


class EstadoProspecto(Base):
    """Estado del flujo por teléfono. Es la fuente de verdad."""

    __tablename__ = "estado_prospecto"

    phone: Mapped[str] = mapped_column(primary_key=True)
    state_json: Mapped[str] = mapped_column(default="{}")
    updated_at: Mapped[str] = mapped_column(default=_ahora)


class EventoProcesado(Base):
    """Eventos de webhook ya atendidos (entrega al menos una vez)."""

    __tablename__ = "eventos_procesados"

    evento_id: Mapped[str] = mapped_column(primary_key=True)
    created_at: Mapped[str] = mapped_column(default=_ahora, index=True)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


inicializar_db = init_db


async def save_message(phone: str, role: str, content: str) -> None:
    async with AsyncSessionLocal() as session:
        conv = await session.execute(select(Conversation).where(Conversation.phone == phone))
        conversacion = conv.scalar_one_or_none()
        if conversacion is None:
            conversacion = Conversation(phone=phone)
            session.add(conversacion)
            await session.flush()
        session.add(
            ConversationMessage(conversation_id=conversacion.id, role=role, content=content)
        )
        await session.commit()


guardar_mensaje = save_message


async def get_history(phone: str, limit: int = 30) -> List[Dict[str, str]]:
    """Historial reciente en orden cronológico."""
    async with AsyncSessionLocal() as session:
        conv = await session.execute(select(Conversation).where(Conversation.phone == phone))
        conversacion = conv.scalar_one_or_none()
        if conversacion is None:
            return []
        msgs = await session.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversacion.id)
            .order_by(ConversationMessage.id.desc())
            .limit(limit)
        )
        filas = list(msgs.scalars().all())
        filas.reverse()
        return [{"role": m.role, "content": m.content} for m in filas if m.content]


obtener_historial = get_history


async def clear_history(phone: str) -> None:
    async with AsyncSessionLocal() as session:
        conv = await session.execute(select(Conversation).where(Conversation.phone == phone))
        conversacion = conv.scalar_one_or_none()
        if conversacion is None:
            return
        await session.execute(
            delete(ConversationMessage).where(
                ConversationMessage.conversation_id == conversacion.id
            )
        )
        await session.delete(conversacion)
        await session.commit()


async def get_estado(phone: str) -> Dict:
    async with AsyncSessionLocal() as session:
        fila = await session.get(EstadoProspecto, phone)
        if fila is None or not fila.state_json:
            return {}
        try:
            datos = json.loads(fila.state_json)
            return datos if isinstance(datos, dict) else {}
        except json.JSONDecodeError:
            return {}


async def guardar_estado(phone: str, estado: Dict) -> None:
    async with AsyncSessionLocal() as session:
        fila = await session.get(EstadoProspecto, phone)
        if fila is None:
            fila = EstadoProspecto(phone=phone)
            session.add(fila)
        fila.state_json = json.dumps(estado or {}, ensure_ascii=False)
        fila.updated_at = _ahora()
        await session.commit()


async def reset_estado(phone: str) -> None:
    async with AsyncSessionLocal() as session:
        fila = await session.get(EstadoProspecto, phone)
        if fila is not None:
            await session.delete(fila)
            await session.commit()


async def marcar_evento_procesado(evento_id: str) -> bool:
    """True si el evento es nuevo; False si ya se procesó."""
    if not evento_id:
        return True
    async with AsyncSessionLocal() as session:
        session.add(EventoProcesado(evento_id=evento_id))
        try:
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False


async def liberar_evento(evento_id: str) -> None:
    if not evento_id:
        return
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(EventoProcesado).where(EventoProcesado.evento_id == evento_id)
        )
        await session.commit()


async def limpiar_eventos_viejos(dias: int = 7) -> None:
    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    async with AsyncSessionLocal() as session:
        await session.execute(delete(EventoProcesado).where(EventoProcesado.created_at < corte))
        await session.commit()


def estado_vacio() -> Dict:
    """Estado inicial de cada prospecto."""
    return {
        "etapa": "inicio",  # inicio | esperando_confirmacion | esperando_nombre | listo
        "nombre": "",
        "confirmo": False,
        "contexto_dado": False,
        "link_enviado": False,
        "saludado": False,
        "turnos": 0,
    }
