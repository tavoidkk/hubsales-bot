"""config.py — carga centralizada de configuración del bot de reclutamiento.

Todas las rutas son absolutas para que funcione igual desde la raíz, desde
tests/ o desde un contenedor. `.env` se carga aquí, antes de que memory.py lea
DATABASE_URL (en la plantilla original se cargaba tarde y en local se ignoraba).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"

load_dotenv(BASE_DIR / ".env")


def _leer_yaml(ruta: Path) -> Dict[str, Any]:
    if not ruta.exists():
        return {}
    with ruta.open("r", encoding="utf-8") as f:
        datos = yaml.safe_load(f) or {}
    return datos if isinstance(datos, dict) else {}


def cargar_business() -> Dict[str, Any]:
    return _leer_yaml(CONFIG_DIR / "business.yaml")


def cargar_prompts() -> Dict[str, Any]:
    return _leer_yaml(CONFIG_DIR / "prompts.yaml")


def env(nombre: str, default: str = "") -> str:
    """Lee una variable de entorno y quita espacios accidentales."""
    return (os.environ.get(nombre, default) or "").strip()


def identidad() -> Tuple[str, str, str]:
    """Devuelve (nombre del bot, rol, empresa)."""
    business = cargar_business()
    agente = business.get("agente") or {}
    nombre = env("BOT_NAME") or str(agente.get("nombre") or "Sofía").strip()
    rol = str(agente.get("rol") or "reclutadora").strip()
    empresa = str(
        agente.get("empresa") or (business.get("negocio") or {}).get("nombre") or "HubSales Group"
    ).strip()
    return nombre, rol, empresa


def link_formulario() -> str:
    """El enlace obligatorio. FORM_LINK gana sobre el YAML (útil en Coolify)."""
    configurado = env("FORM_LINK")
    if configurado:
        return configurado
    business = cargar_business()
    formulario = business.get("formulario") or {}
    for valor in (formulario.get("link"), (business.get("agente") or {}).get("form_link")):
        if str(valor or "").strip():
            return str(valor).strip()
    return ""


def contexto_oferta() -> Dict[str, str]:
    """Datos internos de la oferta. Solo se entregan si el prospecto pregunta."""
    contexto = cargar_business().get("contexto_oferta") or {}
    return {str(clave): str(valor or "").strip() for clave, valor in contexto.items()}


def mensaje(clave: str, **valores: str) -> str:
    """Devuelve un mensaje literal de prompts.yaml con los campos rellenos."""
    textos = (cargar_prompts().get("mensajes") or {})
    plantilla = str(textos.get(clave) or "").strip()
    if not plantilla:
        return ""
    try:
        return plantilla.format(**valores)
    except (KeyError, IndexError, ValueError):
        # Si falta un valor, no inventamos texto: se reporta como error.
        return str(textos.get("error") or "Hubo un problema. Intente de nuevo.")
