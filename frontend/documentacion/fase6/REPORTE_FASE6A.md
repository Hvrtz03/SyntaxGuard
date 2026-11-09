# SyntaxGuard — Informe de la Fase 6A (backend, autenticación y seguridad)

Alcance: **solo backend**. No se creó ninguna pantalla de login/registro ni se tocó la navegación del frontend (Fase 6B).
Contrato para el frontend: `frontend/documentacion/FASE6_CONTRATO_API.md`.

## 1. Qué se implementó

* Registro, login, logout y consulta de sesión (`POST /auth/registro`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`).
* Contraseñas con PBKDF2-HMAC-SHA256, sal aleatoria de 16 bytes, 600 000 iteraciones (formato `pbkdf2_sha256$iter$sal$hash`; se actualiza solo si se suben las iteraciones).
* Sesiones: token de 256 bits (`secrets`); en SQLite solo se guarda su HMAC-SHA256 con `SG_SECRET_KEY`. Expiración absoluta (7 días) e inactividad (24 h), revocación (logout, revocación total, usuario desactivado), tope de 10 sesiones por usuario y rotación al iniciar sesión.
* Cookie `sg_sesion`: `HttpOnly`, `SameSite=Strict`, `Path=/`, `Secure` en HTTPS / `SG_COOKIE_SECURE=1` / producción.
* CSRF: token ligado a la sesión (HMAC), enviado en `X-CSRF-Token`; más validación de `Origin`/`Referer` del mismo sitio.
* Límite de intentos: por usuario+IP, por usuario y por IP, guardado en SQLite; límite de registros por IP. Respuestas `429` con `Retry-After`.
* Migración SQLite segura, idempotente y atómica (`almacen.migrar`): tablas `usuarios`, `sesiones`, `intentos_acceso`; `user_id` en `lotes` y `analisis`; índices; `PRAGMA user_version = 6`; respaldo automático previo (`syntaxguard.db.pre_fase6.bak`) si había datos de la Fase 5.
* Aislamiento por usuario aplicado en el SQL de la capa de almacenamiento (`user_id` es argumento obligatorio de todas las funciones) y en servicio/rutas: historial, detalle, eliminación (uno y varios), retroalimentación, lotes, análisis masivos, errores de archivo, estadísticas y CSV. El `user_id` sale solo de la sesión.
* Registros antiguos: se conservan con `user_id = NULL`; no se asignan a nadie y ningún usuario puede verlos ni manipularlos.
* Secretos solo por variables de entorno (sin claves en el código). Sin `SG_SECRET_KEY`: clave aleatoria en memoria (con advertencia); con `SG_ENTORNO=produccion` o clave < 32 caracteres el servidor no arranca.
* Corrección encontrada por las pruebas: un id mayor que 2^63 en `/historial/{id}`, `/lotes/{id}` o `X-Lote-Id` provocaba HTTP 500 (`OverflowError`, ya existía en la Fase 5); ahora responde 404/422.

## 2. Archivos

**Nuevos**

| Archivo | Para qué |
|---|---|
| `backend/app/seguridad.py` | PBKDF2, tokens, HMAC, CSRF, validación de datos, configuración por entorno |
| `backend/app/usuarios.py` | Usuarios, sesiones, límite de intentos (SQLite) |
| `backend/app/dependencias.py` | Dependencias FastAPI: sesión, origen, CSRF, cookies, errores |
| `backend/app/rutas_auth.py` | Router `/auth/*` |
| `backend/scripts/test_auth_fase6.py` | Pruebas de autenticación y seguridad (22 grupos) |
| `backend/scripts/test_aislamiento_fase6.py` | Aislamiento e IDOR entre 3 usuarios (11 grupos) |
| `backend/scripts/test_migracion_fase6.py` | Migración y registros antiguos (8 grupos) |
| `backend/scripts/auth_helper.py` | Ayuda para que las pruebas inicien sesión (solo pruebas) |
| `backend/scripts/generar_ejemplos_contrato_fase6.py` | Genera los ejemplos reales del contrato |
| `frontend/documentacion/FASE6_CONTRATO_API.md` | Contrato de API para la Fase 6B |
| `frontend/documentacion/fase6/REPORTE_FASE6A.md` y `evidencias/` | Este informe y la salida real de cada prueba |

**Modificados**

| Archivo | Cambio |
|---|---|
| `backend/app/almacen.py` | Migración, tablas nuevas, `user_id` obligatorio y filtrado en todas las consultas, corrección de desbordamiento de enteros |
| `backend/app/servicio.py` | `user_id` obligatorio en registrar/analizar |
| `backend/app/rutas_historial.py`, `rutas_analisis.py`, `rutas_correo.py` | Dependencia `exigir_usuario` en todo el router y `user_id` de la sesión |
| `backend/app/main.py` | Valida la configuración al arrancar, router `/auth`, `/predecir` protegido (contrato intacto), manejadores de error de autenticación |
| `backend/scripts/smoke_test.py`, `smoke_test_correo.py`, `smoke_test_frontend.py`, `smoke_test_fase4.py`, `smoke_test_fase5.py`, `test_almacen_servicio.py` | Adaptadas para iniciar sesión / pasar `user_id` y usar base temporal (la lógica comprobada es la misma) |
| `ejecutable/probar_todo.bat` | Agrega las 3 pruebas nuevas; retira la prueba 7 (Chromium de la Fase 5) porque la interfaz aún no inicia sesión |
| `.env.example`, `.gitignore`, `README.md` | Variables `SG_*`, respaldo `.bak` ignorado, sección de la Fase 6A |

**Sin modificar (SHA-256 verificado antes y después):** `detector.py`, `schemas.py`, `clasificador.pkl`, `metricas.json`, `dataset.csv`, `requirements.txt`. No se agregaron dependencias. No se hicieron commits.

## 3. Resultados REALES de las pruebas

Ejecutadas en Linux con Python 3.12.3, las dependencias exactas de `requirements.txt` instaladas en un entorno virtual limpio, el modelo real `clasificador.pkl`, spaCy `en_core_web_sm` 3.7.1 y NLTK. La salida completa está en `evidencias/`.

| Prueba | Resultado |
|---|---|
| `smoke_test.py` (Fase 1, detector y API) | OK |
| `smoke_test_correo.py` (Fases 2/3, 35 correos reales, paridad 100 %) | OK |
| `smoke_test_frontend.py` | OK |
| `smoke_test_fase4.py` | OK |
| `test_almacen_servicio.py` (Fase 5, detector SIMULADO, 21 grupos) | OK |
| `smoke_test_fase5.py` (Fase 5, API y modelo real, 17 grupos) | OK |
| `test_auth_fase6.py` | OK, 22 grupos |
| `test_aislamiento_fase6.py` | OK, 11 grupos |
| `test_migracion_fase6.py` | OK, 8 grupos |
| `probar_concurrencia.py` (informativa) | 0 diferencias, 0 errores |

Además se comprobó que las pruebas detectan fallos: al quitar temporalmente el filtro de propietario del detalle, al desactivar la comprobación CSRF y al hacer que el logout no revoque en el servidor, las pruebas fallaron como debían (el código se restauró).

**No se ejecutó (límites declarados):**

* `frontend/documentacion/fase5/pruebas/probar_interfaz_fase5.py` (Chromium): fallaría hasta la Fase 6B porque la interfaz no inicia sesión; no se ejecutó.
* No se probó en Windows ni con Python 3.11 (el entorno de pruebas fue Linux/3.12). El código usa solo la biblioteca estándar y las dependencias ya existentes.
* No se probó con HTTPS real ni detrás de un proxy: `Secure` y `X-Forwarded-*` se verificaron con el cliente de pruebas, simulando HTTPS y cabeceras.
* No se hizo prueba de carga ni auditoría externa de seguridad.

## 4. Cómo ejecutar el backend (Windows, PowerShell, desde la raíz del proyecto)

```powershell
# 1. Una vez: crear .env y fijar la clave del servidor
copy .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # pega el resultado en SG_SECRET_KEY= dentro de .env

# 2. Iniciar (crea el entorno e instala dependencias la primera vez; migra la base de datos sola)
.\ejecutable\iniciar.bat

# 3. Probar (con el entorno virtual creado por iniciar.bat)
.\ejecutable\probar_todo.bat
# o una por una:
.\.venv\Scripts\python.exe backend\scripts\test_auth_fase6.py
.\.venv\Scripts\python.exe backend\scripts\test_aislamiento_fase6.py
.\.venv\Scripts\python.exe backend\scripts\test_migracion_fase6.py
```

Prueba manual rápida con la API en marcha (`Invoke-RestMethod` / curl deben enviar `Origin`):

```powershell
curl.exe -i -c cj.txt -H "Origin: http://127.0.0.1:8000" -H "Content-Type: application/json" -d "{\"usuario\":\"ana\",\"contrasena\":\"una-clave-larga-2026\"}" http://127.0.0.1:8000/auth/registro
curl.exe -b cj.txt http://127.0.0.1:8000/auth/me
```

Si ya tienes una base de datos de la Fase 5 en `backend/storage/`, se migra al arrancar y se crea antes `syntaxguard.db.pre_fase6.bak`. Esos datos antiguos quedarán **sin propietario** (invisibles para todos los usuarios). Si quieres asignarlos a alguien, hay que decidirlo explícitamente en otra fase.

## 5. Consecuencias y decisiones para tener presentes

* **La interfaz web actual no puede analizar correos hasta la Fase 6B**: sus llamadas privadas recibirán 401.
* El identificador de cuenta es un **nombre de usuario** (no correo electrónico): el prompt no pidió correo ni verificación.
* El registro **abre sesión** automáticamente (201 con cookie).
* Sin `SG_SECRET_KEY` fija las sesiones se invalidan al reiniciar el servidor. Con varios procesos (workers) la clave debe estar fijada en `.env`; `run.py` usa un solo proceso.
* `/docs`, `/redoc` y `/openapi.json` siguen públicos (comportamiento previo); conviene desactivarlos si el servicio se expone a internet.
* Un atacante que conozca un usuario puede bloquear su inicio de sesión **desde su propia IP**, pero no el del dueño legítimo desde otra IP, salvo con 20 fallos distribuidos (bloqueo de 15 min). Es el compromiso habitual entre fuerza bruta y denegación de servicio.
* Las respuestas de error 404 de `/historial/{id}` no llevan `Cache-Control: no-store` (no contienen datos); las respuestas con datos sí.

## 6. Pendiente para otras fases

Pantallas de login/registro y manejo de sesión expirada en el frontend (Fase 6B, siguiendo la sección 9 del contrato), cambio/recuperación de contraseña, verificación de correo, eliminación de cuenta, endpoint de “cerrar todas las sesiones” (la función `usuarios.revocar_sesiones_usuario` ya existe) y decidir qué hacer con los registros antiguos sin propietario.
