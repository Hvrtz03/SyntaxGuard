"""Captura las respuestas de los endpoints originales para un conjunto fijo de casos.
Uso: python -I capturar_respuestas.py <raiz_proyecto> <salida.json>
"""
import json
import sys
from pathlib import Path

raiz = Path(sys.argv[1]).resolve()
salida = Path(sys.argv[2])
sys.path.insert(0, str(raiz))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

HTML_ENGANO = '<html><body><a href="http://paypa1.com/login">http://paypal.com</a><div style="display:none">x</div></body></html>'
CASOS = {
    "spam_con_html": {"texto": "WINNER!! Claim your FREE prize now: http://bit.ly/claim-now", "html": HTML_ENGANO},
    "spam_solo_texto": {"texto": "WINNER!! Claim your FREE prize now: http://bit.ly/claim-now"},
    "ham_normal": {"texto": "Hi John, attached is the agenda for tomorrow's meeting. Let me know if the time works for you."},
    "ip_en_url": {"texto": "Verify your account at http://192.168.10.5/login immediately!!!"},
    "texto_vacio": {"texto": "   "},
    "sin_texto": {"html": "<p>hola</p>"},
    "texto_demasiado_largo": {"texto": "a" * 20001},
    "html_demasiado_largo": {"texto": "hola", "html": "a" * 200001},
}

res = {}
with TestClient(app) as c:
    for ruta in ("/salud", "/metricas"):
        r = c.get(ruta)
        res[f"GET {ruta}"] = {"status": r.status_code, "json": r.json()}
    for nombre, cuerpo in CASOS.items():
        r = c.post("/predecir", json=cuerpo)
        res[f"POST /predecir [{nombre}]"] = {"status": r.status_code, "json": r.json()}
    # método no permitido sobre rutas originales
    res["POST /salud"] = {"status": c.post("/salud").status_code}
    res["GET /predecir"] = {"status": c.get("/predecir").status_code}

salida.write_text(json.dumps(res, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
print(f"{len(res)} respuestas guardadas en {salida}")
for k, v in res.items():
    j = v.get("json")
    extra = ""
    if isinstance(j, dict) and "es_spam" in j:
        extra = f" es_spam={j['es_spam']} prob={j['probabilidad']}"
    print(f"  {k}: {v['status']}{extra}")
