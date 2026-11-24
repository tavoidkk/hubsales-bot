"""test_flujo.py — recorrido completo del reclutamiento.

Verifica el saludo exacto, la captura de nombre, la confirmación, la entrega
obligatoria del formulario y la regla de contexto solo si preguntan.
"""

from __future__ import annotations

import pytest

from agent.config import link_formulario
from agent.flow import procesar_turno

TEL = "1111111111"
LINK = link_formulario()


async def turno(texto: str, telefono: str = TEL):
    return await procesar_turno(telefono, texto, [])


def _sin_acentos(texto: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    ).lower()


async def test_saludo_exacto_y_sin_ia():
    respuesta, estado, real = await turno("hola")

    assert respuesta == (
        "Hola, le escribe Sofía, reclutadora en HubSales Group. "
        "¿Me podría indicar su nombre y confirmarme que viene por la oferta de vendedor que publicamos?"
    )
    assert estado["etapa"] == "inicio"
    assert real is True
    plano = _sin_acentos(respuesta)
    assert "bot" not in plano
    assert "inteligencia artificial" not in plano
    # Tono formal: "usted", sin voseo.
    assert "Me podría indicar su nombre" in respuesta
    assert "venís" not in respuesta and "decís" not in respuesta


async def test_nombre_personalizable_por_env(monkeypatch):
    monkeypatch.setenv("BOT_NAME", "Lucía")
    respuesta, _estado, _real = await turno("hola")
    assert "le escribe Lucía, reclutadora en HubSales Group" in respuesta


async def test_flujo_nombre_luego_confirmacion():
    saludo, _e1, _r1 = await turno("hola")
    pedir_conf, e2, _r2 = await turno("Ana")

    assert saludo.startswith("Hola, le escribe")
    assert pedir_conf == "¿Me confirma que viene por la oferta de vendedor que publicamos?"
    assert e2["etapa"] == "esperando_confirmacion"
    assert e2["nombre"] == "Ana"

    despedida, e3, real = await turno("sí, vengo por la oferta publicada")

    assert LINK in despedida
    assert "Muchas gracias, Ana" in despedida
    assert e3["etapa"] == "listo"
    assert e3["confirmo"] is True
    assert e3["link_enviado"] is True
    assert real is True


async def test_flujo_confirmacion_luego_nombre():
    await turno("hola")
    pedir_nombre, e1, _r1 = await turno("sí, vengo por la oferta publicada")
    despedida, e2, _r2 = await turno("me llamo Marta López")

    assert pedir_nombre == "¿Me podría indicar su nombre, por favor?"
    assert e1["etapa"] == "esperando_nombre"
    assert e1["confirmo"] is True
    assert "Marta López" in despedida
    assert LINK in despedida
    assert e2["etapa"] == "listo"


async def test_nombre_y_confirmacion_en_un_solo_mensaje():
    await turno("hola")
    respuesta, estado, _real = await turno("Soy Ana, vengo por la oferta publicada")

    assert LINK in respuesta
    assert estado["nombre"] == "Ana"
    assert estado["etapa"] == "listo"


@pytest.mark.parametrize(
    "entrada",
    (
        "Gustavo vidal si",
        "Gustavo Vidal, sí",
        "sí, Gustavo Vidal",
        "Gustavo Vidal, sí, vengo por la oferta",
    ),
)
async def test_nombre_y_si_juntos_en_un_solo_mensaje(entrada):
    await turno("hola")
    respuesta, estado, _real = await turno(entrada)

    assert LINK in respuesta
    assert estado["nombre"] == "Gustavo Vidal"
    assert estado["confirmo"] is True
    assert estado["etapa"] == "listo"


async def test_contexto_no_se_da_si_no_preguntan():
    await turno("hola")
    await turno("Ana")
    despedida, estado, _real = await turno("sí, confirmo")

    plano = _sin_acentos(despedida)
    assert "$25" not in despedida
    assert "semanal" not in plano
    assert "bonificacion" not in plano
    assert "remoto" not in plano
    assert "condicion" not in plano
    assert estado["contexto_dado"] is False


async def test_contexto_solo_preguntado_incluye_datos_autorizados():
    await turno("hola")
    respuesta, estado, real = await turno("¿cuánto pagan y es remoto?")

    assert "$25 por ventas" in respuesta
    assert "pagos semanales" in respuesta
    assert "bonificaciones por cumplimiento de metas" in respuesta
    assert "trabajo remoto" in respuesta
    assert "Ciertas condiciones aplican" in respuesta
    assert "lo contacta" in _sin_acentos(respuesta)
    assert estado["contexto_dado"] is True
    assert real is False


async def test_contexto_repetido_entrega_datos_otra_vez():
    """Si lo vuelven a preguntar, se lo volvemos a decir (antes y después del link)."""
    await turno("hola")
    await turno("¿cuánto pagan?")
    segunda, estado, _real = await turno("¿y losbonos?")

    assert estado["contexto_dado"] is True
    assert "$25" in segunda
    assert "bonificaciones por cumplimiento de metas" in segunda
    assert "nombre" not in segunda.lower()
    assert "confirm" not in segunda.lower()


async def test_reenvia_link_sin_pedir_confirmacion_ni_estado_formulario():
    await turno("hola")
    await turno("Ana")
    await turno("sí")
    reenviado, _estado, real = await turno("¿me pasás el link otra vez?")

    assert LINK in reenviado
    assert real is True
    plano = _sin_acentos(reenviado)
    assert "completaste" not in plano
    assert "completo" not in plano
    assert "recibí" not in plano


async def test_despues_de_listo_agradecimiento_no_genera_respuesta():
    await turno("hola")
    await turno("Ana")
    await turno("sí")
    respuesta, _estado, real = await turno("gracias")

    assert respuesta == ""
    assert real is False


async def test_despues_del_formulario_no_repite_el_link():
    """El bug reportado: después del formulario lo mandaba en cada mensaje."""
    await turno("hola")
    await turno("Ana")
    await turno("sí")
    respuesta, estado, _real = await turno("ok, ya está")

    assert LINK not in respuesta
    assert "formulario" not in respuesta.lower()
    assert "nombre" not in respuesta.lower()
    assert "confirm" not in respuesta.lower()
    assert estado["etapa"] == "listo"
    assert estado["nombre"] == "Ana"


@pytest.mark.parametrize(
    "entrada",
    (
        "me das mas informacion",
        "me das informacion de la oferta",
        "me das informacion de la oferta publicada precios y cuanto pagan",
    ),
)
async def test_pide_informacion_despues_del_formulario_recibe_datos_no_link(entrada):
    await turno("hola")
    await turno("Gustavo vidal si")
    respuesta, estado, _real = await turno(entrada)

    assert "$25" in respuesta
    assert "remoto" in respuesta.lower()
    assert LINK not in respuesta
    assert estado["etapa"] == "listo"


async def test_pide_humano_no_revela_mas_de_la_linea():
    await turno("hola")
    respuesta, _estado, real = await turno("¿puedo hablar con una persona del equipo?")

    plano = _sin_acentos(respuesta)
    assert "$25" not in respuesta
    assert "equipo de hubsales group" in plano
    assert real is False


async def test_solo_espanol():
    await turno("hola")
    respuesta, _estado, real = await turno("hello, my name is Anna")

    assert "Solo atiendo en español" in respuesta
    assert real is False


async def test_no_hay_horario_el_bot_responde_siempre():
    """El flujo no tiene rama de horario: siempre contesta al que escribe."""
    await turno("hola")
    respuesta, _estado, real = await turno("Ana")

    plano = _sin_acentos(respuesta)
    assert "horario" not in plano
    assert "fuera de" not in plano
    assert real is True


@pytest.mark.parametrize("texto", ["hola", "Hola!", "buenas", "hey"])
async def test_saludos_inician_el_flujo(texto):
    respuesta, estado, _real = await turno(texto)
    assert respuesta.startswith("Hola, le escribe")
    assert estado["etapa"] == "inicio"
