"""Pruebas de AISLAMIENTO de datos entre usuarios (Fase 6A), con la API REAL y el MODELO REAL.

Uso (desde la raíz del proyecto, con el entorno virtual activo):   python backend\\scripts\\test_aislamiento_fase6.py

Tres usuarios (ana, beto y carla). Ana y Beto crean datos reales: análisis individuales (con el modelo real), un lote
con correos reales del corpus, errores de archivo, retroalimentación. Carla no crea nada. Después se comprueba, para
CADA recurso, que ningún usuario puede ver ni manipular lo de otro, ni siquiera conociendo los ids (IDOR).
Recursos: historial, detalle, eliminación individual y múltiple, retroalimentación, lotes, análisis masivos, errores de
archivos, estadísticas de uso y CSV. También: el cliente no puede imponer un user_id.
La base de datos es TEMPORAL.
"""
import csv
import io
import os
import sqlite3
import sys
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

GRUPOS = 0
TEXTO_SPAM = "WINNER!! Claim your FREE prize now: http://bit.ly/claim-now"
TEXTO_HAM = "Hi team, attached are the notes for tomorrow's meeting. Thanks, see you at ten."


def ok(msg):
    global GRUPOS
    GRUPOS += 1
    print(f"[OK] {msg}")


def comprobar(cond, msg):
    assert cond, msg


def corpus(carpeta, desde, n):
    d = BACKEND / "data" / carpeta
    return [d / x for x in sorted(os.listdir(d))[desde:desde + n]]


def sql(consulta, par=()):
    con = sqlite3.connect(os.environ["SG_DB"])
    con.row_factory = sqlite3.Row
    try:
        return con.execute(consulta, par).fetchall()
    finally:
        con.close()


def csv_filas(r):
    return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))


def crear_datos(c, quien):
    """Crea datos reales con el cliente `c` (ya autenticado). Devuelve los ids creados."""
    d = {"individuales": [], "lote": None, "masivos": [], "errores": [], "retro": [], "marcas": []}
    for i, texto in enumerate((TEXTO_SPAM, TEXTO_HAM)):
        pred = c.post("/predecir", json={"texto": texto})
        assert pred.status_code == 200, pred.text
        marca = f"SECRETO-{quien}-individual-{i}"
        r = c.post("/historial", json={"resultado": pred.json(), "nombre_archivo": f"{marca}.eml", "asunto": marca,
                                       "remitente": f"{quien}@privado.example", "enlaces": [f"http://dominio-{quien}.example/ruta?token=XYZ"],
                                       "enlaces_total": 1})
        assert r.status_code == 201, r.text
        d["individuales"].append(r.json()["id"])
        d["marcas"].append(marca)
    lote = c.post("/lotes", json={"total": 4})
    assert lote.status_code == 201, lote.text
    d["lote"] = lote.json()["id"]
    desde = 0 if quien == "ana" else 20  # correos distintos para cada usuario
    for p in corpus("easy_ham", desde, 2) + corpus("spam", desde, 1):
        marca = f"SECRETO-{quien}-{p.name[:8]}"
        r = c.post("/analisis/archivo", content=p.read_bytes(),
                   headers={"Content-Type": "message/rfc822", "X-Nombre-Archivo": marca + ".eml", "X-Lote-Id": str(d["lote"])})
        assert r.status_code == 200 and r.json()["estado"] == "ok", r.text
        d["masivos"].append(r.json()["id"])
        d["marcas"].append(marca)
    marca_err = f"SECRETO-{quien}-vacio"
    r = c.post("/analisis/archivo", content=b"   ", headers={"Content-Type": "text/plain", "X-Nombre-Archivo": marca_err + ".txt",
                                                              "X-Lote-Id": str(d["lote"])})
    assert r.status_code == 200 and r.json()["estado"] == "error", r.text
    d["errores"].append(r.json()["id"])
    d["marcas"].append(marca_err)
    for aid, acuerdo in ((d["individuales"][0], True), (d["individuales"][0], False), (d["masivos"][0], True)):
        r = c.post("/retroalimentacion", json={"analisis_id": aid, "de_acuerdo": acuerdo, "comentario": f"COMENTARIO-{quien}-{aid}"})
        assert r.status_code == 201, r.text
        d["retro"].append(r.json()["id"])
    d["todos"] = d["individuales"] + d["masivos"] + d["errores"]
    return d


def main():
    with TestClient(app) as base:
        ana, beto, carla = TestClient(app), TestClient(app), TestClient(app)
        sa = auth_helper.iniciar_sesion(ana, "ana")
        sb = auth_helper.iniciar_sesion(beto, "beto")
        sc = auth_helper.iniciar_sesion(carla, "carla")
        ida, idb, idc = sa["usuario"]["id"], sb["usuario"]["id"], sc["usuario"]["id"]
        comprobar(len({ida, idb, idc}) == 3, "tres usuarios distintos")
        A = crear_datos(ana, "ana")
        B = crear_datos(beto, "beto")
        comprobar(not set(A["todos"]) & set(B["todos"]) and A["lote"] != B["lote"], "ids distintos")
        ok(f"Preparación: ana creó {len(A['todos'])} análisis y un lote; beto {len(B['todos'])} y otro lote; carla no creó nada")

        # ---------- Historial privado ----------
        la = ana.get("/historial", params={"por_pagina": 100}).json()
        lb = beto.get("/historial", params={"por_pagina": 100}).json()
        lc = carla.get("/historial", params={"por_pagina": 100}).json()
        comprobar({i["id"] for i in la["items"]} == set(A["todos"]) and la["total"] == len(A["todos"]), "historial de ana")
        comprobar({i["id"] for i in lb["items"]} == set(B["todos"]) and lb["total"] == len(B["todos"]), "historial de beto")
        comprobar(lc["total"] == 0 and lc["items"] == [], "carla ve su historial vacío")
        for filtro in ({"q": "SECRETO-ana"}, {"clasificacion": "spam"}, {"clasificacion": "error"}, {"tipo": "masivo"}, {"solo_ok": "true"}):
            ids_b = {i["id"] for i in beto.get("/historial", params={**filtro, "por_pagina": 100}).json()["items"]}
            comprobar(not ids_b & set(A["todos"]), f"el filtro {filtro} no deja pasar registros de ana a beto")
        comprobar(beto.get("/historial", params={"q": "SECRETO-ana"}).json()["total"] == 0, "buscar el texto de ana desde beto no devuelve nada")
        comprobar(beto.get("/historial", params={"lote_id": A["lote"], "por_pagina": 100}).json()["total"] == 0, "filtrar por el lote de ana desde beto -> vacío")
        ok("Historial privado: cada usuario lista solo lo suyo, con cualquier filtro (búsqueda, clasificación, tipo, lote)")

        # ---------- Detalle / IDOR por id ----------
        todas = sql("SELECT id, user_id FROM analisis")
        comprobar(len(todas) == len(A["todos"]) + len(B["todos"]), "la base contiene todos los análisis")
        dueno = {f["id"]: f["user_id"] for f in todas}
        comprobar(all(dueno[i] == ida for i in A["todos"]) and all(dueno[i] == idb for i in B["todos"]), "propietarios en la base de datos")
        inexistente = beto.get("/historial/99999999")
        for uid_c, cli, nombre in ((ida, ana, "ana"), (idb, beto, "beto"), (idc, carla, "carla")):
            for aid, prop in dueno.items():
                r = cli.get(f"/historial/{aid}")
                if prop == uid_c:
                    comprobar(r.status_code == 200 and r.json()["id"] == aid, f"{nombre} ve su análisis {aid}")
                else:
                    comprobar(r.status_code == 404, f"IDOR: {nombre} NO debe ver el análisis {aid} de otro (fue {r.status_code})")
                    comprobar(r.json() == inexistente.json(), "un id ajeno responde IGUAL que uno inexistente (no revela que existe)")
        for raro in ("0", "-1", "9223372036854775808", "abc", "1.5", "1;DROP TABLE analisis"):
            r = beto.get(f"/historial/{raro}")
            comprobar(r.status_code in (404, 422), f"id raro {raro!r} -> {r.status_code}")
        ok(f"IDOR en detalle: probados los {len(dueno)} ids reales con los 3 usuarios; los ajenos dan 404 idéntico a los inexistentes")

        # ---------- Eliminación ----------
        r = beto.delete(f"/historial/{A['individuales'][0]}")
        comprobar(r.status_code == 404, "beto no puede eliminar un análisis de ana")
        r = beto.post("/historial/eliminar", json={"ids": A["todos"] + [B["errores"][0]]})
        comprobar(r.status_code == 200 and r.json()["eliminados"] == 1, f"solo se elimina el suyo: {r.text}")
        comprobar(ana.get("/historial", params={"por_pagina": 100}).json()["total"] == len(A["todos"]), "ana conserva todos sus análisis")
        comprobar(beto.get(f"/historial/{B['errores'][0]}").status_code == 404, "el análisis propio sí se eliminó")
        B["todos"].remove(B["errores"][0]); B["errores"] = []
        comprobar(carla.post("/historial/eliminar", json={"ids": A["todos"] + B["todos"]}).json()["eliminados"] == 0, "carla no elimina nada ajeno")
        comprobar(sql("SELECT COUNT(*) AS n FROM analisis")[0]["n"] == len(A["todos"]) + len(B["todos"]), "ningún registro ajeno desapareció")
        ok("Eliminación individual y múltiple: solo afecta a registros del propio usuario; los ids ajenos se ignoran")

        # ---------- Retroalimentación ----------
        r = beto.post("/retroalimentacion", json={"analisis_id": A["individuales"][0], "de_acuerdo": False, "comentario": "intruso"})
        comprobar(r.status_code == 404, f"beto no puede opinar sobre el análisis de ana: {r.status_code}")
        comprobar(r.json() == beto.post("/retroalimentacion", json={"analisis_id": 99999999, "de_acuerdo": True}).json(), "mismo error que un análisis inexistente")
        comprobar(sql("SELECT COUNT(*) AS n FROM retroalimentacion WHERE comentario='intruso'")[0]["n"] == 0, "no se guardó nada")
        lr_b = beto.get("/retroalimentacion", params={"por_pagina": 100}).json()
        comprobar(all(i["comentario"].startswith("COMENTARIO-beto") for i in lr_b["items"]) and lr_b["total"] == 3, "beto solo ve sus opiniones")
        comprobar(beto.get("/retroalimentacion", params={"analisis_id": A["individuales"][0]}).json()["total"] == 0, "filtrar por un análisis de ana -> vacío")
        lr_a = ana.get("/retroalimentacion", params={"por_pagina": 100}).json()
        comprobar(lr_a["total"] == 3 and all("COMENTARIO-ana" in i["comentario"] for i in lr_a["items"]), "ana ve solo las suyas")
        comprobar(carla.get("/retroalimentacion").json()["total"] == 0, "carla ninguna")
        det_b = beto.get(f"/historial/{B['individuales'][0]}").json()
        comprobar(det_b["retro_total"] == 2 and all("beto" in x["comentario"] for x in det_b["retroalimentaciones"]), "el detalle solo trae sus opiniones")
        ok("Retroalimentación privada: no se puede opinar, listar ni ver opiniones sobre análisis ajenos")

        # ---------- Lotes y análisis masivos ----------
        rl = beto.get(f"/lotes/{A['lote']}")
        comprobar(rl.status_code == 404 and rl.json() == beto.get("/lotes/99999999").json(), "lote ajeno = lote inexistente")
        antes = ana.get(f"/lotes/{A['lote']}").json()
        r = beto.post("/analisis/archivo", content=corpus("easy_ham", 40, 1)[0].read_bytes(),
                      headers={"Content-Type": "message/rfc822", "X-Nombre-Archivo": "intruso.eml", "X-Lote-Id": str(A["lote"])})
        comprobar(r.status_code == 404, f"beto no puede añadir correos al lote de ana: {r.status_code} {r.text}")
        r = beto.post("/analisis/archivo", content=b"   ", headers={"Content-Type": "text/plain", "X-Nombre-Archivo": "intruso2.txt", "X-Lote-Id": str(A["lote"])})
        comprobar(r.status_code == 404, "ni siquiera un archivo con error")
        comprobar(ana.get(f"/lotes/{A['lote']}").json() == antes, "el resumen del lote de ana no cambió")
        comprobar(sql("SELECT COUNT(*) AS n FROM analisis WHERE nombre_archivo LIKE 'intruso%'")[0]["n"] == 0, "no se guardó nada")
        sa_lote = ana.get(f"/lotes/{A['lote']}").json()
        comprobar(sa_lote["total_procesados"] == 4 and sa_lote["errores"] == 1 and sa_lote["clasificados"] == 3, f"resumen de ana {sa_lote}")
        sb_lote = beto.get(f"/lotes/{B['lote']}").json()
        comprobar(sb_lote["total_procesados"] == 3 and sb_lote["errores"] == 0, f"resumen de beto {sb_lote}")
        comprobar(carla.get(f"/lotes/{A['lote']}").status_code == 404 and carla.get(f"/lotes/{B['lote']}").status_code == 404, "carla no ve ningún lote")
        # lote del usuario correcto pero lote_id enviado en una cabecera inválida
        comprobar(ana.post("/analisis/archivo", content=b"x", headers={"Content-Type": "text/plain", "X-Lote-Id": "abc"}).status_code == 422, "X-Lote-Id inválido")
        for lote_ajeno in range(1, 6):
            if lote_ajeno not in (B["lote"],):
                comprobar(beto.get(f"/lotes/{lote_ajeno}").status_code == 404 or lote_ajeno == B["lote"], "beto solo ve su lote")
        ok("Lotes y análisis masivos: un lote ajeno es indistinguible de uno inexistente; no se pueden añadir correos a lotes de otro")

        # ---------- Errores de archivos ----------
        er_b = beto.get("/historial", params={"clasificacion": "error", "por_pagina": 100}).json()
        comprobar(er_b["total"] == 0, "beto (que eliminó su error) no ve el error de ana")
        er_a = ana.get("/historial", params={"clasificacion": "error", "por_pagina": 100}).json()
        comprobar(er_a["total"] == 1 and er_a["items"][0]["nombre_archivo"].startswith("SECRETO-ana"), "ana ve su error de archivo")
        comprobar(beto.get(f"/historial/{A['errores'][0]}").status_code == 404, "el detalle del error de ana no es accesible")
        comprobar(carla.get("/historial", params={"clasificacion": "error"}).json()["total"] == 0, "carla no ve errores")
        ok("Errores de archivos: pertenecen al usuario que subió el archivo; nadie más los ve")

        # ---------- Estadísticas ----------
        ea, eb, ec = (cli.get("/estadisticas/uso").json() for cli in (ana, beto, carla))
        comprobar(ea["analizados"] == 5 and ea["errores"] == 1 and ea["lotes"] == 1 and ea["retroalimentaciones"] == 3, f"stats de ana {ea}")
        comprobar(eb["analizados"] == 5 and eb["errores"] == 0 and eb["lotes"] == 1 and eb["retroalimentaciones"] == 3, f"stats de beto {eb}")
        comprobar(ea["spam"] + ea["legitimos"] == 5 and ea["individuales"] == 2 and ea["masivos"] == 3, f"desglose de ana {ea}")
        comprobar(ec["analizados"] == 0 and ec["errores"] == 0 and ec["lotes"] == 0 and ec["retroalimentaciones"] == 0 and ec["porcentaje_spam"] is None
                  and all(x["total"] == 0 for x in ec["por_dia"]), f"carla debe ver todo en cero: {ec}")
        comprobar(sum(x["total"] for x in ea["por_dia"]) == 5 and sum(x["total"] for x in eb["por_dia"]) == 5, "series diarias separadas")
        ok("Estadísticas privadas: cada usuario ve únicamente sus conteos (y carla, ceros reales)")

        # ---------- CSV ----------
        ra, rb, rc = (cli.get("/historial/exportar.csv") for cli in (ana, beto, carla))
        fa, fb, fc = csv_filas(ra), csv_filas(rb), csv_filas(rc)
        comprobar(fa[0] == almacen.COLUMNAS_CSV and len(fa) - 1 == len(A["todos"]) and {int(f[0]) for f in fa[1:]} == set(A["todos"]), "CSV de ana")
        comprobar(len(fb) - 1 == len(B["todos"]) and {int(f[0]) for f in fb[1:]} == set(B["todos"]), "CSV de beto")
        comprobar(len(fc) == 1, "CSV de carla: solo la cabecera")
        texto_b = rb.content.decode("utf-8-sig")
        comprobar("SECRETO-ana" not in texto_b and "ana@privado" not in texto_b and "dominio-ana" not in texto_b, "el CSV de beto no contiene nada de ana")
        comprobar("SECRETO-beto" not in ra.content.decode("utf-8-sig"), "el CSV de ana no contiene nada de beto")
        comprobar(len(csv_filas(beto.get("/historial/exportar.csv", params={"lote_id": A["lote"]}))) == 1, "CSV de un lote ajeno: vacío")
        comprobar(len(csv_filas(beto.get("/historial/exportar.csv", params={"q": "SECRETO-ana"}))) == 1, "buscar a ana en el CSV de beto: vacío")
        comprobar(len(csv_filas(ana.get("/historial/exportar.csv", params={"lote_id": A["lote"]}))) - 1 == 4, "ana sí exporta su lote")
        comprobar(ra.headers["cache-control"] == "no-store" and "attachment" in ra.headers["content-disposition"], "el CSV no se guarda en caché")
        ok("CSV privado: cada usuario exporta solo lo suyo (también con filtros por lote o texto)")

        # ---------- El cliente no puede imponer un user_id ----------
        pred = beto.post("/predecir", json={"texto": TEXTO_SPAM, "user_id": ida}).json()
        r = beto.post("/historial", json={"resultado": pred, "asunto": "INYECCION-1", "user_id": ida, "usuario_id": ida, "owner": ida},
                      params={"user_id": ida}, headers={"X-User-Id": str(ida), "X-User": "ana"})
        comprobar(r.status_code == 201, r.text)
        nuevo = r.json()["id"]
        comprobar(sql("SELECT user_id FROM analisis WHERE id=?", (nuevo,))[0]["user_id"] == idb, "el registro es de beto, no de ana")
        comprobar(ana.get(f"/historial/{nuevo}").status_code == 404 and beto.get(f"/historial/{nuevo}").status_code == 200, "ana no lo ve")
        r = beto.post("/lotes", json={"total": 1, "user_id": ida}, params={"user_id": ida}, headers={"X-User-Id": str(ida)})
        comprobar(r.status_code == 201 and sql("SELECT user_id FROM lotes WHERE id=?", (r.json()["id"],))[0]["user_id"] == idb, "el lote nuevo es de beto")
        r = beto.get("/historial", params={"user_id": ida, "usuario_id": ida}, headers={"X-User-Id": str(ida)})
        comprobar(r.json()["total"] == len(B["todos"]) + 1 and not {i["id"] for i in r.json()["items"]} & set(A["todos"]), "parámetros user_id ignorados al listar")
        r = beto.get("/estadisticas/uso", params={"user_id": ida})
        comprobar(r.json()["analizados"] == eb["analizados"] + 1, "parámetros user_id ignorados en estadísticas")
        ok("El user_id sale solo de la sesión: user_id/usuario_id/owner en cuerpo, URL o cabeceras se ignoran")

        # ---------- Cierre de sesión de uno no afecta al otro ----------
        r = ana.post("/auth/logout", headers={"X-CSRF-Token": sa["csrf_token"]})
        comprobar(r.status_code == 200 and ana.get("/historial").status_code == 401, "ana cerró sesión")
        comprobar(beto.get("/historial").status_code == 200, "la sesión de beto sigue activa")
        # Tras volver a entrar, ana recupera sus datos intactos
        sa2 = auth_helper.iniciar_sesion(ana, "ana")
        comprobar(ana.get("/historial", params={"por_pagina": 100}).json()["total"] == len(A["todos"]), "ana recupera todo al volver a entrar")
        # Un cliente con la sesión de beto y el CSRF de ana no pasa
        r = beto.post("/predecir", json={"texto": TEXTO_HAM}, headers={"X-CSRF-Token": sa2["csrf_token"]})
        comprobar(r.status_code == 403, "CSRF de otro usuario rechazado")
        ok("Las sesiones son independientes entre usuarios; el token CSRF de un usuario no sirve para otro")

        # ---------- Estado final de la base ----------
        sin_dueno = sql("SELECT COUNT(*) AS n FROM analisis WHERE user_id IS NULL")[0]["n"]
        comprobar(sin_dueno == 0, "todo registro creado en la Fase 6 tiene propietario")
        comprobar(sql("PRAGMA foreign_key_check") == [], "integridad referencial")
    print(f"\n{GRUPOS} grupos de comprobaciones superados (API real y modelo real).")


if __name__ == "__main__":
    main()
