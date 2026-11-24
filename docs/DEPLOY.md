# Deploy e integración — HubSales Group

Orden recomendado: **GitHub → Coolify → Zernio → Meta (campaña)**.
No tocar el bot de Don McGill Toyota: el webhook de Zernio de ese bot se deja igual.

---

## 1. GitHub

El repo es `https://github.com/tavoidkk/hubsales-bot` (público, vacío).
La imagen de Coolify se construye desde ese repo. El `.env` NO se sube.

---

## 2. Coolify (servicio separado)

1. **New resource → Application** (o *Service*), conectar GitHub y elegir
   `tavoidkk/hubsales-bot`, rama `main`.
2. **Build Pack:** `Dockerfile`. El Dockerfile ya usa `PORT` y expone `8000`.
3. **Puerto interno:** `8000`. Coolify se encarga del dominio y HTTPS.
4. **Persistent Storage:** montar un volumen en `/data` (dentro del contenedor).
   Sin ese volumen, el SQLite se borra en cada redeploy.
5. **Environment variables** (en la pestaña de variables del servicio):

```env
BOT_NAME=Sofía
FORM_LINK=https://forms.gle/dW6Dj8XXJhzhZims7
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=deepseek/deepseek-v4.1-flash-1017
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MAX_TOKENS=700
WHATSAPP_PROVIDER=zernio
ZERNIO_API_KEY=sk_...
ZERNIO_WEBHOOK_SECRET=...
ZERNIO_ACCOUNT_ID=...
PORT=8000
ENVIRONMENT=production
DATABASE_URL=sqlite+aiosqlite:////data/hubsales.db
```

   Si se usa `docker-compose.yml` en vez de Dockerfile directo, el compose ya fija
   `DATABASE_URL` y el volumen; no hace falta repetirlos.

6. **Health check:** ruta `/` (o `/health`). Respuesta esperada:

```json
{"status":"ok","service":"hubsales-reclutamiento","proveedor":"ProveedorZernio", ...}
```

   Si `status` es `degradado`, mirar el campo `conexion.detalle`: dice qué falta.
7. **Dominio:** generar dominio en Settings → Networking. Queda algo como
   `https://hubsales-xxx.coolify.app`. Esa URL (sin `/webhook`) se usa en el paso 4.

> No agregar `PORT` manualmente si Coolify lo inyecta; el Dockerfile respeta el valor.

### ¿Se puede automatizar con `COOLIFY_DEPLOY_KEY`?

Sí, por API, pero con el token **solo** no alcanza: además hace falta la URL de la
instancia (ej. `https://coolify.tudominio.com`) y el proyecto/servidor donde crear
el recurso. El token **no debe ir en el `.env` del bot**: `docker-compose.yml`
inyecta todas las variables al contenedor y quedaría dentro de la imagen en
ejecución. Guardarlo fuera del repo (por ejemplo en un archivo local aparte) o
pasarlo en la sesión de trabajo, nunca en `README.md`, `docs/` ni `.env.example`.

---

## 3. Zernio — sin haber comprado el número (sandbox)

El sandbox tiene un número compartido y sirve para probar hoy mismo.

**Paso 1 — API key.** En Zernio → Settings → API Keys → Create API Key. La key
empieza con `sk_` y solo se muestra una vez. Pegarla en `ZERNIO_API_KEY` del `.env`.

**Paso 2 — Secreto propio.** Elegir un texto largo y aleatorio para
`ZERNIO_WEBHOOK_SECRET`, distinto del secreto del bot de Toyota.

**Paso 3 — Ver el sandbox.** Con el intérprete que ya tiene las dependencias:

```powershell
..\whatsapp-agentkit\.venv\Scripts\python.exe scripts\zernio_setup.py estado
```

Copiar el `accountId` del sandbox en `ZERNIO_ACCOUNT_ID` del `.env` (solo para esta
prueba). Si la cuenta tiene otros números, no confundirlos.

**Paso 4 — Activar tu celular como probador.**

```powershell
..\whatsapp-agentkit\.venv\Scripts\python.exe scripts\zernio_setup.py activar +13465551234
```

Reemplazar por tu número en formato E.164. Te llega un WhatsApp desde el número
compartido: **responderlo** desde el celular. Verificar con:

```powershell
..\whatsapp-agentkit\.venv\Scripts\python.exe scripts\zernio_setup.py sesiones
```

La sesión dura 7 días con 50 mensajes/día. Si ya hay otro teléfono activo,
`revocar <session_id>` y repetir.

**Paso 5 — URL pública temporal.** Primero arrancar el servidor local con el `.env`
de HubSales en otra terminal:

```powershell
..\whatsapp-agentkit\.venv\Scripts\python.exe -m uvicorn agent.main:app --port 8000
```

Después levantar un túnel:


```powershell
cloudflared tunnel --url http://localhost:8000
```

(o `ngrok http 8000`). Copiar la URL `https://...` que muestre.

**Paso 6 — Crear el webhook del bot.** En otra terminal:

```powershell
..\whatsapp-agentkit\.venv\Scripts\python.exe scripts\zernio_setup.py webhook https://TU-URL-TEMPORAL
```

El script le agrega `/webhook`, usa el secreto del `.env` y manda
`"accountIds": ["<ZERNIO_ACCOUNT_ID>"]`. Eso evita que lleguen mensajes de Toyota.

**Paso 7 — Confirmar el filtro.**

```powershell
..\whatsapp-agentkit\.venv\Scripts\python.exe scripts\zernio_setup.py webhooks
```

Buscar `HubSales Group — Reclutamiento`. Debe decir
`filtro: cuentas: <accountId del sandbox>`. El webhook de Toyota: **no tocarlo**.

**Paso 8 — Probar.**

```powershell
..\whatsapp-agentkit\.venv\Scripts\python.exe scripts\zernio_setup.py webhook-test <webhook_id>
```

Después escribir `hola` al número compartido desde el celular activado. El log del
servidor debe mostrar el mensaje y la respuesta de Sofía.

---

## 4. Zernio — cuando compres el número propio

1. Dashboard de Zernio → **Connections → Connect new → WhatsApp**.
2. Completar el **Embedded Signup** de Meta: elegir/crear la cuenta de WhatsApp
   Business (WABA), la página de Facebook asociada y el número nuevo.
   El número debe estar verificado ante Meta para campañas; Zernio guía ese paso.
3. Ejecutar `estado` y copiar el `accountId` del **número nuevo** en
   `ZERNIO_ACCOUNT_ID` (reemplaza el del sandbox).
4. En Coolify actualizar `ZERNIO_ACCOUNT_ID` y `ENVIRONMENT=production`, redesplegar.
5. Crear el webhook definitivo apuntando al dominio de Coolify:

```powershell
..\whatsapp-agentkit\.venv\Scripts\python.exe scripts\zernio_setup.py webhook https://TU-DOMINIO-COOLIFY
```

6. Verificar con `webhooks` que el nuevo tenga `cuentas: <accountId real>`.
   Solo después de confirmarlo, pausar/borrar el webhook de prueba del sandbox.
   **Nunca borrar el webhook de Toyota.**
7. Mandar un mensaje real desde otro celular al número nuevo y revisar el log.

Nota: `Zernio webhook.test` ignora `accountIds`, pero el bot solo procesa eventos
`message.received`; además `agent/providers/zernio.py` descarta mensajes cuyo
`accountId` no sea el configurado. Doble barrera para no cruzar bots.

---

## 5. Meta — conectar la campaña al número

El Embedded Signup de Zernio deja la WABA vinculada a tu portafolio de Meta.

1. **Verificar el negocio:** Business Manager → Configuración → Verificación del
   negocio. Sin esto Meta puede no dejar usar el número en anuncios.
2. **Confirmar el número:** WhatsApp Manager → números de teléfono → el número
   nuevo debe figurar como conectado/activo.
3. **Asociar la página:** en WhatsApp Manager, seleccioná el número → **Páginas**
   y vinculá la página de Facebook que vas a usar en el anuncio. Si usás
   Instagram, vinculá también esa cuenta desde el administrador de chats.
4. **Crear la campaña en Ads Manager:**
   - Objetivo: **Mensajes** (si no aparece, *Ventas* o *Leads* con destino
     **WhatsApp**, según la versión del administrador).
   - Destino: **WhatsApp** → elegir la página y **el número nuevo de HubSales**
     (verificar bien que no sea el de Toyota).
   - Audiencia, presupuesto y programación según la campaña.
   - En el anuncio, CTA **Enviar mensaje** / **Chatear con WhatsApp**.
5. **Mensaje inicial sugerido (recomendado):** cargar como texto pre-rellenado algo
   como `Hola, vengo por la oferta de vendedor que publicamos`. El bot es
   **reactivo**: necesita que la persona envíe el primer mensaje para responder.
   Con el texto sugerido, el candidato llega con la confirmación casi lista; el bot
   solo le pide el nombre y le pasa el formulario.
6. **Prueba final:** publicar la campaña, hacer clic en el anuncio desde un celular
   de prueba, enviar el mensaje y confirmar que Sofía responde (dentro de la
   ventana de 24 horas, siempre por ser reactiva).

Regla de oro: en Meta y en Zernio, seleccionar siempre el **número nuevo**. El de
Toyota pertenece a otro bot y debe seguir funcionando con su propio webhook.
