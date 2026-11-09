"""Pruebas de la MIGRACIÓN SQLite de la Fase 6A y de los registros antiguos sin propietario.

Uso (desde la raíz del proyecto, con el entorno virtual activo):   python backend\\scripts\\test_migracion_fase6.py

Se crea una base de datos con el esquema EXACTO de la Fase 5 (copia congelada en este archivo) y datos reales, y se
comprueba: migración correcta, idempotencia, respaldo previo, atomicidad (si falla, no queda a medias), que los
registros antiguos conservan user_id = NULL, que NUNCA se asignan al primer usuario y que ningún usuario puede verlos
ni manipularlos por la API. Todo en bases de datos TEMPORALES.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import auth_helper  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import almacen  # noqa: E402
from app.main import app  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="sg_migracion_"))
GRUPOS = 0

# Esquema de la Fase 5, tal como estaba ANTES de la Fase 6A (copia congelada).
ESQUEMA_FASE5 = """
CREATE TABLE lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creado_en TEXT NOT NULL DEFAULT (datetime('now')),
    total_previsto INTEGER
);
CREATE TABLE analisis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creado_en TEXT NOT NULL DEFAULT (datetime('now')),
    tipo TEXT NOT NULL CHECK (tipo IN ('individual', 'masivo')),
    lote_id INTEGER REFERENCES lotes(id) ON DELETE SET NULL,
    nombre_archivo TEXT, asunto TEXT, remitente TEXT, fecha_correo TEXT,
    estado TEXT NOT NULL CHECK (estado IN ('ok', 'error')),
    error TEXT, es_spam INTEGER, probabilidad REAL, rasgos_json TEXT, dominios_json TEXT,
    enlaces_total INTEGER, advertencias_json TEXT, tamano_bytes INTEGER, adjuntos_ignorados INTEGER
);
CREATE INDEX idx_analisis_creado ON analisis(creado_en);
CREATE INDEX idx_analisis_lote ON analisis(lote_id);
CREATE TABLE retroalimentacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analisis_id INTEGER NOT NULL REFERENCES analisis(id) ON DELETE CASCADE,
    de_acuerdo INTEGER NOT NULL CHECK (de_acuerdo IN (0, 1)),
    comentario TEXT,
    creado_en TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_retro_analisis ON retroalimentacion(analisis_id);
"""
COLS_FASE5 = ("id, creado_en, tipo, lote_id, nombre_archivo, asunto, remitente, fecha_correo, estado, error, es_spam, "
              "probabilidad, rasgos_json, dominios_json, enlaces_total, advertencias_json, tamano_bytes, adjuntos_ignorados")


def ok(msg):
    global GRUPOS
    GRUPOS += 1
    print(f"[OK] {msg}")


def comprobar(cond, msg):
    assert cond, msg


def crear_base_fase5(ruta: Path):
    """Base de la Fase 5 con 2 lotes, 6 análisis (spam, legítimo, error) y 3 opiniones."""
    con = sqlite3.connect(str(ruta))
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(ESQUEMA_FASE5)
    con.execute("INSERT INTO lotes (total_previsto) VALUES (3)")
    con.execute("INSERT INTO lotes (total_previsto) VALUES (1)")
    filas = [
        ("individual", None, "antiguo1.eml", "ASUNTO-ANTIGUO-1", "a@x.com", "ok", None, 1, 0.97),
        ("individual", None, "antiguo2.eml", "ASUNTO-ANTIGUO-2", "b@x.com", "ok", None, 0, 0.12),
        ("masivo", 1, "antiguo3.eml", "ASUNTO-ANTIGUO-3", "c@x.com", "ok", None, 1, 0.80),
        ("masivo", 1, "antiguo4.eml", "ASUNTO-ANTIGUO-4", "d@x.com", "ok", None, 0, 0.30),
        ("masivo", 1, "antiguo5.eml", None, None, "error", "Archivo vacío", None, None),
        ("masivo", 2, "antiguo6.eml", "ASUNTO-ANTIGUO-6", "e@x.com", "ok", None, 0, 0.05),
    ]
    for tipo, lote, nombre, asunto, rem, estado, error, spam, prob in filas:
        con.execute("INSERT INTO analisis (tipo, lote_id, nombre_archivo, asunto, remitente, estado, error, es_spam, probabilidad,"
                    " rasgos_json, dominios_json, enlaces_total) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (tipo, lote, nombre, asunto, rem, estado, error, spam, prob, "[]" if estado == "ok" else None, "[]", 0))
    for aid, acuerdo in ((1, 1), (1, 0), (3, 1)):
        con.execute("INSERT INTO retroalimentacion (analisis_id, de_acuerdo, comentario) VALUES (?,?,?)", (aid, acuerdo, f"opinion-antigua-{aid}"))
    con.commit()
    con.close()


def instantanea(ruta: Path):
    con = sqlite3.connect(str(ruta))
    try:
        return {
            "analisis": con.execute(f"SELECT {COLS_FASE5} FROM analisis ORDER BY id").fetchall(),
            "lotes": con.execute("SELECT id, creado_en, total_previsto FROM lotes ORDER BY id").fetchall(),
            "retro": con.execute("SELECT id, analisis_id, de_acuerdo, comentario, creado_en FROM retroalimentacion ORDER BY id").fetchall(),
        }
    finally:
        con.close()


def esquema(ruta: Path):
    con = sqlite3.connect(str(ruta))
    try:
        return sorted(con.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall())
    finally:
        con.close()


def main():
    # ---------- user_id es obligatorio en la capa de datos ----------
    os.environ["SG_DB"] = str(TMP / "obligatorio.db")
    almacen.iniciar()
    for fn, args in ((almacen.listar_analisis, {}), (almacen.estadisticas_uso, {}), (almacen.exportar_csv, {})):
        try:
            fn(**args)
            raise AssertionError(f"{fn.__name__} debe exigir user_id")
        except TypeError:
            pass
    for malo in (None, 0, -1, True, "1", 1.5):
        try:
            almacen.listar_analisis(user_id=malo)
            raise AssertionError(f"user_id={malo!r} debe rechazarse")
        except ValueError:
            pass
    ok("La capa de datos exige user_id (ausente, None, 0, negativo, booleano, texto o decimal -> error): no hay forma de consultar sin propietario")

    # ---------- Migración de una base de la Fase 5 con datos ----------
    ruta = TMP / "fase5.db"
    os.environ["SG_DB"] = str(ruta)
    crear_base_fase5(ruta)
    antes = instantanea(ruta)
    comprobar(len(antes["analisis"]) == 6 and len(antes["lotes"]) == 2 and len(antes["retro"]) == 3, "base de la Fase 5 preparada")
    almacen.iniciar()
    con = sqlite3.connect(str(ruta))
    tablas = {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    comprobar({"usuarios", "sesiones", "intentos_acceso", "lotes", "analisis", "retroalimentacion"} <= tablas, f"tablas: {tablas}")
    for t in ("lotes", "analisis"):
        cols = {f[1]: f for f in con.execute(f"PRAGMA table_info({t})")}
        comprobar("user_id" in cols and cols["user_id"][4] is None and cols["user_id"][3] == 0, f"{t}.user_id existe, admite NULL y sin valor por defecto")
        comprobar(any(f[2] == "usuarios" and f[3] == "user_id" for f in con.execute(f"PRAGMA foreign_key_list({t})")), f"{t}.user_id referencia a usuarios")
    indices = {f[0] for f in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    for idx in ("idx_lotes_user", "idx_analisis_user_creado", "idx_analisis_user_lote", "idx_sesiones_user", "idx_sesiones_expira", "idx_intentos_clave",
                "idx_analisis_creado", "idx_analisis_lote", "idx_retro_analisis"):
        comprobar(idx in indices, f"falta el índice {idx}")
    comprobar(con.execute("PRAGMA user_version").fetchone()[0] == almacen.VERSION_ESQUEMA == 6, "user_version = 6")
    comprobar(con.execute("PRAGMA integrity_check").fetchone()[0] == "ok" and con.execute("PRAGMA foreign_key_check").fetchall() == [], "integridad")
    comprobar(con.execute("SELECT COUNT(*) FROM analisis WHERE user_id IS NOT NULL").fetchone()[0] == 0, "ningún análisis antiguo tiene propietario")
    comprobar(con.execute("SELECT COUNT(*) FROM lotes WHERE user_id IS NOT NULL").fetchone()[0] == 0, "ningún lote antiguo tiene propietario")
    comprobar(con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0, "la migración NO crea ningún usuario")
    con.close()
    comprobar(instantanea(ruta) == antes, "todos los datos antiguos (todas las columnas) quedaron idénticos")
    ok("Migración Fase 5 -> 6A: tablas, user_id (NULL), índices y user_version; los 6 análisis, 2 lotes y 3 opiniones quedan idénticos y sin propietario")

    respaldo = ruta.with_name(ruta.name + ".pre_fase6.bak")
    comprobar(respaldo.exists(), "se creó el respaldo previo a la migración")
    comprobar(instantanea(respaldo) == antes, "el respaldo contiene los datos originales")
    cb = sqlite3.connect(str(respaldo))
    comprobar("user_id" not in {f[1] for f in cb.execute("PRAGMA table_info(analisis)")}, "el respaldo es el esquema anterior")
    cb.close()
    mtime = respaldo.stat().st_mtime_ns
    ok("Respaldo automático (.pre_fase6.bak) con el esquema y los datos originales, creado ANTES de modificar")

    esquema1 = esquema(ruta)
    for _ in range(3):
        almacen.iniciar()
    comprobar(esquema(ruta) == esquema1, "el esquema no cambia al repetir la migración")
    comprobar(instantanea(ruta) == antes, "los datos no cambian al repetir la migración")
    comprobar(respaldo.stat().st_mtime_ns == mtime, "el respaldo no se vuelve a escribir")
    ok("Idempotente: ejecutar la migración 3 veces más no cambia el esquema, los datos ni el respaldo")

    # ---------- Base nueva: sin respaldo ----------
    os.environ["SG_DB"] = str(TMP / "nueva.db")
    almacen.iniciar()
    comprobar(not (TMP / "nueva.db.pre_fase6.bak").exists(), "una base nueva no necesita respaldo")
    con = sqlite3.connect(str(TMP / "nueva.db"))
    comprobar(con.execute("PRAGMA user_version").fetchone()[0] == 6 and con.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "base nueva")
    con.close()
    ok("Base nueva: se crea directamente con el esquema de la Fase 6A, sin respaldo")

    # ---------- Atomicidad ----------
    ruta_f = TMP / "falla.db"
    os.environ["SG_DB"] = str(ruta_f)
    crear_base_fase5(ruta_f)
    esquema_ant, datos_ant = esquema(ruta_f), instantanea(ruta_f)
    original = almacen.INDICES_AUTH
    almacen.INDICES_AUTH = original + "\nCREATE INDEX idx_roto ON tabla_que_no_existe(x);"
    try:
        almacen.iniciar()
        raise AssertionError("la migración debía fallar")
    except sqlite3.OperationalError:
        pass
    finally:
        almacen.INDICES_AUTH = original
    comprobar(esquema(ruta_f) == esquema_ant and instantanea(ruta_f) == datos_ant, "tras el fallo la base quedó EXACTAMENTE como estaba (rollback)")
    comprobar("user_id" not in {f[1] for f in sqlite3.connect(str(ruta_f)).execute("PRAGMA table_info(analisis)")}, "sin columnas a medias")
    almacen.iniciar()  # y al corregir el problema, la migración se completa
    comprobar(instantanea(ruta_f) == datos_ant and sqlite3.connect(str(ruta_f)).execute("PRAGMA user_version").fetchone()[0] == 6, "reintento correcto")
    ok("Atómica: si algo falla a mitad de la migración se revierte todo; al reintentar se completa sin pérdida de datos")

    # ---------- Registros antiguos y API ----------
    ruta_a = TMP / "api.db"
    os.environ["SG_DB"] = str(ruta_a)
    crear_base_fase5(ruta_a)
    antes_api = instantanea(ruta_a)
    with TestClient(app):  # el arranque de la aplicación migra la base
        u1, u2 = TestClient(app), TestClient(app)
        s1 = auth_helper.iniciar_sesion(u1, "primero")
        s2 = auth_helper.iniciar_sesion(u2, "segundo")
        comprobar(s1["usuario"]["id"] == 1, "el primer usuario es el id 1")
        for nombre, cli in (("primero (el primer usuario)", u1), ("segundo", u2)):
            h = cli.get("/historial", params={"por_pagina": 100}).json()
            comprobar(h["total"] == 0 and h["items"] == [], f"{nombre} NO ve los registros antiguos")
            est = cli.get("/estadisticas/uso").json()
            comprobar(est["analizados"] == 0 and est["errores"] == 0 and est["lotes"] == 0 and est["retroalimentaciones"] == 0, f"{nombre}: estadísticas en cero {est}")
            comprobar(len(cli.get("/historial/exportar.csv").content.decode("utf-8-sig").strip().splitlines()) == 1, f"{nombre}: CSV solo con cabecera")
            comprobar("ASUNTO-ANTIGUO" not in cli.get("/historial/exportar.csv").text and cli.get("/retroalimentacion").json()["total"] == 0, "nada antiguo")
            for aid in range(1, 7):
                comprobar(cli.get(f"/historial/{aid}").status_code == 404, f"{nombre}: el análisis antiguo {aid} no es accesible")
                comprobar(cli.post("/retroalimentacion", json={"analisis_id": aid, "de_acuerdo": True}).status_code == 404, "no se puede opinar sobre uno antiguo")
            for lid in (1, 2):
                comprobar(cli.get(f"/lotes/{lid}").status_code == 404, f"{nombre}: el lote antiguo {lid} no es accesible")
                r = cli.post("/analisis/archivo", content=b"Subject: x\n\nhola", headers={"Content-Type": "text/plain", "X-Lote-Id": str(lid)})
                comprobar(r.status_code == 404, "no se pueden añadir correos a un lote antiguo")
            comprobar(cli.post("/historial/eliminar", json={"ids": list(range(1, 7))}).json()["eliminados"] == 0, f"{nombre}: no puede eliminar los antiguos")
            comprobar(cli.delete("/historial/1").status_code == 404, "ni uno por uno")
        # Los usuarios siguen funcionando con normalidad con datos nuevos
        pred = u1.post("/predecir", json={"texto": "WINNER!! Claim your FREE prize now"}).json()
        comprobar(u1.post("/historial", json={"resultado": pred, "asunto": "nuevo"}).status_code == 201, "el usuario crea datos propios")
        comprobar(u1.get("/historial").json()["total"] == 1 and u2.get("/historial").json()["total"] == 0, "y solo él los ve")
    con = sqlite3.connect(str(ruta_a))
    comprobar(con.execute("SELECT COUNT(*) FROM analisis WHERE user_id IS NULL").fetchone()[0] == 6, "los 6 análisis antiguos siguen sin propietario")
    comprobar(con.execute("SELECT COUNT(*) FROM lotes WHERE user_id IS NULL").fetchone()[0] == 2, "los 2 lotes antiguos siguen sin propietario")
    comprobar(con.execute("SELECT COUNT(*) FROM analisis WHERE user_id=1").fetchone()[0] == 1, "solo el registro nuevo es del primer usuario")
    comprobar(con.execute("SELECT COUNT(*) FROM retroalimentacion").fetchone()[0] == 3, "las opiniones antiguas siguen ahí")
    con.close()
    comprobar(instantanea(ruta_a)["analisis"][:6] == antes_api["analisis"], "los registros antiguos no cambiaron ni una columna")
    ok("Registros antiguos: se conservan con user_id = NULL, NUNCA se asignan al primer usuario y ningún usuario puede verlos, exportarlos, contarlos, opinar, eliminarlos ni añadirlos a sus lotes")

    # ---------- Borrado en cascada de un usuario ----------
    os.environ["SG_DB"] = str(TMP / "cascada.db")
    almacen.iniciar()
    from app import usuarios as u
    uid = u.crear_usuario("temporal", "Contrasena-de-prueba-2026")["id"]
    almacen.guardar_analisis(user_id=uid, tipo="individual", estado="ok", es_spam=False, probabilidad=0.1, rasgos=[])
    with almacen.conexion() as c:
        c.execute("DELETE FROM usuarios WHERE id=?", (uid,))
        comprobar(c.execute("SELECT COUNT(*) FROM analisis").fetchone()[0] == 0, "al borrar un usuario se borran sus datos (no quedan huérfanos accesibles)")
    ok("Si se elimina un usuario, sus análisis y sesiones se eliminan en cascada (no quedan datos huérfanos)")
    print(f"\n{GRUPOS} grupos de comprobaciones superados.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
