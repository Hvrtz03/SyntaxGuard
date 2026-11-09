# SyntaxGuard · Fase 5 — Reporte de pruebas

> **Leer primero.** Las pruebas de este reporte se ejecutaron en un entorno **sin FastAPI, sin spaCy/NLTK y sin el modelo real**
> (no se podían instalar: sin red; además el entorno tiene scikit-learn 1.9.1 y el modelo exige 1.4.2).
> Por eso hay dos grupos, y nunca se mezclan:
> * **Ejecutadas aquí** — con un **detector SIMULADO** (marcado en cada fila). Prueban el almacenamiento, la lógica, la interfaz y su
>   integración, **no el modelo**. La extracción de correos (`app/correo.py`), la base de datos SQLite y los correos del corpus son reales.
> * **Pendientes de ejecutar en tu Windows con el MODELO REAL** — el código de prueba ya está escrito (`ejecutable\probar_todo.bat`).
>   **No las doy por aprobadas.**

## A. Ejecutadas en esta sesión

| # | Prueba | Detector | Resultado | Evidencia |
|---|---|---|---|---|
| A1 | `backend/scripts/test_almacen_servicio.py`: SQLite, lotes, errores como registros, filtros, paginación, búsqueda (sin inyección SQL), retroalimentación, estadísticas, CSV (BOM y fórmulas), eliminación en cascada, persistencia en un proceso nuevo, D1 (el `.db` no contiene cuerpo ni URL completas), protegidos | **Simulado** (12 correos reales del corpus + casos de error) | **21/21 grupos OK** | `evidencias/salida_test_almacen_servicio_DETECTOR_SIMULADO.txt` |
| A2 | Lógica de los **routers reales** (`rutas_analisis.py`, `rutas_historial.py`): 12 rutas registradas, orden de `/historial/exportar.csv` antes de `/historial/{id}`, 415/404/validaciones | Simulado, con módulos **sustitutos** de fastapi/pydantic (no es FastAPI real) | OK | `evidencias/salida_verificacion_routers_MODULOS_SUSTITUTOS.txt` |
| A3 | `fase5/pruebas/probar_interfaz_fase5.py` en **Chromium**: recorrido de los 10 pasos, masivo (archivos, carpeta con subcarpeta, arrastrar/soltar, quitar, vaciar, duplicados, progreso, cambio de sección, resumen, filtros, búsqueda, detalle, CSV, **cancelación**), historial (filtros, fechas, paginación, eliminar uno/varios, CSV), métricas, retroalimentación, acerca de, **persistencia tras reiniciar el servidor**, responsivo 390/768/1280 px, sin errores de consola | **Simulado** (`servidor_prueba_fase5.py`) | **84/84** (6 ejecuciones seguidas limpias) | `evidencias/salida_interfaz_fase5_DETECTOR_SIMULADO.txt` |
| A4 | Regresión **Fase 3** (`probar_flujo_fase3.py`) | Backend simulado | **94/94** | `evidencias/regresion_fase3_BACKEND_SIMULADO.json` |
| A5 | Regresión **Fase 4** (`probar_resultados_fase4.py`) | Backend simulado (las pruebas «(real)» usaron el detector simulado) | **145/145** | `evidencias/regresion_fase4_BACKEND_SIMULADO.json` |
| A6 | Regresión **Fase 2** (`probar_interfaz.py`) | Backend simulado | **82/83**. Único fallo: `GET /docs` → 404, porque el servidor simulado no ofrece Swagger (FastAPI real sí). **No es un fallo del proyecto; se confirma en Windows** | `evidencias/regresion_fase2_BACKEND_SIMULADO.json` |
| A7 | Integridad de archivos protegidos (comparación byte a byte con el original y SHA-256) | — | **Todos idénticos** | `LISTA_ARCHIVOS_FASE5.md` |
| A8 | Reglas estáticas heredadas de la Fase 4 en el código nuevo (sin `innerHTML`/`eval`, sin `<a>` en resultado/analizar/evidencias, sin `localStorage`) | — | Cumplidas (por revisión del mismo patrón que usa `smoke_test_fase4.py`) | — |

Cambios en suites antiguas (documentados en cada archivo): formato es-MX (`97.3 %`, `1.1 KB`, `2,000`) y 6 elementos de menú.
Todas las fallas intermedias fueron de la prueba (esperas, selectores, formato) y se corrigieron; no se debilitó ninguna comprobación.

## B. PENDIENTES — requieren tu Windows y el MODELO REAL

| # | Prueba | Comando | Qué demuestra |
|---|---|---|---|
| B1 | Regresión: `smoke_test.py`, `smoke_test_correo.py`, `smoke_test_frontend.py`, `smoke_test_fase4.py` | `ejecutable\probar_todo.bat` (pasos 1–4) | Los endpoints originales y el modelo siguen igual (estas pruebas necesitan FastAPI y el modelo) |
| B2 | `smoke_test_fase5.py` (API real + modelo real, BD temporal) | pasos 6 | Endpoints nuevos con FastAPI real (códigos 201/404/415/422), CORS, CSV, persistencia, y que **cada resultado del análisis masivo coincide exactamente con `/correo/extraer` + `/predecir`** |
| B3 | Interfaz en Chromium contra el servidor real | paso 7 (`--servidor-real`) | El mismo recorrido de 84 comprobaciones con el modelo real |
| B4 | `probar_concurrencia.py` | paso 8 | Si el detector compartido es seguro en paralelo. **Hasta tener este resultado la concurrencia sigue en 1** |
| B5 | Regresión Fase 2 `GET /docs` | automático al correr la suite de la Fase 2 con el servidor real | Que Swagger sigue disponible |
| B6 | Tiempo por correo del análisis masivo | lo imprime `smoke_test_fase5.py` | Rendimiento real (no lo he medido) |

## C. Limitaciones conocidas de la verificación
- Arrastrar y soltar **una carpeta** (recorrido recursivo con `webkitGetAsEntry`) no se pudo automatizar; sí se probaron arrastrar archivos y el selector de carpeta (que incluye subcarpetas).
- Solo se probó Chromium. El selector de carpeta depende del navegador; si no existe, el botón se desactiva y se explica.
- La capa FastAPI (validación Pydantic, serialización, códigos 422) se verifica por primera vez con B2.
