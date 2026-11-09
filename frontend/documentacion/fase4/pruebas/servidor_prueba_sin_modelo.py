"""Servidor de PRUEBA para entornos donde NO existe models/clasificador.pkl.

NO es parte de SyntaxGuard y NO sustituye al modelo real: usa un detector falso, con el mismo
formato de respuesta que SpamDetector, solo para poder probar la interfaz. Sirve el frontend y
el resto de endpoints reales (/correo/extraer, /metricas, /salud). No modifica ningún archivo del proyecto.

Si tienes el modelo real (tu caso), NO uses este script: arranca la aplicación normal con run.py.

Uso:  python servidor_prueba_sin_modelo.py [puerto]
"""
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(RAIZ / "backend"))

import uvicorn  # noqa: E402

import app.main as principal  # noqa: E402

PALABRAS = {"free", "win", "winner", "prize", "claim", "cash", "urgent", "click", "offer", "money", "bonus"}


class DetectorFalso:
    """Respuesta con el mismo formato que SpamDetector.predecir (es_spam, probabilidad, rasgos_detectados)."""

    def __init__(self, ruta=None):
        self.umbral = 0.5

    def predecir(self, texto, html=None):
        palabras = re.findall(r"[a-z]+", texto.lower())
        golpes = sum(1 for w in palabras if w in PALABRAS)
        letras = [c for c in texto if c.isalpha()]
        mayus = sum(c.isupper() for c in letras) / max(len(letras), 1)
        excl = texto.count("!")
        acortador = 1.0 if re.search(r"bit\.ly|tinyurl", texto + (html or ""), re.I) else 0.0
        proba = min(0.99, 0.04 + 0.12 * golpes + 0.25 * mayus + 0.03 * min(excl, 5) + 0.25 * acortador)
        rasgos = [
            {"rasgo": "txt_mayusculas", "categoria": "texto", "valor": round(mayus, 4), "activo": mayus > 0.30,
             "descripcion": "Alta densidad de letras mayúsculas"},
            {"rasgo": "txt_exclamaciones", "categoria": "texto", "valor": float(excl), "activo": excl >= 3,
             "descripcion": "Exceso de signos de exclamación"},
            {"rasgo": "url_acortador", "categoria": "url", "valor": acortador, "activo": acortador > 0,
             "descripcion": "URL con acortador de enlaces"},
            {"rasgo": "dep_prof_max", "categoria": "sintactico", "valor": 4.0, "activo": False,
             "descripcion": "Profundidad máxima del árbol de dependencias (spaCy)"},
        ]
        if html:
            rasgos.append({"rasgo": "dom_distancia_ref", "categoria": "dom", "valor": 0.55, "activo": True,
                           "descripcion": "Estructura DOM cercana al árbol de referencia de spam (distancia de edición zss normalizada)"})
        return {"es_spam": proba >= self.umbral, "probabilidad": round(proba, 4), "rasgos_detectados": rasgos}


principal.SpamDetector = DetectorFalso

if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(principal.app, host="127.0.0.1", port=puerto, log_level="warning")
