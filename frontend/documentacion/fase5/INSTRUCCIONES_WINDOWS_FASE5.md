# SyntaxGuard · Fase 5 — Instalación y pruebas en Windows

Proyecto de trabajo: `C:\Users\marti\Downloads\SyntaxGuard(1) - modificado-fase3 - copia`
(escribe siempre las rutas **entre comillas**: tienen espacios y paréntesis).

## 1. Instalar los cambios (sin perder tu entorno virtual)
1. **Respaldo:** copia la carpeta del proyecto completa (por ejemplo, a `...\SyntaxGuard - respaldo antes de fase5`).
2. Descomprime el ZIP en una carpeta temporal, por ejemplo `C:\Temp\SyntaxGuard_Fase5` (clic derecho → *Extraer todo*).
3. Copia su contenido **encima** de tu proyecto (no borra nada; conserva tu `.venv`). En PowerShell:
```powershell
robocopy "C:\Temp\SyntaxGuard_Fase5\SyntaxGuard" "C:\Users\marti\Downloads\SyntaxGuard(1) - modificado-fase3 - copia" /E
```
   (Si al extraer no se crea la subcarpeta `SyntaxGuard`, usa `C:\Temp\SyntaxGuard_Fase5` como origen.)
4. No se movió ningún archivo: `ejecutable\run.py`, `requirements.txt` y `README.md` siguen donde estaban.
5. **No hay que instalar dependencias nuevas** (`requirements.txt` no cambió; SQLite viene con Python).

## 2. Iniciar el sistema
```powershell
cd "C:\Users\marti\Downloads\SyntaxGuard(1) - modificado-fase3 - copia"
.venv\Scripts\activate
python ejecutable\run.py
```
Se abre http://127.0.0.1:8000/. También sirve el doble clic en `ejecutable\iniciar.bat` (crea el entorno e instala solo la primera vez).
El historial se guarda en `backend\storage\syntaxguard.db` y permanece al cerrar y volver a abrir.

## 3. Ejecutar TODAS las pruebas con el modelo real (un solo comando)
Una sola vez, instala Playwright (solo para las pruebas de interfaz; **no** se agrega a `requirements.txt`):
```powershell
cd "C:\Users\marti\Downloads\SyntaxGuard(1) - modificado-fase3 - copia"
.venv\Scripts\activate
pip install playwright
python -m playwright install chromium
```
Después:
```powershell
ejecutable\probar_todo.bat
```
Corre las 8 pruebas en orden y escribe el informe `PRUEBAS_REALES_FASE5.txt` en la raíz del proyecto (tarda varios minutos: arranca el servidor real). Envíame ese archivo para cerrar los pendientes B1–B6 del reporte. Las pruebas usan una base de datos temporal: **no tocan tu historial**.

### Pruebas por separado (con el entorno activado, desde la raíz)
```powershell
python backend\scripts\smoke_test.py
python backend\scripts\smoke_test_correo.py
python backend\scripts\smoke_test_frontend.py
python backend\scripts\smoke_test_fase4.py
python backend\scripts\test_almacen_servicio.py          :: detector simulado: solo prueba datos
python backend\scripts\smoke_test_fase5.py                :: API real + modelo real
python frontend\documentacion\fase5\pruebas\probar_interfaz_fase5.py --servidor-real
python backend\scripts\probar_concurrencia.py             :: opcional: --n 100 --hilos 2 4 8 --rondas 3
```
Regresión de interfaz de fases anteriores (con el servidor iniciado en otra ventana: `python ejecutable\run.py --sin-navegador`):
```powershell
python frontend\documentacion\fase2\pruebas\probar_interfaz.py http://127.0.0.1:8000 capt2 res2.json
python frontend\documentacion\fase3\pruebas\probar_flujo_fase3.py http://127.0.0.1:8000 capt3 res3.json
python frontend\documentacion\fase4\pruebas\probar_resultados_fase4.py http://127.0.0.1:8000 capt4 res4.json
```
(estas tres escriben en tu historial real si analizas correos; para evitarlo inicia el servidor con `set SG_DB=%TEMP%\prueba.db` antes).

## 4. Recorrido manual sugerido (los 10 pasos)
1. Abrir SyntaxGuard → 2. **Análisis**: pega o sube un `.eml` y analiza → 3. Revisa resultado y evidencias; pulsa «Abrir en el historial» →
4. **Análisis masivo**: «Elegir carpeta» (por ejemplo una carpeta con `.eml`) → «Iniciar análisis» → 5. Revisa resumen, filtros, «Detalles» y «Exportar CSV» →
6. **Historial**: busca, filtra, abre y elimina → 7. Abre un análisis anterior → 8. **Métricas**: pestañas «Rendimiento del modelo» y «Estadísticas de uso» →
9. **Retroalimentación**: elige un análisis, opina y guarda → 10. **Acerca de**.

## 5. Notas
* `.env` es opcional (`SG_HOST`, `SG_PUERTO`, `SG_DB`, `SG_ABRIR_NAVEGADOR`; ver README). No se necesita `.env.example`.
* Para borrar todo el historial: cierra la aplicación y elimina `backend\storage\syntaxguard.db` (se recrea vacía).
* Si el botón «Elegir carpeta» está desactivado, tu navegador no permite elegir carpetas: usa «Elegir archivos».
* Si algo falla, copia el mensaje completo; las pruebas indican qué comprobación falló.
