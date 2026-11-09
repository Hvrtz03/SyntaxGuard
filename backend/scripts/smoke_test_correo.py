"""Prueba del backend de la Fase 3: POST /correo/extraer.

Uso (desde la raíz del proyecto, con el entorno virtual activado):

    python backend\\scripts\\smoke_test_correo.py                  # pruebas + muestra de correos reales
    python backend\\scripts\\smoke_test_correo.py --muestra 40     # más correos reales por carpeta
    python backend\\scripts\\smoke_test_correo.py --completo       # extrae TODO el corpus (sin /predecir)
    python backend\\scripts\\smoke_test_correo.py --eml ruta\\a\\correo.eml   # un archivo concreto

No modifica ni sustituye a smoke_test.py ni a smoke_test_frontend.py. No escribe nada en disco.
"""
import argparse
import re
import sys
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent  # carpeta backend/
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

import auth_helper  # noqa: E402  (Fase 6A: base temporal y claves de prueba; las rutas privadas exigen sesión)
from app import correo as modulo_correo  # noqa: E402
from app.detector import MAX_CHARS, METRICS_PATH  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas import PrediccionRequest  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TEXTO = "WINNER!! Claim your FREE prize now: http://bit.ly/claim-now"
HTML = '<html><body><a href="http://paypa1.com/login">http://paypal.com</a></body></html>'
ORIGINALES = {("/salud", "GET"), ("/metricas", "GET"), ("/predecir", "POST")}
CABECERA_NOMBRE = "X-Nombre-Archivo"


def comprobar(condicion, mensaje):
    assert condicion, mensaje


def ok(texto):
    print(f"[OK] {texto}")


def verificar_formato_prediccion(r: dict):
    comprobar(set(r) == {"es_spam", "probabilidad", "rasgos_detectados"}, "/predecir cambió su formato")
    comprobar(isinstance(r["es_spam"], bool), "es_spam no es booleano")
    comprobar(0.0 <= r["probabilidad"] <= 1.0, "probabilidad fuera de rango")
    for item in r["rasgos_detectados"]:
        comprobar({"rasgo", "categoria", "valor", "activo", "descripcion"} <= set(item), "rasgo incompleto")


def enviar(c, datos, nombre=None, tipo="message/rfc822"):
    cab = {"Content-Type": tipo}
    if nombre is not None:
        cab[CABECERA_NOMBRE] = quote(nombre)
    return c.post("/correo/extraer", content=datos, headers=cab)


# ---------- Correos sintéticos ----------
def correo_multipart() -> bytes:
    m = EmailMessage()
    m["From"] = "Premios <promo@ofertas-ya.example>"
    m["To"] = "victima@correo.example"
    m["Subject"] = "¡Felicidades, ganaste! Reclama tu premio"
    m["Date"] = "Wed, 21 Aug 2002 10:54:46 -0500"
    m.set_content("WINNER!! Claim your FREE prize now: http://bit.ly/claim-now\nVisit www.premios-ya.example today!")
    m.add_alternative(
        '<html><body><b>WINNER</b> <a href="http://paypa1.com/login">http://paypal.com</a>'
        '<a href="mailto:a@b.example">correo</a></body></html>', subtype="html")
    m.add_attachment(b"%PDF-1.4 contenido-de-adjunto", maintype="application", subtype="pdf", filename="factura.pdf")
    return bytes(m)


def correo_crudo(cuerpo: bytes, charset: str, cte: str = "8bit") -> bytes:
    cab = (f"From: a@b.example\r\nTo: c@d.example\r\nSubject: prueba\r\n"
           f"Content-Type: text/plain; charset={charset}\r\nContent-Transfer-Encoding: {cte}\r\n\r\n")
    return cab.encode("ascii") + cuerpo


def pruebas_sinteticas(c):
    # 1. Multipart: texto + html + adjunto + enlaces + cabeceras decodificadas
    r = enviar(c, correo_multipart(), "premio.eml")
    comprobar(r.status_code == 200, r.text)
    d = r.json()
    comprobar(d["origen"] == "eml" and d["nombre_archivo"] == "premio.eml", "origen/nombre")
    comprobar(d["remitente"] == "Premios <promo@ofertas-ya.example>", f"remitente: {d['remitente']}")
    comprobar(d["destinatario"] == "victima@correo.example", "destinatario")
    comprobar(d["asunto"] == "¡Felicidades, ganaste! Reclama tu premio", f"asunto: {d['asunto']}")
    comprobar(d["fecha"] and d["fecha_iso"] and d["fecha_iso"].startswith("2002-08-21"), "fecha")
    comprobar("WINNER!! Claim your FREE prize" in d["texto"] and "\n" not in d["texto"], "texto normalizado")
    comprobar(d["html"] and "<html>" in d["html"], "html presente")
    comprobar(d["adjuntos_ignorados"] == 1 and "PDF" not in d["texto"], "el adjunto no se lee")
    urls = {e["url"]: e["origen"] for e in d["enlaces"]}
    comprobar("http://bit.ly/claim-now" in urls and urls["http://bit.ly/claim-now"] == "texto", f"enlaces: {urls}")
    comprobar("http://paypa1.com/login" in urls and urls["http://paypa1.com/login"] == "html", "href del html")
    comprobar(not any(u.startswith("mailto:") for u in urls), "mailto no es enlace web")
    comprobar("www.premios-ya.example" in urls, "enlace www")
    comprobar(set(d) >= {"texto", "html"} and "rasgos_detectados" not in d and "es_spam" not in d,
              "la extracción no debe incluir resultados del modelo")
    ok("Multipart: cabeceras, texto, html, enlaces y adjunto ignorado")
    guardado = d

    # 2. Solo HTML
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = "x@y.example", "z@w.example", "Solo html"
    m.set_content("<html><body><p>Hola <b>mundo</b> visita http://ejemplo.example/a</p></body></html>", subtype="html")
    d = enviar(c, bytes(m), "h.eml").json()
    comprobar(d["texto_desde_html"] is True and "Hola mundo" in d["texto"] and d["html"], "solo html")
    comprobar(any("advertencias" in d and "HTML" in a for a in d["advertencias"]), "aviso de texto desde HTML")
    ok("Correo solo HTML: el texto se obtiene del HTML y se avisa")

    # 3. Codificaciones
    d = enviar(c, correo_crudo("Corazón ñandú café".encode("iso-8859-1"), "iso-8859-1"), "a.eml").json()
    comprobar("Corazón ñandú café" in d["texto"], f"iso-8859-1: {d['texto']!r}")
    d = enviar(c, correo_crudo("Dijo “hola” por 5€".encode("windows-1252"), "windows-1252"), "a.eml").json()
    comprobar("“hola”" in d["texto"] and "€" in d["texto"], f"windows-1252: {d['texto']!r}")
    d = enviar(c, correo_crudo("Canción 日本".encode("utf-8"), "utf-8"), "a.eml").json()
    comprobar("Canción 日本" in d["texto"], f"utf-8: {d['texto']!r}")
    d = enviar(c, correo_crudo("Canción".encode("utf-8"), "utf-8", "base64").replace(b"Canci\xc3\xb3n", b"Q2FuY2nDs24="), "a.eml").json()
    comprobar("Canción" in d["texto"], f"base64: {d['texto']!r}")
    d = enviar(c, correo_crudo("Corazón".encode("iso-8859-1"), "x-charset-inventado"), "a.eml").json()
    comprobar(d["texto"].startswith("Coraz"), f"charset desconocido: {d['texto']!r}")
    ok("Codificaciones: UTF-8, ISO-8859-1, Windows-1252, base64 y charset desconocido")

    # 4. Texto pegado (sin cabeceras) y HTML pegado
    d = enviar(c, "Hola, gana dinero FREE ya: http://x.example/y".encode(), None, "text/plain").json()
    comprobar(d["origen"] == "texto" and d["remitente"] is None and d["enlaces"], "texto pegado")
    d = enviar(c, b"<html><body><a href='http://q.example'>click</a> ahora</body></html>", None, "text/plain").json()
    comprobar(d["origen"] == "texto" and d["html"] and "click ahora" in d["texto"], "html pegado")
    ok("Texto y HTML pegados sin cabeceras")

    # 5. HTML malicioso: se devuelve como DATO; no se ejecuta ni se convierte en enlace
    malo = (b"From: a@b.example\r\nTo: c@d.example\r\nSubject: x\r\nContent-Type: text/html\r\n\r\n"
            b"<script>alert(1)</script><img src=x onerror=alert(1)>"
            b"<a href=\"javascript:alert(1)\">a</a><a href=\"http://evil.example/x\">http://paypal.com</a>")
    r = enviar(c, malo, "m.eml")
    d = r.json()
    comprobar(r.headers["content-type"].startswith("application/json"), "la respuesta debe ser JSON, no HTML")
    comprobar(not any(e["url"].lower().startswith("javascript:") for e in d["enlaces"]), "javascript: no es enlace")
    comprobar(any(e["url"] == "http://evil.example/x" for e in d["enlaces"]), "href http conservado como texto")
    comprobar("<script>" in d["html"], "el html se conserva como cadena de texto")
    ok("HTML malicioso: solo texto, sin javascript: y sin ejecutar nada")

    # 6. Validaciones
    casos = [
        ("vacío", enviar(c, b"", "a.eml"), 400),
        ("solo espacios", enviar(c, b"  \r\n \n", "a.eml"), 400),
        ("binario (.eml falso)", enviar(c, b"\xd0\xcf\x11\xe0\x00\x00\x00\x00" + b"\x00" * 200, "a.eml"), 415),
        ("extensión .pdf", enviar(c, b"From: a@b.example\r\n\r\nhola", "doc.pdf"), 415),
        ("extensión .msg", enviar(c, b"From: a@b.example\r\n\r\nhola", "doc.msg"), 415),
        ("multipart/form-data", enviar(c, b"hola", "a.eml", "multipart/form-data; boundary=x"), 415),
        ("JSON", enviar(c, b'{"texto":"hola"}', None, "application/json"), 415),
        ("sin cuerpo de texto", enviar(c, b"From: a@b.example\r\nTo: c@d.example\r\nSubject: vacio\r\n\r\n", "a.eml"), 422),
        ("más de 5 MB", enviar(c, b"A" * (modulo_correo.MAX_BYTES + 1), "a.eml"), 413),
    ]
    for nombre, resp, esperado in casos:
        comprobar(resp.status_code == esperado, f"{nombre}: esperaba {esperado} y llegó {resp.status_code} {resp.text[:120]}")
        comprobar(isinstance(resp.json().get("detail"), str) and resp.json()["detail"], f"{nombre}: falta mensaje claro")

    def trozos():  # sin Content-Length: ejercita la lectura por partes
        for _ in range(6):
            yield b"A" * (1024 * 1024)
    r = c.post("/correo/extraer", content=trozos(), headers={"Content-Type": "message/rfc822"})
    comprobar(r.status_code == 413, f"cuerpo por partes >5 MB: {r.status_code}")
    justo = b"From: a@b.example\r\n\r\n" + b"hola " * 1000
    comprobar(enviar(c, justo, "a.eml").status_code == 200, "un correo pequeño debe pasar")
    ok("Validaciones: vacío, binario, extensión, tipo de contenido, sin texto y >5 MB (con y sin Content-Length)")

    # 7. Nombre de archivo: solo etiqueta, nunca ruta
    d = enviar(c, justo, "../../etc/passwd.eml").json()
    comprobar(d["nombre_archivo"] == "passwd.eml", f"nombre: {d['nombre_archivo']}")
    d = enviar(c, justo, "reseña de correo.eml").json()
    comprobar(d["nombre_archivo"] == "reseña de correo.eml", f"nombre con acentos: {d['nombre_archivo']}")
    ok("Nombre de archivo saneado (sin rutas) y con acentos")

    # 8. Límites de campos
    largo = b"From: a@b.example\r\n\r\n" + (b"palabra " * 4000)  # 32 000 caracteres
    d = enviar(c, largo, "a.eml").json()
    comprobar(len(d["texto"]) <= modulo_correo.MAX_TEXTO and d["texto_truncado"], "texto recortado")
    comprobar(any(str(MAX_CHARS).replace(",", "") in a.replace(" ", "") for a in d["advertencias"]), "aviso de límite de análisis")
    ok("Texto largo: se recorta al límite del esquema y se avisa del límite del detector")
    return guardado


def pruebas_de_coherencia():
    comprobar(modulo_correo.LIMITE_ANALISIS == MAX_CHARS, "LIMITE_ANALISIS debe coincidir con detector.MAX_CHARS")
    esquema = PrediccionRequest.model_json_schema()["properties"]
    comprobar(esquema["texto"]["maxLength"] == modulo_correo.MAX_TEXTO, "MAX_TEXTO distinto al de schemas.py")
    h = esquema["html"]
    max_html = h.get("maxLength") or next(x["maxLength"] for x in h["anyOf"] if "maxLength" in x)
    comprobar(max_html == modulo_correo.MAX_HTML, "MAX_HTML distinto al de schemas.py")
    ok("Constantes coherentes con detector.py y schemas.py")


def regresion_originales(c):
    rutas = {(r.path, m) for r in app.routes for m in (getattr(r, "methods", None) or ())}
    comprobar(ORIGINALES <= rutas, f"Faltan endpoints originales: {ORIGINALES - rutas}")
    comprobar(("/correo/extraer", "POST") in rutas, "No está registrado /correo/extraer")
    r = c.get("/salud")
    comprobar(r.status_code == 200 and r.json() == {"estado": "ok", "modelo_cargado": True}, "/salud cambió")
    import json
    r = c.get("/metricas")
    comprobar(r.status_code == 200 and r.json() == json.loads(METRICS_PATH.read_text(encoding="utf-8")),
              "/metricas ya no devuelve metricas.json tal cual")
    comprobar(r.json()["test"]["accuracy"] == 0.9533 and r.json()["test"]["matriz_confusion_lista"] == [[175, 4], [10, 111]],
              "las métricas de prueba no coinciden con las originales")
    r = c.post("/predecir", json={"texto": TEXTO, "html": HTML})
    comprobar(r.status_code == 200, r.text)
    verificar_formato_prediccion(r.json())
    comprobar(c.post("/predecir", json={"texto": "   "}).status_code == 422, "/predecir ya no valida texto vacío")
    comprobar(c.get("/").status_code == 200, "GET / (interfaz) dejó de funcionar")
    ok("Endpoints originales intactos: /salud, /metricas (0,9533 · 175/4/10/111), /predecir, y la interfaz en /")


def ida_y_vuelta(c, extraido):
    """El resultado de /correo/extraer sirve tal cual como entrada de /predecir."""
    r = c.post("/predecir", json={"texto": extraido["texto"], "html": extraido["html"]})
    comprobar(r.status_code == 200, r.text)
    verificar_formato_prediccion(r.json())
    ok(f"Extraer -> /predecir con el modelo real: es_spam={r.json()['es_spam']} · probabilidad={r.json()['probabilidad']}")


# ---------- Correos reales ----------
def paridad_con_entrenamiento(ruta: Path, d: dict, leer_correo):
    """Compara con scripts/build_dataset.py (formato de entrenamiento). Devuelve None si no aplica."""
    try:
        t0, h0 = leer_correo(ruta)
    except Exception:
        return None
    if not t0 or len(t0) >= modulo_correo.MAX_TEXTO:
        return None  # build_dataset no pudo leerlo (este procesador sí) o fue recortado
    ctrl = modulo_correo.CONTROL_RE
    return d["texto"] == ctrl.sub("", t0) and (d["html"] or "") == ctrl.sub("", h0).strip()


def correos_reales(c, carpetas, muestra, completo, predecir_n):
    try:
        from build_dataset import leer_correo
    except Exception:
        leer_correo = None
    resumen = {"ok": 0, "sin_texto(422)": 0, "paridad_ok": 0, "paridad_distinta": 0, "predicciones": 0}
    distintos = []
    for carpeta in carpetas:
        if not carpeta.is_dir():
            print(f"[--] No existe {carpeta}; se omite.")
            continue
        archivos = sorted(f for f in carpeta.iterdir() if f.is_file() and f.name != "cmds")
        if not completo and muestra and len(archivos) > muestra:
            paso = len(archivos) // muestra
            archivos = archivos[::paso][:muestra]
        etiqueta = "ham" if "ham" in carpeta.name.lower() else "spam"
        for i, f in enumerate(archivos):
            r = enviar(c, f.read_bytes(), f.name + ".eml")  # el corpus no trae extensión: se añade .eml
            comprobar(r.status_code in (200, 422), f"{f.name}: estado inesperado {r.status_code} {r.text[:150]}")
            if r.status_code == 422:
                resumen["sin_texto(422)"] += 1
                continue
            d = r.json()
            resumen["ok"] += 1
            comprobar(d["texto"].strip() and len(d["texto"]) <= modulo_correo.MAX_TEXTO, f"{f.name}: texto inválido")
            if leer_correo:
                p = paridad_con_entrenamiento(f, d, leer_correo)
                if p is True:
                    resumen["paridad_ok"] += 1
                elif p is False:
                    resumen["paridad_distinta"] += 1
                    distintos.append(f.name)
            if not completo and i < predecir_n:
                rp = c.post("/predecir", json={"texto": d["texto"], "html": d["html"]})
                comprobar(rp.status_code == 200, f"{f.name}: /predecir {rp.status_code} {rp.text[:150]}")
                verificar_formato_prediccion(rp.json())
                resumen["predicciones"] += 1
                veredicto = "SPAM" if rp.json()["es_spam"] else "LEGÍTIMO"
                print(f"     {carpeta.name}/{f.name[:12]}…  carpeta={etiqueta:<4}  modelo={veredicto:<8}  P(spam)={rp.json()['probabilidad']}")
    return resumen, distintos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestra", type=int, default=12, help="correos reales por carpeta (por defecto 12)")
    ap.add_argument("--completo", action="store_true", help="extraer todo el corpus (no llama a /predecir)")
    ap.add_argument("--predecir", type=int, default=3, help="cuántos correos reales por carpeta pasan por /predecir")
    ap.add_argument("--eml", help="probar un archivo .eml concreto y mostrar lo extraído")
    args = ap.parse_args()

    pruebas_de_coherencia()
    with TestClient(app) as c:
        auth_helper.iniciar_sesion(c)  # Fase 6A: /correo/extraer y /predecir exigen sesión
        regresion_originales(c)
        extraido = pruebas_sinteticas(c)
        ida_y_vuelta(c, extraido)

        if args.eml:
            ruta = Path(args.eml)
            r = enviar(c, ruta.read_bytes(), ruta.name)
            print(f"\n{args.eml} -> HTTP {r.status_code}")
            if r.status_code == 200:
                d = r.json()
                for campo in ("origen", "remitente", "destinatario", "asunto", "fecha", "adjuntos_ignorados", "enlaces_total"):
                    print(f"  {campo}: {d[campo]}")
                print(f"  texto ({len(d['texto'])} caracteres): {d['texto'][:200]!r}")
                print(f"  html: {'sí (%d caracteres)' % len(d['html']) if d['html'] else 'no'}")
                print(f"  advertencias: {d['advertencias']}")
                for e in d["enlaces"][:5]:
                    print(f"  enlace ({e['origen']}): {e['url']}")
            else:
                print("  ", r.json())
            return 0 if r.status_code == 200 else 1

        base = ROOT / "data"
        print("\nCorreos reales del corpus:")
        resumen, distintos = correos_reales(
            c, [base / "easy_ham", base / "spam", base / "spam_2"], args.muestra, args.completo, args.predecir)
        print(f"\n     Resumen: {resumen}")
        if distintos:
            print(f"     Distintos al formato de entrenamiento (solo se espera por caracteres de control): {distintos[:5]}")
        comprobar(resumen["ok"] > 0 or not (base / "easy_ham").is_dir(), "no se pudo extraer ningún correo real")
        if resumen["paridad_ok"] + resumen["paridad_distinta"]:
            tasa = resumen["paridad_ok"] / (resumen["paridad_ok"] + resumen["paridad_distinta"])
            comprobar(tasa >= 0.99, f"solo {tasa:.1%} de los correos coincide con el formato de entrenamiento")
            ok(f"Correos reales: {resumen['ok']} extraídos; {tasa:.1%} idénticos al formato de entrenamiento")
        else:
            ok(f"Correos reales: {resumen['ok']} extraídos")
    print("\nPrueba del backend de la Fase 3 superada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
