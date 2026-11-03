# Reporte de pruebas — Fase 2 (cascarón y sistema de diseño)

Fecha: 30 de octubre de 2026.
Este reporte distingue lo que **se ejecutó** de lo que **no se ejecutó**. Todas las salidas citadas están guardadas en `docs/fase2/pruebas/`.

## 1. Entorno donde se ejecutaron las pruebas

| Elemento | Valor |
|---|---|
| Sistema | Linux 6.18 (entorno en la nube del asistente). **No es Windows.** |
| Python | 3.11.18, en un entorno virtual propio, fuera del proyecto |
| Dependencias | Las de `requirements.txt` instaladas con sus versiones exactas (fastapi 0.110.3, uvicorn 0.29.0, pydantic 2.7.1, scikit-learn 1.4.2, numpy 1.26.4, pandas 2.2.2, spacy 3.7.5, nltk 3.9.1, etc.) y `en_core_web_sm` 3.7.1 |
| Navegador | Chromium 153 con Playwright 1.63 (Python 3.13 del sistema) |
| Proyecto probado | Copia independiente del ZIP original + los 17 archivos de la Fase 2 |

Tu proyecto local, `.venv` y `.venv_respaldo` no participaron en ninguna prueba.

## 2. Integridad: lo que no debía cambiar, no cambió

Comparación de hashes SHA-256 entre el proyecto original y el proyecto integrado:

| Elemento | Resultado |
|---|---|
| `models/clasificador.pkl`, `models/metricas.json` | Idénticos |
| `data/` completa (4.450 archivos, incluido `dataset.csv`) | Idéntica (hash combinado igual) |
| `app/detector.py`, `app/schemas.py` | Idénticos |
| `scripts/train.py`, `scripts/build_dataset.py`, `scripts/smoke_test.py` | Idénticos |
| `requirements.txt` | Idéntico |
| `app/main.py` | **Modificado** (solo añadidos; ver sección 3) |
| `README.md` | **Modificado** (el texto original queda íntegro; se añadió una sección al final) |
| 15 archivos de `frontend/` y `scripts/smoke_test_frontend.py` (16 en total) | Nuevos |

## 3. Backend original: comparación antes y después

Se capturaron las respuestas de la API sobre una copia sin cambios (línea base) y sobre el proyecto integrado, con 12 llamadas fijas:

- `GET /salud`, `GET /metricas`.
- `POST /predecir` con: spam con HTML engañoso, spam solo texto, correo normal, URL con IP, texto vacío, falta de `texto`, texto de 20.001 caracteres y HTML de 200.001 caracteres.
- `POST /salud` y `GET /predecir` (deben dar 405).

**Resultado: las 12 respuestas son idénticas byte a byte** (`cmp` sin diferencias). Valores observados, iguales en ambas versiones: spam con HTML 0,8267; spam solo texto 0,8167; correo normal 0,1233 (no spam); URL con IP 0,7033; los cuatro casos inválidos devolvieron 422 y los dos métodos incorrectos 405.

Qué cambió exactamente en `app/main.py` (se comparó contra el original; el original sin cambios se conservó aparte en la carpeta de respaldo del asistente): se añadieron los imports `mimetypes`, `Path`, `FileResponse` y `StaticFiles`; la constante `FRONTEND_DIR`; y, al final y solo si existe `frontend/`, el registro de los tipos MIME `.js`/`.css`, el montaje de `/static` y la ruta `GET /`. Los tres endpoints no se tocaron.

## 4. Pruebas ejecutadas

| # | Prueba | Resultado real |
|---|---|---|
| 1 | `python scripts/smoke_test.py` sobre la copia **sin** cambios | Superada (`salida_smoke_test_linea_base.txt`) |
| 2 | `python scripts/smoke_test.py` sobre el proyecto integrado | Superada (`salida_smoke_test_integrado.txt`) |
| 3 | `python scripts/smoke_test_frontend.py` | Superada: 6 bloques de verificación OK, incluidos 14 archivos estáticos con MIME correcto, importaciones entre módulos JS y bloqueo de salida de `frontend/` (`salida_smoke_test_frontend.txt`) |
| 4 | Comparación de 12 respuestas de la API antes/después | Idénticas |
| 5 | Navegador real (Chromium) contra `uvicorn` en ejecución, escritorio 1366×860 y móvil 390×844 | **83 comprobaciones, 83 correctas, 0 fallas** (`salida_probar_interfaz.txt`, `resultados_interfaz.json`) |
| 6 | Registro del servidor durante la prueba 5 | Solo respuestas 200; sin errores ni trazas |

La prueba 5 verifica, en escritorio y en móvil:
- La raíz abre `#/analisis`.
- El chip de la API indica "Modelo cargado" y el pie muestra "API v1.0.0".
- Existen 5 elementos de menú, y cada uno abre su vista con el título y el `<title>` correctos y queda marcado como activo.
- No hay desplazamiento horizontal en ninguna vista.
- En Análisis, `/salud` y `/metricas` aparecen como "Conectado", con los valores reales de `metricas.json` (2.000 filas, F1 0,9407).
- El botón de prueba de `/predecir` responde desde la interfaz (spam, 81,7 %, 8 rasgos).
- El enlace directo `#/metricas` funciona, una ruta inexistente vuelve a `#/analisis` y atrás/adelante no rompen la aplicación.
- No hay errores ni avisos de consola, ni peticiones fallidas, ni respuestas HTTP ≥ 400.
- Con la API bloqueada, el chip pasa a "API sin conexión", el pie a "versión desconocida" y las filas de Análisis muestran un error legible.
- `/docs`, `/salud` y `/metricas` siguen funcionando abiertos directamente en el navegador.

**Limitaciones de estas 83 comprobaciones:** 10 de ellas (la de "indicador de pasos" en cada vista y viewport) son muy débiles, porque aceptan 0 o 1 indicador. La presencia correcta del indicador se verificó viendo las capturas. La revisión visual la hizo el asistente sobre las capturas; no es una prueba automática.

## 5. Capturas (`docs/fase2/capturas/`)

14 imágenes: las 5 vistas y el estado de API caída, más Análisis antes de pulsar el botón de prueba, en escritorio (`escritorio_*.png`) y móvil (`movil_*.png`, escala 2×).
En móvil el menú lateral pasa a una barra horizontal desplazable.

## 6. No ejecutado / no verificado

- **Ejecución en Windows con VS Code y tu `.venv`.** No se pudo hacer desde este entorno. Debes comprobarlo con las instrucciones de `INSTRUCCIONES_INTEGRACION.md`. El riesgo específico de Windows (tipo MIME de `.js`) está cubierto en `main.py`, pero no verificado en Windows.
- **Navegadores distintos de Chromium** (Edge, Firefox, Safari) y **dispositivos físicos**.
- Las "41 comprobaciones" y la revisión de Playwright que reportó la conversación anterior **no se pudieron reproducir ni verificar**, porque no se entregó su detalle. Este reporte las sustituye con las pruebas de arriba.
- Accesibilidad más allá de lo básico (lector de pantalla, contraste medido) y rendimiento.
- Todo lo correspondiente a las Fases 3 a 6, que no se tocó.

## 7. Observaciones (sin cambios realizados)

1. **No fue necesario corregir ningún archivo de la Fase 2.** Los 17 archivos se integraron tal como llegaron.
2. **Formato numérico.** `frontend/js/ui.js` usa `es-ES` (coma decimal: "0,9407", "81,7 %", "2.000"). El propio comentario del archivo indica que para punto decimal estilo México basta cambiar `LOCALE_NUMEROS` a `es-MX`. No lo cambié porque no se me pidió; es una decisión tuya.
3. **Vistas pendientes.** Historial, Métricas, Retroalimentación y Acerca de son tarjetas "En construcción" (Fase 5) por diseño. Análisis tiene una comprobación temporal de conexión que la Fase 3 reemplazará.
4. **Pendientes previos del diagnóstico**, que siguen sin tocarse: sesgo por HTML, 2.000 de 4.403 filas usadas, modelo en inglés, CORS abierto (`*`) y `en_core_web_sm` que no está en `requirements.txt` (se instala aparte con `python -m spacy download`).
5. `scripts/smoke_test_frontend.py` y los scripts de `docs/fase2/pruebas/` son pruebas, no parte del funcionamiento de la aplicación. Playwright **no** se agregó a `requirements.txt`.
