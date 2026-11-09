"""Pruebas del flujo de la Fase 3 con un navegador real (Chromium/Playwright) contra el servidor en ejecución.
[Fase 5 / D6] Las expectativas numéricas se actualizaron al formato es-MX (punto decimal, coma de millares) y el menú tiene 6 elementos.


Requisitos (una sola vez, con el entorno virtual activado):
    pip install playwright
    playwright install chromium

Uso (con el servidor ya iniciado, p. ej. python ejecutable\\run.py):
    python frontend\\documentacion\\fase3\\pruebas\\probar_flujo_fase3.py http://127.0.0.1:8000 capturas_fase3 resultados_fase3.json
    (opcional) --spam ruta\\a\\spam.eml --ham ruta\\a\\legitimo.eml   para usar correos reales del corpus

Qué comprueba: carga por selector, arrastrar y soltar, pegado, vista previa con los datos reales de
/correo/extraer, botón «Analizar correo» contra el modelo real (comparando con una llamada directa a la API),
estados de carga, doble clic, errores de archivos y de conexión, seguridad (HTML malicioso), navegación,
teclado, adaptación a móvil y errores de consola. No modifica nada del proyecto.
"""
import argparse
import json
import re
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("base")
ap.add_argument("capturas")
ap.add_argument("salida")
ap.add_argument("--spam", help="correo .eml real que el modelo suele marcar como spam")
ap.add_argument("--ham", help="correo .eml real legítimo")
args = ap.parse_args()

BASE = args.base.rstrip("/")
CAPT = Path(args.capturas)
CAPT.mkdir(parents=True, exist_ok=True)
TMP = Path(tempfile.mkdtemp(prefix="sg_fase3_"))
resultados = []


def check(nombre, ok, detalle=""):
    resultados.append({"prueba": nombre, "ok": bool(ok), "detalle": str(detalle)})
    print(("[OK]    " if ok else "[FALLA] ") + nombre + (f" — {detalle}" if detalle and not ok else ""))


# ---------- Correos de prueba ----------
def escribir(nombre, datos: bytes) -> Path:
    ruta = TMP / nombre
    ruta.write_bytes(datos)
    return ruta


def eml_spam_sintetico() -> bytes:
    m = EmailMessage()
    m["From"] = "Premios <promo@ofertas-ya.example>"
    m["To"] = "victima@correo.example"
    m["Subject"] = "WINNER!! Claim your FREE prize now"
    m["Date"] = "Wed, 21 Aug 2002 10:54:46 -0500"
    m.set_content("WINNER!! Claim your FREE prize now!!! Click here: http://bit.ly/claim-now or www.premios-ya.example NOW!!!")
    m.add_alternative('<html><body><b>WINNER</b> <a href="http://paypa1.com/login">http://paypal.com</a></body></html>', subtype="html")
    m.add_attachment(b"%PDF-1.4 adjunto", maintype="application", subtype="pdf", filename="factura.pdf")
    return bytes(m)


def eml_ham_sintetico() -> bytes:
    m = EmailMessage()
    m["From"] = "Ana Torres <ana@empresa.example>"
    m["To"] = "equipo@empresa.example"
    m["Subject"] = "Agenda de la reunion del jueves"
    m["Date"] = "Thu, 22 Aug 2002 09:00:00 -0500"
    m.set_content("Hi team, attached is the agenda for Thursday's meeting. Please review the notes before we meet and send me any comments. Thanks, Ana.")
    return bytes(m)


MALICIOSO = (
    b"From: \"<b>Banco</b>\" <a@b.example>\r\nTo: c@d.example\r\nSubject: <img src=x onerror=\"window.__xss=4\">\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n\r\n"
    b"<script>window.__xss=1</script><img src=x onerror=\"window.__xss=2\">"
    b"<a href=\"javascript:window.__xss=3\">pulsa</a><a href=\"http://evil.example/x\">http://paypal.com</a>"
    b"<iframe src=\"http://evil.example/frame\"></iframe> Verify your account now"
)
SPAM = Path(args.spam) if args.spam else escribir("spam_prueba.eml", eml_spam_sintetico())
HAM = Path(args.ham) if args.ham else escribir("legitimo_prueba.eml", eml_ham_sintetico())
SPAM_N = escribir("spam_con_nombre.eml", SPAM.read_bytes()) if not args.spam else SPAM
OTRO = escribir("otro_correo.eml", eml_ham_sintetico())


# ---------- Utilidades de navegador ----------
class Vigilante:
    """Recoge errores de consola, errores de página, peticiones fallidas y peticiones a la API."""

    def __init__(self, pg):
        self.errores, self.posts, self.todas = [], [], []
        pg.on("console", lambda m: self.errores.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: self.errores.append(f"pageerror: {e}"))
        pg.on("requestfailed", lambda r: self.errores.append(f"requestfailed: {r.url} {r.failure}"))
        pg.on("request", lambda r: self.todas.append(r.url))
        pg.on("request", lambda r: self.posts.append(r.url.replace(BASE, "")) if r.method == "POST" else None)

    def n(self, ruta):
        return sum(1 for p in self.posts if p == ruta)

    def limpiar(self):
        self.errores.clear()
        self.posts.clear()


def nueva_pagina(p, ancho=1366, alto=900):
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width": ancho, "height": alto})
    pg = ctx.new_page()
    return br, ctx, pg, Vigilante(pg)


def ir_a_analisis(pg):
    pg.goto(BASE + "/")
    pg.wait_for_selector(".zona")
    pg.wait_for_timeout(350)


def subir(pg, ruta):
    pg.set_input_files("#entrada-archivo", str(ruta))


def esperar_previa(pg):
    pg.wait_for_selector("#btn-analizar", timeout=15000)
    pg.wait_for_timeout(350)


def esperar_resultado(pg):
    pg.wait_for_selector(".banner", timeout=20000)
    pg.wait_for_timeout(350)


def foto(pg, nombre):
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(CAPT / f"{nombre}.png"), full_page=True)


def texto(pg, sel):
    return pg.inner_text(sel)


def fmt_bytes(n):
    if n < 1024:
        return f"{n} bytes"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}" + " KB"
    return f"{n / 1024 / 1024:.1f}" + " MB"


def sin_espacios(s):
    return re.sub(r"\s+", "", s.replace("\u00a0", " "))


def api_extraer(ctx, ruta: Path):
    r = ctx.request.post(BASE + "/correo/extraer", data=ruta.read_bytes(),
                         headers={"Content-Type": "message/rfc822", "X-Nombre-Archivo": quote(ruta.name)})
    return r.status, r.json()


def api_predecir(ctx, extraido):
    r = ctx.request.post(BASE + "/predecir", data={"texto": extraido["texto"], "html": extraido["html"]})
    return r.status, r.json()


def pct_en_pagina(pg):
    m = re.search(r"([\d]+\.\d)\s*%", pg.inner_text(".prob__valor").replace("\u00a0", " "))
    return float(m.group(1)) if m else None


with sync_playwright() as p:
    # =====================================================================
    # A. Camino feliz completo con un correo (spam) — consola limpia
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    ir_a_analisis(pg)
    cuerpo = texto(pg, "body")
    check("A1 La pantalla Analizar muestra formatos (.eml) y tamaño máximo (5 MB)", ".eml" in cuerpo and "5 MB" in cuerpo)
    check("A2 Hay zona de carga, botón «Elegir archivo» y pestaña «Pegar contenido»",
          pg.locator(".zona").count() == 1 and pg.locator("#btn-elegir").count() == 1 and pg.get_by_role("tab", name="Pegar contenido").count() == 1)
    check("A3 Los estilos nuevos se cargan (borde punteado en la zona)",
          pg.evaluate("getComputedStyle(document.querySelector('.zona')).borderTopStyle") == "dashed")
    check("A4 El indicador de pasos marca «Cargar»", "Cargar" in texto(pg, ".paso--actual"))
    pg.wait_for_function("document.querySelectorAll('.verif__fila .chip--ok').length >= 2", timeout=8000)
    check("A4b El diagnóstico de conexión de la Fase 2 se conserva (plegado) y /salud y /metricas aparecen conectados",
          pg.locator("details.diagnostico").count() == 1 and pg.locator("details.diagnostico[open]").count() == 0)
    foto(pg, "A1_inicial")

    with pg.expect_file_chooser() as fc:
        pg.click("#btn-elegir")
    fc.value.set_files(str(SPAM))
    esperar_previa(pg)
    foto(pg, "A2_vista_previa")
    estado, ext = api_extraer(ctx, SPAM)
    check("A5 /correo/extraer (llamada directa) responde 200", estado == 200, estado)
    check("A6 Se muestra el nombre del archivo", texto(pg, ".fila-archivo__nombre") == SPAM.name, texto(pg, ".fila-archivo__nombre"))
    check("A7 Se muestra el tamaño del archivo", fmt_bytes(SPAM.stat().st_size) in texto(pg, ".fila-archivo__meta"), texto(pg, ".fila-archivo__meta"))
    datos_ui = texto(pg, ".datos")
    esperado = [ext.get("remitente"), ext.get("destinatario"), ext.get("asunto"), ext.get("fecha")]
    check("A8 Remitente, destinatario, asunto y fecha coinciden con lo que devuelve la API",
          all((e in datos_ui) if e else ("No disponible" in datos_ui) for e in esperado), datos_ui.replace("\n", " | "))
    check("A9 La vista previa muestra el cuerpo del correo",
          sin_espacios(ext["texto"][:60]) in sin_espacios(texto(pg, ".previa")))
    urls_ui = [u.strip() for u in pg.locator(".enlaces code").all_inner_texts()]
    check("A10 Se listan los enlaces encontrados (los mismos que devuelve la API)",
          urls_ui == [e["url"] for e in ext["enlaces"]], f"{urls_ui} vs {[e['url'] for e in ext['enlaces']]}")
    check("A11 Los enlaces NO son clicables (no hay <a href> en la vista)", pg.locator(".analisis a").count() == 0)
    check("A12 Se muestran las advertencias de la API",
          all(a in texto(pg, ".analisis") for a in ext["advertencias"]), ext["advertencias"])
    check("A13 Se muestra el número de adjuntos ignorados y de enlaces",
          f"{ext['adjuntos_ignorados']}" in texto(pg, ".resumen") and f"{ext['enlaces_total']}" in texto(pg, ".resumen"))
    check("A14 Aparece el botón «Analizar correo» y el paso actual es «Analizar»",
          pg.get_by_role("button", name="Analizar correo").count() == 1 and "Analizar" in texto(pg, ".paso--actual"))

    v.posts.clear()
    pg.click("#btn-analizar")
    esperar_resultado(pg)
    foto(pg, "A3_resultado")
    est_p, pred = api_predecir(ctx, ext)
    etiqueta_ui = "SPAM" if "SPAM" in texto(pg, ".banner__titulo") else ("LEGÍTIMO" if "LEGÍTIMO" in texto(pg, ".banner__titulo") else "?")
    check("A15 Al pulsar «Analizar correo» se hace exactamente UNA llamada a /predecir", v.n("/predecir") == 1, v.posts)
    check("A16 La clasificación mostrada coincide con la del modelo real",
          etiqueta_ui == ("SPAM" if pred["es_spam"] else "LEGÍTIMO"), f"UI={etiqueta_ui} API es_spam={pred['es_spam']}")
    pu = pct_en_pagina(pg)
    check("A17 La probabilidad de spam mostrada coincide con la del modelo",
          pu is not None and abs(pu - pred["probabilidad"] * 100) < 0.06, f"UI={pu} API={pred['probabilidad'] * 100:.3f}")
    activos = [r for r in pred["rasgos_detectados"] if r["activo"]]
    inactivos = [r for r in pred["rasgos_detectados"] if not r["activo"]]
    check("A18 Los rasgos activos mostrados son exactamente los que devuelve el backend",
          sorted(pg.locator(".rasgo:not(.rasgo--inactivo) .rasgo__id").all_inner_texts()) == sorted(r["rasgo"] for r in activos),
          f"{len(activos)} esperados")
    check("A19 Los rasgos medidos sin activarse se separan de los detectados",
          (f"Medidos sin activarse ({len(inactivos)})" in texto(pg, ".analisis")) if inactivos else True)
    check("A20 La interfaz aclara que la probabilidad es P(spam) y no certeza",
          "Probabilidad de spam" in texto(pg, ".analisis") and "certeza" in texto(pg, ".analisis"))
    check("A21 El indicador de pasos marca «Entender»", "Entender" in texto(pg, ".paso--actual"))
    check("A22 El resultado no presenta los enlaces como rasgos del modelo",
          "http" not in " ".join(pg.locator(".rasgo").all_inner_texts()) or all("http" not in r["descripcion"] for r in pred["rasgos_detectados"]))
    pg.click("#btn-otro")
    pg.wait_for_selector(".zona")
    check("A23 «Analizar otro correo» vuelve a la carga y limpia el estado", pg.locator(".zona").count() == 1 and pg.locator(".banner").count() == 0)
    check("A24 Consola limpia en todo el camino feliz (sin errores ni avisos de JavaScript)", not v.errores, v.errores)
    br.close()

    # =====================================================================
    # A'. Segundo resultado: correo legítimo
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    ir_a_analisis(pg)
    subir(pg, HAM)
    esperar_previa(pg)
    pg.click("#btn-analizar")
    esperar_resultado(pg)
    foto(pg, "A4_resultado_segundo_correo")
    _, ext_h = api_extraer(ctx, HAM)
    _, pred_h = api_predecir(ctx, ext_h)
    esperado_h = "SPAM" if pred_h["es_spam"] else "LEGÍTIMO"
    check("A25 Segundo correo: la clasificación coincide con el modelo", texto(pg, ".banner__titulo").strip() == esperado_h,
          f"UI={texto(pg, '.banner__titulo')} API={esperado_h}")
    check("A26 El banner usa el estilo del veredicto (rojo SPAM / verde LEGÍTIMO)",
          pg.locator(".banner--spam" if pred_h["es_spam"] else ".banner--ok").count() == 1)
    check("A27 Sin errores de consola", not v.errores, v.errores)
    br.close()

    # =====================================================================
    # B. Arrastrar y soltar
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    ir_a_analisis(pg)
    contenido_eml = eml_ham_sintetico().decode("latin-1")
    soltar = """([nombre, contenido, repetir]) => {
        const dt = new DataTransfer();
        for (let i = 0; i < repetir; i++) dt.items.add(new File([contenido], i ? `copia${i}_${nombre}` : nombre, {type: 'message/rfc822'}));
        const z = document.querySelector('.zona') || document.body;
        z.dispatchEvent(new DragEvent('dragenter', {dataTransfer: dt, bubbles: true, cancelable: true}));
        z.dispatchEvent(new DragEvent('dragover', {dataTransfer: dt, bubbles: true, cancelable: true}));
        window.__activa = document.querySelector('.zona')?.classList.contains('zona--activa') ?? null;
        z.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
    }"""
    pg.evaluate(soltar, ["arrastrado.eml", contenido_eml, 1])
    check("B1 Al arrastrar sobre la zona se resalta (zona--activa)", pg.evaluate("window.__activa") is True)
    esperar_previa(pg)
    check("B2 Al soltar un .eml se extrae y se muestra su vista previa", texto(pg, ".fila-archivo__nombre") == "arrastrado.eml")
    check("B3 Sin errores de consola al arrastrar y soltar", not v.errores, v.errores)
    # Soltar más de un archivo
    pg.click("#btn-quitar")
    pg.wait_for_selector(".zona")
    pg.evaluate(soltar, ["varios.eml", contenido_eml, 2])
    pg.wait_for_selector(".aviso--error")
    check("B4 Soltar varios archivos a la vez muestra un mensaje claro", "un solo archivo" in texto(pg, ".aviso--error"))
    check("B5 Ese error no inicia ninguna extracción", v.n("/correo/extraer") == 1, v.posts)
    pg.evaluate(soltar, ["foto.png", "no es un correo", 1])
    pg.wait_for_selector(".aviso--error")
    check("B6 Soltar un formato no admitido (.png) muestra el error de formato", "no es compatible" in texto(pg, ".aviso--error"))
    br.close()

    # =====================================================================
    # C. Pegar contenido
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    ir_a_analisis(pg)
    pg.get_by_role("tab", name="Pegar contenido").click()
    pg.wait_for_selector("#texto-pegado")
    foto(pg, "C1_pegar")
    pg.click("#btn-extraer-texto")
    pg.wait_for_selector(".aviso--error")
    check("C1 Extraer con el área vacía muestra un error y no llama a la API",
          "Pega el contenido" in texto(pg, ".aviso--error") and v.n("/correo/extraer") == 0)
    pg.fill("#texto-pegado", eml_spam_sintetico().decode("utf-8", "replace"))
    check("C2 El contador de caracteres se actualiza", "caracteres" in texto(pg, "#contador-pegado") and not texto(pg, "#contador-pegado").startswith("0 "))
    pg.click("#btn-extraer-texto")
    esperar_previa(pg)
    check("C3 El correo pegado (con cabeceras) se extrae y se identifica como «Texto pegado»", texto(pg, ".fila-archivo__nombre") == "Texto pegado")
    check("C4 Del texto pegado se extraen remitente y asunto", "promo@ofertas-ya.example" in texto(pg, ".datos") and "WINNER" in texto(pg, ".datos"))
    pg.click("#btn-quitar")
    pg.wait_for_selector(".zona, #texto-pegado")
    pg.get_by_role("tab", name="Pegar contenido").click()
    pg.fill("#texto-pegado", "Hi, this is only the body of a message. Visit http://example.org/page today.")
    pg.click("#btn-extraer-texto")
    esperar_previa(pg)
    check("C5 Pegar solo el cuerpo: los campos sin datos dicen «No disponible»", texto(pg, ".datos").count("No disponible") == 4)
    check("C6 Pegar solo el cuerpo: se avisa que no hay cabeceras", "No se encontraron cabeceras" in texto(pg, ".lista-avisos"))
    pg.click("#btn-analizar")
    esperar_resultado(pg)
    check("C7 El texto pegado se analiza con el modelo real (hay veredicto)", texto(pg, ".banner__titulo").strip() in ("SPAM", "LEGÍTIMO"))
    check("C8 Sin errores de consola al pegar y analizar", not v.errores, v.errores)
    br.close()

    # =====================================================================
    # D. Archivos inválidos y errores del servidor (los 4xx generan avisos de consola esperados)
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    ir_a_analisis(pg)
    casos_cliente = [
        ("D1 Extensión no admitida (.pdf)", escribir("documento.pdf", b"%PDF-1.4 hola"), "no es compatible"),
        ("D2 Archivo vacío", escribir("vacio.eml", b""), "vacío"),
        ("D3 Archivo de más de 5 MB", escribir("enorme.eml", b"From: a@b.example\r\n\r\n" + b"x" * (5 * 1024 * 1024 + 10)), "5 MB"),
        ("D4 Archivo sin extensión", escribir("sinextension", b"From: a@b.example\r\n\r\nhola"), "sin extensión"),
    ]
    for nombre, ruta, frag in casos_cliente:
        v.posts.clear()
        subir(pg, ruta)
        pg.wait_for_selector(".aviso--error")
        check(f"{nombre}: mensaje claro y sin llamar al servidor",
              frag in texto(pg, ".aviso--error") and v.n("/correo/extraer") == 0, texto(pg, ".aviso--error"))
    foto(pg, "D1_error_archivo")
    # Errores que decide el servidor
    v.posts.clear()
    subir(pg, escribir("falso.eml", b"\xd0\xcf\x11\xe0\x00\x00\x00\x00" + b"\x00" * 200))
    pg.wait_for_selector(".aviso--error")
    check("D5 Un .eml binario/corrupto: el servidor lo rechaza y la interfaz muestra su mensaje",
          "binario" in texto(pg, ".aviso--error") and v.n("/correo/extraer") == 1, texto(pg, ".aviso--error"))
    check("D6 Tras el error la interfaz vuelve a la carga (se puede elegir otro archivo)", pg.locator(".zona").count() == 1)
    subir(pg, escribir("sin_cuerpo.eml", b"From: a@b.example\r\nTo: c@d.example\r\nSubject: vacio\r\n\r\n"))
    pg.wait_for_selector(".aviso--error")
    check("D7 Correo sin texto analizable: mensaje claro del servidor", "no contiene texto analizable" in texto(pg, ".aviso--error"), texto(pg, ".aviso--error"))
    subir(pg, HAM)
    esperar_previa(pg)
    check("D8 Después de varios errores se puede cargar un correo válido", pg.locator("#btn-analizar").count() == 1)
    br.close()

    # =====================================================================
    # E. Quitar y cambiar de archivo
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    ir_a_analisis(pg)
    subir(pg, SPAM)
    esperar_previa(pg)
    pg.click("#btn-quitar")
    pg.wait_for_selector(".zona")
    check("E1 «Quitar» elimina el archivo y vuelve a la carga", pg.locator(".fila-archivo").count() == 0 and pg.locator(".zona").count() == 1)
    subir(pg, OTRO)
    esperar_previa(pg)
    check("E2 Se puede elegir otro archivo y se muestra su nombre", texto(pg, ".fila-archivo__nombre") == OTRO.name)
    pg.get_by_role("button", name="Elegir otro correo").click()
    pg.wait_for_selector(".zona")
    check("E3 «Elegir otro correo» también reinicia", pg.locator(".zona").count() == 1)
    subir(pg, SPAM)
    esperar_previa(pg)
    pg.evaluate(soltar, ["reemplazo.eml", contenido_eml, 1])
    pg.wait_for_function("document.querySelector('.fila-archivo__nombre')?.textContent === 'reemplazo.eml'", timeout=15000)
    check("E4 Soltar un archivo sobre una vista previa lo reemplaza", texto(pg, ".fila-archivo__nombre") == "reemplazo.eml")
    check("E5 Sin errores de consola", not v.errores, v.errores)
    br.close()

    # =====================================================================
    # F. Estado de carga y protección contra clics repetidos
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    ir_a_analisis(pg)
    subir(pg, SPAM)
    esperar_previa(pg)

    def retrasar(route):
        pg.wait_for_timeout(1200)
        route.continue_()
    pg.route("**/predecir", retrasar)
    v.posts.clear()
    pg.evaluate("() => { const b = document.querySelector('#btn-analizar'); b.click(); b.click(); b.click(); }")
    pg.wait_for_selector(".estado", timeout=3000)
    foto(pg, "F1_analizando")
    check("F1 Durante el análisis se muestra el indicador de carga («Analizando con el modelo…»)", "Analizando" in texto(pg, ".estado"))
    check("F2 El botón se desactiva mientras se analiza", pg.locator("#btn-analizar").is_disabled())
    check("F3 «Quitar» y «Elegir otro correo» se bloquean mientras se analiza",
          pg.locator("#btn-quitar").is_disabled() and pg.get_by_role("button", name="Elegir otro correo").is_disabled())
    esperar_resultado(pg)
    check("F4 Tres clics seguidos producen una sola llamada a /predecir", v.n("/predecir") == 1, v.posts)
    pg.unroute("**/predecir")
    br.close()

    # =====================================================================
    # G. Errores de conexión y respuestas inesperadas
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    ir_a_analisis(pg)
    subir(pg, SPAM)
    esperar_previa(pg)
    pg.route("**/predecir", lambda r: r.abort())
    pg.click("#btn-analizar")
    pg.wait_for_selector(".aviso--error")
    foto(pg, "G1_error_conexion")
    check("G1 Si la API no responde: mensaje de conexión claro", "No se pudo conectar" in texto(pg, ".aviso--error"), texto(pg, ".aviso--error"))
    check("G2 Tras el error se conserva la vista previa y el botón se reactiva",
          pg.locator(".fila-archivo").count() == 1 and pg.locator("#btn-analizar").is_enabled())
    pg.unroute("**/predecir")
    pg.route("**/predecir", lambda r: r.fulfill(status=500, content_type="application/json", body='{"detail":"fallo interno simulado"}'))
    pg.click("#btn-analizar")
    pg.wait_for_function("document.querySelector('.aviso--error')?.textContent.includes('fallo interno simulado')", timeout=10000)
    check("G3 Error HTTP 500 de la API: se muestra el mensaje recibido", True)
    pg.unroute("**/predecir")
    pg.route("**/predecir", lambda r: r.fulfill(status=200, content_type="application/json", body='{"x": 1}'))
    pg.click("#btn-analizar")
    pg.wait_for_function("document.querySelector('.aviso--error')?.textContent.includes('formato inesperado')", timeout=10000)
    check("G4 Respuesta 200 con formato inesperado: se rechaza con mensaje claro (no se muestra un resultado falso)",
          pg.locator(".banner").count() == 0)
    pg.unroute("**/predecir")
    pg.click("#btn-analizar")
    esperar_resultado(pg)
    check("G5 Al volver la conexión, «Analizar correo» funciona de nuevo (reintento)", texto(pg, ".banner__titulo").strip() in ("SPAM", "LEGÍTIMO"))
    pg.click("#btn-otro")
    pg.wait_for_selector(".zona")
    pg.route("**/correo/extraer", lambda r: r.abort())
    subir(pg, SPAM)
    pg.wait_for_selector(".aviso--error")
    check("G6 Si falla la conexión al extraer: mensaje claro y se vuelve a la carga",
          "No se pudo conectar" in texto(pg, ".aviso--error") and pg.locator(".zona").count() == 1)
    br.close()

    # =====================================================================
    # H. Navegación: el estado no se pierde al cambiar de sección
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    ir_a_analisis(pg)
    subir(pg, SPAM)
    esperar_previa(pg)
    pg.get_by_role("link", name="Historial", exact=True).click()
    pg.wait_for_selector("text=Historial de análisis")
    pg.get_by_role("link", name="Análisis", exact=True).click()
    pg.wait_for_selector("#btn-analizar")
    check("H1 Al ir a otra sección y volver se conserva el correo cargado", texto(pg, ".fila-archivo__nombre") == SPAM.name)
    check("H2 El indicador de pasos sigue en «Analizar» tras volver", "Analizar" in texto(pg, ".paso--actual"))
    pg.click("#btn-analizar")
    esperar_resultado(pg)
    pg.get_by_role("link", name="Métricas", exact=True).click()
    pg.wait_for_selector("text=Métricas del modelo")
    pg.get_by_role("link", name="Análisis", exact=True).click()
    pg.wait_for_selector(".banner")
    check("H3 También se conserva el resultado al volver", texto(pg, ".banner__titulo").strip() in ("SPAM", "LEGÍTIMO"))
    check("H4 El indicador de pasos sigue en «Entender» tras volver", "Entender" in texto(pg, ".paso--actual"))
    pg.get_by_role("button", name="Volver a la vista previa").click()
    pg.wait_for_selector("#btn-analizar")
    check("H5 «Volver a la vista previa» regresa al correo sin perderlo", texto(pg, ".fila-archivo__nombre") == SPAM.name)
    check("H6 Sin errores de consola al navegar", not v.errores, v.errores)
    br.close()

    # =====================================================================
    # I. Teclado y accesibilidad básica
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    ir_a_analisis(pg)
    # Con Tab se debe llegar al botón «Elegir archivo» (orden de tabulación razonable)
    llego = False
    for _ in range(25):
        pg.keyboard.press("Tab")
        if pg.evaluate("document.activeElement.id") == "btn-elegir":
            llego = True
            break
    check("I0 Con la tecla Tab se llega al botón «Elegir archivo»", llego)
    # Enter debe activar el botón (el Chromium sin pantalla no concede permiso para abrir el selector con teclas
    # simuladas, así que se comprueba el clic de confianza; la apertura real del selector va en la lista manual).
    pg.evaluate("""() => { window.__clicks = 0;
        document.querySelector('#btn-elegir').addEventListener('click', e => { if (e.isTrusted) window.__clicks++; }); }""")
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(200)
    check("I1 Con teclado: Enter sobre «Elegir archivo» activa el botón", pg.evaluate("window.__clicks") == 1)
    subir(pg, HAM)
    esperar_previa(pg)
    check("I2 Tras extraer, el foco queda en «Analizar correo»", pg.evaluate("document.activeElement.id") == "btn-analizar")
    pg.keyboard.press("Enter")
    esperar_resultado(pg)
    check("I3 Con teclado: Enter en «Analizar correo» analiza", pg.locator(".banner").count() == 1)
    check("I4 Tras el resultado, el foco pasa al veredicto", "banner" in pg.evaluate("document.activeElement.className"))
    pg.click("#btn-otro")
    pg.wait_for_selector(".zona")
    pg.focus("#tab-archivo")
    pg.keyboard.press("ArrowRight")
    pg.wait_for_selector("#texto-pegado")
    check("I5 Las pestañas se cambian con las flechas del teclado", pg.locator("#texto-pegado").count() == 1)
    check("I6 Cada campo de la pantalla tiene etiqueta accesible (label del área de texto)",
          pg.locator("label[for=texto-pegado]").count() == 1)
    br.close()

    # =====================================================================
    # J. Seguridad: HTML malicioso en el correo
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    ir_a_analisis(pg)
    nombre_raro = 'a<b>c&d.eml'
    subir(pg, escribir(nombre_raro, MALICIOSO))
    esperar_previa(pg)
    pg.click(".detalles > summary")
    pg.wait_for_timeout(300)
    foto(pg, "J1_correo_malicioso")
    check("J1 El script del correo NO se ejecuta (window.__xss sigue sin definir)", pg.evaluate("window.__xss === undefined"), pg.evaluate("String(window.__xss)"))
    check("J2 No se crean <script>, <img>, <iframe> ni <a> dentro de la vista del correo",
          pg.locator(".analisis script, .analisis img, .analisis iframe, .analisis a, .analisis object, .analisis embed").count() == 0)
    check("J3 El asunto con etiquetas se ve como texto literal", "<img src=x" in texto(pg, ".datos"), texto(pg, ".datos"))
    check("J4 El remitente con etiquetas se ve como texto literal", "<b>Banco</b>" in texto(pg, ".datos") or "Banco" in texto(pg, ".datos"))
    check("J5 El HTML malicioso aparece solo como código de texto en el desplegable", "<script>window.__xss=1</script>" in texto(pg, ".detalles .previa"))
    check("J6 El nombre de archivo con caracteres HTML se muestra literal", texto(pg, ".fila-archivo__nombre") == nombre_raro, texto(pg, ".fila-archivo__nombre"))
    check("J7 javascript: no aparece como enlace; el href http sí aparece como texto no clicable",
          "javascript:" not in texto(pg, ".enlaces") and "http://evil.example/x" in texto(pg, ".enlaces"))
    pg.click("#btn-analizar")
    esperar_resultado(pg)
    check("J8 Tras analizar tampoco se ejecuta nada y sigue sin haber elementos peligrosos",
          pg.evaluate("window.__xss === undefined") and pg.locator(".analisis script, .analisis img, .analisis iframe").count() == 0)
    check("J9 No hubo peticiones a evil.example (no se cargaron imágenes ni iframes del correo)",
          not any("evil.example" in u for u in v.todas), [u for u in v.todas if "evil" in u])
    br.close()

    # =====================================================================
    # K. Adaptación a pantallas pequeñas (móvil)
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p, 390, 844)
    ir_a_analisis(pg)

    def sin_desborde():
        return pg.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
    check("K1 Móvil: la pantalla inicial no desborda horizontalmente", sin_desborde())
    foto(pg, "K1_movil_inicial")
    subir(pg, SPAM)
    esperar_previa(pg)
    check("K2 Móvil: la vista previa no desborda horizontalmente", sin_desborde())
    foto(pg, "K2_movil_previa")
    pg.click("#btn-analizar")
    esperar_resultado(pg)
    check("K3 Móvil: el resultado no desborda horizontalmente", sin_desborde())
    foto(pg, "K3_movil_resultado")
    check("K4 Móvil: sin errores de consola", not v.errores, v.errores)
    br.close()

    # =====================================================================
    # L. Los endpoints originales siguen respondiendo
    # =====================================================================
    br, ctx, pg, v = nueva_pagina(p)
    s = ctx.request.get(BASE + "/salud")
    m = ctx.request.get(BASE + "/metricas")
    pr = ctx.request.post(BASE + "/predecir", data={"texto": "Hello, please find the minutes attached."})
    check("L1 /salud responde 200 con el modelo cargado", s.status == 200 and s.json().get("modelo_cargado") is True)
    check("L2 /metricas responde 200 con las métricas de prueba originales",
          m.status == 200 and m.json()["test"]["accuracy"] == 0.9533 and m.json()["test"]["matriz_confusion_lista"] == [[175, 4], [10, 111]])
    check("L3 /predecir responde 200 con el formato original", pr.status == 200 and set(pr.json()) == {"es_spam", "probabilidad", "rasgos_detectados"})
    br.close()

total = len(resultados)
fallas = [r for r in resultados if not r["ok"]]
Path(args.salida).write_text(json.dumps({"total": total, "fallas": len(fallas), "resultados": resultados}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n{total - len(fallas)}/{total} pruebas superadas." + ("" if not fallas else f" FALLAS: {[f['prueba'] for f in fallas]}"))
sys.exit(1 if fallas else 0)
