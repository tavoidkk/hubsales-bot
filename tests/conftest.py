"""conftest.py — entorno aislado para las pruebas.

Se ejecuta ANTES de importar `agent`, así que fija las variables que el código
lee al importarse:

  - DATABASE_URL: SQLite temporal (nunca la base real del negocio).
  - WHATSAPP_PROVIDER=mock: nada sale por red.
  - FORM_LINK: link de prueba para poder verificar la entrega del formulario.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

_DB = Path(tempfile.gettempdir()) / f"hubsales_test_{os.getpid()}.db"
if _DB.exists():
    _DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB.as_posix()}"
os.environ["ENVIRONMENT"] = "test"
os.environ["WHATSAPP_PROVIDER"] = "mock"
os.environ["FORM_LINK"] = "https://formulario.ejemplo.test/registro"
# Las pruebas son deterministas y no gastan créditos de OpenRouter.
# La rama con IA se prueba con un modelo falso en tests/test_ia.py.
os.environ["IA_MODO"] = "determinista"
os.environ["LLM_PROVIDER"] = ""
os.environ.pop("BOT_NAME", None)


@pytest_asyncio.fixture(autouse=True)
async def db_limpio():
    """Cada prueba empieza con tablas vacías y sin mensajes capturados."""
    from agent.memory import (
        AsyncSessionLocal,
        Conversation,
        ConversationMessage,
        EstadoProspecto,
        EventoProcesado,
        init_db,
    )
    from agent.providers.mock import limpiar_enviados

    await init_db()
    async with AsyncSessionLocal() as session:
        await session.execute(delete(ConversationMessage))
        await session.execute(delete(Conversation))
        await session.execute(delete(EstadoProspecto))
        await session.execute(delete(EventoProcesado))
        await session.commit()
    limpiar_enviados()
    yield
