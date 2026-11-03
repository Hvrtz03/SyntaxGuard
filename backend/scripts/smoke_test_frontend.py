"""Prueba de humo de la interfaz web y de que los endpoints originales siguen intactos.

Uso (desde la raíz del proyecto):  python scripts/smoke_test_frontend.py
No modifica ni sustituye a scripts/smoke_test.py.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.detector import METRICS_PATH  # noqa: E402
from app.main import FRONTEND_DIR, app  # noqa: E402

TEXTO = "WINNER!! Claim your FREE prize now: http://bit.ly/claim-now"
HTML = '<html><body><a href="http://paypa1.com/login">http://paypal.com</a></body></html>'
ORIGINALES = {("/salud", "GET"), ("/metricas", "GET"), ("/predecir", "POST")}


def comprobar(condicion, mensaje):
    assert condicion, mensaje


def main():
    comprobar(FRONTEND_DIR.is_dir(), f"No existe la carpeta del frontend: {FRONTEND_DIR}")

    rutas = {(r.path, m) for r in app.routes for m in (getattr(r, "methods", None) or ())}
    comprobar(ORIGINALES <= rutas, f"Faltan endpoints originales: {ORIGINALES - rutas}")
    print("[OK] Endpoints originales registrados: /salud, /metricas, /predecir")

    with TestClient(app) as c:
        # ---- Endpoints originales: mismo comportamiento ----
        r = c.get("/salud")
        comprobar(r.status_code == 200 and r.json() == {"estado": "ok", "modelo_cargado": True}, "/salud cambió")

        r = c.get("/metricas")
        esperado = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        comprobar(r.status_code == 200 and r.json() == esperado, "/metricas ya no devuelve metricas.json tal cual")

        r = c.post("/predecir", json={"texto": TEXTO, "html": HTML})
        comprobar(r.status_code == 200, r.text)
        d = r.json()
        comprobar(set(d) == {"es_spam", "probabilidad", "rasgos_detectados"}, "/predecir cambió su formato")
        comprobar(c.post("/predecir", json={"texto": "   "}).status_code == 422, "/predecir ya no valida texto vacío")
        print("[OK] /salud, /metricas y /predecir responden igual que antes")

        # ---- Interfaz ----
        r = c.get("/")
        comprobar(r.status_code == 200 and "text/html" in r.headers["content-type"], "GET / no sirve el HTML")
        comprobar('id="contenido"' in r.text and "SyntaxGuard" in r.text, "index.html no es el esperado")
        print("[OK] GET / sirve la interfaz")

        archivos = sorted(p for p in FRONTEND_DIR.rglob("*") if p.is_file() and p.name != "index.html")
        comprobar(archivos, "El frontend no tiene archivos CSS/JS")
        for p in archivos:
            url = "/static/" + p.relative_to(FRONTEND_DIR).as_posix()
            r = c.get(url)
            comprobar(r.status_code == 200, f"{url} -> {r.status_code}")
            if p.suffix == ".js":
                comprobar("javascript" in r.headers["content-type"], f"{url}: tipo MIME incorrecto ({r.headers['content-type']})")
            if p.suffix == ".css":
                comprobar("text/css" in r.headers["content-type"], f"{url}: tipo MIME incorrecto ({r.headers['content-type']})")
        print(f"[OK] {len(archivos)} archivos estáticos servidos con el tipo MIME correcto")

        # Todo lo que referencia index.html existe
        refs = re.findall(r'(?:href|src)="(/static/[^"]+)"', c.get("/").text)
        comprobar(refs and all(c.get(u).status_code == 200 for u in refs), "index.html referencia archivos inexistentes")

        # Las importaciones entre módulos JS existen
        for p in (FRONTEND_DIR / "js").rglob("*.js"):
            for rel in re.findall(r"""(?:from|import\()\s*['"](\.{1,2}/[^'"]+)['"]""", p.read_text(encoding="utf-8")):
                destino = (p.parent / rel).resolve()
                comprobar(destino.is_file(), f"{p.name} importa un módulo inexistente: {rel}")
        print("[OK] Todas las importaciones entre módulos JS existen")

        # Seguridad: no se puede salir de frontend/
        r = c.get("/static/%2e%2e/app/main.py")
        comprobar(r.status_code in (400, 404), f"Posible acceso fuera de frontend/: {r.status_code}")
        print("[OK] /static no permite salir de la carpeta frontend/")

    print("Prueba de humo del frontend superada.")


if __name__ == "__main__":
    main()
