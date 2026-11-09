# Instalar y probar la Fase 4 (Windows · PowerShell)

Reemplaza `C:\ruta\a\SyntaxGuard` por la carpeta real de tu proyecto (la que contiene `backend` y `frontend`).

## Paso 0 · Antes de copiar nada (respaldo y línea base)

```powershell
cd C:\ruta\a\SyntaxGuard
.\.venv\Scripts\Activate.ps1

# Respaldo de los 2 archivos que se van a reemplazar
Copy-Item frontend\index.html frontend\index.html.respaldo-fase3
Copy-Item frontend\js\vistas\analizar.js frontend\js\vistas\analizar.js.respaldo-fase3-previo

```

## Paso 1 · Copiar la entrega

Descarga `SyntaxGuard_Fase4_entrega.zip` y guárdalo, por ejemplo, en `C:\Users\TuUsuario\Downloads`.

```powershell
cd C:\ruta\a\SyntaxGuard
$zip = "$env:USERPROFILE\Downloads\SyntaxGuard_Fase4_entrega.zip"
$tmp = "$env:TEMP\sg_fase4"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $tmp
# Copia respetando las rutas relativas (solo hay 2 archivos que se reemplazan; el resto es nuevo)
Copy-Item -Path "$tmp\*" -Destination . -Recurse -Force
```

Si `Expand-Archive` se queja de las rutas, usa: `tar -xf $zip -C $tmp`.

### Reemplazan a un archivo existente (2)
* `frontend\index.html`
* `frontend\js\vistas\analizar.js`

### Archivos nuevos (copiar)
* `frontend\js\evidencias.js`
* `frontend\js\vistas\resultado.js`
* `frontend\js\vistas\analizar.js.respaldo-fase3` (copia de la versión anterior)
* `frontend\css\resultados.css`
* `backend\scripts\smoke_test_fase4.py`
* `frontend\documentacion\fase4\` (reporte, instrucciones, pruebas y capturas)

## Paso 2 · Pruebas con TU modelo real

```powershell
cd C:\ruta\a\SyntaxGuard
python backend\scripts\smoke_test.py
python backend\scripts\smoke_test_frontend.py
python backend\scripts\smoke_test_correo.py
python backend\scripts\smoke_test_fase4.py
# Opcional (después de lo anterior): guarda la línea base del modelo para vigilar clasificador.pkl en el futuro
python backend\scripts\smoke_test_fase4.py --guardar-linea-base
```
Las cuatro deben terminar con «superada». Si `smoke_test_fase4.py` dice que un archivo protegido cambió, **detente** y avísame.

## Paso 3 · Abrir la aplicación

```powershell
python ejecutable\run.py
```
(si en tu proyecto el lanzador está en la raíz: `python run.py`). Se abre http://127.0.0.1:8000/ — pulsa **Ctrl + F5** para saltar la caché.

## Paso 4 · Pruebas de navegador (opcional, con la app en ejecución)

En **otra** ventana de PowerShell:

```powershell
cd C:\ruta\a\SyntaxGuard
pip install playwright
playwright install chromium
python frontend\documentacion\fase4\pruebas\probar_resultados_fase4.py http://127.0.0.1:8000 frontend\documentacion\fase4\capturas frontend\documentacion\fase4\pruebas\resultados_fase4.json
python frontend\documentacion\fase3\pruebas\probar_flujo_fase3.py http://127.0.0.1:8000 frontend\documentacion\fase3\capturas frontend\documentacion\fase3\pruebas\resultados_fase3.json
python frontend\documentacion\fase2\pruebas\probar_interfaz.py http://127.0.0.1:8000 frontend\documentacion\fase2\capturas frontend\documentacion\fase2\pruebas\resultados_interfaz.json
```
Esperado: Fase 4 = 145/145, Fase 3 = 94/94, Fase 2 = 83/83. (`playwright` no es una dependencia del proyecto: es solo para estas pruebas.)

## Paso 5 · Revisión manual (5 minutos)
1. Sube un `.eml` legítimo → debe salir LEGÍTIMO con la escala de riesgo en Bajo/Moderado.
2. Sube un spam evidente → SPAM, riesgo Alto/Muy alto.
3. Recorre las pestañas Rasgos, Texto extraído, Enlaces y Estructura.
4. Abre «Limitaciones del clasificador»: deben verse 175 / 4 / 10 / 111 y 95,3 %.
5. Cambia a «Métricas» y vuelve: el resultado debe seguir ahí.
6. Reduce la ventana (móvil): no debe aparecer barra de desplazamiento horizontal.
7. F12 → Consola: sin errores en rojo.

## Cómo deshacer
```powershell
Copy-Item frontend\js\vistas\analizar.js.respaldo-fase3 frontend\js\vistas\analizar.js -Force
Copy-Item frontend\index.html.respaldo-fase3 frontend\index.html -Force
```
