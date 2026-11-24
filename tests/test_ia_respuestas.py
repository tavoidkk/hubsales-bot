"""test_ia_respuestas.py — salida cruda del LLM (sin red).

El modelo devolvió un JSON cortado a mitad y el cliente vio el fragmento.
Estas pruebas fijan que un JSON inválido o incompleto se DESCARTA entero.
"""

from __future__ import annotations

import pytest

from agent import ia


class _Respuesta:
    def __init__(self, cuerpo):
        self.status_code = 200
        self.text = ""
        self._cuerpo = cuerpo

    def json(self):
        return self._cuerpo


def _instalar(monkeypatch, contenido, finish="stop", vistos=None, estado=200):
    monkeypatch.setenv("IA_MODO", "")
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk_test_no_real")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://ejemplo.test/v1")

    cuerpo = {
        "choices": [{"message": {"content": contenido}, "finish_reason": finish}]
    } if estado == 200 else {}

    class _Cliente:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **kwargs):
            if vistos is not None:
                vistos.append(kwargs)
            respuesta = _Respuesta(cuerpo)
            respuesta.status_code = estado
            return respuesta

    monkeypatch.setattr(ia.httpx, "AsyncClient", lambda *_a, **_k: _Cliente())


async def _generar():
    return await ia.generar_respuesta_ia(
        "hola", [], {"etapa": "inicio", "turnos": 1, "nombre": ""}, {}
    )


async def test_json_truncado_no_se_devuelve(monkeypatch):
    _instalar(monkeypatch, '{"accion":"pedir_nombre","texto":"Buen día, soy Sofía')

    assert await _generar() is None


async def test_json_cortado_por_tokens_no_se_devuelve(monkeypatch):
    _instalar(
        monkeypatch,
        '{"accion":"pedir_nombre","texto":"Hola, ¿me indica su nombre?"}',
        finish="length",
    )

    assert await _generar() is None


async def test_json_valido_se_devuelve(monkeypatch):
    _instalar(monkeypatch, '{"accion":"pedir_nombre","texto":"¿Me indica su nombre?"}')

    assert await _generar() == ("pedir_nombre", "¿Me indica su nombre?")


async def test_texto_plano_normal_sigue_aceptandose(monkeypatch):
    _instalar(monkeypatch, "Buen día, ¿me podría indicar su nombre?")

    assert await _generar() == ("sugerido", "Buen día, ¿me podría indicar su nombre?")


async def test_texto_plano_con_pistas_de_json_no_se_devuelve(monkeypatch):
    _instalar(monkeypatch, 'accion":"pedirnombre","texto":"Hola')

    assert await _generar() is None


async def test_max_tokens_nunca_baja_de_900(monkeypatch):
    vistos = []
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "700")
    _instalar(monkeypatch, "Hola", vistos=vistos)

    await _generar()

    assert vistos[0]["json"]["max_tokens"] == 900
