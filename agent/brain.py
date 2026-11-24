"""brain.py — punto único para el mensaje de error.

La generación con IA vive en `agent/ia.py` y la Decide la máquina de estados en
`agent/flow.py`. Este módulo se conserva como interfaz estable para `main.py`
y para los textos de respaldo de config/prompts.yaml.
"""

from __future__ import annotations

from .config import mensaje


def obtener_mensaje_error() -> str:
    return mensaje("error") or "Estoy teniendo un problema técnico momentáneo. ¿Me repites eso, por favor?"
