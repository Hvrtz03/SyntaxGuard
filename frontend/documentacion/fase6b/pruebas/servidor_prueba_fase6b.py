"""Servidor de prueba de la Fase 6B: el backend REAL de la Fase 6A (FastAPI, rutas_auth, dependencias, seguridad,
usuarios, almacén SQLite, rutas de historial/análisis) con UNA sola sustitución: el DETECTOR es SIMULADO.

Motivo: en el entorno donde se preparó esta entrega no están instalados spaCy ni scikit-learn ni se puede ejecutar
el modelo real. Con tu modelo real usa  python ejecutable\\run.py  (o --servidor-real en probar_interfaz_fase6b.py).
NO modifica ningún archivo del backend: inyecta un módulo `app.detector` falso en sys.modules antes de importar main.

Uso:  python servidor_prueba_fase6b.py <puerto>     (las variables SG_* las pone quien lo lanza)
"""
import sys
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(RAIZ / "backend"))
PUERTO = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

PALABRAS = ("winner", "free", "prize", "gratis", "click here", "urgent")


class DetectorSimulado:
    """Mismo formato de salida que SpamDetector.predecir (PrediccionResponse). NO es el modelo."""

    def __init__(self, ruta=None):
        pass

    def predecir(self, texto, html=None):
        spam = any(p in (texto or "").lower() for p in PALABRAS)
        return {
            "es_spam": spam,
            "probabilidad": 0.93 if spam else 0.07,
            "rasgos_detectados": [
                {"rasgo": "txt_palabras_clave", "categoria": "texto", "valor": 1.0 if spam else 0.0, "activo": spam,
                 "descripcion": "Palabras típicas de spam (detector simulado)"},
                {"rasgo": "txt_mayusculas", "categoria": "texto", "valor": 0.1, "activo": False,
                 "descripcion": "Alta densidad de letras mayúsculas"},
            ],
        }


falso = types.ModuleType("app.detector")
falso.METRICS_PATH = RAIZ / "backend" / "models" / "metricas.json"
falso.MODEL_PATH = RAIZ / "backend" / "models" / "clasificador.pkl"
falso.SpamDetector = DetectorSimulado
sys.modules["app.detector"] = falso

import uvicorn  # noqa: E402
from app.main import app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PUERTO, log_level="warning")
