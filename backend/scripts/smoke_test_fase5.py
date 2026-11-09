"""Prueba de la Fase 5 con la API REAL de FastAPI y el MODELO REAL (sin detectores simulados).

Uso (desde la raíz del proyecto, con el entorno virtual activo):
    python backend\\scripts\\smoke_test_fase5.py

Qué hace:
  * Usa fastapi.testclient.TestClient sobre app.main.app: se ejecuta el lifespan completo (carga clasificador.pkl).
  * Usa una base de datos TEMPORAL (SG_DB): no toca backend/storage/syntaxguard.db.
  * Usa correos REALES del corpus del proyecto (copiados con extensión .eml en memoria).
  * Comprueba que los endpoints originales (/salud, /metricas, /predecir) y los archivos protegidos siguen iguales.
  * Comprueba que el análisis masivo da exactamente el mismo resultado que el flujo original
    (/correo/extraer + /predecir) para cada correo.
No evalúa la exactitud del modelo (el corpus incluye correos de entrenamiento): solo la integración.
"""
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PROYECTO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TMP = Path(tempfile.mkdtemp(prefix="sg_smoke5_"))
os.environ["SG_DB"] = str(TMP / "smoke.db")

import auth_helper  # noqa: E402  (Fase 6A: claves de prueba; las rutas privadas exigen sesión)
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

GRUPOS = 0
TEXTO = "WINNER!! Claim your FREE prize now: http://bit.ly/claim-now"
HTML = '<html><body><a href="http://paypa1.com/login">http://paypal.com</a></body></html>'
PROTEGIDOS = {
    "backend/app/detector.py": "0baab83513a554f80b72d006e418bf76a25722d0529a60edb8c757c769a0351c",
    "backend/app/schemas.py": "61dbc2c7a716ccac5f824087ad0e781afa195eb42621e245b69a4f53b494b91b",
    "backend/models/clasificador.pkl": "99fa052be599b1f1ee591de036d8dc9e43a0724b41d0d5a6df58ad265453233c",
    "backend/models/metricas.json": "bf93833e92aaad6407e62dfed74e14b775b92f994bd731a9081df551fe02d5e5",
    "backend/data/dataset.csv": "e17235062818f114904adf0309d25278ea78f55cbfc04d705d66253628c71cab",
    "requirements.txt": "10d0def4755eb90baa91d66c7a9566f1c6d49c43c0fd7abdba47667f1490fc07",
}


def ok(msg):
    global GRUPOS
    GRUPOS += 1
    print(f"[OK] {msg}", flush=True)


def corpus(carpeta, n):
    d = BACKEND / "data" / carpeta
    return sorted(d.iterdir())[:n]


def cabeceras(nombre, lote=None, tipo="message/rfc822"):
    h = {"X-Nombre-Archivo": nombre, "Content-Type": tipo}
    if lote is not None:
        h["X-Lote-Id"] = str(lote)
    return h


def main():
    # ---------- 0. Archivos protegidos ----------
    for rel, esperado in PROTEGIDOS.items():
        real = hashlib.sha256((PROYECTO / rel).read_bytes()).hexdigest()
        assert real == esperado, f"¡{rel} fue modificado! {real}"
    ok("Archivos protegidos idénticos (SHA-256): detector, schemas, modelo, métricas, dataset y requirements")
    m = json.loads((BACKEND / "models" / "metricas.json").read_text(encoding="utf-8"))
    assert m["test"]["accuracy"] == 0.9533 and m["test"]["matriz_confusion"] == {"tn": 175, "fp": 4, "fn": 10, "tp": 111}

    with TestClient(app) as c:
        auth_helper.iniciar_sesion(c, "fase5")  # Fase 6A
        # ---------- 1. Endpoints originales ----------
        s = c.get("/salud").json()
        assert s["modelo_cargado"] is True, s
        assert c.get("/metricas").json() == m, "/metricas debe devolver metricas.json sin cambios"
        r = c.post("/predecir", json={"texto": TEXTO, "html": HTML})
        assert r.status_code == 200 and set(r.json()) == {"es_spam", "probabilidad", "rasgos_detectados"}, r.text
        assert c.post("/predecir", json={"texto": "   "}).status_code == 422
        ok("Endpoints originales /salud, /metricas y /predecir con el modelo real, sin cambios")

        # ---------- 2. Seguridad CORS (D3) ----------
        malo = c.get("/salud", headers={"Origin": "http://sitio-malicioso.example"})
        assert "access-control-allow-origin" not in malo.headers, malo.headers
        for origen in ("http://localhost:8000", "http://127.0.0.1:8000"):
            assert c.get("/salud", headers={"Origin": origen}).headers.get("access-control-allow-origin") == origen
        ok("CORS: solo se permiten localhost y 127.0.0.1; un sitio externo no recibe permiso")

        # ---------- 3. Archivos estáticos nuevos ----------
        for ruta in ("/", "/static/css/gestion.css", "/static/js/vistas/masivo.js", "/static/js/vistas/historial.js",
                     "/static/js/vistas/metricas.js", "/static/js/vistas/retroalimentacion.js", "/static/js/vistas/acerca.js"):
            assert c.get(ruta).status_code == 200, ruta
        ok("El frontend (index, CSS y las 6 vistas) se sirve correctamente")

        # ---------- 4. Análisis individual: flujo original + guardado ----------
        spam0 = corpus("spam", 1)[0].read_bytes()
        ext = c.post("/correo/extraer", content=spam0, headers=cabeceras("individual.eml"))
        assert ext.status_code == 200, ext.text
        e = ext.json()
        pred = c.post("/predecir", json={"texto": e["texto"], "html": e["html"]})
        assert pred.status_code == 200
        p = pred.json()
        reg = c.post("/historial", json={
            "resultado": p, "nombre_archivo": e["nombre_archivo"], "asunto": e["asunto"], "remitente": e["remitente"], "fecha": e["fecha"],
            "tamano_bytes": e["tamano_bytes"], "enlaces": [x["url"] for x in e["enlaces"]], "enlaces_total": e["enlaces_total"],
            "adjuntos_ignorados": e["adjuntos_ignorados"], "advertencias": e["advertencias"]})
        assert reg.status_code == 201, reg.text
        g = reg.json()
        assert g["tipo"] == "individual" and g["es_spam"] == p["es_spam"] and g["probabilidad"] == p["probabilidad"]
        assert len(g["rasgos_detectados"]) == len(p["rasgos_detectados"])
        assert all("://" not in d for d in g["dominios"]), g["dominios"]
        det = c.get(f"/historial/{g['id']}").json()
        assert det["id"] == g["id"] and det["estado"] == "ok"
        ok(f"Individual: /correo/extraer → /predecir → /historial guardado (n.º {g['id']}; P(spam) {p['probabilidad']})")
        # validaciones del guardado
        assert c.post("/historial", json={"resultado": {**p, "es_spam": not p["es_spam"]}}).status_code == 422
        assert c.post("/historial", json={}).status_code == 422
        assert c.post("/historial", json={"resultado": {"es_spam": True}}).status_code == 422
        ok("Validaciones de POST /historial (es_spam incoherente con P(spam), cuerpo vacío, resultado incompleto)")

        # ---------- 5. Análisis masivo con correos reales y el modelo real ----------
        lote = c.post("/lotes", json={"total": 14}).json()
        assert c.post("/lotes", json={"total": -1}).status_code == 422
        archivos = [(f"spam_{i}.eml", p.read_bytes()) for i, p in enumerate(corpus("spam", 6))] + \
                   [(f"ham_{i}.eml", p.read_bytes()) for i, p in enumerate(corpus("easy_ham", 6))]
        t0 = time.perf_counter()
        igual = 0
        for nombre, datos in archivos:
            r = c.post("/analisis/archivo", content=datos, headers=cabeceras(nombre, lote["id"]))
            assert r.status_code == 200, (nombre, r.text)
            a = r.json()
            assert a["estado"] == "ok" and a["tipo"] == "masivo" and a["lote_id"] == lote["id"], a
            # mismo resultado que el flujo original (extraer + predecir)
            ex = c.post("/correo/extraer", content=datos, headers=cabeceras(nombre)).json()
            pr = c.post("/predecir", json={"texto": ex["texto"], "html": ex["html"]}).json()
            assert (a["es_spam"], a["probabilidad"]) == (pr["es_spam"], pr["probabilidad"]), f"{nombre}: masivo {a['probabilidad']} ≠ /predecir {pr['probabilidad']}"
            assert [(x["rasgo"], x["valor"], x["activo"]) for x in a["rasgos_detectados"]] == [(x["rasgo"], x["valor"], x["activo"]) for x in pr["rasgos_detectados"]]
            igual += 1
        dt = time.perf_counter() - t0
        ok(f"Masivo: 12 correos reales; el resultado coincide EXACTAMENTE con /correo/extraer + /predecir ({igual}/12; {dt / 12 * 1000:.0f} ms por correo incluyendo la verificación)")

        errores = [(b"", "vacio.eml"), (bytes(range(256)) * 4, "binario.eml"), (b"hola mundo", "foto.jpg"), (b"From: a@b.c\nSubject: x\n\n", "sincuerpo.eml")]
        for datos, nombre in errores:
            r = c.post("/analisis/archivo", content=datos, headers=cabeceras(nombre, lote["id"]))
            assert r.status_code == 200 and r.json()["estado"] == "error" and r.json()["es_spam"] is None, (nombre, r.text)
        grande = c.post("/analisis/archivo", content=b"x" * (6 * 1024 * 1024), headers=cabeceras("enorme.eml", lote["id"]))
        assert grande.status_code == 200 and grande.json()["estado"] == "error", grande.text
        txt = c.post("/analisis/archivo", content=b"Subject: hi\n\nClick the free offer now", headers=cabeceras("nota.txt", lote["id"], "text/plain"))
        assert txt.status_code == 200 and txt.json()["estado"] == "ok", txt.text
        ok("Masivo: errores individuales (vacío, binario, extensión, sin cuerpo, >5 MB) se guardan como registros y no detienen el lote; .txt aceptado")
        assert c.post("/analisis/archivo", json={"a": 1}).status_code == 415
        assert c.post("/analisis/archivo", content=b"x", headers=cabeceras("a.eml", 99999)).status_code == 404
        ok("Masivo: cuerpo JSON → 415; lote inexistente → 404")

        res = c.get(f"/lotes/{lote['id']}").json()
        assert res["total_procesados"] == 12 + 5 + 1 and res["errores"] == 5, res  # 12 reales + 5 errores + 1 .txt
        assert res["spam"] + res["legitimos"] == res["clasificados"] == 13, res
        ok(f"Resumen del lote: {res['total_procesados']} procesados · {res['spam']} SPAM · {res['legitimos']} LEGÍTIMOS · {res['errores']} errores (aparte)")

        # ---------- 6. Historial ----------
        todo = c.get("/historial", params={"por_pagina": 100}).json()
        assert todo["total"] == 1 + 18, todo["total"]
        for clas, esperado in (("spam", res["spam"] + (1 if g["es_spam"] else 0)), ("legitimo", res["legitimos"] + (0 if g["es_spam"] else 1)), ("error", 5)):
            assert c.get("/historial", params={"clasificacion": clas}).json()["total"] == esperado, clas
        assert c.get("/historial", params={"tipo": "individual"}).json()["total"] == 1
        assert c.get("/historial", params={"lote_id": lote["id"]}).json()["total"] == 18
        assert c.get("/historial", params={"q": "vacio"}).json()["total"] == 1
        pg = c.get("/historial", params={"por_pagina": 5, "pagina": 4}).json()
        assert len(pg["items"]) == 4 and pg["paginas"] == 4, pg["paginas"]
        for mal in ({"clasificacion": "otro"}, {"desde": "05/11/2026"}, {"tipo": "x"}, {"pagina": 0}, {"desde": "2026-12-01", "hasta": "2026-01-01"}):
            assert c.get("/historial", params=mal).status_code == 422, mal
        assert c.get("/historial/99999").status_code == 404
        assert c.get("/historial/abc").status_code == 422
        ok("Historial: listado, filtros (resultado, tipo, lote, texto), paginación, validaciones y 404")

        # ---------- 7. CSV (ruta declarada antes que /historial/{id}) ----------
        r = c.get("/historial/exportar.csv")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv"), (r.status_code, r.text[:100])
        assert "attachment" in r.headers["content-disposition"] and r.content.startswith(b"\xef\xbb\xbf")
        filas = [l for l in r.content.decode("utf-8-sig").splitlines() if l.strip()]
        assert len(filas) == 19 + 1 and filas[0].startswith("id,fecha_hora_local,tipo,lote,archivo")
        r2 = c.get("/historial/exportar.csv", params={"lote_id": lote["id"], "clasificacion": "spam"})
        assert r2.status_code == 200 and all(",SPAM," in l for l in r2.content.decode("utf-8-sig").splitlines()[1:])
        assert c.get("/historial/exportar.csv", params={"clasificacion": "zzz"}).status_code == 422
        ok("CSV: 200, text/csv, adjunto, BOM UTF-8, filas = registros, filtros y validación")

        # ---------- 8. Retroalimentación ----------
        aid = g["id"]
        r1 = c.post("/retroalimentacion", json={"analisis_id": aid, "de_acuerdo": True, "comentario": "Correcto"})
        r2 = c.post("/retroalimentacion", json={"analisis_id": aid, "de_acuerdo": False, "comentario": "Ahora no estoy seguro"})
        assert r1.status_code == r2.status_code == 201 and r2.json()["creado_en"].endswith("Z")
        lista = c.get("/retroalimentacion", params={"analisis_id": aid}).json()
        assert lista["total"] == 2 and lista["items"][0]["id"] == r2.json()["id"], lista
        d2 = c.get(f"/historial/{aid}").json()
        assert d2["retro_total"] == 2 and d2["retro_ultima"]["de_acuerdo"] is False and len(d2["retroalimentaciones"]) == 2
        err_id = c.get("/historial", params={"clasificacion": "error"}).json()["items"][0]["id"]
        assert c.post("/retroalimentacion", json={"analisis_id": err_id, "de_acuerdo": True}).status_code == 422
        assert c.post("/retroalimentacion", json={"analisis_id": 99999, "de_acuerdo": True}).status_code == 404
        assert c.post("/retroalimentacion", json={"analisis_id": aid}).status_code == 422
        assert c.post("/retroalimentacion", json={"analisis_id": aid, "de_acuerdo": True, "comentario": "x" * 1001}).status_code == 422
        assert c.get("/metricas").json() == m, "la retroalimentación no debe tocar las métricas del modelo"
        ok("Retroalimentación: varias entradas ligadas al análisis, la más reciente primero, validaciones; no altera el modelo ni las métricas")

        # ---------- 9. Estadísticas de uso ----------
        u = c.get("/estadisticas/uso").json()
        assert u["analizados"] == 13 + 1 and u["errores"] == 5 and u["spam"] + u["legitimos"] == u["analizados"], u
        assert u["individuales"] == 1 and u["masivos"] == 13 and u["retroalimentaciones"] == 2 and len(u["por_dia"]) == 30
        assert "accuracy" not in u and "exactitud" not in u
        ok(f"Estadísticas de uso: {u['analizados']} analizados (errores aparte: {u['errores']}), sin mezclar métricas del modelo")

        # ---------- 10. Eliminación ----------
        antes = c.get("/historial").json()["total"]
        assert c.delete(f"/historial/{aid}").status_code == 200
        assert c.delete(f"/historial/{aid}").status_code == 404
        assert c.get("/retroalimentacion", params={"analisis_id": aid}).json()["total"] == 0
        ids = [i["id"] for i in c.get("/historial", params={"por_pagina": 3}).json()["items"]]
        assert c.post("/historial/eliminar", json={"ids": ids}).json()["eliminados"] == 3
        assert c.post("/historial/eliminar", json={"ids": []}).status_code == 422
        assert c.get("/historial").json()["total"] == antes - 4
        ok("Eliminación de uno y de varios (la retroalimentación se borra con su análisis)")
        total_final = c.get("/historial").json()["total"]

    # ---------- 11. Persistencia: servidor nuevo, misma base de datos ----------
    with TestClient(app) as c2:
        auth_helper.iniciar_sesion(c2, "fase5")  # Fase 6A: nueva sesión del mismo usuario (otro "navegador")
        assert c2.get("/historial").json()["total"] == total_final
        assert c2.get("/estadisticas/uso").json()["analizados"] >= 1
        assert c2.get("/salud").json()["modelo_cargado"] is True
    ok(f"Persistencia: tras reiniciar la aplicación el historial conserva sus {total_final} registros")

    for rel, esperado in PROTEGIDOS.items():
        assert hashlib.sha256((PROYECTO / rel).read_bytes()).hexdigest() == esperado, rel
    ok("Archivos protegidos siguen idénticos después de todas las pruebas")
    print(f"\n{GRUPOS} grupos de comprobaciones superados con el MODELO REAL.")


if __name__ == "__main__":
    import shutil
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
