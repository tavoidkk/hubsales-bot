"""test_regresiones.py — reglas generales que fallaron en producción.

No se prueban nombres concretos ni conversaciones puntuales: se prueban las
REGLASS (link obligatorio, nombres compuestos, preguntas sobre la oferta,
errores del formulario) para que no vuelvan a romperse con otros clientes.
"""

from __future__ import annotations

import pytest

from agent import flow
from agent.config import link_formulario, link_formulario_alternativo
from agent.flow import procesar_turno

TEL = "3333333333"
LINK = link_formulario()
LINK_ALT = link_formulario_alternativo()


async def turno(texto: str, telefono: str = TEL):
    return await procesar_turno(telefono, texto, [])


def con_ia(monkeypatch, propuestas):
    """Fuerza la rama de IA con respuestas en orden, sin llamar a OpenRouter."""
    cola = list(propuestas)
    monkeypatch.setattr(flow, "ia_disponible", lambda: True)

    async def falsa(entrada, historial, estado, senales):
        if not cola:
            pytest.fail("La IA fue llamada más veces de lo esperado")
        return cola.pop(0)

    monkeypatch.setattr(flow, "generar_respuesta_ia", falsa)


# ── Link obligatorio y cierre en femenino ────────────────────────────────


async def test_entrega_siempre_incluye_el_link_aunque_la_ia_lo_omita(monkeypatch):
    await turno("hola")
    con_ia(
        monkeypatch,
        [("entregar_formulario", "Le dejo el formulario para que lo complete. Quedo atenta.")],
    )

    respuesta, estado, _real = await turno("Camila, sí, vengo por la oferta")

    assert LINK in respuesta
    assert estado["link_enviado"] is True


async def test_cierre_nunca_dice_atento():
    await turno("hola")
    despedida, _estado, _real = await turno("Camila, sí")

    assert "atenta" in despedida.lower()
    assert "atento" not in despedida.lower()

    await turno("hola", "otro-telefono")
    await turno("Camila, sí", "otro-telefono")
    # Un "gracias" no se contesta; cualquier otro mensaje posterior sí recibe
    # el cierre corto, que también debe decir "atenta".
    cierre, _estado, _real = await turno("entiendo, perfecto", "otro-telefono")

    assert "atenta" in cierre.lower()
    assert "atento" not in cierre.lower()


# ── Captura de nombre y confirmación ─────────────────────────────────────


@pytest.mark.parametrize(
    "mensaje, nombre",
    (
        ("Valeria, y si, vengo por eso", "Valeria"),
        ("Marta López, si por la vacante", "Marta López"),
        ("José Luis Rivera, si sobre la vacante de vendedor", "José Luis Rivera"),
        ("Hola, María José", "María José"),
        ("Dielys Serrano\nOferta de vendedor", "Dielys Serrano"),
    ),
)
async def test_nombre_y_confirmacion_combinados_entregan_el_link(mensaje, nombre):
    await turno("hola")
    respuesta, estado, _real = await turno(mensaje)

    if "Hola, María José" in mensaje:
        # El nombre llegó solo: todavía falta la confirmación.
        assert estado["nombre"] == nombre
        assert LINK not in respuesta
        await turno("sí, vengo por eso")
    else:
        assert estado["nombre"] == nombre
        assert estado["confirmo"] is True
        assert LINK in respuesta


async def test_nombre_completo_no_se_degrada_a_un_solo_nombre():
    await turno("hola")
    await turno("José Luis Rivera")
    await turno("Jose")

    respuesta, estado, _real = await turno("sí")

    assert estado["nombre"] == "José Luis Rivera"
    assert "José Luis Rivera" in respuesta
    assert LINK in respuesta


async def test_respuesta_citada_no_se_toma_como_nombre():
    """WhatsApp puede incluir el mensaje citado dentro del texto entrante."""
    await turno("hola")
    citado = (
        "You\n"
        "Hola, le escribe Sofía, reclutadora en HubSales Group. ¿Me podría indicar su nombre?\n"
        "Marta López Ruiz, si sobre la vacante de vendedor"
    )

    respuesta, estado, _real = await turno(citado)

    assert estado["nombre"] == "Marta López Ruiz"
    assert LINK in respuesta
    assert "le escribe Sofía" not in respuesta


# ── Información de la oferta, antes y después del link ───────────────────


@pytest.mark.parametrize(
    "pregunta",
    (
        "¿de qué trata?",
        "¿de qué trata la oferta?",
        "me das mas informacion",
        "precios y cuanto pagan",
    ),
)
async def test_la_oferta_se_explica_siempre_que_la_piden(pregunta):
    await turno("hola")
    respuesta, _estado, _real = await turno(pregunta)

    assert "$25" in respuesta
    assert "trabajo remoto" in respuesta
    assert LINK not in respuesta


async def test_despues_del_link_la_oferta_tambien_se_explica():
    await turno("hola")
    await turno("Camila, sí")
    respuesta, estado, _real = await turno("¿y de qué trata la oferta?")

    assert estado["link_enviado"] is True
    assert "$25" in respuesta
    assert "pagos semanales" in respuesta
    assert LINK not in respuesta


# ── Errores del formulario ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "problema",
    (
        "me da error el formulario",
        "no me permite subir el currículum",
        "operación rechazada por el servidor",
        "no carga el archivo",
        "el link no funciona",
    ),
)
async def test_error_del_formulario_nunca_cierra_la_postulacion(problema):
    await turno("hola")
    respuesta, estado, _real = await turno(problema)

    plano = respuesta.lower()
    assert LINK_ALT in respuesta
    assert LINK not in respuesta
    assert "lamento" in plano or "disculpa" in plano
    assert "incógnito" in plano or "incognito" in plano
    assert "sesión de google" in plano or "sesion de google" in plano
    assert "pdf" in plano
    assert "paréntesis" in plano or "parentesis" in plano
    # Nada de cerrar ni de confirmar que llegó la postulación.
    assert "se comunicará" not in respuesta
    assert "atenta" not in plano
    assert "atento" not in plano
    # El estado real no se altera: si el formulario no se entregó, sigue pendiente.
    assert estado["link_enviado"] is False


async def test_error_del_formulario_despues_de_entregado_no_reenvia_el_principal():
    await turno("hola")
    await turno("Camila, sí")
    respuesta, estado, _real = await turno("me da error al subir el CV")

    assert LINK not in respuesta
    assert LINK_ALT in respuesta
    assert estado["link_enviado"] is True
    assert estado["etapa"] == "listo"


async def test_error_del_formulario_no_ofrece_enviar_nada_por_whatsapp(monkeypatch):
    await turno("hola")
    con_ia(
        monkeypatch,
        [
            (
                "error_formulario",
                "Lamento el error. Abra en incógnito con una sola sesión de Google activa, "
                "renombre el PDF sin paréntesis ni caracteres especiales y enviamelo por whatsapp.",
            )
        ],
    )

    respuesta, _estado, _real = await turno("me da error al subir el CV")

    plano = respuesta.lower()
    assert "whatsapp" not in plano
    assert "enviamelo" not in plano
    assert LINK_ALT in respuesta


@pytest.mark.parametrize(
    "propuesta",
    (
        "Lamento el fallo. Abra el enlace en incógnito con una sola sesión de Google activa "
        "y renombre el PDF sin paréntesis ni caracteres especiales, por ejemplo CV_Camila_2026.pdf.",
        "Disculpe el inconveniente técnico con el archivo: use una ventana de incógnito con "
        "una sola sesión de Google y guarde el PDF sin paréntesis ni caracteres especiales.",
    ),
)
async def test_error_del_formulario_la_redaccion_la_escribe_la_ia(monkeypatch, propuesta):
    await turno("hola")
    con_ia(monkeypatch, [("error_formulario", propuesta)])

    respuesta, _estado, _real = await turno("no me deja adjuntar el archivo")

    assert respuesta.startswith(propuesta)
    assert LINK_ALT in respuesta
    assert "Lamento el inconveniente" not in respuesta  # no es el texto fijo


async def test_error_sin_ingredientes_cae_al_texto_fijo(monkeypatch):
    await turno("hola")
    con_ia(monkeypatch, [("error_formulario", "Probá de nuevo más tarde.")])

    respuesta, _estado, _real = await turno("me da error el formulario")

    assert "Lamento el inconveniente" in respuesta
    assert LINK_ALT in respuesta


# ── Nunca JSON crudo en el chat ──────────────────────────────────────────


@pytest.mark.parametrize(
    "fragmento",
    (
        '{"accion":"pedirnombre","texto":"Buen día, soy Sofía',
        '{"accion": "pedir_nombre", "texto": "Hola"',
        '["accion","texto"',
    ),
)
async def test_json_crudo_de_la_ia_nunca_llega_al_cliente(monkeypatch, fragmento):
    await turno("hola")
    con_ia(monkeypatch, [("sugerido", fragmento)])

    respuesta, _estado, _real = await turno("hola?")

    assert "accion" not in respuesta.lower()
    assert "{" not in respuesta
    assert "¿Me podría indicar su nombre, por favor?" in respuesta
