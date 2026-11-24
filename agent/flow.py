"""flow.py — cerebro del reclutamiento: IA con barandas.

La IA propone una ACCIÓN y un TEXTO. Este módulo es la autoridad:
  - detecta inyecciones ANTES de llamar al modelo;
  - extrae nombre y confirmación del mensaje del candidato (no del modelo);
  - fuerza la entrega del formulario cuando ya hay nombre + confirmación;
  - valida y limpia el texto de la IA (enlaces, markdown, datos no autorizados);
  - cae a textos fijos si la IA no está disponible o se sale de la línea.

Estados:
    inicio -> esperando_nombre / esperando_confirmacion -> listo
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, List, Tuple

from .config import (
    contexto_oferta,
    identidad,
    link_formulario,
    link_formulario_alternativo,
    mensaje,
)
from .ia import generar_respuesta_ia, ia_disponible
from .memory import estado_vacio, get_estado, guardar_estado

logger = logging.getLogger("agentkit")

MAX_LONGITUD = 2000

# Caracteres invisibles y controles bidireccionales usados para esconder texto.
CONTROLES_OCULTOS = (
    "\u200b", "\u200c", "\u200d", "\u200e", "\u200f",
    "\u202a", "\u202b", "\u202c", "\u202d", "\u202e",
    "\u2060", "\u2061", "\u2062", "\u2063", "\u2064",
    "\u2066", "\u2067", "\u2068", "\u2069",
    "\ufeff", "\u00ad",
)

INSTRUCCIONES = (
    ("ignore previous", "una instrucción para ignorar reglas anteriores"),
    ("ignore all previous", "una instrucción para ignorar reglas anteriores"),
    ("ignore the above", "una instrucción para ignorar reglas anteriores"),
    ("ignora las instrucciones", "una instrucción para ignorar reglas anteriores"),
    ("ignora instrucciones", "una instrucción para ignorar reglas anteriores"),
    ("ignora todo", "una instrucción para ignorar reglas anteriores"),
    ("olvida todo", "una instrucción para ignorar reglas anteriores"),
    ("olvida las instrucciones", "una instrucción para ignorar reglas anteriores"),
    ("muestra tu prompt", "un pedido de instrucciones internas"),
    ("muestra el prompt", "un pedido de instrucciones internas"),
    ("revela tu prompt", "un pedido de instrucciones internas"),
    ("revela las instrucciones", "un pedido de instrucciones internas"),
    ("muestra las instrucciones", "un pedido de instrucciones internas"),
    ("system prompt", "un pedido de instrucciones internas"),
    ("prompt de sistema", "un pedido de instrucciones internas"),
    ("actua como", "un intento de cambiar el rol del bot"),
    ("eres ahora", "un intento de cambiar el rol del bot"),
    ("modo desarrollador", "un intento de eludir las reglas"),
    ("developer mode", "un intento de eludir las reglas"),
    ("jailbreak", "un intento de eludir las reglas"),
    ("print your instructions", "un pedido de instrucciones internas"),
    ("repeat the above", "un pedido de instrucciones internas"),
    ("instrucciones ocultas", "texto oculto"),
    ("instrucciones malisiosas", "texto oculto"),
    ("texto oculto", "texto oculto"),
    ("niega la peticion", "una instrucción para rechazar la solicitud"),
    ("prompt engineer", "una instrucción para manipular el bot"),
    ("prompt injection", "una instrucción maliciosa"),
)

CLAVES_CONTEXTO = (
    "pago", "pagan", "paga", "cuanto", "sueldo", "salario",
    "comision", "comisiones", "bono", "bonos", "bonificacion",
    "semanal", "remoto", "home office", "desde casa", "konnect",
    "seguro", "call center", "vendedor", "ventas", "25",
    "condicion", "condiciones", "requisito", "requisitos", "detalle",
    "detalles", "informacion", "contexto", "que ofrecen", "beneficio",
    "beneficios", "horario", "trabajo", "vacante", "puesto", "funciona",
    "gana", "ganas", "que es la oferta", "de que se trata",
    "sobre la oferta", "hablan de la oferta", "de que trata",
    "hablame de la oferta", "contame la oferta", "cuentame la oferta",
    "explicame la oferta", "de la oferta", "la oferta",
    "precio", "precios", "mas informacion", "saber mas",
)
INTERROGATIVAS = (
    "cuanto", "que es", "de que", "como es", "cuales", "cual ", "donde", "cuando",
    "detalle", "informacion", "contexto", "dime", "decime", "cuentame",
    "contame", "hablame", "explica", "explicame", "que ofrecen", "como funciona",
    "que pay", "que tal", "cuenta", "precio", "precios", "me das", "me comparte",
    "me indica", "quisiera saber", "necesito saber", "quiero saber", "saber",
)

CLAVES_LINK = (
    "link", "enlace", "formulario", "form", "pasame", "pasarme", "mandame",
    "mandarme", "envíame", "enviamne", "envia me", "acceso", "inscribirme",
    "inscripcion", "donde me anoto", "donde aplico",
    # Después de recibir el formulario, "no lo veo" es una forma de pedirlo.
    "no lo veo", "no lo encuentro", "no me llego", "no aparece", "no lo recibi",
)

CLAVES_HUMANO = (
    "humano", "persona real", "hablar con alguien", "hablar con una persona",
    "agente real", "alguien del equipo", "un asesor",
)

# Problemas reales reportados por el prospecto. Se detectan ANTES de cualquier
# cierre: si el formulario falló, no podemos decir que la postulación sigue
# adelante como si nada hubiera pasado.
CLAVES_ERROR_FORMULARIO = (
    "me da error", "me dio error", "me sale error", "me tira error", "da error",
    "no me deja", "no me permite", "no puedo subir", "no puedo adjuntar",
    "no carga el archivo", "no me carga", "no se carga", "no se sube",
    "operacion rechazada", "operación rechazada", "rechaza el archivo",
    "falla el formulario", "falla el link", "el link no funciona",
    "el enlace no funciona", "no abre el link", "no abre el enlace",
    "no puedo completar", "no puedo acceder", "error al enviar",
    "error al subir", "error al cargar", "se cayo el link", "se cayó el link",
    "no funciona el formulario", "no me deja subir", "no me deja adjuntar",
    "formulario roto", "no me abre", "no me deja entrar",
)

AFIRMATIVAS = (
    "s", "si", "sii", "dale", "ok", "okey", "claro", "correcto", "exacto",
    "de acuerdo", "asi es", "confirmo", "confirmado", "afirmativo", "si es",
)
# Para frases combinadas tipo "Gustavo Vidal, sí": se recorta el último token.
AFIRMATIVAS_SUELTAS = {
    "s", "si", "sii", "dale", "ok", "okey", "claro", "correcto", "exacto",
    "confirmo", "confirmado", "afirmativo", "vale", "bueno", "gracias",
}
NO_NOMBRE = {
    "la", "el", "una", "un", "los", "las", "soy", "mi", "nombre",
    "interesada", "interesado", "persona", "candidata", "candidato",
    "gracias", "hola", "buenas", "buenos", "confirmo", "s", "si", "sí",
    "hey", "hi", "hello", "que", "tal", "vale", "ok",
    "quiero", "necesito", "busco", "dame", "pasa", "tengo",
    "vengo", "vine", "voy", "sobre", "bajo", "por", "para", "de", "del",
    "vacante", "oferta", "publicada", "publicado", "puesto", "puedo",
    "postularme", "postular", "recibir", "formulario", "link", "enlace",
    "buen", "dia", "día", "tarde", "mañana", "noche", "todo", "bien",
    "tambien", "también", "asi", "así", "bueno", "perfecto", "listo",
}

# Se quitan de los bordes antes de decidir si lo que queda es un nombre.
CONECTORES_NOMBRE = {
    "y", "e", "tambien", "también", "pues", "bien", "entonces", "asi que",
    "bueno", "mira", "buenas", "hola", "hey",
}

# El nombre puede venir pegado a la confirmación: se corta antes de estas
# palabras para que "Valeria, y si, vengo por eso" dé solo "Valeria".
MARCADORES_CORTE = (
    r"\b(?:s[ií]|confirmo|vale|dale|ok|claro)\b",
    r"\b(?:vengo|vine|viene)\s+(?:por|por la)\b",
    r"\b(?:sobre|por|de)\s+la\s+(?:vacante|oferta|publicaci[oó]n)\b",
    r"\b(?:la\s+)?oferta\s+de\s+vendedor\b",
)

NOMBRE_RE = re.compile(
    r"\b(?:me llamo|mi nombre es|soy|nombre)\s+"
    r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’\-]*"
    r"(?:\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’\-]*){0,2})",
    re.IGNORECASE,
)

TEMAS_FUERA = (
    "vehiculo", "automovil", "auto", "carro", "coche", "concesionario",
    "freddy", "toyota", "clima", "politica", "futbol", "receta", "chiste",
    "adivinanza", "apuesta", "criptomoneda", "inversion", "novia", "novio",
    "mascota", "pelicula", "musica", "juego",
)

INGLES = (
    "hello", "my name is", "i am", "can you", "what is", "how much",
    "pay", "salary", "remote", "please", "yes i", "tell me",
)

# Frases que la IA no puede decir aunque el modelo las genere.
REVELAR_IA = (
    r"\bsoy\s+(?:un|una|una)?\s*(?:bot|inteligencia artificial|ia|asistente virtual|modelo|sistema automatizado)\b",
    r"\b(?:como|por ser|ser)\s+(?:un|una)?\s*(?:ia|bot|inteligencia artificial|asistente virtual)\b",
    r"\binteligencia artificial\b",
    r"\basistente virtual\b",
    r"\bsistema automatizado\b",
    r"\bsoy un bot\b",
)
ESTADO_FORMULARIO = (
    r"(completaste|complet[óo]|enviaste|envi[óo]|subiste|subi[óo]|cargaste|carg[óo])[^.?!]{0,40}formulario",
    r"formulario[^.?!]{0,40}(completaste|complet[óo]|enviaste|envi[óo]|subiste|subi[óo]|cargaste|carg[óo])",
)
DATOS_NO_AUTORIZADOS = (
    r"\$25", r"semanal", r"bonificacion", r"\bbonos?\b", r"\bremoto\b",
    r"ciertas condiciones", r"konnectmd", r"call center",
)

# La IA no puede decir "te paso el formulario" si la acción no es de entrega:
# antes pasaba y el candidato veía un mensaje prometiendo el link sin link.
PROMESA_FORMULARIO = (
    r"(te|les|le)\s+(dejo|paso|mando|envio|acompanio|comparto)\s+(el\s+)?(formulario|link|enlace)",
    r"ac[aa]\s+(va|tenes|esta)\s+(el\s+)?(formulario|link|enlace)",
    r"aqui\s+(va|esta)\s+(el\s+)?(formulario|link|enlace)",
    r"(formulario|link|enlace)\s+(para\s+)?(que\s+)?(completes|llenes|veas|lo\s+complete)",
    r"completa(lo|r)?\s+(el\s+)?formulario",
    r"complete\s+(el\s+)?formulario",
    r"para\s+que\s+lo\s+complete",
    r"me\sfalto\s+el\s+enlace",
    r"copialo\s+en\s+el\s+navegador",
    r"te\s+lo\s+paso\s+de\s+nuevo",
)

# El dueño pidió expresamente no ofrecer el envío del CV por WhatsApp.
OFRECER_ENVIO = (
    r"(te|le|les)\s+(envio|envi[oó]|mando|paso|adjunto|hago\s+llegar)\s+"
    r"(el\s+|su\s+|tu\s+)?(cv|curriculum|pdf|archivo|formulario)",
    r"(enviamelo|mandamelo|pasamelo|adjuntamelo)\s+por\s+(aqui|aquí|whatsapp|este\s+chat)",
    r"por\s+(este\s+|el\s+)?(chat|whatsapp|aqui|aquí)",
)

# Ingredientes que la respuesta de error debe tener, la escriba la IA o no.
INGREDIENTES_ERROR = {
    "disculpa": r"(lamento|perdon|perd[oó]n|disculpa|lo\s+siento|inconveniente)",
    "incognito": r"(inc[oó]gnito|modo\s+privado)",
    "google": r"(sesion|sesi[oó]n)\s+de\s+google",
    "pdf": r"\bpdf\b",
    "renombrar": r"(renombr|nombr|guarda|llama|sin\s+par[ée]ntesis|caracteres\s+especiales)",
}

# Un JSON a medio escribir no puede llegar al cliente aunque pase _sanitizar.
JSON_ROTO = re.compile(
    r'\{\s*["\']?(?:accion|texto)["\']?\s*:|["\'](?:accion|texto)["\']\s*:',
    re.IGNORECASE,
)

# El usuario pidió que el formulario se complete sin decir desde dónde ni con qué.
# Estas palabras se descartan incluso si el modelo las escribe en un reenvío.
MENCIONES_FORMULARIO = (
    r"\bcelular\b", r"\bcv\b", r"\bnavegador\b", r"\bcomputadora\b",
    r"\bdesktop\b", r"\bdesde (?:el|tu|su)\s+\w+",
)

# Al entregar el formulario no puede seguir pidiendo los datos que ya tiene.
PREGUNTA_DATOS = (
    r"\b(?:me\s+)?confirm(?:as|ás)\b",
    r"\b(?:decime|decis|indicame|indicas|contame)\s+(?:tu|el)\s+nombre\b",
    r"\b(?:c[óo]mo te llam|tu nombre|me llam[áa]s)\b",
)


def _sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in normalizado if not unicodedata.combining(c)).lower()


def _frase(texto: str) -> str:
    limpio = re.sub(r"[^a-z0-9]+", " ", _sin_acentos(texto)).strip()
    return f" {limpio} "


def _fragmento(texto: str) -> str:
    """Muestra un pedazo corto y legible del texto detectado, sin enlaces."""
    limpio = re.sub(r"https?://\S+", "[enlace]", texto or "")
    limpio = "".join(c if c.isprintable() else " " for c in limpio)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    if len(limpio) > 50:
        limpio = limpio[:47] + "..."
    return f': "{limpio}"' if limpio else ""


def _detectar_malicioso(texto: str) -> Tuple[bool, str]:
    """Detecta instrucciones incrustadas y texto oculto. Nunca ejecuta nada."""
    if any(control in texto for control in CONTROLES_OCULTOS):
        return True, "caracteres invisibles o de dirección oculta" + _fragmento(texto)

    if re.search(r"<!--[\s\S]*?-->", texto) or re.search(r"</?[A-Za-z][^>]*>", texto):
        return True, "etiquetas o comentarios HTML ocultos" + _fragmento(texto)

    if re.search(r"\b(?:javascript:|data:text/html)", texto, re.IGNORECASE):
        return True, "contenido incrustado" + _fragmento(texto)

    blob = texto.strip()
    if (
        len(blob) >= 40
        and re.fullmatch(r"[A-Za-z0-9+/\s]+={0,2}", blob)
        and any(simbolo in blob for simbolo in ("=", "+", "/"))
    ):
        return True, "un bloque codificado" + _fragmento(texto)

    plano = _sin_acentos(texto)
    for patron, detalle in INSTRUCCIONES:
        if patron in plano:
            return True, detalle + _fragmento(texto)
    return False, ""


def _es_afirmativa(texto: str) -> bool:
    corto = _frase(texto).strip()
    if " no " in f" {corto} " and "sin embargo" not in corto:
        return False
    return any(corto == a or corto.startswith(f"{a} ") for a in AFIRMATIVAS)


def _confirma(texto: str) -> bool:
    """True ante una aceptación clara de la oferta publicada.

    Acepta también las formas que la gente usa en WhatsApp sin escribir "sí":
    "vengo por eso", "si por la vacante", "oferta de vendedor", etc.
    Una pregunta ("¿de qué trata la oferta de vendedor?") NUNCA confirma.
    """
    frase = _frase(texto)
    if any(
        x in frase
        for x in (" no vengo", " no es", " no confirmo", " no gracias", " no interesa")
    ):
        return False
    if re.search(r"\b(?:si|sí)\s+(?:vengo|vine|confirmo)\b", frase):
        return True
    if _es_afirmativa(texto):
        return True
    # "Gustavo Vidal, sí" y "Gustavo vidal si" también son confirmación:
    # el nombre y el "sí" vinieron juntos en un solo mensaje.
    palabras = frase.strip().split()
    if (
        "?" not in texto
        and 1 < len(palabras) <= 10
        and palabras[-1] in AFIRMATIVAS_SUELTAS
    ):
        return True
    if "?" in texto:
        return False
    confirmadores = (
        " vengo por eso",
        " vine por eso",
        " vengo por la oferta",
        " vine por la oferta",
        " vengo por la vacante",
        " vine por la vacante",
        " vengo por el puesto",
        " por la oferta publicada",
        " por la oferta de vendedor",
        " sobre la vacante",
        " por la vacante",
        " la vacante de vendedor",
        " oferta de vendedor",
        " por la publicad",
        " es por la oferta",
        " confirmo que vengo",
        " asi es",
    )
    return any(clave in frase for clave in confirmadores)


def _recortar_afirmativas(palabras: list[str]) -> list[str]:
    """Quita 'sí', 'ok', 'gracias', etc. de los extremos del nombre."""
    mientras = True
    while mientras and palabras:
        mientras = False
        for indice in (0, -1):
            if _sin_acentos(palabras[indice].strip(".,!?¿")) in AFIRMATIVAS_SUELTAS:
                palabras.pop(indice)
                mientras = True
                break
    return palabras


def _recortar_conectores(palabras: list[str]) -> list[str]:
    """Quita saludos y conectores de los bordes: 'hola María José' -> 'María José'."""
    mientras = True
    while mientras and palabras:
        mientras = False
        for indice in (0, -1):
            if _sin_acentos(palabras[indice].strip(".,!?¿")) in CONECTORES_NOMBRE:
                palabras.pop(indice)
                mientras = True
                break
    return palabras


def _limpiar_citas(texto: str) -> str:
    """
    WhatsApp puede mandar la respuesta citada dentro del mismo texto:

        You
        Hola, le escribe Sofía, reclutadora...
        José Luis Rivera, si sobre la vacante de vendedor

    Nos quedamos solo con lo que escribió la persona, nunca con la cita.
    """
    lineas = [linea.strip() for linea in (texto or "").splitlines() if linea.strip()]
    if len(lineas) < 2:
        return texto or ""

    nombre_bot, _rol, _empresa = identidad()
    presentacion = f"le escribe {_sin_acentos(nombre_bot)}"
    utiles = []
    for linea in lineas:
        baja = _sin_acentos(linea)
        es_cita = (
            linea.startswith(">")
            or re.match(r"^(you|tu|t[uú]|usted|agente|asistente)\b", baja) is not None
            or presentacion in baja
        )
        if not es_cita:
            utiles.append(linea)
    if not utiles:
        return lineas[-1]
    return " ".join(utiles)


def _nombre_limpio(palabras: list[str]) -> str:
    """Nombre con mayúsculas correctas. Acepta hasta tres palabras ('José Luis Rivera')."""
    return " ".join(palabra.title() for palabra in palabras[:3]).strip(".,!?")


def _extraer_nombre(texto: str, etapa: str, solo_explicito: bool = False) -> str:
    texto = _limpiar_citas(texto or "")

    coincidencia = NOMBRE_RE.search(texto)
    if coincidencia:
        partes = coincidencia.group(1).split()
        while partes and partes[0].lower() in NO_NOMBRE:
            partes.pop(0)
        partes = _recortar_afirmativas(partes)
        partes = _recortar_conectores(partes)
        if partes:
            return _nombre_limpio(partes)

    if solo_explicito:
        # "¿cuánto pagan?" no es un nombre: es una pregunta sobre la oferta.
        return ""

    # El nombre y la confirmación pueden venir juntos en cualquier orden:
    # "Gustavo Vidal, sí", "sí, Gustavo Vidal" o "Valeria, y si, vengo por eso".
    candidatos = [texto]
    for marcador in MARCADORES_CORTE:
        candidatos.extend(re.split(marcador, texto, flags=re.IGNORECASE))

    for candidato in candidatos:
        limpio = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’\- ]+", " ", candidato).strip()
        palabras = _recortar_afirmativas(limpio.split())
        palabras = _recortar_conectores(palabras)
        if 1 <= len(palabras) <= 3 and all(2 <= len(p) <= 20 for p in palabras):
            if all(_sin_acentos(palabra) not in NO_NOMBRE for palabra in palabras):
                return _nombre_limpio(palabras)
    return ""


def _detecta_error_formulario(texto: str) -> bool:
    """El prospecto reportó un fallo con el enlace, el formulario o el archivo."""
    plano = _frase(texto)
    if any(_sin_acentos(clave) in plano for clave in CLAVES_ERROR_FORMULARIO):
        return True
    return bool(
        re.search(
            r"(error|falla|fallo|rechaz|no\s+carga|no\s+abre|no\s+funciona)"
            r"[^.?!]{0,30}(formulario|link|enlace|archivo|cv|pdf|subir|adjuntar)",
            plano,
        )
    )


def _pide_contexto(texto: str) -> bool:
    plano = _sin_acentos(texto)
    # "sí, vengo por la oferta publicada" es una confirmación, no una pregunta.
    if _confirma(texto) and "?" not in texto:
        return False
    tiene_clave = any(clave in plano for clave in CLAVES_CONTEXTO)
    pregunta = "?" in texto or any(clave in plano for clave in INTERROGATIVAS)
    return tiene_clave and pregunta


def _pide_link(texto: str) -> bool:
    """Busca palabras completas: "información" NO es un pedido de "form"."""
    plano = _sin_acentos(texto)
    for clave in CLAVES_LINK:
        patron = rf"(?<![a-z0-9]){re.escape(_sin_acentos(clave))}(?![a-z0-9])"
        if re.search(patron, plano):
            return True
    return False


def _pide_humano(texto: str) -> bool:
    plano = _sin_acentos(texto)
    return any(clave in plano for clave in CLAVES_HUMANO)


def _es_ingles(texto: str) -> bool:
    plano = _sin_acentos(texto)
    return any(re.search(rf"\b{re.escape(palabra)}\b", plano) for palabra in INGLES)


def _es_saludo(texto: str) -> bool:
    plano = _sin_acentos(texto).strip(" !.?¿,")
    return any(
        plano == s or plano.startswith(f"{s} ") or plano.startswith(f"{s},")
        for s in ("hola", "buenas", "buenos dias", "buen dia", "hey", "hi", "que tal")
    )


def _es_fuera(texto: str) -> bool:
    plano = f" {_sin_acentos(texto)} "
    return any(clave in plano for clave in TEMAS_FUERA)


def _es_agradecimiento(texto: str) -> bool:
    plano = _sin_acentos(texto).strip(" !.?¿,")
    return any(plano.startswith(p) for p in ("gracias", "mil gracias", "listo", "perfecto", "genial"))


def _accion_determinista(
    estado: Dict[str, Any],
    nombre: str,
    confirmo: bool,
    senales: Dict[str, bool],
    texto: str,
) -> str:
    """Decide la acción sin IA. Es el modo por defecto en tests y respaldo."""
    etapa = str(estado.get("etapa") or "inicio")
    if senales.get("error_formulario"):
        return "error_formulario"
    if senales["pide_contexto"]:
        return "contexto"
    if senales["pide_humano"]:
        return "humano"
    if etapa == "listo":
        # El formulario se entrega UNA vez. Solo se reenvía si lo piden de nuevo;
        # para cualquier otro mensaje alcanza con un cierre corto, sin enlace.
        if senales["pide_link"]:
            return "reenviar_link"
        if senales["es_agradecimiento"]:
            return "sin_responder"
        return "post_formulario"
    if not nombre and not confirmo and not senales["es_saludo"]:
        if _es_fuera(texto) or len(texto.strip()) > 120:
            return "fuera_de_linea"
    if nombre and confirmo:
        return "entregar_formulario"
    if nombre:
        return "pedir_confirmacion"
    if confirmo:
        return "pedir_nombre"
    if not estado.get("saludado"):
        return "saludo"
    # Ya se presentó: repetir el saludo literal es justo lo que el usuario
    # rechazó. Si no hay IA, al menos pedimos el nombre con naturalidad.
    return "pedir_nombre"


def _forzar_accion(
    accion: str,
    estado: Dict[str, Any],
    senales: Dict[str, bool],
) -> str:
    """La máquina de estados manda sobre la IA."""
    nombre = str(estado.get("nombre") or "")
    confirmo = bool(estado.get("confirmo"))
    link_enviado = bool(estado.get("link_enviado"))

    # Un problema con el formulario se atiende antes que cualquier cierre:
    # nunca decimos "listo" cuando la persona no pudo completarlo.
    if senales.get("error_formulario"):
        return "error_formulario"

    # Si preguntan por la oferta, se la damos siempre: antes del formulario,
    # después del formulario y aunque ya se la hayamos contado.
    if senales.get("pide_contexto"):
        return "contexto"

    # El formulario es obligatorio y va apenas tengamos los dos datos.
    if nombre and confirmo and not link_enviado:
        return "entregar_formulario"
    if confirmo and not nombre:
        return "pedir_nombre"
    if nombre and not confirmo:
        return "pedir_confirmacion"

    if accion == "sin_responder":
        # No podemos callar si todavía falta información para avanzar.
        if not nombre:
            return "pedir_nombre"
        if not confirmo:
            return "pedir_confirmacion"

    if link_enviado:
        # Con el formulario ya entregado, el bot no puede volver a pedir nombre
        # ni confirmación, ni reenviar el enlace en cada mensaje. Solo lo manda
        # otra vez si la persona lo pide explícitamente.
        if senales.get("pide_link"):
            return "reenviar_link"
        if accion in (
            "entregar_formulario", "reenviar_link", "continuar",
            "pedir_nombre", "pedir_confirmacion",
        ):
            return "post_formulario"
    if accion == "contexto" and not senales.get("pide_contexto"):
        # La IA no puede entregar datos de la oferta si no se los pidieron.
        return "fuera_de_linea"
    return accion


def _sanitizar(texto: str) -> str:
    """Limpia el texto de la IA. Devuelve '' si debe descartarse."""
    texto = unicodedata.normalize("NFKC", texto or "").strip()
    if texto[0] in "{[" or JSON_ROTO.search(texto):
        # Un JSON truncado nunca se muestra al prospecto. El JSON válido ya
        # fue convertido en (acción, texto) por ia.py antes de llegar acá.
        return ""
    texto = re.sub(r"https?://\S+", "", texto)  # se vuelve a poner el enlace oficial
    texto = re.sub(r"(?m)^\s*[-#>]\s+", "", texto)
    texto = re.sub(r"[`*]", "", texto)
    # Los guiones bajos dentro de un nombre de archivo son parte del nombre
    # (CV_Nombre_2026.pdf). Solo se quitan los que marcan énfasis en markdown.
    texto = re.sub(r"(?<!\w)_|_(?!\w)", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    if not texto or len(texto) > 500:
        return ""
    if any(re.search(patron, texto, re.IGNORECASE) for patron in REVELAR_IA):
        return ""
    if any(re.search(patron, texto, re.IGNORECASE) for patron in ESTADO_FORMULARIO):
        return ""
    return texto


def _preparar_texto(accion: str, texto: str) -> str:
    # La entrega y el reenvío usan la plantilla fija de prompts.yaml. Así el
    # enlace forms.gle y el "Quedo atenta" no dependen de lo que escriba el
    # modelo (era exactamente donde se perdía el link).
    if accion in ("entregar_formulario", "reenviar_link"):
        return ""

    texto = _sanitizar(texto)
    if not texto:
        return ""

    if accion == "error_formulario":
        # En el error la redacción SÍ la escribe la IA, adaptada al problema.
        # El enlace alternativo lo pone el código, nunca el modelo.
        alternativo = link_formulario_alternativo()
        if not alternativo:
            return ""
        if alternativo not in texto:
            base = texto.rstrip()
            if not base:
                texto = alternativo
            elif base.endswith((".", "!", "?", ":", ";")):
                texto = f"{base} {alternativo}"
            else:
                texto = f"{base}. {alternativo}"
    return texto


def _validar(accion: str, texto: str, estado: Dict[str, Any]) -> bool:
    """Chequeos finales antes de enviar texto generado."""
    plano = _sin_acentos(texto)

    # Regla del dueño: nunca ofrecer enviar el CV o el formulario por WhatsApp.
    if any(re.search(patron, plano) for patron in OFRECER_ENVIO):
        return False

    if accion == "error_formulario":
        # La redacción es libre, pero los ingredientes no son negociables y el
        # enlace alternativo lo exige el código. Si falta algo, se usa el texto
        # fijo de emergencia (que sí los trae todos).
        alternativo = link_formulario_alternativo()
        if not alternativo or alternativo not in texto:
            return False
        for nombre_ingrediente, patron in INGREDIENTES_ERROR.items():
            if not re.search(patron, plano):
                logger.info("Error de formulario sin '%s'; se usa el texto fijo", nombre_ingrediente)
                return False
        if any(re.search(patron, plano) for patron in PROMESA_FORMULARIO):
            return False
        return True

    if any(re.search(patron, plano) for patron in MENCIONES_FORMULARIO):
        return False

    if accion != "contexto":
        if any(re.search(patron, plano) for patron in DATOS_NO_AUTORIZADOS):
            return False

    if accion not in ("entregar_formulario", "reenviar_link"):
        if any(re.search(patron, plano) for patron in PROMESA_FORMULARIO):
            return False

    if accion == "contexto":
        # Si lo vuelven a pedir, se lo volvemos a dar: puede no haberlo leído,
        # o puede haber llegado después de entregar el formulario.
        necesarios = (
            "$25", "semanal", "bonificacion", "remoto",
            "ciertas condiciones", "contacta",
        )
        if not all(marca in plano for marca in necesarios):
            return False
        return True

    if accion in ("entregar_formulario", "reenviar_link"):
        link = link_formulario()
        if not link or link not in texto:
            return False
        if any(re.search(patron, plano) for patron in PREGUNTA_DATOS):
            return False

    return True


def _validar_primer_mensaje(texto: str, estado: Dict[str, Any]) -> bool:
    """
    El primer mensaje lo escribe la IA, pero tiene que presentarse y pedir los
    dos datos. Si se salta la identidad, se cae al saludo literal de respaldo.
    """
    if int(estado.get("turnos") or 0) != 1:
        return True
    plano = _sin_acentos(texto)
    nombre_bot, rol, empresa = identidad()
    return (
        _sin_acentos(nombre_bot) in plano
        and _sin_acentos(rol) in plano
        and _sin_acentos(empresa) in plano
        and ("nombre" in plano or "llam" in plano)
        and "oferta" in plano
    )


def _sin_pedir_datos(texto: str, estado: Dict[str, Any]) -> str:
    """
    Después de entregar el formulario no tiene sentido volver a pedir el nombre
    y la confirmación: eso es lo que hacía que el bot sonara como un bucle.
    """
    if not estado.get("link_enviado"):
        return texto

    # Los textos de respaldo piden nombre y confirmación "mientras tanto".
    # Después del formulario eso ya no tiene sentido: se saca la frase completa.
    partes = re.split(r"(?<=[.!?])\s+", texto)
    utiles = []
    for parte in partes:
        baja = _sin_acentos(parte)
        pide_nombre = "nombre" in baja or "llam" in baja
        pide_confirmacion = (
            "confirm" in baja
            or "viene por la oferta" in baja
            or "vienes por la oferta" in baja
            or "venis por la oferta" in baja
        )
        if pide_nombre and pide_confirmacion:
            continue
        utiles.append(parte)
    if not utiles:
        return texto
    resultado = " ".join(utiles).strip()
    return resultado or texto


def respuesta_determinista(
    accion: str,
    nombre: str,
    estado: Dict[str, Any],
) -> str:
    """Texto fijo de respaldo, leído de config/prompts.yaml."""
    link = link_formulario()
    nombre_bot, rol, empresa = identidad()

    if accion == "saludo":
        return mensaje("saludo", nombre=nombre_bot, rol=rol, empresa=empresa)
    if accion == "pedir_nombre":
        return mensaje("pedir_nombre")
    if accion == "pedir_confirmacion":
        return mensaje("pedir_confirmacion")
    if accion == "entregar_formulario":
        if not link:
            return mensaje("sin_link", nombre=nombre)
        return mensaje("despedida", nombre=nombre, link=link)
    if accion == "reenviar_link":
        if not link:
            return mensaje("sin_link", nombre=nombre)
        return mensaje("reenviar_link", link=link)
    if accion == "post_formulario":
        if nombre:
            return mensaje("post_formulario", nombre=nombre)
        return mensaje("post_formulario_sin_nombre")
    if accion == "contexto":
        datos = contexto_oferta()
        if estado.get("contexto_dado"):
            return _sin_pedir_datos(mensaje("contexto_repetido", **datos), estado)
        return mensaje("contexto", **datos)
    if accion == "error_formulario":
        alternativo = link_formulario_alternativo()
        if not alternativo:
            return mensaje("error")
        return mensaje("error_formulario", link_alternativo=alternativo)
    if accion == "humano":
        return _sin_pedir_datos(mensaje("humano"), estado)
    if accion == "ingles":
        return _sin_pedir_datos(mensaje("ingles"), estado)
    if accion == "fuera_de_linea":
        return _sin_pedir_datos(mensaje("fuera_de_linea"), estado)
    if accion == "continuar":
        # La IA se pasó de libre y se descartó: volvemos a lo esencial.
        if nombre:
            return mensaje("pedir_confirmacion")
        return mensaje("pedir_nombre", nombre=nombre)
    return ""


def _aplicar_estado(
    estado: Dict[str, Any],
    accion: str,
    nombre: str,
    confirmo: bool,
) -> None:
    estado["nombre"] = nombre
    estado["confirmo"] = confirmo
    estado["saludado"] = True
    if accion == "saludo":
        estado["etapa"] = "inicio"
    elif accion == "pedir_nombre":
        estado["etapa"] = "esperando_nombre"
    elif accion == "pedir_confirmacion":
        estado["etapa"] = "esperando_confirmacion"
    elif accion == "entregar_formulario":
        estado["etapa"] = "listo"
        estado["link_enviado"] = True
    elif accion == "contexto":
        estado["contexto_dado"] = True


def _es_real(accion: str) -> bool:
    """Señal informativa: respuestas que avanzan la conversación (historial aparte)."""
    return accion in (
        "saludo", "pedir_nombre", "pedir_confirmacion",
        "entregar_formulario", "reenviar_link", "error_formulario",
    )


async def procesar_turno(
    telefono: str,
    entrada: str,
    historial: List[dict],
) -> Tuple[str, Dict[str, Any], bool]:
    """Procesa un turno. Devuelve (respuesta, estado, es_respuesta_real)."""
    estado: Dict[str, Any] = dict(estado_vacio())
    estado.update(await get_estado(telefono))
    estado["turnos"] = int(estado.get("turnos") or 0) + 1

    texto = _limpiar_citas(unicodedata.normalize("NFKC", entrada or ""))
    if len(texto) > MAX_LONGITUD:
        texto = texto[:MAX_LONGITUD]

    malicioso, detalle = _detectar_malicioso(texto)
    if malicioso:
        logger.info("Texto rechazado de %s: %s", telefono, detalle)
        await guardar_estado(telefono, estado)
        return _sin_pedir_datos(mensaje("malicioso", detalle=detalle), estado), estado, False

    senales = {
        "error_formulario": _detecta_error_formulario(texto),
        "pide_contexto": _pide_contexto(texto),
        "pide_link": _pide_link(texto),
        "pide_humano": _pide_humano(texto),
        "es_ingles": _es_ingles(texto) and not _confirma(texto),
        "es_saludo": _es_saludo(texto),
        "es_fuera": _es_fuera(texto),
        "es_agradecimiento": _es_agradecimiento(texto),
    }

    nombre = str(estado.get("nombre") or "")
    es_pregunta = any(
        (senales["pide_contexto"], senales["pide_link"], senales["pide_humano"])
    )
    # Después de entregar el formulario ya no se buscan nombres: cualquier
    # frase corta ("ok, ya está") se tomaría como nombre y el bot quedaría
    # saludando a una persona inventada.
    extraido = ""
    if not estado.get("link_enviado"):
        extraido = _extraer_nombre(
            texto, str(estado.get("etapa") or "inicio"), solo_explicito=es_pregunta
        )
    if extraido:
        # Un nombre completo ya guardado no se degrada a uno más corto:
        # "Jose" después de "José Luis Rivera" no debe borrar los apellidos.
        if not nombre or len(extraido.split()) >= len(nombre.split()):
            nombre = extraido
    confirmo = bool(estado.get("confirmo")) or _confirma(texto)

    # Las decisiones de abajo deben ver los datos recién capturados, no los del
    # turno anterior (si no, el formulario se entrega un mensaje tarde).
    estado["nombre"] = nombre
    estado["confirmo"] = confirmo

    if senales["es_ingles"]:
        estado["saludado"] = True
        await guardar_estado(telefono, estado)
        return respuesta_determinista("ingles", nombre, estado), estado, False

    accion = ""
    texto_ia = ""
    if ia_disponible():
        propuesta = await generar_respuesta_ia(texto, historial, estado, senales)
        if propuesta:
            accion, texto_ia = propuesta

    if not accion or accion == "sugerido":
        # "sugerido" = el modelo escribió bien pero no respetó el JSON.
        # La acción sigue siendo decisión del código, nunca del modelo.
        accion = _accion_determinista(estado, nombre, confirmo, senales, texto)

    # El primer mensaje también lo genera la IA. Solo si no se presenta
    # correctamente volvemos al saludo literal (para no perder la identidad).
    if (
        estado["turnos"] == 1
        and not senales["error_formulario"]
        and texto_ia
        and not _validar_primer_mensaje(texto_ia, estado)
    ):
        logger.info("Primer mensaje de IA incompleto; se usa el saludo de respaldo")
        texto_ia = ""
        accion = "saludo"

    accion_ia = accion
    accion = _forzar_accion(accion, estado, senales)
    if accion == "post_formulario" and accion_ia != "post_formulario":
        # La IA quería reenviar o volver a pedir datos: se descarta su texto y
        # se usa el cierre corto, que no repite el enlace.
        texto_ia = ""
    if accion == "error_formulario" and accion_ia != "error_formulario":
        # Un texto escrito para otra acción no sirve para explicar el fallo.
        texto_ia = ""

    if accion == "sin_responder":
        estado["saludado"] = True
        await guardar_estado(telefono, estado)
        return "", estado, False

    if texto_ia:
        respuesta = _sin_pedir_datos(_preparar_texto(accion, texto_ia), estado)
        if respuesta and not _validar(accion, respuesta, estado):
            logger.info("Respuesta de IA descartada por validación: acción=%s", accion)
            respuesta = ""
        if respuesta:
            _aplicar_estado(estado, accion, nombre, confirmo)
            await guardar_estado(telefono, estado)
            return respuesta, estado, _es_real(accion)

    respuesta = respuesta_determinista(accion, nombre, estado)
    if not respuesta:
        await guardar_estado(telefono, estado)
        return "", estado, False

    _aplicar_estado(estado, accion, nombre, confirmo)
    await guardar_estado(telefono, estado)
    return respuesta, estado, _es_real(accion)
