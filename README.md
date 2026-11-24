# HubSales Group — bot de reclutamiento por WhatsApp

Bot reactivo que responde por WhatsApp con IA (OpenRouter) y sigue una línea fija:
pide nombre, confirma que la persona viene por **la oferta de vendedor que publicamos**
y le entrega el formulario `https://forms.gle/dW6Dj8XXJhzhZims7`.

- No se presenta como bot ni como IA: es Sofía, reclutadora de HubSales Group.
- Habla español con tono formal y cordial (trato de "usted"), en mensajes cortos de
  WhatsApp, sin markdown.
- La IA redacta; `agent/flow.py` decide la acción y aplica las reglas (guardrails).
- El formulario se entrega una sola vez. Después solo se reenvía si la persona lo
  pide explícitamente; el resto de los mensajes recibe un cierre corto.
- Datos de la oferta, solo si preguntan. Más información, solo si los contacta el equipo.
- Comparte cuenta de Zernio con el bot de Toyota, pero usa **otro número** y otro
  `ZERNIO_WEBHOOK_SECRET`. El webhook se filtra por `accountIds` y el código vuelve a
  verificar el `accountId` del mensaje.

## Probar en local

```powershell
cd C:\Users\user\dev\hubsales-bot
$env:PYTHONIOENCODING='utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

..\whatsapp-agentkit\.venv\Scripts\python.exe -m pytest -q
..\whatsapp-agentkit\.venv\Scripts\python.exe tests\chat_local.py
```

En `tests/chat_local.py` se usa `WHATSAPP_PROVIDER=mock`: no sale nada por WhatsApp.
Comandos del chat: `salir`, `limpiar`, `estado`.

## Variables de entorno

Copiar `.env.example` a `.env` y completar. El `.env` está en `.gitignore`: **nunca subirlo**.

| Variable | Valor |
|---|---|
| `BOT_NAME` | `Sofía` (opcional) |
| `FORM_LINK` | link del formulario (tiene prioridad sobre `config/business.yaml`) |
| `LLM_PROVIDER` | `openrouter` |
| `OPENROUTER_API_KEY` | key de OpenRouter |
| `OPENROUTER_MODEL` | `deepseek/deepseek-v4.1-flash-1017` |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` |
| `OPENROUTER_MAX_TOKENS` | `700` (no subir sin revisar costos) |
| `IA_MODO` | `determinista` fuerza textos fijos, sin gasto de tokens |
| `WHATSAPP_PROVIDER` | `zernio` en producción, `mock` para pruebas |
| `ZERNIO_API_KEY` | misma cuenta que Toyota, empieza con `sk_` |
| `ZERNIO_WEBHOOK_SECRET` | **distinto** del de Toyota |
| `ZERNIO_ACCOUNT_ID` | accountId del número nuevo de HubSales |
| `PORT` | `8000` |
| `ENVIRONMENT` | `production` en Coolify |
| `DATABASE_URL` | `sqlite+aiosqlite:////data/hubsales.db` (volumen persistente) |

## Deploy y configuración

Ver [`docs/DEPLOY.md`](docs/DEPLOY.md): Zernio (sandbox y número propio), Coolify y
campaña de Meta (click-to-WhatsApp).

Estado del servicio: `GET /` o `GET /health` devuelve proveedor, conexión y si el
formulario está configurado. No expone el link ni secretos.
