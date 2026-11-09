"""Pruebas de la Fase 4 (resultados y evidencias) en un navegador real (Chromium + Playwright).
[Fase 5 / D6] Las expectativas numéricas se actualizaron al formato es-MX (punto decimal, coma de millares) y el menú tiene 6 elementos.


Uso:
  python probar_resultados_fase4.py http://127.0.0.1:8000 ..\\capturas resultados_fase4.json

Qué usa de verdad y qué simula:
  * /correo/extraer, /metricas y la interfaz: SIEMPRE los reales del servidor que indiques.
  * /predecir: en las pruebas marcadas «(simulada)» se intercepta la respuesta en el navegador para
    forzar probabilidades exactas (0,50; 0,4999; 0; 1…), algo que no se puede conseguir con correos reales.
    En las pruebas marcadas «(real)» se usa el modelo del servidor sin interceptar nada.
  Una respuesta simulada solo prueba cómo DIBUJA la interfaz; no prueba al modelo.
"""
import argparse
import json
import re
import sys
import time
from email.message import EmailMessage
from pathlib import Path

from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("base")
ap.add_argument("capturas")
ap.add_argument("salida")
args = ap.parse_args()
BASE = args.base.rstrip("/")
CAPT = Path(args.capturas)
CAPT.mkdir(parents=True, exist_ok=True)

RESULTADOS = []


def check(nombre, condicion, detalle=""):
    ok = bool(condicion)
    RESULTADOS.append({"prueba": nombre, "ok": ok, "detalle": "" if ok else str(detalle)})
    print(("[OK]   " if ok else "[FALLA]") + " " + nombre + ("" if ok else f"  -> {detalle}"))


def sec(titulo):
    print(f"\n=== {titulo} ===")


# ---------------------------------------------------------------- correos de prueba
def correo(asunto="Oferta", de="Tienda <ventas@tienda.example>", para="yo@ejemplo.org", cuerpo="Hola, mira esto.",
           html=None, fecha="Mon, 02 Nov 2026 10:00:00 -0600", adjunto=False):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Date"] = de, para, asunto, fecha
    if cuerpo is not None:
        m.set_content(cuerpo)
    if html:
        if cuerpo is None:
            m.set_content(html, subtype="html")
        else:
            m.add_alternative(html, subtype="html")
    if adjunto:
        m.add_attachment(b"%PDF-1.4 falso", maintype="application", subtype="pdf", filename="factura.pdf")
    return m.as_bytes()


EML_SPAM = correo(
    asunto="WINNER!! Claim your FREE prize", de="Premios <promo@ofertas-ya.example>",
    cuerpo="WINNER!! Claim your FREE prize now: http://bit.ly/claim-now and also www.ejemplo.org/oferta",
    html='<html><body><table><tr><td><a href="http://promo.example/oferta">http://paypal.com</a></td></tr></table></body></html>')
EML_HAM = correo(asunto="Reunión del lunes", de="Ana <ana@universidad.example>",
                 cuerpo="Hola Martín, te confirmo la reunión del lunes a las 10:00 en el laboratorio. Saludos, Ana.")
EML_MALICIOSO = correo(
    asunto='<img src=x onerror="window.__xss=1">', de='"<b>Banco</b>" <x@banco.example>',
    cuerpo="Texto <script>window.__xss=1</script> con http://evil.example/x y javascript:alert(1)",
    html='<html><body><script>window.__xss=1</script><img src="http://evil.example/p.png" onerror="window.__xss=1">'
         '<iframe src="http://evil.example/f"></iframe><a href="javascript:window.__xss=1">clic</a>'
         '<a href="http://evil.example/x">http://banco.example</a></body></html>')
EML_SOLO_HTML = correo(cuerpo=None, html="<html><body><p>Solo parte HTML con <a href='http://sitio.example/a'>enlace</a></p></body></html>")
EML_ADJUNTO = correo(cuerpo="Adjunto la factura.", adjunto=True)
TEXTO_LARGO = "Hola. " + ("Esto es una frase de relleno para superar el límite del detector. " * 80)
EML_LARGO = correo(cuerpo=TEXTO_LARGO)
SIN_CABECERAS = "Hola, este es solo el cuerpo del mensaje sin cabeceras. Visita www.ejemplo.org/promo hoy."


# ---------------------------------------------------------------- respuestas simuladas de /predecir
def rasgo(id_, cat, valor, activo, desc):
    return {"rasgo": id_, "categoria": cat, "valor": valor, "activo": activo, "descripcion": desc}


RASGOS_BASE = [
    rasgo("txt_mayusculas", "texto", 0.41, True, "Alta densidad de letras mayúsculas"),
    rasgo("url_acortador", "url", 1.0, True, "URL con acortador de enlaces"),
    rasgo("dom_distancia_ref", "dom", 0.52, True, "Estructura DOM cercana al árbol de referencia de spam"),
    rasgo("dep_prof_max", "sintactico", 4.0, False, "Profundidad máxima del árbol de dependencias (spaCy)"),
    rasgo("pos_verbos", "sintactico", 0.12, False, "Proporción de verbos según etiquetado POS (NLTK)"),
]


def resp(p, es_spam=None, rasgos=None):
    return {"es_spam": (p >= 0.5) if es_spam is None else es_spam, "probabilidad": p,
            "rasgos_detectados": RASGOS_BASE if rasgos is None else rasgos}


# ---------------------------------------------------------------- utilidades de navegador
class Vigilante:
    def __init__(self, pg):
        self.errores, self.todas, self.posts = [], [], []
        pg.on("console", lambda m: self.errores.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: self.errores.append(str(e)))
        pg.on("request", lambda r: (self.todas.append(r.url), self.posts.append(r.url) if r.method == "POST" else None))

    def n(self, ruta):
        return sum(1 for u in self.posts if u.endswith(ruta))

    def get(self, ruta):
        return sum(1 for u in self.todas if u.endswith(ruta))


def nueva(p, ancho=1366, alto=900):
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width": ancho, "height": alto})
    pg = ctx.new_page()
    return br, ctx, pg, Vigilante(pg)


def mockear(pg, respuesta=None, estado=200, retraso=0.0):
    """Intercepta /predecir. Devuelve la lista donde se anotan las llamadas."""
    llamadas = []

    if retraso:  # el retraso se aplica en el navegador (bloquear aquí detendría a Playwright)
        pg.add_init_script("""(() => { const f = window.fetch; window.fetch = async (u, o) => {
            if (String(u).endsWith('/predecir')) await new Promise((r) => setTimeout(r, %d));
            return f(u, o); }; })();""" % int(retraso * 1000))

    def manejador(route):
        llamadas.append(route.request.post_data)
        route.fulfill(status=estado, content_type="application/json", body=json.dumps(respuesta))

    pg.route("**/predecir", manejador)
    return llamadas


def abrir(pg):
    pg.goto(BASE + "/")
    pg.wait_for_selector(".zona")
    pg.wait_for_timeout(300)


def subir(pg, datos, nombre="correo.eml"):
    pg.set_input_files("#entrada-archivo", files=[{"name": nombre, "mimeType": "message/rfc822", "buffer": datos}])
    pg.wait_for_selector("#btn-analizar", timeout=15000)
    pg.wait_for_timeout(250)


def analizar(pg):
    pg.click("#btn-analizar")
    pg.wait_for_selector(".banner", timeout=20000)
    pg.wait_for_timeout(300)


def flujo(pg, datos, respuesta=None, nombre="correo.eml"):
    llamadas = mockear(pg, respuesta) if respuesta is not None else None
    abrir(pg)
    subir(pg, datos, nombre)
    analizar(pg)
    return llamadas


def txt(pg, sel):
    return pg.inner_text(sel).replace(" ", " ")


def foto(pg, nombre, completo=True):
    pg.wait_for_timeout(250)
    pg.screenshot(path=str(CAPT / f"{nombre}.png"), full_page=completo)


def pct_ui(pg):
    return txt(pg, ".prob__valor").strip()


def hay_desborde(pg):
    return pg.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")


def extraer_api(ctx, datos, nombre="correo.eml"):
    r = ctx.request.post(BASE + "/correo/extraer", data=datos, headers={"Content-Type": "message/rfc822"})
    return r.json()


with sync_playwright() as p:
    # =====================================================================
    sec("A. Clasificación y probabilidad (simulada)")
    # =====================================================================
    casos = [
        # id, p, es_spam, texto P(spam), nivel, distancia
        ("A1", 0.9732, True, "97.3 %", "Muy alto", "+47.3 puntos"),
        ("A2", 0.12, False, "12.0 %", "Bajo", "−38 puntos"),
        ("A3", 0.42, False, "42.0 %", "Moderado", "−8 puntos"),
        ("A4", 0.5, True, "50.0 %", "Alto", "+0 puntos"),
        ("A5", 0.0, False, "0.0 %", "Bajo", "−50 puntos"),
        ("A6", 1.0, True, "100.0 %", "Muy alto", "+50 puntos"),
    ]
    for id_, pr, spam, esperado_pct, nivel, dist in casos:
        br, ctx, pg, v = nueva(p)
        flujo(pg, EML_SPAM, resp(pr, spam))
        etiqueta = "SPAM" if spam else "LEGÍTIMO"
        check(f"{id_} (simulada) p={pr}: el veredicto es {etiqueta}", txt(pg, ".banner__titulo").strip() == etiqueta)
        check(f"{id_} P(spam) se muestra como {esperado_pct}", pct_ui(pg) == esperado_pct, pct_ui(pg))
        check(f"{id_} El banner usa el estilo {'rojo' if spam else 'verde'} del veredicto",
              pg.locator(".banner--spam" if spam else ".banner--ok").count() == 1)
        ancho = pg.evaluate("document.querySelector('.medidor__relleno').style.width")
        check(f"{id_} La barra mide {pr * 100:g} %", abs(float(ancho.rstrip('%')) - pr * 100) < 0.06, ancho)
        check(f"{id_} Un solo tramo de riesgo activo: «{nivel}»",
              pg.locator(".escala__tramo--activo").count() == 1 and nivel in txt(pg, ".escala__tramo--activo"),
              txt(pg, ".escala__tramo--activo"))
        check(f"{id_} La distancia al umbral es {dist}", dist in txt(pg, ".cifras"), txt(pg, ".cifras"))
        check(f"{id_} La regla del umbral 50 % aparece en el banner", "P(spam) ≥ 50.0 %" in txt(pg, ".banner__regla"))
        if id_ == "A1":
            foto(pg, "A1_resultado_spam_escritorio")
        if id_ == "A2":
            foto(pg, "A2_resultado_legitimo_escritorio")
        br.close()

    br, ctx, pg, v = nueva(p)
    flujo(pg, EML_SPAM, resp(0.42, False))
    t = txt(pg, ".analisis")
    check("A7 El resultado distingue clasificación final y P(spam) como cosas separadas",
          "Clasificación final" in txt(pg, ".cifras") and "Probabilidad de spam" in t)
    check("A8 La interfaz aclara que P(spam) no es certeza ni confianza", "certeza" in t and "no es una segunda salida del modelo" in t)
    check("A9 El nivel de riesgo se presenta como lectura orientativa y no calibrada",
          "lectura orientativa" in t and "no están calibrados" in t)
    check("A10 Con P(spam)=42 % y LEGÍTIMO se aclara que depende del umbral",
          "inferior al umbral de decisión (50.0 %)" in t and "únicamente de si P(spam) alcanza 50.0 %" in t)
    check("A11 Un caso a menos de 10 puntos del umbral se marca como caso límite", "Caso cercano al umbral" in t)
    br.close()

    br, ctx, pg, v = nueva(p)
    flujo(pg, EML_SPAM, resp(0.12, False))
    check("A12 Un caso lejano del umbral (12 %) NO se marca como caso límite", "Caso cercano al umbral" not in txt(pg, ".analisis"))
    br.close()

    br, ctx, pg, v = nueva(p)
    flujo(pg, EML_SPAM, resp(0.5, False))
    t = txt(pg, ".analisis")
    check("A13 P(spam) redondeada a 50 % con es_spam=false: sigue siendo LEGÍTIMO y se explica el redondeo",
          txt(pg, ".banner__titulo").strip() == "LEGÍTIMO" and "redondeada a 50 %" in t)
    check("A14 Ese caso de redondeo no se presenta como error", pg.locator(".analisis .aviso--error").count() == 0)
    br.close()

    br, ctx, pg, v = nueva(p)
    flujo(pg, EML_SPAM, resp(0.9, False))
    check("A15 Si la API devuelve es_spam y P(spam) incoherentes se avisa, y se respeta es_spam",
          pg.locator(".analisis .aviso--error").count() == 1 and txt(pg, ".banner__titulo").strip() == "LEGÍTIMO")
    br.close()

    # Funciones puras
    br, ctx, pg, v = nueva(p)
    abrir(pg)
    tramos = pg.evaluate("""async () => {
        const m = await import('/static/js/vistas/resultado.js');
        const f = (x) => m.nivelRiesgo(x).id;
        return [f(0), f(0.2499), f(0.25), f(0.4999), f(0.5), f(0.7499), f(0.75), f(1), f(-3), f(7),
                m.coherencia({es_spam: true, probabilidad: 0.5}), m.coherencia({es_spam: false, probabilidad: 0.5}),
                m.coherencia({es_spam: false, probabilidad: 0.4999}), m.coherencia({es_spam: true, probabilidad: 0.3}),
                m.UMBRAL, m.distanciaUmbral(0.6732)];
    }""")
    check("A16 Los tramos de riesgo cortan exactamente en 25 %, 50 % y 75 %",
          tramos[:10] == ["bajo", "bajo", "moderado", "moderado", "alto", "alto", "muy-alto", "muy-alto", "bajo", "muy-alto"], tramos[:10])
    check("A17 coherencia(): concuerda / redondeo / incoherente", tramos[10:14] == [None, "redondeo", None, "incoherente"], tramos[10:14])
    check("A18 El umbral usado en la interfaz es 0,5 y la distancia se calcula bien", tramos[14] == 0.5 and tramos[15] == 17.3, tramos[14:])
    br.close()

    # =====================================================================
    sec("B. Evidencias del correo (extracción real, predicción simulada)")
    # =====================================================================
    br, ctx, pg, v = nueva(p)
    ext = extraer_api(ctx, EML_SPAM)
    flujo(pg, EML_SPAM, resp(0.9732))
    datos = txt(pg, ".datos")
    check("B1 Remitente, destinatario, asunto y fecha coinciden con lo que extrajo el backend",
          all(str(ext[k]) in datos for k in ("remitente", "destinatario", "asunto", "fecha")), datos)
    check("B2 Hay un solo bloque de datos del mensaje en la pantalla (sin duplicados)", pg.locator(".datos").count() == 1)
    pg.get_by_role("tab", name=re.compile("Texto extraído")).click()
    check("B3 La pestaña «Texto extraído» muestra el texto que extrajo el backend",
          ext["texto"][:60] in txt(pg, "#panel-ev-texto .previa"))
    check("B4 El HTML del correo se ofrece como código en un desplegable, no renderizado",
          pg.locator("#panel-ev-texto details summary").count() == 1 and pg.locator("#panel-ev-texto table").count() == 0)
    pg.get_by_role("tab", name=re.compile("Enlaces")).click()
    urls_ui = [u.strip() for u in pg.locator("#panel-ev-enlaces .enlaces code").all_inner_texts()]
    check("B5 Los enlaces mostrados son exactamente los del backend", urls_ui == [e["url"] for e in ext["enlaces"]], urls_ui)
    check("B6 Cada enlace indica su origen (texto o HTML)", "En el texto" in txt(pg, "#panel-ev-enlaces") and "En un enlace HTML" in txt(pg, "#panel-ev-enlaces"))
    check("B7 Se muestra el dominio como dato informativo", "Dominio: bit.ly" in txt(pg, "#panel-ev-enlaces"), txt(pg, "#panel-ev-enlaces"))
    check("B8 Los enlaces NO son clicables (cero <a> en la pantalla)", pg.locator(".analisis a").count() == 0)
    check("B9 La interfaz no califica los enlaces como maliciosos",
          not re.search(r"malicios|peligros|fraudulent", txt(pg, "#panel-ev-enlaces"), re.I), txt(pg, "#panel-ev-enlaces"))
    check("B10 Aclara que encontrar un enlace no lo vuelve sospechoso", "no lo vuelve sospechoso" in txt(pg, "#panel-ev-enlaces"))
    pg.get_by_role("tab", name="Estructura").click()
    est = txt(pg, "#panel-ev-estructura")
    check("B11 Las características estructurales salen de datos reales del backend",
          "Correo con cabeceras (.eml)" in est and f"{ext['enlaces_total']}" in est and "Parte HTML" in est and "Sí ·" in est, est)
    check("B12 La pestaña Estructura declara lo que la API no entrega", "no devuelve el árbol HTML" in est)
    pg.get_by_role("tab", name=re.compile("Rasgos")).click()
    ids = pg.locator(".rasgo:not(.rasgo--inactivo) .rasgo__id").all_inner_texts()
    check("B13 Los rasgos activos mostrados son exactamente los de la respuesta",
          sorted(ids) == sorted(r["rasgo"] for r in RASGOS_BASE if r["activo"]), ids)
    check("B14 Los rasgos sin activarse se separan y se cuentan",
          "Medidos sin activarse (2)" in txt(pg, "#panel-ev-rasgos"))
    check("B15 Se aclara que los rasgos son heurísticas y no atribuciones causales",
          "heurísticas" in txt(pg, "#panel-ev-rasgos") and "no son atribuciones causales" in txt(pg, "#panel-ev-rasgos").lower())
    check("B16 Los enlaces no se presentan como rasgos del modelo", pg.locator(".rasgo").filter(has_text="http").count() == 0)
    foto(pg, "B1_evidencias_rasgos")
    br.close()

    # Ausencia de información
    br, ctx, pg, v = nueva(p)
    abrir(pg)
    mockear(pg, resp(0.2, False, rasgos=[rasgo("txt_mayusculas", "texto", 0.01, False, "Alta densidad de letras mayúsculas")]))
    pg.get_by_role("tab", name="Pegar contenido").click()
    pg.fill("#texto-pegado", SIN_CABECERAS)
    pg.click("#btn-extraer-texto")
    pg.wait_for_selector("#btn-analizar")
    analizar(pg)
    check("B17 Sin cabeceras, los cuatro campos dicen «No disponible»", txt(pg, ".datos").count("No disponible") == 4)
    av = txt(pg, ".analisis")
    check("B18 Se avisa que no hubo cabeceras y que falta HTML", "No se encontraron cabeceras" in av and "no incluye HTML" in av)
    check("B19 Se enumeran los campos no disponibles", "No disponible en este correo: remitente, destinatario, asunto, fecha." in av)
    pg.get_by_role("tab", name="Estructura").click()
    check("B20 Estructura: texto pegado sin HTML se describe como tal",
          "Texto pegado sin cabeceras" in txt(pg, "#panel-ev-estructura") and "Parte HTML" in txt(pg, "#panel-ev-estructura"))
    pg.get_by_role("tab", name="Texto extraído").click()
    check("B21 Sin HTML, la pestaña de texto lo dice", "no incluye parte HTML" in txt(pg, "#panel-ev-texto"))
    br.close()

    br, ctx, pg, v = nueva(p)
    flujo(pg, EML_SOLO_HTML, resp(0.3, False))
    check("B22 Correo solo HTML: se avisa que el texto se obtuvo del HTML", "se obtuvo del HTML" in txt(pg, ".analisis"))
    br.close()

    br, ctx, pg, v = nueva(p)
    flujo(pg, EML_ADJUNTO, resp(0.3, False))
    check("B23 Con adjunto: se avisa que se ignoró y el contador lo refleja",
          "Se ignoraron 1 adjunto" in txt(pg, ".analisis") and "1" in txt(pg, ".resumen"))
    br.close()

    br, ctx, pg, v = nueva(p)
    flujo(pg, EML_LARGO, resp(0.3, False))
    pg.get_by_role("tab", name="Texto extraído").click()
    check("B24 Texto largo: se marca dónde deja de leer el detector", pg.locator("#panel-ev-texto .previa__corte").count() == 1)
    check("B25 Texto largo: la advertencia del backend aparece en «Avisos»", "solo analiza los primeros" in txt(pg, ".analisis"))
    br.close()

    br, ctx, pg, v = nueva(p)
    flujo(pg, EML_HAM, resp(0.1, False, rasgos=[]))
    check("B26 Si la API no devuelve rasgos, se dice (sin romper la pantalla)", "no devolvió rasgos" in txt(pg, "#panel-ev-rasgos"))
    check("B27 Sin enlaces: el contador es 0 y se informa", "No se encontraron enlaces" in
          (pg.get_by_role("tab", name=re.compile("Enlaces")).click() or txt(pg, "#panel-ev-enlaces")))
    br.close()

    # =====================================================================
    sec("C. Explicación del resultado")
    # =====================================================================
    br, ctx, pg, v = nueva(p)
    flujo(pg, EML_HAM, resp(0.42, False))
    titulos = pg.locator(".acordeon__item > summary").all_inner_texts()
    check("C1 Hay cinco preguntas de explicación", len(titulos) == 5, titulos)
    for fragmento in ("SPAM?", "LEGÍTIMO?", "P(spam)", "50 %", "Limitaciones"):
        check(f"C2 Existe la explicación «{fragmento}»", any(fragmento in t_ for t_ in titulos), titulos)
    pg.locator(".acordeon__item > summary").nth(3).click()
    cuerpo = txt(pg, ".acordeon__item:nth-child(4)")
    check("C3 La explicación del umbral usa el valor real del caso (42.0 % bajo 50.0 %)", "42.0 %" in cuerpo and "50.0 %" in cuerpo, cuerpo)
    pg.locator(".acordeon__item > summary").nth(2).click()
    check("C4 Se explica que P(spam) no es confianza", "no es una medida de confianza" in txt(pg, ".acordeon__item:nth-child(3)").lower())
    base_m = v.get("/metricas")  # el panel de diagnóstico de la Fase 2 ya pide /metricas una vez al abrir la pantalla
    check("C5 Abrir las demás explicaciones no pide /metricas (solo Limitaciones lo hace)", base_m == 1, base_m)
    pg.locator("#acordeon-limitaciones > summary").click()
    pg.wait_for_selector(".metricas-mini .tabla-datos", timeout=10000)
    m = txt(pg, ".metricas-mini")
    metricas_real = ctx.request.get(BASE + "/metricas").json()["test"]
    mc = metricas_real["matriz_confusion"]
    check("C6 Limitaciones: se enumeran, incluida la ausencia de categoría phishing", "phishing" in txt(pg, "#acordeon-limitaciones"))
    check("C7 Muestra las métricas REALES de prueba (de /metricas), no cifras inventadas",
          all(str(x) in m for x in (mc["tn"], mc["fp"], mc["fn"], mc["tp"])) and "95.3 %" in m, m)
    check("C8 Aclara que son cifras de prueba, no de validación", "conjunto de prueba" in m and "no de validación" in m)
    check("C9 Abrir Limitaciones pidió /metricas una sola vez más", v.get("/metricas") == base_m + 1, v.get("/metricas"))
    pg.locator("#acordeon-limitaciones > summary").click()
    pg.locator("#acordeon-limitaciones > summary").click()
    check("C10 Cerrar y reabrir no repite la petición a /metricas", v.get("/metricas") == base_m + 1, v.get("/metricas"))
    foto(pg, "C1_explicacion_limitaciones")
    br.close()

    br, ctx, pg, v = nueva(p)
    pg.route("**/metricas", lambda r: r.abort())
    flujo(pg, EML_HAM, resp(0.42, False))
    pg.locator("#acordeon-limitaciones > summary").click()
    pg.wait_for_selector(".metricas-mini .aviso", timeout=10000)
    check("C11 Si /metricas falla, se muestra un aviso claro sin romper la pantalla",
          "No se pudieron cargar las métricas" in txt(pg, ".metricas-mini") and pg.locator(".banner").count() == 1)
    br.close()

    # =====================================================================
    sec("D. Experiencia de usuario y estados")
    # =====================================================================
    br, ctx, pg, v = nueva(p)
    llamadas = flujo(pg, EML_SPAM, resp(0.9732))
    antes = v.n("/predecir")
    for nombre_tab in ("Texto extraído", "Enlaces", "Estructura", "Rasgos"):
        pg.get_by_role("tab", name=re.compile(nombre_tab)).click()
    check("D1 Cambiar de pestaña no hace nuevas solicitudes al backend", v.n("/predecir") == antes == 1 and v.n("/correo/extraer") == 1,
          (v.n("/predecir"), v.n("/correo/extraer")))
    pg.get_by_role("tab", name="Estructura").click()
    pg.get_by_role("link", name="Historial", exact=True).click()
    pg.wait_for_timeout(300)
    pg.get_by_role("link", name="Análisis", exact=True).click()
    pg.wait_for_selector(".banner")
    check("D2 Al ir a otra sección y volver, el resultado sigue ahí", txt(pg, ".banner__titulo").strip() == "SPAM" and pct_ui(pg) == "97.3 %")
    check("D3 …y se conserva la pestaña de evidencias elegida", pg.get_by_role("tab", name="Estructura").get_attribute("aria-selected") == "true")
    check("D4 …sin repetir solicitudes", v.n("/predecir") == 1 and v.n("/correo/extraer") == 1)
    check("D5 El indicador de pasos marca «Entender»", "Entender" in txt(pg, ".paso--actual"))
    pg.get_by_role("tab", name="Estructura").focus()
    pg.keyboard.press("ArrowRight")
    check("D6 Las pestañas se manejan con flechas (→ lleva a Rasgos)", pg.get_by_role("tab", name=re.compile("Rasgos")).get_attribute("aria-selected") == "true"
          and pg.evaluate("document.activeElement.id") == "tab-ev-rasgos")
    pg.keyboard.press("End")
    check("D7 Tecla Fin lleva a la última pestaña", pg.get_by_role("tab", name="Estructura").get_attribute("aria-selected") == "true")
    check("D8 Solo un panel visible a la vez", pg.locator("[role=tabpanel]:visible").count() == 1)
    pg.click("#btn-nuevo-analisis")
    pg.wait_for_selector(".zona")
    check("D9 El botón «Nuevo análisis» del banner vuelve a la carga y limpia el estado",
          pg.locator(".banner").count() == 0 and pg.locator("#btn-elegir").count() == 1)
    subir(pg, EML_HAM)
    analizar(pg)
    check("D10 Un segundo análisis funciona y usa una nueva (y única) solicitud", v.n("/predecir") == 2 and v.n("/correo/extraer") == 2)
    pg.click("#btn-otro")
    pg.wait_for_selector(".zona")
    check("D11 «Analizar otro correo» (panel lateral) también reinicia", pg.locator(".banner").count() == 0)
    pg.get_by_role("link", name="Métricas", exact=True).click()
    pg.get_by_role("link", name="Análisis", exact=True).click()
    check("D12 Sin consola con errores en todo el flujo", not v.errores, v.errores)
    br.close()

    # Carga y duplicados
    br, ctx, pg, v = nueva(p)
    llamadas = mockear(pg, resp(0.8), retraso=1.2)
    abrir(pg)
    subir(pg, EML_SPAM)
    pg.click("#btn-analizar")
    pg.wait_for_timeout(250)
    estado_carga = pg.locator("#btn-analizar").is_disabled() and pg.locator(".estado .spinner").count() == 1
    for _ in range(3):
        pg.locator("#btn-analizar").click(force=True, timeout=1500) if pg.locator("#btn-analizar").count() else None
    pg.wait_for_selector(".banner", timeout=20000)
    check("D13 Durante el análisis: botón bloqueado y estado de carga visible", estado_carga)
    check("D14 Clics repetidos durante la carga = una sola solicitud", len(llamadas) == 1, len(llamadas))
    br.close()

    # Error HTTP -> vuelve a la previa con mensaje
    br, ctx, pg, v = nueva(p)
    mockear(pg, {"detail": "Modelo no cargado"}, estado=503)
    abrir(pg)
    subir(pg, EML_SPAM)
    pg.click("#btn-analizar")
    pg.wait_for_selector(".aviso--error", timeout=10000)
    check("D15 Error 503: se muestra el motivo y se puede reintentar sin perder el correo",
          "Modelo no cargado" in txt(pg, ".aviso--error") and pg.locator("#btn-analizar").is_enabled() and pg.locator(".banner").count() == 0)
    br.close()

    br, ctx, pg, v = nueva(p)
    mockear(pg, {"foo": "bar"})
    abrir(pg)
    subir(pg, EML_SPAM)
    pg.click("#btn-analizar")
    pg.wait_for_selector(".aviso--error", timeout=10000)
    check("D16 Respuesta con formato inesperado: aviso claro y sin resultado a medias", "formato inesperado" in txt(pg, ".aviso--error") and pg.locator(".banner").count() == 0)
    br.close()

    # =====================================================================
    sec("E. Seguridad e integridad")
    # =====================================================================
    rasgos_hostiles = [rasgo("txt_x", "texto", 1.0, True, '<img src=x onerror="window.__xss=1"> <script>window.__xss=1</script>'),
                       rasgo("url_y", "url", 1.0, False, "<b>negrita</b>")]
    br, ctx, pg, v = nueva(p)
    flujo(pg, EML_MALICIOSO, resp(0.8, rasgos=rasgos_hostiles))
    check("E1 No se ejecuta ningún script del correo ni de la respuesta (window.__xss sin definir)", pg.evaluate("window.__xss === undefined"))
    for nombre_tab in ("Texto extraído", "Enlaces", "Estructura", "Rasgos"):
        pg.get_by_role("tab", name=re.compile(nombre_tab)).click()
    check("E2 No existen script, img, iframe, a, object ni embed dentro de la pantalla de resultados",
          pg.locator(".analisis script, .analisis img, .analisis iframe, .analisis a, .analisis object, .analisis embed").count() == 0)
    check("E3 El asunto con etiquetas se ve como texto literal", '<img src=x onerror="window.__xss=1">' in txt(pg, ".datos"), txt(pg, ".datos"))
    check("E4 El remitente con etiquetas se ve como texto literal", "<b>Banco</b>" in txt(pg, ".datos"))
    pg.get_by_role("tab", name=re.compile("Rasgos")).click()
    check("E5 Una descripción de rasgo con HTML (respuesta hostil) se muestra literal",
          '<img src=x onerror="window.__xss=1">' in txt(pg, "#panel-ev-rasgos") and "<b>negrita</b>" in pg.text_content("#panel-ev-rasgos") and pg.locator("#panel-ev-rasgos b").count() == 0)
    pg.get_by_role("tab", name="Texto extraído").click()
    pg.locator("#panel-ev-texto details summary").click()
    check("E6 El HTML hostil aparece solo como código de texto", "<script>window.__xss=1</script>" in txt(pg, "#panel-ev-texto details pre"))
    pg.get_by_role("tab", name=re.compile("Enlaces")).click()
    en = txt(pg, "#panel-ev-enlaces")
    check("E7 «javascript:» no aparece como enlace; los http aparecen como texto", "javascript:" not in en and "http://evil.example/x" in en, en)
    check("E8 No hubo peticiones a evil.example (nada se carga desde el correo)", not any("evil" in u for u in v.todas), [u for u in v.todas if "evil" in u])
    check("E9 Sin errores de consola", not v.errores, v.errores)
    br.close()

    src = {f: (Path(__file__).resolve().parents[3] / "js" / f).read_text(encoding="utf-8") for f in ("evidencias.js", "vistas/resultado.js")}
    for f, codigo in src.items():
        sin_comentarios = re.sub(r"//.*", "", codigo)
        check(f"E10 {f} no usa innerHTML, outerHTML, insertAdjacentHTML, document.write ni eval",
              not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function", sin_comentarios))

    # =====================================================================
    sec("F. Escritorio y móvil")
    # =====================================================================
    br, ctx, pg, v = nueva(p, 1366, 900)
    flujo(pg, EML_SPAM, resp(0.9732))
    caja = lambda sel: pg.locator(sel).bounding_box()  # noqa: E731
    check("F1 Escritorio: sin desbordamiento horizontal", not hay_desborde(pg))
    check("F2 Escritorio: dos columnas (el correo analizado queda a la derecha de la probabilidad)",
          caja(".resultado__lado")["x"] > caja(".resultado__prob")["x"] + caja(".resultado__prob")["width"] - 5)
    br.close()

    br, ctx, pg, v = nueva(p, 390, 844)
    flujo(pg, EML_SPAM, resp(0.9732))
    for nombre_tab in ("Texto extraído", "Enlaces", "Estructura", "Rasgos"):
        pg.get_by_role("tab", name=re.compile(nombre_tab)).click()
        check(f"F3 Móvil 390 px: sin desbordamiento horizontal en la pestaña «{nombre_tab}»", not hay_desborde(pg))
    ys = [pg.locator(s).bounding_box()["y"] for s in (".resultado__banner", ".resultado__prob", ".resultado__lado", ".resultado__evid", ".resultado__expl")]
    check("F4 Móvil: orden banner → probabilidad → correo analizado → evidencias → explicación", ys == sorted(ys), ys)
    check("F5 Móvil: las escalas de riesgo y cifras caben en pantalla", pg.evaluate(
        "[...document.querySelectorAll('.escala__tramo, .cifra, .pestana')].every(e => e.getBoundingClientRect().right <= innerWidth + 1)"))
    check("F6 Móvil: los botones se pueden tocar (alto ≥ 36 px)", pg.evaluate(
        "[...document.querySelectorAll('.analisis button')].filter(b => b.offsetParent).every(b => b.getBoundingClientRect().height >= 36)"))
    foto(pg, "F1_resultado_movil")
    br.close()

    br, ctx, pg, v = nueva(p, 360, 740)
    flujo(pg, EML_MALICIOSO, resp(0.8, rasgos=rasgos_hostiles))
    check("F7 Móvil 360 px con contenido largo y hostil: sin desbordamiento horizontal", not hay_desborde(pg))
    br.close()

    # =====================================================================
    sec("G. Con el modelo del servidor, sin interceptar (real)")
    # =====================================================================
    for nombre_caso, datos_caso in (("spam", EML_SPAM), ("legítimo", EML_HAM)):
        br, ctx, pg, v = nueva(p)
        abrir(pg)
        subir(pg, datos_caso)
        analizar(pg)
        ext = extraer_api(ctx, datos_caso)
        pred = ctx.request.post(BASE + "/predecir", data={"texto": ext["texto"], "html": ext["html"]}).json()
        check(f"G1 (real) correo {nombre_caso}: la clasificación mostrada coincide con /predecir",
              txt(pg, ".banner__titulo").strip() == ("SPAM" if pred["es_spam"] else "LEGÍTIMO"))
        m_ = re.search(r"(\d+\.\d) %", pct_ui(pg))
        check(f"G2 (real) correo {nombre_caso}: P(spam) mostrada coincide con /predecir",
              m_ and abs(float(m_.group(1)) - pred["probabilidad"] * 100) < 0.06, (pct_ui(pg), pred["probabilidad"]))
        check(f"G3 (real) correo {nombre_caso}: los rasgos activos mostrados son los de /predecir",
              sorted(pg.locator(".rasgo:not(.rasgo--inactivo) .rasgo__id").all_inner_texts()) ==
              sorted(r["rasgo"] for r in pred["rasgos_detectados"] if r["activo"]))
        check(f"G4 (real) correo {nombre_caso}: el nivel de riesgo corresponde al tramo de P(spam)",
              pg.evaluate("p => import('/static/js/vistas/resultado.js').then(m => m.nivelRiesgo(p).nombre)", pred["probabilidad"])
              in txt(pg, ".escala__tramo--activo"))
        check(f"G5 (real) correo {nombre_caso}: una sola solicitud a /predecir", v.n("/predecir") == 1)
        check(f"G6 (real) correo {nombre_caso}: sin errores de consola", not v.errores, v.errores)
        if nombre_caso == "spam":
            foto(pg, "G1_real_spam")
        br.close()

    fallos = [r for r in RESULTADOS if not r["ok"]]
    resumen = {"total": len(RESULTADOS), "superadas": len(RESULTADOS) - len(fallos), "fallidas": len(fallos), "resultados": RESULTADOS}
    Path(args.salida).write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nTOTAL: {resumen['superadas']}/{resumen['total']} pruebas superadas")
    sys.exit(1 if fallos else 0)
