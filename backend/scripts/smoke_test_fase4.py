"""Prueba de humo de la Fase 4 (resultados y evidencias). No modifica nada.

Uso (desde la carpeta backend):  python scripts/smoke_test_fase4.py [--guardar-linea-base]

Comprueba:
  1. Que los archivos PROTEGIDOS no cambiaron (detector.py, schemas.py, metricas.json, requirements.txt, clasificador.pkl).
     - detector.py, schemas.py, metricas.json y requirements.txt se comparan con los valores SHA-256 de la entrega de la Fase 3.
     - clasificador.pkl se compara con una línea base que TÚ guardas antes de instalar: --guardar-linea-base
  2. Que /metricas siga devolviendo las cifras reales de prueba (0,9533 · 175/4/10/111).
  3. Que el frontend de la Fase 4 esté completo, se sirva bien y sus módulos se importen entre sí.
  4. Reglas de seguridad del código nuevo (sin innerHTML ni enlaces clicables) y el umbral 0,5.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # carpeta backend
PROYECTO = ROOT.parent
sys.path.insert(0, str(ROOT))

LINEA_BASE = Path(__file__).resolve().parent / "linea_base_protegidos.json"
SHA_FASE3 = {  # SHA-256 de los archivos protegidos tal como llegaron en el ZIP de la Fase 3
    "backend/app/detector.py": "0baab83513a554f80b72d006e418bf76a25722d0529a60edb8c757c769a0351c",
    "backend/app/schemas.py": "61dbc2c7a716ccac5f824087ad0e781afa195eb42621e245b69a4f53b494b91b",
    "backend/models/metricas.json": "bf93833e92aaad6407e62dfed74e14b775b92f994bd731a9081df551fe02d5e5",
    "requirements.txt": "10d0def4755eb90baa91d66c7a9566f1c6d49c43c0fd7abdba47667f1490fc07",
}
RUTA_PKL = PROYECTO / "backend" / "models" / "clasificador.pkl"


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def comprobar(cond, msg):
    assert cond, msg


def main():
    if "--guardar-linea-base" in sys.argv:
        datos = {"backend/models/clasificador.pkl": sha(RUTA_PKL)} if RUTA_PKL.exists() else {}
        datos.update({k: sha(PROYECTO / k) for k in SHA_FASE3 if (PROYECTO / k).exists()})
        LINEA_BASE.write_text(json.dumps(datos, indent=2), encoding="utf-8")
        print(f"[OK] Línea base guardada en {LINEA_BASE} ({len(datos)} archivos).")
        return

    # ---- 1. Archivos protegidos ----
    for rel, esperado in SHA_FASE3.items():
        p = PROYECTO / rel
        comprobar(p.exists(), f"Falta el archivo protegido {rel}")
        comprobar(sha(p) == esperado, f"¡{rel} CAMBIÓ respecto a la Fase 3! No debe modificarse.")
    print("[OK] detector.py, schemas.py, metricas.json y requirements.txt son idénticos a los de la Fase 3")
    if LINEA_BASE.exists():
        base = json.loads(LINEA_BASE.read_text(encoding="utf-8"))
        for rel, esperado in base.items():
            comprobar((PROYECTO / rel).exists() and sha(PROYECTO / rel) == esperado, f"¡{rel} cambió respecto a la línea base!")
        print(f"[OK] Línea base guardada: {len(base)} archivos protegidos sin cambios (incluye clasificador.pkl si existía)")
    else:
        print("[--] No hay línea base de clasificador.pkl. Para vigilarlo: python scripts/smoke_test_fase4.py --guardar-linea-base (ANTES de instalar la Fase 4).")

    # ---- 2. Métricas reales ----
    m = json.loads((ROOT / "models" / "metricas.json").read_text(encoding="utf-8"))["test"]
    comprobar((m["accuracy"], m["precision"], m["recall"], m["f1"]) == (0.9533, 0.9652, 0.9174, 0.9407), "Las métricas de prueba no son las reales")
    cm = m["matriz_confusion"]
    comprobar((cm["tn"], cm["fp"], cm["fn"], cm["tp"]) == (175, 4, 10, 111), "La matriz de confusión no es la real")
    print("[OK] metricas.json conserva las cifras reales de prueba (0,9533 · 0,9652 · 0,9174 · 0,9407 · 175/4/10/111)")

    # ---- 3. Frontend de la Fase 4 ----
    fe = PROYECTO / "frontend"
    nuevos = ["js/evidencias.js", "js/vistas/resultado.js", "css/resultados.css"]
    for rel in nuevos:
        comprobar((fe / rel).is_file(), f"Falta frontend/{rel}")
    comprobar("/static/css/resultados.css" in (fe / "index.html").read_text(encoding="utf-8"), "index.html no enlaza resultados.css")
    for p in (fe / "js").rglob("*.js"):
        for rel in re.findall(r"""(?:from|import\()\s*['"](\.{1,2}/[^'"]+)['"]""", p.read_text(encoding="utf-8")):
            comprobar((p.parent / rel).resolve().is_file(), f"{p.name} importa un módulo inexistente: {rel}")
    print("[OK] Archivos nuevos presentes, index.html enlaza resultados.css y todas las importaciones JS existen")

    # ---- 4. Seguridad y reglas del código nuevo ----
    prohibido = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function")
    for rel in ("js/evidencias.js", "js/vistas/resultado.js", "js/vistas/analizar.js"):
        codigo = re.sub(r"//.*", "", (fe / rel).read_text(encoding="utf-8"))
        comprobar(not prohibido.search(codigo), f"{rel} usa una API insegura (innerHTML, eval…)")
        comprobar(not re.search(r"""h\(\s*['"]a['"]""", codigo), f"{rel} crea enlaces <a> clicables")
    print("[OK] El código de resultados no usa innerHTML/eval y no crea enlaces <a>")
    res = (fe / "js/vistas/resultado.js").read_text(encoding="utf-8")
    comprobar("export const UMBRAL = 0.5;" in res, "El umbral de la interfaz no es 0.5")
    comprobar("api.predecir" not in res and "api.extraerCorreo" not in res, "resultado.js no debe llamar a /predecir ni /correo/extraer")
    print("[OK] Umbral 0,5 y resultado.js sin llamadas de análisis (no duplica solicitudes)")

    # ---- API ----
    import auth_helper  # noqa: F401  (Fase 6A: base de datos temporal; no toca backend/storage)
    from fastapi.testclient import TestClient
    from app.detector import METRICS_PATH
    from app.main import app
    with TestClient(app) as c:
        r = c.get("/metricas")
        comprobar(r.status_code == 200 and r.json() == json.loads(METRICS_PATH.read_text(encoding="utf-8")), "/metricas cambió")
        comprobar(c.get("/static/css/resultados.css").status_code == 200, "No se sirve resultados.css")
        comprobar(c.get("/static/js/vistas/resultado.js").headers["content-type"].startswith("text/javascript") or "javascript" in c.get("/static/js/vistas/resultado.js").headers["content-type"], "MIME de resultado.js")
        comprobar(c.get("/static/js/evidencias.js").status_code == 200, "No se sirve evidencias.js")
    print("[OK] /metricas intacto y los archivos nuevos se sirven con el tipo MIME correcto")
    print("Prueba de humo de la Fase 4 superada.")


if __name__ == "__main__":
    main()
