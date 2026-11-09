# SyntaxGuard · Fase 3 — Carga, extracción, análisis y resultado

Flujo implementado en el navegador (HTML + CSS + JavaScript puro, servido por FastAPI):

```
Elegir / arrastrar / pegar  →  POST /correo/extraer  →  vista previa segura
        →  «Analizar correo»  →  POST /predecir (modelo real)  →  SPAM o LEGÍTIMO + P(spam) + rasgos
```

## 1. Qué cambió

**Archivos nuevos**

| Archivo | Para qué sirve |
|---|---|
| `frontend/css/analisis.css` | Estilos de la zona de carga, pestañas, vista previa, resultado y móvil |
| `frontend/documentacion/fase3/pruebas/probar_flujo_fase3.py` | 94 pruebas en navegador real (Chromium/Playwright) |
| `frontend/documentacion/fase3/REPORTE_PRUEBAS_FASE3.md` | Este reporte |

**Archivos modificados (solo se añadió; no se quitó nada)**

| Archivo | Cambio |
|---|---|
| `frontend/js/vistas/analizar.js` | Reemplazado: la vista completa del flujo. La comprobación de conexión de la Fase 2 se conserva en un panel plegable |
| `frontend/js/api.js` | `pedir()` acepta cuerpo crudo y cabeceras; nueva función `api.extraerCorreo()` (no hay un segundo cliente) |
| `frontend/js/state.js` | Nuevo campo `analisis` (el flujo no se pierde al cambiar de sección) |
| `frontend/js/ui.js` | Nuevas `fmtBytes()` y `actualizarPasos()` |
| `frontend/js/iconos.js` | 8 iconos nuevos |
| `frontend/index.html` | 1 línea: enlace a `analisis.css` |
| `frontend/documentacion/fase2/pruebas/probar_interfaz.py` | 1 línea: despliega el panel de diagnóstico (ahora plegable) antes de leerlo |

**No se tocó:** `detector.py`, `schemas.py`, `clasificador.pkl`, `metricas.json`, el dataset, `router.js`, `app.js`, ni los endpoints `/salud`, `/metricas` y `/predecir`.

## 2. Decisiones de diseño (todo basado en lo que devuelve el backend)

- **Probabilidad:** se muestra como «Probabilidad de spam» (P(spam)), con una marca en el umbral de 50 %. Se aclara que no es una medida de certeza.
- **Rasgos:** solo los que devuelve `/predecir`. Los que tienen `activo = true` se muestran como «detectados»; los que tienen `activo = false` van aparte, como «medidos sin activarse».
- **Enlaces:** salen de `/correo/extraer` y se rotulan como «encontrados en el correo». No se presentan como rasgos del modelo y no son clicables.
- **Límites reales avisados en pantalla:** el modelo se entrenó con correos en inglés y solo analiza los primeros 3.000 caracteres del texto (la vista previa marca dónde cae el corte).
- **Seguridad:** todo dato del correo se inserta como nodo de texto. El HTML solo aparece como código dentro de un `<pre>`. No hay `innerHTML` con datos externos.

## 3. Cómo ejecutarlo

```powershell
cd C:\ruta\a\SyntaxGuard
# con tu entorno virtual activado
python ejecutable\run.py          # abre http://127.0.0.1:8000
```

Si el navegador muestra la versión anterior, recarga sin caché con **Ctrl + F5**.

## 4. Pruebas automatizadas (ya ejecutadas)

Se ejecutaron en un entorno aislado con las versiones de `requirements.txt` (Python 3.12, Linux) y Chromium sin pantalla.

| Prueba | Resultado |
|---|---|
| `backend/scripts/smoke_test.py` (original) | Superada |
| `backend/scripts/smoke_test_frontend.py` (original, todos los archivos estáticos) | Superada |
| `backend/scripts/smoke_test_correo.py` (backend de extracción + correos reales) | Superada |
| `frontend/documentacion/fase2/pruebas/probar_interfaz.py` (interfaz de la Fase 2, escritorio y móvil) | 83/83 |
| `frontend/documentacion/fase3/pruebas/probar_flujo_fase3.py` (flujo completo en navegador) | **94/94** |

La prueba del flujo cubre, con correos reales del corpus (ya recortados a `.eml`) y sintéticos:

- **A.** Camino feliz completo: los datos de la vista previa coinciden con `/correo/extraer`, y la clasificación, la probabilidad y los rasgos coinciden con una llamada directa a `/predecir`. Una sola llamada a `/predecir`. Consola limpia.
- **B.** Arrastrar y soltar: resaltado de la zona, soltar un archivo, varios archivos y formato no admitido.
- **C.** Pegar contenido: vacío, correo completo y solo el cuerpo («No disponible» y aviso de que faltan cabeceras).
- **D.** Archivos inválidos: `.pdf`, vacío, de más de 5 MB (sin llamar al servidor), sin extensión, binario, correo sin texto.
- **E.** Quitar y cambiar de archivo.
- **F.** Estado de carga y tres clics seguidos = una sola llamada.
- **G.** Fallos de conexión, error HTTP 500, respuesta con formato inesperado y reintento.
- **H.** Navegación entre secciones sin perder el estado ni el paso del indicador.
- **I.** Teclado (Tab, Enter, flechas entre pestañas) y foco.
- **J.** Seguridad: correo con `<script>`, `<img onerror>`, `javascript:`, `<iframe>`, asunto y remitente con etiquetas, nombre de archivo con `<b>`. No se ejecuta nada y no se hace ninguna petición a sitios externos.
- **K.** Móvil (390 px): sin desbordamiento horizontal.
- **L.** Endpoints originales intactos (`/metricas` sigue en 0,9533 y 175/4/10/111).

Las capturas están en `frontend/documentacion/fase3/capturas/`.

Para repetirlas:

```powershell
pip install playwright
playwright install chromium
python frontend\documentacion\fase3\pruebas\probar_flujo_fase3.py http://127.0.0.1:8000 frontend\documentacion\fase3\capturas frontend\documentacion\fase3\pruebas\resultados_fase3.json
```

Opcional, con correos reales del corpus (el corpus no trae extensión, hay que copiarlos como `.eml`):

```powershell
Copy-Item (Get-ChildItem backend\data\spam\00001.* | Select-Object -First 1) $env:TEMP\spam1.eml
Copy-Item (Get-ChildItem backend\data\easy_ham\0001.* | Select-Object -First 1) $env:TEMP\ham1.eml
python frontend\documentacion\fase3\pruebas\probar_flujo_fase3.py http://127.0.0.1:8000 capturas resultados.json --spam $env:TEMP\spam1.eml --ham $env:TEMP\ham1.eml
```

## 5. Lo que NO se pudo probar automáticamente (hazlo tú en el navegador)

Mis pruebas usaron Chromium sin pantalla en Linux. Estas cosas necesitan una persona en tu computadora:

1. **Diálogo real de archivos de Windows:** pulsa «Elegir archivo» y selecciona un `.eml` de tu equipo.
2. **Arrastre real desde el Explorador de Windows** hasta la zona punteada (las pruebas lo simulan con eventos).
3. **Teclado real:** con Tab llega a «Elegir archivo»; Enter o Espacio abre el diálogo de archivos.
4. **Un correo tuyo de verdad:** en Gmail, «⋮ → Descargar mensaje» genera un `.eml`; en Outlook, «Archivo → Guardar como»; en Thunderbird, «Guardar como». Revisa remitente, asunto, fecha, cuerpo y enlaces.
5. **Pegar el original completo:** en Gmail, «⋮ → Mostrar original», copia todo y pégalo en «Pegar contenido».
6. **Un correo en español:** el modelo se entrenó en inglés; el resultado puede no ser fiable.
7. **Servidor detenido a media sesión:** carga un correo, detén el servidor, pulsa «Analizar correo» (debe salir «No se pudo conectar con la API»), vuelve a iniciarlo y pulsa de nuevo.
8. **Consola del navegador:** abre F12 → Consola y repite todo el flujo; no debe aparecer ningún error en rojo.
9. **Tu navegador habitual:** repite el flujo en Chrome, Edge o Firefox; yo solo probé Chromium.
10. **Pantalla pequeña real o ventana estrecha:** la vista previa y el resultado deben leerse sin desplazamiento horizontal.
11. **Correo grande:** uno de más de 5 MB debe rechazarse con un mensaje claro sin esperar a la red.

## 6. Límites conocidos

- Los correos del corpus probablemente formaron parte del entrenamiento; sus resultados demuestran que la conexión funciona, no la calidad del modelo.
- El modelo solo lee los primeros 3.000 caracteres y se entrenó con correos en inglés.
- El historial, el panel de métricas, la retroalimentación y la sección «Acerca de» siguen como estaban en la Fase 2 (corresponden a fases posteriores).
