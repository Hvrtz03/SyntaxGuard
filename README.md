# SyntaxGuard

Sistema de detección de correos electrónicos SPAM y phishing mediante Machine Learning y análisis sintáctico-estructural.


## Objetivo

Desarrollar una herramienta de apoyo académico que clasifique un correo electrónico como spam o legítimo y muestre las evidencias que influyeron en la decisión (texto, URLs, estructura HTML y sintaxis) junto con su nivel de confianza.

## Equipo

- ESCOBEDO HERNANDEZ MARTIN
- ESPINOSA LORENZO LUIS ANGEL

## Requisitos previos

- Python 3.10 o 3.11
- Git
- Conexión a internet (solo la primera vez, para instalar dependencias)

## Instalación

```bash
git clone https://github.com/Hvrtz03/SyntaxGuard.git
cd SyntaxGuard
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

En Linux o macOS se activa con `source .venv/bin/activate`.

## Ejecución

```bash
python run.py
```

Se abre el navegador en http://127.0.0.1:8000/ y la documentación de la API está en http://127.0.0.1:8000/docs.

También se puede iniciar con doble clic en `iniciar.bat` (Windows) o con `bash iniciar.sh` (Linux/macOS); ambos preparan todo automáticamente la primera vez.

En la Fase 2 la interfaz muestra el menú, el estado real de la API y la conexión con el modelo. Las pantallas completas se entregan en las siguientes fases.

## Variables de entorno

Copia `.env.example` a `.env` y ajusta los valores si lo necesitas. Nunca subas `.env` a Git. El proyecto no usa claves ni contraseñas.

## Conjunto de datos

- Fuente: corpus público de correos Apache SpamAssassin (carpetas `easy_ham`, `spam` y `spam_2`), convertido a `data/dataset.csv` con `scripts/build_dataset.py`.
- Licencia: corpus público de uso libre para investigación y fines académicos.

## Estructura

- `app/`: API y detector de spam
- `frontend/`: interfaz web
- `models/`: modelo entrenado y sus métricas
- `scripts/`: entrenamiento y pruebas
- `data/`: correos y dataset
- `docs/`: documentación y pruebas de cada fase
- `run.py`: lanzador del proyecto
