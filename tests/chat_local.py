"""chat_local.py — chat por terminal, sin WhatsApp y sin red.

Usa el flujo real (agent/flow.py) con el proveedor mock. Sirve para probar el
recorrido completo antes de conectar el número de Zernio.

Comandos:
  salir    cierra el chat
  limpiar  borra el estado y el historial de este teléfono de prueba
  estado   muestra los datos que el bot ya capturó
"""

from __future__ import annotations

import asyncio
import os
import sys

# Consola de Windows: imprime acentos en vez de "Sof?a".
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# El .env real no debe afectar la prueba local.
os.environ.setdefault("WHATSAPP_PROVIDER", "mock")

from agent.flow import procesar_turno  # noqa: E402
from agent.memory import (  # noqa: E402
    clear_history,
    get_estado,
    guardar_mensaje,
    inicializar_db,
    obtener_historial,
    reset_estado,
)

TELEFONO = "local-chat"


async def main() -> None:
    await inicializar_db()
    await clear_history(TELEFONO)
    await reset_estado(TELEFONO)

    print()
    print("=" * 60)
    print("   HubSales Group — Chat local (sin WhatsApp)")
    print("=" * 60)
    print()
    print("  Escribí como si fueras un candidato.")
    print("  Comandos: salir | limpiar | estado")
    print()
    print("-" * 60)
    print()

    while True:
        try:
            mensaje = input("Candidato: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nChat finalizado.")
            break

        if not mensaje:
            continue

        if mensaje.lower() == "salir":
            print("\nChat finalizado.")
            break

        if mensaje.lower() == "limpiar":
            await clear_history(TELEFONO)
            await reset_estado(TELEFONO)
            print("[Estado borrado]\n")
            continue

        if mensaje.lower() == "estado":
            print(f"[Estado: {await get_estado(TELEFONO)}]\n")
            continue

        historial = await obtener_historial(TELEFONO)
        respuesta, estado, real = await procesar_turno(TELEFONO, mensaje, historial)

        if respuesta:
            print(f"\nBot: {respuesta}")
            print(f"     [etapa={estado.get('etapa')} | real={real}]\n")
        else:
            print("\nBot: (sin respuesta)\n")

        # Igual que en producción: toda la conversación entra al historial para
        # que la IA vea lo que ya dijo y no se repita. "real" es solo informativo.
        await guardar_mensaje(TELEFONO, "user", mensaje)
        if respuesta:
            await guardar_mensaje(TELEFONO, "assistant", respuesta)


if __name__ == "__main__":
    asyncio.run(main())
