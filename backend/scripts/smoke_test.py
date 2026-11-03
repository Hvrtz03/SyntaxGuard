import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.detector import MODEL_PATH, SpamDetector  # noqa: E402
from app.main import app  # noqa: E402

TEXTO = "WINNER!! Claim your FREE prize now: http://bit.ly/claim-now"
HTML = '<html><body><a href="http://paypa1.com/login">http://paypal.com</a></body></html>'


def verificar_formato(r: dict):
    assert set(r) == {"es_spam", "probabilidad", "rasgos_detectados"}, "Claves incorrectas"
    assert isinstance(r["es_spam"], bool)
    assert 0.0 <= r["probabilidad"] <= 1.0
    assert isinstance(r["rasgos_detectados"], list) and len(r["rasgos_detectados"]) > 0
    for item in r["rasgos_detectados"]:
        assert {"rasgo", "categoria", "valor", "activo", "descripcion"} <= set(item)


def main():
    assert MODEL_PATH.exists(), "Falta models/clasificador.pkl. Ejecuta: python scripts/train.py"

    verificar_formato(SpamDetector().predecir(TEXTO, HTML))
    print("[OK] Detector: predicción con formato correcto")

    with TestClient(app) as c:
        assert c.get("/salud").json()["modelo_cargado"] is True
        r = c.post("/predecir", json={"texto": TEXTO, "html": HTML})
        assert r.status_code == 200, r.text
        verificar_formato(r.json())
        assert c.post("/predecir", json={"texto": "   "}).status_code == 422
        assert c.get("/metricas").status_code == 200
    print("[OK] API: /salud, /predecir, /metricas")
    print("Prueba de humo superada.")


if __name__ == "__main__":
    main()