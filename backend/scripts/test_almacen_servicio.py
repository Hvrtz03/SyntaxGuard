"""Pruebas de la capa de persistencia y de la lógica de análisis (Fase 5), SIN FastAPI y SIN el modelo.

Uso (desde la raíz del proyecto):   python backend\\scripts\\test_almacen_servicio.py

IMPORTANTE: aquí el detector es un DETECTOR SIMULADO (clase DetectorSimulado) que solo imita el formato de
SpamDetector.predecir. Sirve para probar el almacenamiento, el historial, los lotes, la retroalimentación, las
estadísticas y el CSV. NO prueba el modelo real: eso lo hace smoke_test_fase5.py.
La extracción de correos (app.correo) y los correos del corpus (data/easy_ham, data/spam) SÍ son reales.
Usa una base de datos temporal; no toca storage/syntaxguard.db.
"""
import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PROYECTO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TMP = Path(tempfile.mkdtemp(prefix="sg_prueba_"))
os.environ["SG_DB"] = str(TMP / "prueba.db")
os.environ.setdefault("SG_PBKDF2_ITER", "1000")  # Fase 6A: solo para que la prueba sea rápida

from app import almacen as _almacen, correo, usuarios  # noqa: E402
from app import servicio as _servicio  # noqa: E402
from app.almacen import ErrorAlmacen  # noqa: E402

# Fase 6A: las funciones de almacen/servicio exigen `user_id` (aislamiento por usuario). Estas envolturas se lo
# añaden a cada llamada con un usuario de prueba, así esta prueba de la Fase 5 se conserva casi sin cambios.
# El aislamiento entre usuarios se prueba en test_aislamiento_fase6.py.
UID = None
_CON_USUARIO = {
    _almacen: {"crear_lote", "existe_lote", "resumen_lote", "guardar_analisis", "obtener_analisis", "listar_analisis",
               "eliminar_analisis", "guardar_retro", "listar_retro", "estadisticas_uso", "exportar_csv"},
    _servicio: {"registrar_individual", "registrar_error_archivo", "analizar_archivo"},
}


def _con_usuario(modulo):
    class _Envoltura:
        def __getattr__(self, nombre):
            f = getattr(modulo, nombre)
            if nombre in _CON_USUARIO[modulo]:
                return lambda *a, **k: f(*a, user_id=UID, **k)
            return f
    return _Envoltura()


almacen, servicio = _con_usuario(_almacen), _con_usuario(_servicio)

PRUEBAS = 0


def ok(msg):
    global PRUEBAS
    PRUEBAS += 1
    print(f"[OK] {msg}")


def comprobar(cond, msg):
    assert cond, msg


def lanza(estado, fn, *a, **k):
    try:
        fn(*a, **k)
    except ErrorAlmacen as e:
        comprobar(e.estado == estado, f"se esperaba {estado} y fue {e.estado}: {e.mensaje}")
        return e
    raise AssertionError(f"debía lanzar ErrorAlmacen({estado})")


class DetectorSimulado:
    """NO es el modelo. Mismo formato de salida que SpamDetector.predecir."""
    def predecir(self, texto, html=None):
        p = 0.9 if any(w in texto.lower() for w in ("free", "click", "winner", "offer", "viagra", "money")) else 0.1
        return {"es_spam": p >= 0.5, "probabilidad": p,
                "rasgos_detectados": [{"rasgo": "txt_ratio_spam", "categoria": "texto", "valor": p,
                                       "activo": p > 0.5, "descripcion": "simulado"}]}


class DetectorRoto:
    def predecir(self, texto, html=None):
        raise RuntimeError("fallo simulado")


def corpus(carpeta, n):
    d = BACKEND / "data" / carpeta
    return [d / x for x in sorted(os.listdir(d))[:n]]


def main():
    global UID
    almacen.iniciar()
    UID = usuarios.crear_usuario("pruebas", "Contrasena-de-prueba-2026")["id"]
    ok("La base de datos se crea (tablas lotes, analisis, retroalimentacion)")
    det = DetectorSimulado()

    # ---------- Registro individual ----------
    res = {"es_spam": True, "probabilidad": 0.9123,
           "rasgos_detectados": [{"rasgo": "url_acortador", "categoria": "url", "valor": 1.0, "activo": True, "descripcion": "x"}]}
    sec = "https://phish.example.net/ruta/secreta?token=ABC123SECRETO"
    r = servicio.registrar_individual({
        "resultado": res, "nombre_archivo": "uno.eml", "asunto": "Oferta", "remitente": "a@b.com",
        "enlaces": [sec, "http://www.Ejemplo.com/x"], "enlaces_total": 2, "tamano_bytes": 500,
        "texto": "CUERPO SECRETO DEL CORREO", "html": "<p>HTML SECRETO</p>"})
    comprobar(r["tipo"] == "individual" and r["estado"] == "ok" and r["es_spam"] is True and r["probabilidad"] == 0.9123, "registro individual")
    comprobar(r["dominios"] == ["phish.example.net", "www.ejemplo.com"], f"dominios: {r['dominios']}")
    ok("Registro individual guardado con sus datos y solo los dominios de los enlaces")
    crudo = Path(os.environ["SG_DB"]).read_bytes()
    for prohibido in (b"ABC123SECRETO", b"ruta/secreta", b"CUERPO SECRETO", b"HTML SECRETO"):
        comprobar(prohibido not in crudo, f"el archivo de la base contiene {prohibido!r}")
    ok("D1: la base no contiene el texto, el HTML ni las URL completas")

    lanza(422, servicio.registrar_individual, {"resultado": {**res, "es_spam": False}})
    lanza(422, servicio.registrar_individual, {"resultado": {**res, "probabilidad": 1.5}})
    lanza(422, servicio.registrar_individual, {"resultado": {**res, "rasgos_detectados": [{"rasgo": 1}]}})
    lanza(422, servicio.registrar_individual, {})
    lanza(422, servicio.registrar_individual, {"resultado": {**res, "es_spam": "si"}})
    servicio.registrar_individual({"resultado": {**res, "es_spam": False, "probabilidad": 0.5}})  # redondeo en el límite
    ok("Validaciones: es_spam incoherente con el umbral, probabilidad fuera de rango, rasgos mal formados, cuerpo vacío")

    # ---------- Lote masivo con correos reales ----------
    lote = almacen.crear_lote(14)
    spam_f, ham_f = corpus("spam", 6), corpus("easy_ham", 6)
    nombres = []
    for i, p in enumerate(spam_f + ham_f):
        nombre = f"{i:02d}_{p.name[:8]}.eml"
        nombres.append(nombre)
        out = servicio.analizar_archivo(det, p.read_bytes(), nombre, lote["id"])
        comprobar(out["estado"] == "ok" and out["tipo"] == "masivo" and out["lote_id"] == lote["id"], f"{nombre}: {out}")
        comprobar(out["asunto"] is None or isinstance(out["asunto"], str), "asunto")
    ok("12 correos reales del corpus (6 spam, 6 legítimos) analizados y guardados en un lote")

    malos = [(b"", "vacio.eml"), (b"\x00\x01\x02binario", "bin.eml"), (b"hola", "foto.jpg"),
             (b"From: a@b.c\nSubject: sin cuerpo\n\n", "sincuerpo.eml")]
    for datos, nombre in malos:
        out = servicio.analizar_archivo(det, datos, nombre, lote["id"])
        comprobar(out["estado"] == "error" and out["error"] and out["es_spam"] is None, f"{nombre}: {out}")
    out = servicio.analizar_archivo(DetectorRoto(), spam_f[0].read_bytes(), "roto.eml", lote["id"])
    comprobar(out["estado"] == "error" and "RuntimeError" in out["error"], "error del detector")
    grande = servicio.registrar_error_archivo("enorme.eml", 6 * 1024 * 1024, "El correo supera el tamaño máximo de 5 MB.", lote["id"])
    comprobar(grande["estado"] == "error", "error por tamaño")
    ok("Los errores individuales (vacío, binario, extensión, sin texto, fallo del detector, tamaño) se guardan sin detener el lote")

    # los .txt también se aceptan (D7) con las mismas validaciones
    out = servicio.analizar_archivo(det, b"Subject: hi\n\nClick the free offer now!!!", "nota.txt", lote["id"])
    comprobar(out["estado"] == "ok" and out["es_spam"] is True, "txt")
    out = servicio.analizar_archivo(det, b"Good morning, attached the notes for tomorrow's meeting.", "pegado.txt", lote["id"])
    comprobar(out["estado"] == "ok" and out["es_spam"] is False, "txt sin cabeceras")
    lanza(503, servicio.analizar_archivo, None, b"x", "a.eml", None)
    lanza(404, servicio.analizar_archivo, det, b"x", "a.eml", 99999)
    ok("D7: .txt aceptado con las mismas validaciones; sin modelo -> 503; lote inexistente -> 404")

    s = almacen.resumen_lote(lote["id"])
    comprobar(s["total_procesados"] == 12 + 4 + 1 + 1 + 2, f"total {s}")
    comprobar(s["errores"] == 6 and s["spam"] + s["legitimos"] == s["clasificados"] == 14, f"resumen {s}")
    comprobar(s["porcentaje_spam"] + s["porcentaje_legitimos"] in (100.0, 99.9, 100.1), f"porcentajes {s}")
    comprobar(abs(s["porcentaje_spam"] - 100 * s["spam"] / s["clasificados"]) < 0.06, "porcentaje spam")
    lanza(404, almacen.resumen_lote, 12345)
    ok(f"Resumen del lote correcto: {s['total_procesados']} procesados, {s['spam']} SPAM, {s['legitimos']} LEGÍTIMOS, {s['errores']} errores")

    # ---------- Historial: listado y filtros ----------
    todo = almacen.listar_analisis(por_pagina=100)
    comprobar(todo["total"] == 2 + 20, f"total historial {todo['total']}")  # 2 individuales + 20 del lote
    comprobar(todo["items"][0]["id"] > todo["items"][-1]["id"], "orden: más reciente primero")
    comprobar("rasgos_detectados" not in todo["items"][0], "el listado no trae rasgos")
    sp = almacen.listar_analisis(clasificacion="spam", por_pagina=100)
    lg = almacen.listar_analisis(clasificacion="legitimo", por_pagina=100)
    er = almacen.listar_analisis(clasificacion="error", por_pagina=100)
    comprobar(sp["total"] + lg["total"] + er["total"] == todo["total"], "spam + legítimo + error = total")
    comprobar(all(i["es_spam"] is True and i["estado"] == "ok" for i in sp["items"]), "solo spam")
    comprobar(all(i["es_spam"] is False for i in lg["items"]), "solo legítimos")
    comprobar(all(i["estado"] == "error" for i in er["items"]) and er["total"] == 6, "solo errores")
    ok("Filtros por clasificación (SPAM / LEGÍTIMO / error) coherentes entre sí")

    comprobar(almacen.listar_analisis(q="uno.eml")["total"] == 1, "búsqueda por nombre")
    comprobar(almacen.listar_analisis(q="OFERTA")["total"] == 1, "búsqueda por asunto sin distinguir mayúsculas")
    comprobar(almacen.listar_analisis(q="%")["total"] == 0, "'%' se trata como texto, no como comodín")
    comprobar(almacen.listar_analisis(q="'; DROP TABLE analisis; --")["total"] == 0, "inyección SQL inofensiva")
    comprobar(almacen.listar_analisis()["total"] == todo["total"], "la tabla sigue intacta")
    ok("Búsqueda por nombre y asunto; comodines y comillas tratados como texto (sin inyección SQL)")

    hoy = date.today().isoformat()
    comprobar(almacen.listar_analisis(desde=hoy, hasta=hoy)["total"] == todo["total"], "fecha de hoy")
    comprobar(almacen.listar_analisis(desde="2000-01-01", hasta="2000-12-31")["total"] == 0, "fecha antigua")
    lanza(422, almacen.listar_analisis, desde="05/11/2026")
    lanza(422, almacen.listar_analisis, desde="2026-12-01", hasta="2026-01-01")
    lanza(422, almacen.listar_analisis, clasificacion="otro")
    lanza(422, almacen.listar_analisis, tipo="x")
    lanza(422, almacen.listar_analisis, pagina=0)
    ok("Filtro por rango de fechas (hora local) y validación de parámetros")

    comprobar(almacen.listar_analisis(tipo="individual")["total"] == 2, "tipo individual")
    comprobar(almacen.listar_analisis(tipo="masivo")["total"] == 20, "tipo masivo")
    comprobar(almacen.listar_analisis(lote_id=lote["id"])["total"] == 20, "por lote")
    p1 = almacen.listar_analisis(por_pagina=5, pagina=1)
    p5 = almacen.listar_analisis(por_pagina=5, pagina=5)
    comprobar(len(p1["items"]) == 5 and p1["paginas"] == 5 and len(p5["items"]) == 2, "paginación")
    comprobar(almacen.listar_analisis(por_pagina=100000)["por_pagina"] == almacen.POR_PAGINA_MAX, "tope de página")
    ok("Filtros por tipo y lote; paginación")

    # ---------- Detalle ----------
    det1 = almacen.obtener_analisis(r["id"])
    comprobar(det1["rasgos_detectados"][0]["rasgo"] == "url_acortador" and det1["retroalimentaciones"] == [], "detalle")
    lanza(404, almacen.obtener_analisis, 424242)
    ok("Detalle de un análisis con rasgos; id inexistente -> 404")

    # ---------- Retroalimentación ----------
    a_id = r["id"]
    f1 = almacen.guardar_retro(a_id, True, "Correcto")
    f2 = almacen.guardar_retro(a_id, False, "  Ahora creo que no  ")
    con = sqlite3.connect(os.environ["SG_DB"])
    con.execute("UPDATE retroalimentacion SET creado_en='2026-01-01 10:00:00' WHERE id=?", (f1["id"],))
    con.commit(); con.close()
    d = almacen.obtener_analisis(a_id)
    comprobar([x["id"] for x in d["retroalimentaciones"]] == [f2["id"], f1["id"]], "más reciente primero")
    comprobar(d["retro_total"] == 2 and d["retro_ultima"]["de_acuerdo"] is False and d["retro_ultima"]["comentario"] == "Ahora creo que no", "última retro")
    comprobar(d["retro_ultima"]["creado_en"].endswith("Z") and "T" in d["retro_ultima"]["creado_en"], "fecha ISO UTC")
    lr = almacen.listar_retro()
    comprobar(lr["total"] == 2 and lr["items"][0]["id"] == f2["id"] and lr["items"][0]["asunto"] == "Oferta", "lista de retros")
    comprobar(almacen.listar_retro(analisis_id=a_id)["total"] == 2 and almacen.listar_retro(analisis_id=999)["total"] == 0, "filtro por análisis")
    lanza(404, almacen.guardar_retro, 99999, True)
    lanza(422, almacen.guardar_retro, er["items"][0]["id"], True)
    lanza(422, almacen.guardar_retro, a_id, "si")
    lanza(422, almacen.guardar_retro, a_id, None)
    almacen.guardar_retro(a_id, True, "x" * 5000)
    comprobar(len(almacen.listar_retro(analisis_id=a_id)["items"][0]["comentario"]) == 1000, "comentario recortado a 1000")
    ok("Retroalimentación: varias entradas por análisis, la más reciente primero, con fecha y hora; validaciones")

    # ---------- Estadísticas de uso ----------
    e = almacen.estadisticas_uso()
    comprobar(e["analizados"] == 16 and e["errores"] == 6, f"estadísticas {e}")
    comprobar(e["spam"] + e["legitimos"] == e["analizados"] and e["individuales"] == 2 and e["masivos"] == 14, "conteos")
    comprobar(abs(e["porcentaje_spam"] - 100 * e["spam"] / e["analizados"]) < 0.06, "% spam")
    comprobar(len(e["por_dia"]) == 30 and e["por_dia"][-1]["dia"] == hoy and e["por_dia"][-1]["total"] == 16, "serie diaria")
    comprobar(sum(x["total"] for x in e["por_dia"]) == 16 and e["retroalimentaciones"] == 3 and e["lotes"] == 1, "totales")
    comprobar("exactitud" not in e and "accuracy" not in e, "no mezcla métricas del modelo")
    vacio = TMP / "vacia.db"
    ant = os.environ["SG_DB"]; os.environ["SG_DB"] = str(vacio); almacen.iniciar()
    ev = almacen.estadisticas_uso()
    comprobar(ev["analizados"] == 0 and ev["porcentaje_spam"] is None and all(x["total"] == 0 for x in ev["por_dia"]), "estadísticas vacías")
    os.environ["SG_DB"] = ant
    ok("Estadísticas de uso: solo registros reales (errores aparte), sin porcentajes inventados cuando no hay datos")

    # ---------- CSV ----------
    servicio.registrar_individual({"resultado": res, "nombre_archivo": "=HYPERLINK(\"x\").eml", "asunto": "+cmd|' /C calc'!A0",
                                   "remitente": "@evil", "enlaces": []})
    datos = almacen.exportar_csv()
    comprobar(datos.startswith(b"\xef\xbb\xbf"), "BOM UTF-8")
    filas = list(csv.reader(io.StringIO(datos.decode("utf-8-sig"))))
    comprobar(filas[0] == almacen.COLUMNAS_CSV and len(filas) - 1 == almacen.listar_analisis()["total"], "filas del CSV")
    peligrosas = [f for f in filas[1:] if "HYPERLINK" in f[4]]
    comprobar(peligrosas and peligrosas[0][4].startswith("'=") and peligrosas[0][5].startswith("'+") and peligrosas[0][6].startswith("'@"), "fórmulas neutralizadas")
    clas = {f[7] for f in filas[1:]}
    comprobar(clas <= {"SPAM", "LEGÍTIMO", "ERROR"}, f"clasificaciones {clas}")
    filtrado = list(csv.reader(io.StringIO(almacen.exportar_csv(lote_id=lote["id"]).decode("utf-8-sig"))))
    comprobar(len(filtrado) - 1 == 20 and all(f[3] == str(lote["id"]) for f in filtrado[1:]), "CSV por lote")
    solo_spam = list(csv.reader(io.StringIO(almacen.exportar_csv(clasificacion="spam").decode("utf-8-sig"))))
    comprobar(all(f[7] == "SPAM" for f in solo_spam[1:]), "CSV filtrado")
    ok("CSV: BOM UTF-8, columnas, filtros, y celdas que empiezan con = + - @ neutralizadas")

    # ---------- Eliminación ----------
    n_antes = almacen.listar_analisis()["total"]
    comprobar(almacen.eliminar_analisis([a_id]) == 1, "eliminar uno")
    lanza(404, almacen.obtener_analisis, a_id)
    comprobar(almacen.listar_retro(analisis_id=a_id)["total"] == 0, "la retroalimentación se borra en cascada")
    ids = [i["id"] for i in almacen.listar_analisis(por_pagina=3)["items"]]
    comprobar(almacen.eliminar_analisis(ids) == 3 and almacen.listar_analisis()["total"] == n_antes - 4, "eliminar varios")
    comprobar(almacen.eliminar_analisis([777777]) == 0, "id inexistente")
    lanza(422, almacen.eliminar_analisis, [])
    lanza(422, almacen.eliminar_analisis, ["a"])
    lanza(422, almacen.eliminar_analisis, list(range(1, almacen.MAX_IDS + 2)))
    ok("Eliminación de uno y de varios registros (con su retroalimentación); validaciones")

    # ---------- Persistencia tras reiniciar ----------
    total = almacen.listar_analisis()["total"]
    codigo = ("import os,sys; sys.path.insert(0, r'%s'); from app import almacen; almacen.iniciar(); "
              "print(almacen.listar_analisis(user_id=%d)['total'], almacen.estadisticas_uso(user_id=%d)['analizados'])"
              % (BACKEND, UID, UID))
    out = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, env=dict(os.environ)).stdout.split()
    comprobar(out and int(out[0]) == total, f"otro proceso ve {out}, esperado {total}")
    ok(f"Persistencia: un proceso nuevo lee los mismos {total} registros de la base de datos")

    # ---------- Seguridad / aislamiento ----------
    comprobar("app.detector" not in sys.modules, "servicio/almacen no deben cargar el detector")
    ok("La capa de datos no importa ni duplica el detector")

    # ---------- Archivos protegidos ----------
    esperado = {
        "backend/app/detector.py": "0baab83513a554f80b72d006e418bf76a25722d0529a60edb8c757c769a0351c",
        "backend/app/schemas.py": "61dbc2c7a716ccac5f824087ad0e781afa195eb42621e245b69a4f53b494b91b",
        "backend/models/clasificador.pkl": "99fa052be599b1f1ee591de036d8dc9e43a0724b41d0d5a6df58ad265453233c",
        "backend/models/metricas.json": "bf93833e92aaad6407e62dfed74e14b775b92f994bd731a9081df551fe02d5e5",
        "requirements.txt": "10d0def4755eb90baa91d66c7a9566f1c6d49c43c0fd7abdba47667f1490fc07",
        "backend/data/dataset.csv": "e17235062818f114904adf0309d25278ea78f55cbfc04d705d66253628c71cab",
    }
    for rel, h in esperado.items():
        p = PROYECTO / rel
        comprobar(p.exists(), f"falta {rel}")
        dig = hashlib.sha256(p.read_bytes()).hexdigest()
        comprobar(dig.startswith(h), f"¡{rel} CAMBIÓ!")
    ok("Archivos protegidos idénticos (SHA-256): detector, schemas, modelo, métricas, requirements y dataset")
    m = json.loads((BACKEND / "models" / "metricas.json").read_text(encoding="utf-8"))["test"]
    comprobar((m["accuracy"], m["precision"], m["recall"], m["f1"]) == (0.9533, 0.9652, 0.9174, 0.9407), "métricas")
    comprobar(m["matriz_confusion"] == {"tn": 175, "fp": 4, "fn": 10, "tp": 111}, "matriz")
    ok("metricas.json conserva 0.9533 / 0.9652 / 0.9174 / 0.9407 y la matriz 175/4/10/111")

    print(f"\n{PRUEBAS} grupos de comprobaciones superados (detector SIMULADO; no es una prueba del modelo real).")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
