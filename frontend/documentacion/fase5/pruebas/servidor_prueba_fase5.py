"""SERVIDOR DE PRUEBA para probar la INTERFAZ de la Fase 5 donde no se puede ejecutar FastAPI ni el modelo.

NO es SyntaxGuard y NO sustituye al backend real ni al modelo:
  * Usa un DETECTOR SIMULADO (palabras clave) con el mismo formato que SpamDetector.predecir.
  * Está escrito con la biblioteca estándar (http.server) porque FastAPI no está instalado en este entorno.
  * SÍ reutiliza el código real de la aplicación: app.almacen (SQLite), app.servicio y app.correo (extracción).
    Solo el "enrutador HTTP" y el detector son de prueba; los routers reales (rutas_*.py) NO se ejercitan aquí.
Si tienes el modelo real (tu caso en Windows), no uses este script: usa  python ejecutable\\run.py.

Uso:  python servidor_prueba_fase5.py [puerto] [ruta_bd]
"""
import json
import mimetypes
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

RAIZ = Path(__file__).resolve().parents[4]
PUERTO = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
if len(sys.argv) > 2:
    os.environ["SG_DB"] = sys.argv[2]
sys.path.insert(0, str(RAIZ / "backend"))

from app import almacen, correo, servicio  # noqa: E402
from app.almacen import ErrorAlmacen  # noqa: E402

FRONTEND = RAIZ / "frontend"
METRICAS = RAIZ / "backend" / "models" / "metricas.json"
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
PALABRAS = {"free", "win", "winner", "prize", "claim", "cash", "urgent", "click", "offer", "money", "bonus", "viagra"}


class DetectorSimulado:
    def predecir(self, texto, html=None):
        golpes = sum(1 for w in re.findall(r"[a-z]+", texto.lower()) if w in PALABRAS)
        p = round(min(0.99, 0.05 + 0.2 * golpes), 4)
        return {"es_spam": p >= 0.5, "probabilidad": p, "rasgos_detectados": [
            {"rasgo": "txt_n_spam", "categoria": "texto", "valor": float(golpes), "activo": golpes >= 2, "descripcion": "Palabras típicas de spam (simulado)"},
            {"rasgo": "url_n", "categoria": "url", "valor": 0.0, "activo": False, "descripcion": "Cantidad de enlaces (simulado)"}]}


DETECTOR = DetectorSimulado()


def _entero(q, nombre, defecto):
    v = q.get(nombre, [None])[0]
    if v in (None, ""):
        return defecto
    try:
        return int(v)
    except ValueError:
        raise ErrorAlmacen(422, f"{nombre} debe ser un entero.")


class Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # silencio
        pass

    # ---- utilidades ----
    def _json(self, estado, obj):
        cuerpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _bytes(self, estado, datos, tipo, extra=None):
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(datos)

    def _cuerpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _despachar(self, fn):
        try:
            fn()
        except ErrorAlmacen as e:
            self._json(e.estado, {"detail": e.mensaje})
        except correo.ErrorCorreo as e:
            self._json(e.estado, {"detail": e.mensaje})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"detail": f"Error de prueba: {type(e).__name__}: {e}"})

    # ---- verbos ----
    def do_GET(self):
        self._despachar(self._get)

    def do_POST(self):
        self._despachar(self._post)

    def do_DELETE(self):
        self._despachar(self._delete)

    def _get(self):
        u = urlparse(self.path)
        ruta, q = u.path, parse_qs(u.query)
        if ruta == "/":
            return self._bytes(200, (FRONTEND / "index.html").read_bytes(), "text/html; charset=utf-8")
        if ruta.startswith("/static/"):
            p = (FRONTEND / unquote(ruta[len("/static/"):])).resolve()
            if FRONTEND.resolve() not in p.parents or not p.is_file():
                return self._json(404, {"detail": "Not Found"})
            return self._bytes(200, p.read_bytes(), mimetypes.guess_type(str(p))[0] or "application/octet-stream")
        if ruta == "/salud":
            return self._json(200, {"estado": "ok", "modelo_cargado": True})
        if ruta == "/metricas":
            return self._json(200, json.loads(METRICAS.read_text(encoding="utf-8")))
        if ruta == "/openapi.json":
            return self._json(200, {"info": {"title": "SyntaxGuard (servidor de prueba)", "version": "1.0.0"}})
        if ruta == "/estadisticas/uso":
            return self._json(200, almacen.estadisticas_uso())
        if ruta == "/historial/exportar.csv":
            datos = almacen.exportar_csv(q=q.get("q", [None])[0], clasificacion=q.get("clasificacion", [None])[0],
                                         desde=q.get("desde", [None])[0], hasta=q.get("hasta", [None])[0],
                                         tipo=q.get("tipo", [None])[0], lote_id=_entero(q, "lote_id", None))
            return self._bytes(200, datos, "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="syntaxguard_historial.csv"'})
        if ruta == "/historial":
            return self._json(200, almacen.listar_analisis(
                q=q.get("q", [None])[0], clasificacion=q.get("clasificacion", [None])[0], desde=q.get("desde", [None])[0],
                hasta=q.get("hasta", [None])[0], tipo=q.get("tipo", [None])[0], lote_id=_entero(q, "lote_id", None),
                solo_ok=q.get("solo_ok", [""])[0].lower() == "true", pagina=_entero(q, "pagina", 1), por_pagina=_entero(q, "por_pagina", 25)))
        m = re.fullmatch(r"/historial/(\d+)", ruta)
        if m:
            return self._json(200, almacen.obtener_analisis(int(m.group(1))))
        if ruta == "/retroalimentacion":
            return self._json(200, almacen.listar_retro(analisis_id=_entero(q, "analisis_id", None), pagina=_entero(q, "pagina", 1), por_pagina=_entero(q, "por_pagina", 25)))
        m = re.fullmatch(r"/lotes/(\d+)", ruta)
        if m:
            return self._json(200, almacen.resumen_lote(int(m.group(1))))
        self._json(404, {"detail": "Not Found"})

    def _post(self):
        ruta = urlparse(self.path).path
        cuerpo = self._cuerpo()
        if ruta == "/predecir":
            d = json.loads(cuerpo or b"{}")
            return self._json(200, DETECTOR.predecir(d.get("texto", ""), d.get("html")))
        if ruta == "/correo/extraer":
            nombre = unquote(self.headers.get("X-Nombre-Archivo") or "") or None
            return self._json(200, correo.procesar(cuerpo, nombre))
        if ruta == "/analisis/archivo":
            nombre = unquote(self.headers.get("X-Nombre-Archivo") or "") or None
            lote = self.headers.get("X-Lote-Id")
            return self._json(200, servicio.analizar_archivo(DETECTOR, cuerpo, nombre, int(lote) if lote else None))
        if ruta == "/lotes":
            return self._json(201, almacen.crear_lote(json.loads(cuerpo or b"{}").get("total")))
        if ruta == "/historial":
            return self._json(201, servicio.registrar_individual(json.loads(cuerpo)))
        if ruta == "/historial/eliminar":
            return self._json(200, {"eliminados": almacen.eliminar_analisis(json.loads(cuerpo).get("ids"))})
        if ruta == "/retroalimentacion":
            d = json.loads(cuerpo)
            return self._json(201, almacen.guardar_retro(d.get("analisis_id"), d.get("de_acuerdo"), d.get("comentario")))
        self._json(404, {"detail": "Not Found"})

    def _delete(self):
        m = re.fullmatch(r"/historial/(\d+)", urlparse(self.path).path)
        if not m:
            return self._json(404, {"detail": "Not Found"})
        n = almacen.eliminar_analisis([int(m.group(1))])
        return self._json(200, {"eliminados": n}) if n else self._json(404, {"detail": "El análisis no existe."})


if __name__ == "__main__":
    almacen.iniciar()
    print(f"[servidor de PRUEBA con detector SIMULADO] http://127.0.0.1:{PUERTO}  ·  BD: {almacen.ruta_bd()}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PUERTO), Manejador).serve_forever()
