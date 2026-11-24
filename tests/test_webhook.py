"""test_webhook.py — servidor FastAPI y adaptador de Zernio.

Prueba el camino completo con el proveedor mock: webhook -> deduplicación ->
flujo -> mensaje capturado. Nada sale por red.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient
from starlette.requests import Request

import agent.main as main
from agent.providers.mock import limpiar_enviados, obtener_enviados
from agent.providers.zernio import ProveedorZernio


def _request(body: bytes, headers: dict | None = None) -> Request:
    """Construye un Request de Starlette sin levantar un servidor."""
    cabeceras = [
        (k.lower().encode(), str(v).encode()) for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/webhook",
        "headers": cabeceras,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
        "scheme": "http",
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def test_health_check():
    with TestClient(main.app) as client:
        r = client.get("/")
    assert r.status_code == 200
    datos = r.json()
    assert datos["status"] in ("ok", "degradado")
    assert datos["service"] == "hubsales-reclutamiento"
    assert datos["idioma"] == "es"
    assert datos["link_formulario_configurado"] is True
    assert "reclutadora" in datos["bot"]
    assert "conexion" in datos


def test_webhook_encola_y_el_flujo_responde():
    with TestClient(main.app) as client:
        r = client.post(
            "/webhook",
            json={"texto": "hola", "telefono": "3333333333", "mensaje_id": "evt-web-1"},
        )
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "encolados": 1}

    enviados = obtener_enviados()
    assert len(enviados) == 1
    assert enviados[0]["mensaje"].startswith("Hola, te escribe Sofía, reclutadora")


def test_webhook_duplicado_no_se_procesa():
    payload = {"texto": "hola", "telefono": "4444444444", "mensaje_id": "evt-unico"}
    with TestClient(main.app) as client:
        primera = client.post("/webhook", json=payload)
        segunda = client.post("/webhook", json=payload)

    assert primera.json()["encolados"] == 1
    assert segunda.json()["encolados"] == 0
    assert len(obtener_enviados()) == 1


def test_webhook_ignora_mensaje_vacio():
    with TestClient(main.app) as client:
        r = client.post(
            "/webhook",
            json={"texto": "   ", "telefono": "555", "mensaje_id": "evt-vacio"},
        )
    assert r.json() == {"status": "ok", "encolados": 0}
    assert obtener_enviados() == []


async def test_firma_zernio_valida_e_invalida(monkeypatch):
    secreto = "secreto-de-prueba"
    monkeypatch.setenv("ZERNIO_WEBHOOK_SECRET", secreto)
    monkeypatch.setenv("ZERNIO_API_KEY", "sk_test")
    proveedor = ProveedorZernio()

    cuerpo = b'{"event":"message.received"}'
    firma = hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()

    assert await proveedor.verificar_firma(_request(cuerpo, {"X-Zernio-Signature": firma})) is True
    assert await proveedor.verificar_firma(_request(cuerpo, {"X-Zernio-Signature": "incorrecta"})) is False
    assert await proveedor.verificar_firma(_request(cuerpo)) is False


async def test_zernio_normaliza_mensaje(monkeypatch):
    monkeypatch.setenv("ZERNIO_WEBHOOK_SECRET", "")
    proveedor = ProveedorZernio()

    payload = {
        "event": "message.received",
        "id": "evt-1",
        "message": {
            "platform": "whatsapp",
            "direction": "incoming",
            "text": "hola",
            "conversationId": "conv-1",
            "sender": {"phoneNumber": "+123456789", "businessScopedUserId": "u1"},
        },
        "account": {"id": "acc-1"},
    }
    mensajes = await proveedor.parsear_webhook(
        _request(json.dumps(payload).encode("utf-8"))
    )

    assert len(mensajes) == 1
    msg = mensajes[0]
    assert msg.telefono == "123456789"
    assert msg.texto == "hola"
    assert msg.es_propio is False
    assert msg.contexto["evento_id"] == "evt-1"
    assert msg.contexto["conversation_id"] == "conv-1"
    assert msg.contexto["account_id"] == "acc-1"


async def test_zernio_ignora_mensajes_de_otro_numero(monkeypatch):
    """El bot de HubSales no debe responder mensajes del número de Toyota."""
    monkeypatch.setenv("ZERNIO_WEBHOOK_SECRET", "")
    monkeypatch.setenv("ZERNIO_ACCOUNT_ID", "acc-hubsales")
    proveedor = ProveedorZernio()

    payload = {
        "event": "message.received",
        "id": "evt-otro",
        "message": {
            "platform": "whatsapp",
            "direction": "incoming",
            "text": "hola",
            "sender": {"phoneNumber": "+123456789"},
        },
        "account": {"id": "acc-toyota"},
    }
    assert await proveedor.parsear_webhook(_request(json.dumps(payload).encode())) == []

    payload["account"] = {"id": "acc-hubsales"}
    assert len(await proveedor.parsear_webhook(_request(json.dumps(payload).encode()))) == 1


async def test_zernio_ignora_standby_y_otros_eventos(monkeypatch):
    monkeypatch.setenv("ZERNIO_WEBHOOK_SECRET", "")
    proveedor = ProveedorZernio()

    base = {
        "event": "message.received",
        "id": "evt-2",
        "message": {
            "platform": "whatsapp",
            "direction": "incoming",
            "text": "hola",
            "sender": {"phoneNumber": "+1"},
        },
    }
    assert await proveedor.parsear_webhook(_request(json.dumps(base).encode())) != []
    base["metadata"] = {"standby": True}
    assert await proveedor.parsear_webhook(_request(json.dumps(base).encode())) == []
    base["event"] = "message.delivered"
    assert await proveedor.parsear_webhook(_request(json.dumps(base).encode())) == []
