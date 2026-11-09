# SyntaxGuard

Sistema de detecciÃ³n de correos electrÃ³nicos SPAM mediante Machine Learning y anÃ¡lisis sintÃ¡ctico-estructural. El modelo distingue dos clases: SPAM y LEGÃTIMO.


## Objetivo

Desarrollar una herramienta de apoyo acadÃ©mico que clasifique un correo electrÃ³nico como spam o legÃ­timo y muestre las evidencias que influyeron en la decisiÃ³n (texto, URLs, estructura HTML y sintaxis) junto con la probabilidad de spam, P(spam).

## Equipo

- ESCOBEDO HERNANDEZ MARTIN
- ESPINOSA LORENZO LUIS ANGEL

## Requisitos previos

- Python 3.10 o 3.11
- Git
- ConexiÃ³n a internet (solo la primera vez, para instalar dependencias)

## InstalaciÃ³n

Desde la carpeta raÃ­z del proyecto (la que contiene `requirements.txt`):

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

En Linux o macOS se activa con `source .venv/bin/activate`.

## EjecuciÃ³n

```bash
python ejecutable\run.py
```

Se abre el navegador en http://127.0.0.1:8000/ y la documentaciÃ³n de la API estÃ¡ en http://127.0.0.1:8000/docs.

TambiÃ©n se puede iniciar con doble clic en `ejecutable\iniciar.bat` (Windows) o con `bash ejecutable/iniciar.sh` (Linux/macOS). Ambos trabajan sobre la carpeta raÃ­z del proyecto y preparan todo automÃ¡ticamente la primera vez.

## Funciones de la aplicaciÃ³n (Fase 5)

- **AnÃ¡lisis**: un correo individual (archivo `.eml`/`.txt` o texto pegado) con resultado, P(spam) y evidencias.
- **AnÃ¡lisis masivo**: varios archivos o una carpeta completa, uno por uno; progreso, cancelaciÃ³n, resumen, detalle por correo y exportaciÃ³n a CSV.
- **Historial**: todos los anÃ¡lisis guardados, con bÃºsqueda, filtros (resultado, tipo, fechas), detalle, eliminaciÃ³n y CSV.
- **MÃ©tricas**: rendimiento del modelo (datos de `models/metricas.json`) y, por separado, estadÃ­sticas de uso calculadas con el historial.
- **RetroalimentaciÃ³n**: indicar si estÃ¡s de acuerdo con un resultado. Se guarda, pero **no** reentrena ni modifica el modelo.
- **Acerca de**: quÃ© es SyntaxGuard, cÃ³mo funciona y sus limitaciones.

El historial se guarda en `backend/storage/syntaxguard.db` (SQLite). No se guarda el contenido de los correos: solo metadatos, resultado del modelo, rasgos y dominios de los enlaces.

## Variables de entorno (opcionales)

El proyecto no usa claves ni contraseÃ±as. Se pueden definir en el entorno o en un archivo `.env` en la raÃ­z (no se sube a Git):

| Variable | Para quÃ© sirve | Valor por defecto |
|---|---|---|
| `SG_HOST` | DirecciÃ³n en la que escucha | `127.0.0.1` |
| `SG_PUERTO` | Puerto | `8000` |
| `SG_ABRIR_NAVEGADOR` | Abrir el navegador al iniciar (`1`/`0`) | `1` |
| `SG_DB` | Ruta de la base de datos del historial | `backend/storage/syntaxguard.db` |
| `SG_SECRET_KEY` | Clave del servidor para las sesiones (Fase 6A; ver `.env.example` para las demÃ¡s variables `SG_*`) | aleatoria en memoria |

## Usuarios y sesiones (Fase 6A)

Desde la Fase 6A la API tiene usuarios, sesiones y datos privados por usuario (historial, lotes, retroalimentaciÃ³n,
estadÃ­sticas y CSV). Solo `/salud`, `/metricas`, la interfaz estÃ¡tica y `/auth/registro|login|logout` se pueden usar sin sesiÃ³n.

1. Copia `.env.example` a `.env` y define `SG_SECRET_KEY` (el archivo explica cÃ³mo generarla).
2. Inicia el backend como siempre (`ejecutable\iniciar.bat`). La base de datos se migra sola al arrancar; si ya tenÃ­a datos de la
   Fase 5 se guarda antes una copia `backend/storage/syntaxguard.db.pre_fase6.bak` y esos registros quedan sin propietario
   (no los ve ningÃºn usuario).
3. Contrato para el frontend: `frontend/documentacion/FASE6_CONTRATO_API.md`. Informe: `frontend/documentacion/fase6/REPORTE_FASE6A.md`.


## Pruebas

Consulta `frontend/documentacion/fase6/REPORTE_FASE6A.md` para la documentación de autenticación, almacenamiento y pruebas de Fase 6.

## Conjunto de datos

- Fuente: corpus pÃºblico de correos Apache SpamAssassin (carpetas `easy_ham`, `spam` y `spam_2`), convertido a `backend/data/dataset.csv` con `backend/scripts/build_dataset.py`.
- Licencia: corpus pÃºblico de uso libre para investigaciÃ³n y fines acadÃ©micos.

## Estructura

- `backend/app/`: API (FastAPI), detector, extracciÃ³n de correos, almacenamiento (SQLite) y rutas
- `backend/models/`: modelo entrenado y sus mÃ©tricas
- `backend/data/`: correos y dataset
- `backend/scripts/`: entrenamiento y pruebas
- `backend/storage/`: base de datos del historial (se crea al iniciar)
- `frontend/`: interfaz web (HTML, CSS y JavaScript puro)
- `frontend/documentacion/`: documentaciÃ³n y pruebas de cada fase
- `ejecutable/`: `run.py` (lanzador), `iniciar.bat` e `iniciar.sh`

