# SyntaxGuard · Fase 4 — Resultados y evidencias

Pantalla de resultados del flujo `Cargar → Analizar → Entender`. Se construyó **sobre** la Fase 3 (no se reconstruyó nada): el backend no necesitó ningún cambio.

## 1. Diagnóstico: qué ya existía y qué faltaba

| Elemento pedido | Estado en la Fase 3 | Qué hizo la Fase 4 |
|---|---|---|
| SPAM / LEGÍTIMO | Existía (banner) | Se conserva; se añade la regla «SPAM si P(spam) ≥ 50,0 %» y el botón «Nuevo análisis» |
| P(spam) en % + umbral | Existía (barra con marca en 50 %) | Se conserva; se añaden cifras separadas: *Clasificación final*, *Umbral*, *Distancia al umbral* |
| Nivel de riesgo | **Faltaba** | Escala de 4 tramos (Bajo 0–25, Moderado 25–50, Alto 50–75, Muy alto 75–100) rotulada como *lectura orientativa de P(spam)*, no calibrada y no es confianza |
| Diferenciar P(spam) de la clasificación | Parcial | Explícito en el banner, las cifras y los textos; casos límite, redondeo e incoherencia se avisan |
| Remitente / destinatario / asunto / fecha | Existía | Se reutiliza (una sola implementación compartida) |
| Texto extraído | Solo en la vista previa | Ahora también en el resultado (pestaña «Texto extraído») con la marca de los 3.000 caracteres |
| Enlaces | Desplegable | Pestaña «Enlaces» con origen y dominio (informativo). Siguen siendo texto, no clicables |
| Características estructurales | **Faltaban** | Pestaña «Estructura»: solo datos que entregó `/correo/extraer` |
| Rasgos detectados | Existía | Pestaña «Rasgos» (activos por categoría + medidos sin activarse) |
| Advertencias / información no disponible | Solo en la vista previa | Tarjeta «Avisos sobre este análisis»: advertencias del backend + faltantes (sin cabeceras, sin HTML, sin enlaces) |
| Explicación comprensible | 3 viñetas | Acordeón de 5 preguntas (SPAM, LEGÍTIMO, qué es P(spam), por qué <50 % es LEGÍTIMO, limitaciones). «Limitaciones» muestra las métricas **reales de prueba** leídas de `/metricas` |
| Estados de carga / error / vacío | Existían | Se conservan; se añaden vacíos para rasgos, enlaces y métricas |
| Móvil | Parcial | Distribución propia: banner → probabilidad → correo analizado → evidencias → explicación |
| No perder el resultado / no duplicar solicitudes | Existía | Se conserva; además cambiar de pestaña no hace solicitudes y la pestaña elegida se recuerda |

## 2. Archivos

**Reemplazados (2):** `frontend/index.html` (+1 línea: enlace a `resultados.css`) y `frontend/js/vistas/analizar.js` (se eliminó el resultado antiguo y las piezas duplicadas; ahora usa los módulos nuevos).

**Nuevos:** `frontend/js/evidencias.js`, `frontend/js/vistas/resultado.js`, `frontend/css/resultados.css`, `backend/scripts/smoke_test_fase4.py`, `frontend/js/vistas/analizar.js.respaldo-fase3` (copia exacta de la versión anterior) y la carpeta `frontend/documentacion/fase4/` (este reporte, pruebas, capturas).

**No se tocó:** `detector.py`, `schemas.py`, `clasificador.pkl`, `metricas.json`, dataset, umbral 0,5, `requirements.txt`, `main.py`, `correo.py`, `rutas_correo.py`, `api.js`, `state.js`, `ui.js`, `router.js`. Sin dependencias nuevas. Sin commits ni push.

## 3. Resultados de las pruebas

| Prueba | Resultado |
|---|---|
| `smoke_test_fase4.py` (archivos protegidos por SHA-256, métricas, frontend, seguridad) | Superada |
| `smoke_test_frontend.py` (Fase 2/3) | Superada |
| `smoke_test_correo.py` (Fase 3) | Superada* |
| `probar_interfaz.py` (Fase 2, navegador) | 83/83 |
| `probar_flujo_fase3.py` (Fase 3, navegador) | 94/94 |
| `probar_resultados_fase4.py` (**nueva**, navegador) | **145/145** |

Las 145 pruebas nuevas cubren: A) clasificación y probabilidad en 0, 12, 42, 50, 97,3 y 100 %, redondeo e incoherencia, y los cortes exactos de la escala; B) evidencias contra lo que devuelve el backend, correos sin cabeceras, solo HTML, con adjunto y texto largo; C) explicación y carga única de `/metricas`; D) navegación, teclado, solicitudes sin duplicar, errores 503 y formato inesperado; E) seguridad (script, `<img onerror>`, `<iframe>`, `javascript:`, respuestas hostiles, cero peticiones a sitios externos); F) escritorio, móvil 390 y 360 px sin desbordamiento; G) pruebas «reales» sin interceptar `/predecir`.

### ⚠️ Limitación importante de estas pruebas
El ZIP que recibí **no incluye `clasificador.pkl` ni el dataset**, así que no pude ejecutar el modelo real. Lo que hice:

* Ejecuté todo contra un **detector falso** (`servidor_prueba_sin_modelo.py`) con el mismo formato de respuesta que `SpamDetector`. Todo lo demás (extracción, `/metricas`, interfaz) fue real.
* Por eso (*) en `smoke_test_correo.py` el mensaje «con el modelo real» **no** corresponde a tu modelo, y `smoke_test.py` (que exige el `.pkl`) **no pude ejecutarlo**.
* Las pruebas de la sección A y parte de D/E simulan la respuesta de `/predecir` en el navegador para forzar probabilidades exactas. Prueban cómo **dibuja** la interfaz, no al modelo.
* Entorno: Python 3.13, FastAPI 0.110.3 (el fijado), otras librerías más recientes que las de tu `requirements.txt`, Chromium sin pantalla en Linux.

**Tú debes ejecutar las pruebas con tu modelo real** (instrucciones abajo y en `INSTRUCCIONES_INSTALACION_FASE4.md`); la sección G de la prueba nueva lo verifica.

## 4. Decisiones de diseño (honestidad de la información)

* La clasificación es **siempre** `es_spam` del backend; la interfaz nunca la recalcula. Si `es_spam` y P(spam) no concuerdan con 0,5 se avisa y se respeta `es_spam`.
* El nivel de riesgo es una lectura de presentación; sus cortes (25/50/75 %) los eligió el proyecto, no el modelo, y así se rotula.
* Los rasgos se presentan como heurísticas, no como causas. Los enlaces no se llaman «maliciosos» ni son clicables; el dominio mostrado es solo informativo.
* Las métricas de «Limitaciones» salen de `/metricas` (sección `test`), rotuladas como cifras de prueba y no de validación.

## 5. Límites conocidos

* La pestaña de evidencias se recuerda al cambiar de sección, pero el resultado completo se pierde al recargar la página (como en la Fase 3; el historial es de otra fase).
* El backend no entrega la lista completa de variables del modelo ni el árbol HTML, por eso «Estructura» solo muestra datos de la lectura del correo.
* Pendiente de revisión humana en tu equipo: diálogo real de archivos de Windows, tu navegador habitual, correos tuyos reales y correos en español (el modelo se entrenó en inglés).
