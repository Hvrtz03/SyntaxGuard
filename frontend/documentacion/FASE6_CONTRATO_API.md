# SyntaxGuard — Contrato de API de la Fase 6A (autenticación y sesiones)

Este documento es el contrato que usará el frontend de la Fase 6B. **No se cambiará sin justificación.**
Todos los ejemplos son respuestas reales del backend implementado (generadas con
`backend/scripts/generar_ejemplos_contrato_fase6.py`; los valores aleatorios aparecen abreviados con `…`).

> **Importante:** desde la Fase 6A todos los endpoints privados exigen sesión. La interfaz web de la Fase 5 (que no
> inicia sesión) recibirá `401` en esos endpoints hasta que la Fase 6B agregue las pantallas de login y registro.

---

## 1. Resumen en 30 segundos

1. Al cargar la aplicación: `GET /auth/me`. Si responde `200`, hay sesión (y trae el token CSRF). Si responde `401`, mostrar login.
2. Registro o login: `POST /auth/registro` o `POST /auth/login` con JSON `{usuario, contrasena}`. El servidor guarda la sesión en una **cookie HttpOnly** (el JavaScript no la ve ni la toca) y devuelve en el JSON un **`csrf_token`**.
3. Guardar `csrf_token` **solo en memoria** (variable JS). No usar `localStorage` ni `sessionStorage`.
4. En **cada solicitud que modifica datos** (`POST`, `PUT`, `PATCH`, `DELETE`) enviar la cabecera `X-CSRF-Token: <csrf_token>`. Las lecturas (`GET`) no la necesitan.
5. Si cualquier endpoint responde `401`, la sesión terminó: volver a la pantalla de login.
6. Cerrar sesión: `POST /auth/logout` con `X-CSRF-Token`.

El frontend se sirve desde el mismo origen que la API (FastAPI sirve `/static`), así que **no hace falta CORS ni `credentials`
especiales**: `fetch` envía la cookie automáticamente (`credentials: "same-origin"` es el valor por defecto).
El navegador agrega solo la cabecera `Origin`; el frontend **no debe** intentar fijarla.

---

## 2. Endpoints de autenticación

Todos los cuerpos son JSON (`Content-Type: application/json`) y todas las respuestas llevan `Cache-Control: no-store`.

### 2.1 `POST /auth/registro` — crear cuenta (y abrir sesión)

Cuerpo:

```json
{"usuario": "ana", "contrasena": "una-clave-larga-2026"}
```

Respuesta `201` (con `Set-Cookie`, ver sección 4):

```
HTTP 201
set-cookie: sg_sesion=tvdaTx…(43 caracteres); HttpOnly; Max-Age=604799; Path=/; SameSite=strict
cache-control: no-store
```
```json
{
  "usuario": {"id": 1, "usuario": "ana", "creado_en": "2026-11-07T20:15:00Z"},
  "csrf_token": "4d52e202…(64 hex)",
  "sesion": {"expira_en": "2026-11-07T20:15:00Z"}
}
```

Reglas de los datos:

| Campo | Regla |
|---|---|
| `usuario` | 3 a 32 caracteres: letras minúsculas sin acento, números, `.`, `-`, `_`; empieza con letra o número. Se normaliza (`"Ana"` → `"ana"`, sin espacios en los extremos). No distingue mayúsculas. |
| `contrasena` | 10 a 128 caracteres. No puede ser solo espacios, un único carácter repetido, una contraseña muy común ni contener el nombre de usuario. |

Errores:

| HTTP | `codigo` | Cuándo |
|---|---|---|
| 409 | `usuario_duplicado` | El usuario ya existe |
| 422 | `datos_invalidos` | Datos que no cumplen las reglas, o cuerpo incompleto / mal formado |
| 429 | `demasiados_intentos` | Más de 10 registros por hora desde la misma IP |
| 403 | `origen_no_permitido` | La solicitud no viene de la misma página (ver sección 7) |

```json
// 409
{"detail": "Ese nombre de usuario ya está en uso.", "codigo": "usuario_duplicado",
 "campos": {"usuario": "Ese nombre de usuario ya está en uso."}}
```
```json
// 422 (los mensajes de "campos" están listos para mostrarse junto a cada campo del formulario)
{
  "detail": "Los datos de registro no son válidos.",
  "codigo": "datos_invalidos",
  "campos": {
    "usuario": "El usuario debe tener de 3 a 32 caracteres: letras minúsculas sin acento, números, punto, guion o guion bajo, y empezar con letra o número.",
    "contrasena": "La contraseña debe tener al menos 10 caracteres."
  }
}
```
```json
// 422 con cuerpo incompleto o de tipo incorrecto (misma forma; "campos" lista los campos con problema)
{"detail": "Los datos enviados no son válidos.", "codigo": "datos_invalidos",
 "campos": {"contrasena": "Dato ausente o con formato inválido."}}
```

### 2.2 `POST /auth/login` — iniciar sesión

Cuerpo: igual que el registro. Respuesta `200` con la **misma forma** que el registro (`usuario`, `csrf_token`, `sesion`) y un `Set-Cookie` nuevo.
Cada inicio de sesión crea un token nuevo y revoca la cookie anterior del navegador, si la había. Se permiten varias sesiones
simultáneas (máximo 10 por usuario; al pasar de 10 se revocan las más antiguas).

| HTTP | `codigo` | Cuándo |
|---|---|---|
| 200 | — | Correcto |
| 401 | `credenciales_invalidas` | Usuario o contraseña incorrectos. **El mensaje es idéntico** si el usuario no existe (no se puede averiguar qué cuentas existen) |
| 429 | `demasiados_intentos` | Demasiados intentos fallidos (ver 2.5) |
| 403 | `origen_no_permitido` | Origen no permitido |
| 422 | `datos_invalidos` | Cuerpo incompleto o mal formado |

```json
// 401
{"detail": "Usuario o contraseña incorrectos.", "codigo": "credenciales_invalidas"}
```

### 2.3 `GET /auth/me` — consultar la sesión actual

No necesita CSRF. Respuesta `200`:

```json
{
  "usuario": {"id": 1, "usuario": "ana", "creado_en": "2026-11-07T20:15:00Z"},
  "csrf_token": "a0a2f723…(64 hex)",
  "sesion": {"expira_en": "2026-11-07T20:15:00Z"}
}
```

El `csrf_token` de una sesión **no cambia** mientras la sesión viva: es el mismo que devolvió el login. `/auth/me` sirve para
recuperarlo después de recargar la página (el token está solo en memoria, así que se pierde al recargar).

Errores `401`:

```json
{"detail": "Debes iniciar sesión.", "codigo": "no_autenticado"}
```
```json
{"detail": "Tu sesión expiró o ya no es válida. Inicia sesión de nuevo.", "codigo": "sesion_expirada"}
```

`no_autenticado` = el navegador no envió cookie. `sesion_expirada` = envió una cookie que ya no sirve (expirada, revocada,
usuario desactivado o inválida); en ese caso el servidor además **borra la cookie** con `Set-Cookie ... Max-Age=0`.
El frontend puede tratar ambos igual (ir al login) y usar el código solo para el texto ("Inicia sesión" o "Tu sesión expiró").

### 2.4 `POST /auth/logout` — cerrar sesión

Cabeceras: `X-CSRF-Token: <csrf_token>`. Sin cuerpo. Revoca la sesión **en el servidor** (un token copiado deja de servir) y borra la cookie.

```json
// 200
{"cerrada": true, "habia_sesion": true}
```

| HTTP | `codigo` | Cuándo |
|---|---|---|
| 200 | — | Cerrada. Es idempotente: sin sesión válida también responde `200` con `"habia_sesion": false` y borra la cookie |
| 403 | `csrf_invalido` | Hay sesión válida pero falta el token CSRF o es incorrecto (la sesión **no** se cierra) |
| 403 | `origen_no_permitido` | Origen no permitido |

Tras el logout, el frontend debe borrar su `csrf_token` de memoria y mostrar el login.

### 2.5 Límite de intentos de inicio de sesión

Los fallos se cuentan en una ventana de 15 minutos:

* 5 fallos del mismo usuario desde la misma IP → bloqueo de ese par.
* 20 fallos del mismo usuario desde cualquier IP → bloqueo del usuario (ataque distribuido).
* 30 fallos desde la misma IP con cualquier usuario → bloqueo de la IP.

Mientras hay bloqueo, **incluso la contraseña correcta** recibe `429` y no se abre sesión. Se aplica igual a usuarios que no existen.
El bloqueo termina solo y se guarda en la base de datos (sobrevive al reinicio del servidor).

```
HTTP 429
retry-after: 900
```
```json
{"detail": "Demasiados intentos fallidos. Espera antes de volver a intentar.",
 "codigo": "demasiados_intentos", "reintentar_en_segundos": 900}
```

El frontend debe mostrar el mensaje y deshabilitar el botón durante `reintentar_en_segundos`.

---

## 3. Endpoints públicos y privados

**Públicos (no exigen sesión):**

| Endpoint | Nota |
|---|---|
| `GET /salud` | Sin cambios |
| `GET /metricas` | Sin cambios: devuelve exactamente `metricas.json` |
| `POST /auth/registro`, `POST /auth/login` | Exigen `Origin` válido, no exigen sesión ni CSRF |
| `POST /auth/logout` | Exige `Origin`; exige CSRF solo si hay sesión válida |
| `GET /`, `GET /static/...` | La interfaz estática (HTML, CSS, JS) |
| `GET /docs`, `GET /redoc`, `GET /openapi.json` | Documentación automática de FastAPI |

**Privados (exigen sesión; los que modifican datos exigen además `Origin` válido y `X-CSRF-Token`):**

| Método y ruta | CSRF | Qué hace (contrato de la Fase 5, sin cambios en entrada/salida) |
|---|---|---|
| `GET /auth/me` | no | Usuario y token CSRF de la sesión |
| `POST /predecir` | **sí** | `{texto, html?}` → `{es_spam, probabilidad, rasgos_detectados}` |
| `POST /correo/extraer` | **sí** | Cuerpo crudo (.eml o texto) → campos extraídos |
| `POST /lotes` | **sí** | `{total?}` → `{id, creado_en, total_previsto}` (el lote queda a nombre del usuario) |
| `GET /lotes/{id}` | no | Resumen del lote |
| `POST /analisis/archivo` | **sí** | Cuerpo crudo + `X-Nombre-Archivo`, `X-Lote-Id` → análisis guardado |
| `POST /historial` | **sí** | Guarda un análisis individual ya hecho |
| `GET /historial` | no | Lista paginada con filtros `q, clasificacion, desde, hasta, tipo, lote_id, solo_ok, pagina, por_pagina` |
| `GET /historial/exportar.csv` | no | CSV (mismos filtros) |
| `GET /historial/{id}` | no | Detalle (con sus retroalimentaciones) |
| `DELETE /historial/{id}` | **sí** | Elimina uno |
| `POST /historial/eliminar` | **sí** | `{ids: [...]}` → `{eliminados: n}` |
| `POST /retroalimentacion` | **sí** | `{analisis_id, de_acuerdo, comentario?}` |
| `GET /retroalimentacion` | no | Lista (filtro `analisis_id`) |
| `GET /estadisticas/uso` | no | Estadísticas de uso |

Las formas de entrada y salida de los endpoints privados **no cambian** respecto a la Fase 5 (ver
`frontend/documentacion/fase5/`). Lo único nuevo en ellos: exigen sesión, `Origin`, `X-CSRF-Token` en los métodos que modifican datos y
sus respuestas llevan `Cache-Control: no-store`.

Respuesta real de `GET /historial` de un usuario recién creado:

```json
{"items": [], "total": 0, "pagina": 1, "por_pagina": 25, "paginas": 1}
```

### Cada usuario solo ve sus datos

Historial, detalle, eliminación, retroalimentación, lotes, análisis masivos, errores de archivo, estadísticas y CSV son **privados de cada usuario**.
El dueño siempre es el usuario de la sesión; el servidor ignora cualquier `user_id` que envíe el cliente (el frontend **no debe enviarlo**).
Un id que pertenece a otro usuario responde **igual que un id inexistente**:

```
GET /historial/999   (inexistente o de otro usuario)
HTTP 404
{"detail": "El análisis no existe."}
```

Esto incluye `GET /lotes/{id}` (404) y usar un lote ajeno en `X-Lote-Id` (404). Los registros anteriores a la Fase 6 no pertenecen a nadie y
no son visibles para ningún usuario.

---

## 4. La cookie de sesión

```
Set-Cookie: sg_sesion=<token de 43 caracteres>; HttpOnly; Max-Age=604799; Path=/; SameSite=strict
```

| Atributo | Valor |
|---|---|
| Nombre | `sg_sesion` |
| `HttpOnly` | siempre: JavaScript **no puede leerla** (`document.cookie` no la muestra). El frontend no la maneja |
| `SameSite` | `Strict` por defecto (configurable a `Lax` con `SG_COOKIE_SAMESITE`) |
| `Secure` | se agrega automáticamente cuando la página se sirve por HTTPS, o siempre con `SG_COOKIE_SECURE=1` / `SG_ENTORNO=produccion` |
| `Path` | `/` |
| `Max-Age` | tiempo restante hasta la expiración absoluta (7 días por defecto) |

Vida de la sesión: **expira a los 7 días** de iniciada (`SG_SESION_MAX_HORAS`) **o tras 24 horas sin usarse** (`SG_SESION_INACTIVIDAD_HORAS`), lo que ocurra primero.
Usar la aplicación renueva la inactividad, no la expiración absoluta. El servidor guarda solo un HMAC del token, nunca el token.

Para borrar la cookie el servidor envía `sg_sesion=""; Max-Age=0; Path=/`. El navegador la elimina solo.

---

## 5. Token CSRF

* Se recibe en el JSON de `registro`, `login` y `me` como `csrf_token` (64 caracteres hexadecimales).
* Está ligado a la sesión: el de otra sesión o usuario no sirve. Cambia con cada inicio de sesión.
* Guardarlo **solo en una variable en memoria**. Tras recargar la página se recupera con `GET /auth/me`.
* Enviarlo en la cabecera `X-CSRF-Token` en todo `POST`, `PUT`, `PATCH` y `DELETE` privado (incluido `POST /auth/logout`).

```
POST /predecir
Origin: http://testserver          <- lo agrega el navegador
X-CSRF-Token: <csrf_token>
{"texto": "WINNER!! Claim your FREE prize now"}

HTTP 200
{"es_spam": true, "probabilidad": 0.81, "rasgos_detectados": [{"rasgo": "txt_mayusculas", "categoria": "texto", "valor": 0.4074, "activo": true, "descripcion": "Alta densidad de letras mayúsculas"}, "…"]}
```

Sin el token (o con uno incorrecto):

```
POST /predecir   (sin X-CSRF-Token)
HTTP 403
{"detail": "Falta el token CSRF o no es válido.", "codigo": "csrf_invalido"}
```

---

## 6. Encabezados de las solicitudes

| Cabecera | Cuándo | Quién la pone |
|---|---|---|
| `Cookie: sg_sesion=...` | siempre que haya sesión | el navegador, automáticamente |
| `Origin` | `POST`/`PUT`/`PATCH`/`DELETE` | el navegador, automáticamente |
| `X-CSRF-Token` | `POST`/`PUT`/`PATCH`/`DELETE` privados | **el frontend** |
| `Content-Type: application/json` | cuerpos JSON (`/auth/*`, `/predecir`, `/historial`, `/lotes`, `/retroalimentacion`) | el frontend |
| `Content-Type: message/rfc822` o `text/plain` + `X-Nombre-Archivo`, `X-Lote-Id` | `/correo/extraer`, `/analisis/archivo` (cuerpo crudo, sin multipart ni JSON) | el frontend (como en la Fase 5) |

Clientes que **no** son un navegador (curl, scripts) deben enviar ellos mismos `Origin` con el mismo host que la URL, por ejemplo
`-H "Origin: http://127.0.0.1:8000"`, además de `Cookie` y `X-CSRF-Token`.

---

## 7. Origen (protección adicional contra CSRF)

En todo método que modifica datos (y en login, registro y logout) el servidor exige `Origin` (o `Referer` si falta `Origin`) del
**mismo sitio** que la API (mismo host y puerto). Si falta, es `null` o es de otro sitio:

```
HTTP 403
{"detail": "Origen no permitido.", "codigo": "origen_no_permitido"}
```

Si algún día la API se publica detrás de otro nombre de host, se agregan los orígenes permitidos con `SG_ORIGENES_PERMITIDOS`
(lista separada por comas, p. ej. `https://app.ejemplo.com`). No se admite que otra página (otro origen) use la sesión con CORS: la política de CORS no concede credenciales.

---

## 8. Resumen de códigos HTTP y `codigo` de error

Errores de autenticación y seguridad: `{"detail": "<mensaje en español>", "codigo": "<código estable>", ...extras}`.
Programar la lógica con `codigo` (estable), mostrar `detail` (texto para personas).

| HTTP | `codigo` | Significado | Qué hace el frontend |
|---|---|---|---|
| 200 / 201 | — | Correcto | — |
| 401 | `no_autenticado` | Sin cookie de sesión | Mostrar login |
| 401 | `sesion_expirada` | Cookie inválida, expirada o revocada | Mostrar login con "Tu sesión expiró" |
| 401 | `credenciales_invalidas` | Login incorrecto | Mensaje en el formulario |
| 403 | `csrf_invalido` | Falta/incorrecto `X-CSRF-Token` | Ver sección 9 (renovar el token una vez) |
| 403 | `origen_no_permitido` | `Origin` ausente o ajeno | Error inesperado en un navegador normal: mostrar mensaje genérico |
| 409 | `usuario_duplicado` | Usuario ya existe | Mensaje en el campo usuario |
| 422 | `datos_invalidos` | Validación en `/auth/*` | Mostrar `campos` junto a cada campo |
| 429 | `demasiados_intentos` | Límite de intentos o de registros | Mostrar espera (`reintentar_en_segundos`, cabecera `Retry-After`) |

Los demás endpoints conservan los errores de la Fase 5: `{"detail": "texto"}` (404, 422 de validación propia, 415, 503...) y, para
errores de validación de FastAPI en rutas que no son `/auth/*`, `{"detail": [ {...} ]}`.

---

## 9. Cómo debe comportarse el frontend cuando la sesión expira

Cualquier endpoint privado puede responder `401` en cualquier momento (pasaron 7 días, 24 h sin uso, se revocó la sesión o se
reinició el servidor sin `SG_SECRET_KEY` fija). Regla única:

1. Si una respuesta es **`401`** (con `no_autenticado` o `sesion_expirada`): borrar el `csrf_token` y el usuario de la memoria,
   cancelar las solicitudes pendientes y navegar a la pantalla de login, mostrando "Tu sesión expiró. Inicia sesión de nuevo."
   No reintentar automáticamente. Conservar lo que el usuario estaba escribiendo si es posible.
2. Si una respuesta es **`403` con `csrf_invalido`**: llamar una vez a `GET /auth/me`. Si responde `200`, guardar el nuevo `csrf_token` y
   **reintentar la solicitud una sola vez**; si responde `401`, aplicar la regla 1.
3. Si es **`429`**: no reintentar; informar la espera.
4. Al cargar la aplicación (y al volver a la pestaña tras mucho tiempo) llamar `GET /auth/me` para decidir qué pantalla mostrar.
5. Un análisis masivo en curso debe detenerse al primer `401` (no seguir enviando archivos).

Ejemplo de envoltura de `fetch` basada en este contrato:

```js
let csrfToken = null;                       // solo en memoria

async function api(ruta, opciones = {}, reintento = true) {
  const metodo = (opciones.method || "GET").toUpperCase();
  const cabeceras = { ...(opciones.headers || {}) };
  if (metodo !== "GET" && metodo !== "HEAD" && csrfToken) cabeceras["X-CSRF-Token"] = csrfToken;
  const r = await fetch(ruta, { ...opciones, headers: cabeceras });   // la cookie va sola

  if (r.status === 401) { csrfToken = null; mostrarLogin("Tu sesión expiró. Inicia sesión de nuevo."); throw new Error("sin_sesion"); }
  if (r.status === 403 && reintento) {
    const err = await r.clone().json().catch(() => ({}));
    if (err.codigo === "csrf_invalido") {
      const me = await fetch("/auth/me");
      if (me.ok) { csrfToken = (await me.json()).csrf_token; return api(ruta, opciones, false); }
      csrfToken = null; mostrarLogin("Tu sesión expiró. Inicia sesión de nuevo."); throw new Error("sin_sesion");
    }
  }
  return r;
}

async function iniciarSesion(usuario, contrasena) {
  const r = await fetch("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
                                          body: JSON.stringify({ usuario, contrasena }) });
  const datos = await r.json();
  if (r.ok) csrfToken = datos.csrf_token;
  return { ok: r.ok, estado: r.status, datos };         // datos.codigo, datos.campos, datos.reintentar_en_segundos
}
```

---

## 10. Variables de entorno (las pone quien ejecuta el backend, no el frontend)

| Variable | Valor por defecto | Para qué |
|---|---|---|
| `SG_SECRET_KEY` | *(aleatoria en memoria)* | Clave del servidor (≥ 32 caracteres) para el HMAC del token de sesión y del token CSRF. **Defínela**: sin ella las sesiones se pierden al reiniciar. Obligatoria con `SG_ENTORNO=produccion` |
| `SG_ENTORNO` | `desarrollo` | `produccion` exige `SG_SECRET_KEY` y fuerza cookie `Secure` |
| `SG_COOKIE_SECURE` | `0` | `1` fuerza `Secure` |
| `SG_COOKIE_SAMESITE` | `strict` | `strict` o `lax` |
| `SG_SESION_MAX_HORAS` | `168` | Expiración absoluta |
| `SG_SESION_INACTIVIDAD_HORAS` | `24` | Expiración por inactividad |
| `SG_SESIONES_MAX` | `10` | Sesiones simultáneas por usuario |
| `SG_LOGIN_MAX_INTENTOS` | `5` | Fallos por usuario+IP en la ventana (usuario = ×4, IP = ×6) |
| `SG_LOGIN_VENTANA_SEG` | `900` | Ventana y duración del bloqueo |
| `SG_REGISTRO_MAX_POR_HORA` | `10` | Registros por IP y hora |
| `SG_ORIGENES_PERMITIDOS` | *(vacío)* | Orígenes extra aceptados (lista separada por comas) |
| `SG_CONFIAR_PROXY` | `0` | `1` solo detrás de un proxy propio: usa `X-Forwarded-For/Proto/Host` |
| `SG_PBKDF2_ITER` | `600000` | Iteraciones de PBKDF2 (no bajar en producción; solo se reduce en las pruebas) |

---

## 11. Qué no hace la Fase 6A (queda para otras fases)

Pantallas de login y registro, cambio y recuperación de contraseña, verificación de correo electrónico, eliminación de cuenta y endpoint
para cerrar todas las sesiones. La función de revocación total existe en el backend (`usuarios.revocar_sesiones_usuario`) y queda lista para exponerse.
