# Cómo probar la Fase 2 en tu computadora (Windows + VS Code)

Objetivo: probar la entrega **sin tocar tu proyecto principal ni tus entornos virtuales**.
Todo se hace en una carpeta nueva junto a tu proyecto. Tu `SyntaxGuard\SyntaxGuard\` no se modifica en ningún paso.

## Estructura resultante

```text
SyntaxGuard\                    <- carpeta externa que ya tienes
├── SyntaxGuard\                <- TU PROYECTO PRINCIPAL (no se toca)
│   ├── .venv\
│   ├── .venv_respaldo\
│   └── ...
└── SyntaxGuard_Fase2\          <- NUEVA: copia de prueba con la Fase 2 integrada
    ├── app\  frontend\  data\  models\  scripts\  docs\
    ├── README.md
    └── requirements.txt
```

El ZIP ya trae esa carpeta `SyntaxGuard_Fase2` como raíz, por lo que al extraerlo **no puede sobrescribir** nada de tu proyecto.

## Paso 1. Extraer el ZIP junto a tu proyecto

En la terminal de VS Code (PowerShell), colócate en la carpeta **externa** `SyntaxGuard` y extrae:

```powershell
cd RUTA\A\TU\SyntaxGuard                      # la carpeta externa, la que contiene a SyntaxGuard\
Expand-Archive "$HOME\Downloads\SyntaxGuard_Fase2.zip" -DestinationPath .
Test-Path .\SyntaxGuard_Fase2\app\main.py     # debe responder True
```

Ajusta la ruta del ZIP si lo guardaste en otro lugar.

## Paso 2. Confirmar que tu proyecto coincide con el que revisé

Mis pruebas se hicieron sobre el ZIP original que me enviaste. Para confirmar que tu proyecto local tiene los mismos archivos críticos, compara estos hashes (solo lee, no modifica):

```powershell
Get-FileHash .\SyntaxGuard\models\clasificador.pkl, .\SyntaxGuard\models\metricas.json, .\SyntaxGuard\data\dataset.csv, .\SyntaxGuard\app\detector.py, .\SyntaxGuard\app\schemas.py -Algorithm SHA256 | Format-Table Hash, Path
```

Valores esperados (PowerShell los muestra en mayúsculas; da igual):

| Archivo | SHA-256 esperado |
|---|---|
| `models\clasificador.pkl` | `99fa052be599b1f1ee591de036d8dc9e43a0724b41d0d5a6df58ad265453233c` |
| `models\metricas.json` | `2277423ac74a657cbfc3782457c5ac38d4477d064383cae5605f328dfc939df7` |
| `data\dataset.csv` | `e17235062818f114904adf0309d25278ea78f55cbfc04d705d66253628c71cab` |
| `app\detector.py` | `69519a80807e19d1a3ee5a259795a54b953a62cacfffc5a68a43e37279bb369b` |
| `app\schemas.py` | `e33c8592b34d109798563019babb6890cb2befe041c02953c96b7566f9357c28` |

Si alguno **no coincide**, tu proyecto local es distinto del ZIP que revisé. No continúes y avísame cuál difiere.

## Paso 3. Probar usando tu `.venv` actual (sin copiarlo ni modificarlo)

Un `.venv` de Windows no se puede copiar a otra carpeta sin que se rompa, así que la copia de prueba usa directamente el Python de tu `.venv`:

```powershell
cd .\SyntaxGuard_Fase2
$env:PYTHONDONTWRITEBYTECODE = 1              # evita que Python escriba cachés en tu .venv
$py = "..\SyntaxGuard\.venv\Scripts\python.exe"

& $py scripts\smoke_test.py                   # prueba original del backend
& $py scripts\smoke_test_frontend.py          # prueba de la interfaz y de los endpoints originales
```

Resultado esperado:

- `smoke_test.py`: tres líneas, terminando en `Prueba de humo superada.`
- `smoke_test_frontend.py`: seis líneas `[OK]` y `Prueba de humo del frontend superada.`

Si aparece `ModuleNotFoundError`, a tu `.venv` le falta alguna dependencia. **No instales nada todavía**: copia el mensaje y envíamelo.

## Paso 4. Arrancar y revisar la interfaz

```powershell
& $py -m uvicorn app.main:app --port 8000
```

Abre en el navegador:

| Dirección | Debe mostrar |
|---|---|
| http://localhost:8000/ | La interfaz. Arriba a la derecha, chip verde **"Modelo cargado"**. |
| Sección **Análisis** | Tres filas "Conectado". Pulsa el botón de prueba: debe aparecer `es_spam: sí · probabilidad 81,7 % · 8 rasgos devueltos`. |
| http://localhost:8000/salud | `{"estado":"ok","modelo_cargado":true}` |
| http://localhost:8000/metricas | El contenido de `metricas.json` |
| http://localhost:8000/docs | La documentación interactiva |

Pruebas rápidas adicionales:
1. Recorre las 5 secciones del menú. Las de Historial, Métricas, Retroalimentación y Acerca de deben mostrar "En construcción".
2. Reduce la ventana del navegador (o usa F12 → modo dispositivo): el menú debe convertirse en una barra horizontal.
3. Con la página abierta, detén el servidor (`Ctrl+C`) y **no recargues**: en un máximo de 30 segundos (o al cambiar de pestaña y volver) la barra superior debe cambiar a **"API sin conexión"** (así lo indica el código, que consulta la API cada 30 s; yo probé el estado de error bloqueando la API al cargar, no apagando el servidor con la página abierta). Si recargas con el servidor apagado, el navegador mostrará su propio error, porque la página la sirve ese mismo servidor.

Para detener el servidor: `Ctrl+C` en la terminal.

## Paso 5. (Opcional) Abrirlo en VS Code

`Archivo → Abrir carpeta…` y elige `SyntaxGuard_Fase2`. Si VS Code pide un intérprete de Python: `Ctrl+Shift+P` → *Python: Select Interpreter* → *Enter interpreter path…* → `..\SyntaxGuard\.venv\Scripts\python.exe` (ruta completa).

## Qué hacer con el resultado

- **Si todo funciona:** dímelo y autorizas el cierre de la Fase 2. Decidimos juntos cómo llevar estos cambios a tu proyecto principal (son solo 17 archivos más el README; la lista está en `LISTA_ARCHIVOS.md`) antes de empezar la Fase 3.
- **Si algo falla:** envíame el texto exacto del error de la terminal (o una captura) y en qué paso ocurrió.

Tu proyecto principal solo se modificaría cuando tú lo autorices expresamente. Hasta entonces, para volver al estado anterior basta con borrar la carpeta `SyntaxGuard_Fase2`.
