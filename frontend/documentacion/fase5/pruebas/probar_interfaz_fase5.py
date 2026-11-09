"""Prueba de la INTERFAZ de la Fase 5 en un navegador real (Chromium, Playwright).

Dos modos:
  python probar_interfaz_fase5.py
      Arranca servidor_prueba_fase5.py (DETECTOR SIMULADO, sin FastAPI) con una base de datos temporal.
      Es lo que se puede ejecutar sin el modelo. NO prueba el modelo real.
  python probar_interfaz_fase5.py --servidor-real
      Arranca ejecutable\\run.py (API REAL + MODELO REAL) en un puerto libre con una base de datos TEMPORAL, ejecuta
      la misma prueba y lo apaga. Es el modo recomendado para validar con tu modelo (tarda ~1 min más por la carga).
  python probar_interfaz_fase5.py --url http://127.0.0.1:8000
      Prueba contra tu servidor REAL ya iniciado (python ejecutable\\run.py) con el MODELO REAL. Las comprobaciones no
      dependen de qué clasifica el modelo, solo de que la interfaz y la API sean coherentes. Escribe en el
      historial del servidor al que apuntas: arráncalo con una base de datos de prueba (set SG_DB=...) si no
      quieres mezclar datos. Las comprobaciones de conteo asumen una base de datos VACÍA al empezar.

Requiere:  pip install playwright   y   python -m playwright install chromium   (solo para esta prueba).
Resultados: resultados_interfaz_fase5.json (junto a este archivo).
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[3]
CORPUS = RAIZ / "backend" / "data"
RESULTADOS = []
FALLOS = []


def chk(nombre, cond, detalle=""):
    RESULTADOS.append({"prueba": nombre, "ok": bool(cond), "detalle": str(detalle)[:300]})
    print(("[OK]    " if cond else "[FALLO] ") + nombre + (f"  -> {detalle}" if (detalle and not cond) else ""), flush=True)
    if not cond:
        FALLOS.append(nombre)


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def arrancar_servidor(puerto, bd, real=False):
    """Servidor de prueba (detector SIMULADO) o, con real=True, el servidor REAL de SyntaxGuard con el modelo real."""
    if real:
        entorno = dict(os.environ, SG_DB=str(bd), SG_ABRIR_NAVEGADOR="0")
        p = subprocess.Popen([sys.executable, str(RAIZ / "ejecutable" / "run.py"), "--puerto", str(puerto), "--sin-navegador"],
                             env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        limite = 240  # segundos: la primera carga de spaCy/NLTK/modelo puede tardar
        for _ in range(limite * 2):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/salud", timeout=2) as r:
                    if json.loads(r.read()).get("modelo_cargado") is True:
                        return p
            except Exception:
                pass
            if p.poll() is not None:
                raise RuntimeError("run.py terminó antes de tiempo (revisa que el entorno virtual tenga las dependencias)")
            time.sleep(0.5)
        p.terminate()
        raise RuntimeError("el servidor real no cargó el modelo a tiempo")
    p = subprocess.Popen([sys.executable, str(AQUI / "servidor_prueba_fase5.py"), str(puerto), str(bd)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", puerto), 0.3).close()
            return p
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("el servidor de prueba no arrancó")


def preparar_archivos(base: Path):
    """Correos REALES del corpus del proyecto copiados con extensión .eml (el corpus original no tiene extensión)."""
    carpeta = base / "carpeta_correos"
    sub = carpeta / "subcarpeta"
    sub.mkdir(parents=True)
    spam = sorted((CORPUS / "spam").iterdir())[:16]
    ham = sorted((CORPUS / "easy_ham").iterdir())[:16]
    for i, p in enumerate(spam[:14] + ham[:14]):
        (carpeta / f"{i:02d}_{'spam' if i < 14 else 'ham'}_{p.name[:6]}.eml").write_bytes(p.read_bytes())
    for i, p in enumerate([spam[14], ham[14]]):
        (sub / f"sub_{i}_{p.name[:6]}.eml").write_bytes(p.read_bytes())
    (carpeta / "nota.txt").write_bytes(b"Subject: Offer\n\nClick now to claim your free prize money!")
    (carpeta / "vacio.eml").write_bytes(b"")
    (carpeta / "binario.eml").write_bytes(bytes(range(256)) * 4)
    (carpeta / "imagen.jpg").write_bytes(b"\xff\xd8\xff\xe0 no es un correo")
    return carpeta  # 30 correos reales + nota.txt + vacio + binario = 33 por extensión; el .jpg se ignora


def num(texto):
    return int(re.sub(r"[^\d]", "", texto))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="URL de un servidor ya iniciado (modo real)")
    ap.add_argument("--servidor-real", action="store_true", help="arranca ejecutable/run.py con el modelo real y una BD temporal")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="sg_ui_"))
    carpeta = preparar_archivos(tmp)
    propio = args.url is None
    real = bool(args.servidor_real) and propio
    puerto = puerto_libre() if propio else None
    bd = tmp / "ui.db"
    srv = arrancar_servidor(puerto, bd, real) if propio else None
    base = args.url.rstrip("/") if args.url else f"http://127.0.0.1:{puerto}"
    errores_js, respuestas_malas = [], []
    hoy = date.today().isoformat()

    try:
        with sync_playwright() as pw:
            nav = pw.chromium.launch()
            ctx = nav.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
            page = ctx.new_page()
            page.set_default_timeout(20000)
            page.on("pageerror", lambda e: errores_js.append(f"pageerror: {e}"))
            page.on("console", lambda m: errores_js.append(f"console.{m.type}: {m.text}") if (m.type == "error" and "favicon" not in m.text and "404" not in m.text) else None)
            page.on("response", lambda r: respuestas_malas.append(f"{r.status} {r.request.method} {r.url}") if (r.status >= 400 and "favicon" not in r.url) else None)

            def api(ruta):
                return ctx.request.get(base + ruta)

            # ---------- 1. Abrir SyntaxGuard ----------
            page.goto(base + "/")
            page.wait_for_selector(".nav__item")
            etiquetas = [t.strip() for t in page.locator(".nav__item").all_inner_texts()]
            chk("1. El menú lateral tiene 6 secciones, incluida «Análisis masivo»",
                etiquetas == ["Análisis", "Análisis masivo", "Historial", "Métricas", "Retroalimentación", "Acerca de"], etiquetas)
            page.wait_for_function("document.getElementById('chip-api') && document.getElementById('chip-api').textContent.includes('Modelo cargado')")
            chk("1. El indicador de la API muestra «Modelo cargado»", True)
            chk("1. La sección Análisis está activa al abrir", page.locator('.nav__item[aria-current="page"]').inner_text().strip() == "Análisis")

            # ---------- 2-3. Análisis individual y evidencias ----------
            page.click("#tab-pegar")
            page.fill("#texto-pegado", "From: Promo <promo@example-offers.test>\nTo: yo@example.test\nSubject: Claim your free prize\nDate: Thu, 05 Nov 2026 10:00:00 -0600\n\n"
                      "Congratulations winner! Click here to claim your free cash offer now http://bit.ly/abc123/secreto?token=XYZ")
            page.click("#btn-extraer-texto")
            page.wait_for_selector("#btn-analizar")
            chk("2. La vista previa muestra el asunto extraído", "Claim your free prize" in page.inner_text(".contenido"))
            page.click("#btn-analizar")
            page.wait_for_selector("#btn-ver-historial")
            banner = page.inner_text(".banner")
            chk("3. Resultado: muestra SPAM o LEGÍTIMO", ("SPAM" in banner) or ("LEGÍTIMO" in banner), banner[:80])
            chk("3. Resultado: probabilidad con punto decimal (es-MX) y «%»", re.search(r"\d+\.\d\s?%", page.inner_text(".contenido")) is not None)
            chk("3. Resultado: chip «Guardado» en el historial", page.inner_text("#chip-guardado").strip() == "Guardado")
            visibles = []
            for clave in ("rasgos", "texto", "enlaces", "estructura"):
                page.click(f"#tab-ev-{clave}")
                visibles.append(page.is_visible(f"#panel-ev-{clave}") and not any(page.is_visible(f"#panel-ev-{o}") for o in ("rasgos", "texto", "enlaces", "estructura") if o != clave))
            chk("3. Evidencias: las 4 pestañas (rasgos, texto, enlaces, estructura) abren su panel", all(visibles), visibles)
            chk("3. Evidencias: el enlace acortador se muestra en la pestaña Enlaces", (page.click("#tab-ev-enlaces") or True) and "bit.ly" in page.inner_text("#panel-ev-enlaces"))
            page.click("#btn-ver-historial")
            page.wait_for_selector("#tit-detalle")
            texto_det = page.inner_text(".contenido")
            chk("3. El detalle guardado muestra el dominio del enlace", "bit.ly" in texto_det)
            chk("3. D1: el detalle NO muestra la URL completa ni el cuerpo",
                "token=XYZ" not in texto_det and "abc123" not in texto_det and "Congratulations winner" not in texto_det)
            page.go_back()
            page.wait_for_selector("#btn-ver-historial")
            chk("10. Al volver a Análisis se conserva el resultado (estado entre secciones)", True)

            # ---------- 4-5. Análisis masivo ----------
            page.click('.nav__item[data-ruta="masivo"]')
            page.wait_for_selector("#zona-masivo")
            lista_inicial = sorted(carpeta.glob("0[0-2]_*.eml")) + [carpeta / "imagen.jpg"]
            page.set_input_files("#entrada-masivo-archivos", [str(p) for p in lista_inicial])
            page.wait_for_selector("#tabla-masivo")
            chk("4. Archivos agregados: se listan los 3 .eml y se ignora el .jpg",
                page.locator("#tabla-masivo tbody tr").count() == 3 and "ignoraron" in page.inner_text(".aviso"), page.inner_text(".contenido")[:200])
            primera_fila = page.locator("#tabla-masivo tbody tr").first.inner_text()
            chk("4. Cada fila muestra nombre y tamaño", re.search(r"\d+(\.\d+)?\s?(KB|MB|B)", primera_fila) is not None, primera_fila)
            page.set_input_files("#entrada-masivo-archivos", [str(p) for p in lista_inicial[:3]])
            page.wait_for_function("document.querySelector('.aviso') && document.querySelector('.aviso').textContent.includes('ya estaban')")
            chk("4. Los archivos repetidos no se duplican", page.locator("#tabla-masivo tbody tr").count() == 3)
            nombre_quitado = page.locator("#tabla-masivo tbody tr").first.locator(".celda-nombre__texto").inner_text()
            page.locator("#tabla-masivo tbody tr").first.get_by_role("button", name=re.compile("Quitar")).click()
            page.wait_for_function("document.querySelectorAll('#tabla-masivo tbody tr').length === 2")
            chk("4. «Quitar» elimina un archivo antes de iniciar", nombre_quitado not in page.inner_text("#tabla-masivo"))
            page.click("#btn-vaciar-masivo")
            page.wait_for_function("document.querySelector('#tabla-masivo') === null")
            chk("4. «Vaciar lista» deja la lista vacía", page.locator("#btn-iniciar-masivo").is_disabled())
            page.evaluate("""() => { const dt = new DataTransfer();
                dt.items.add(new File(['Subject: hi\\n\\nClick free offer'], 'arrastrado.eml', {type: 'message/rfc822'}));
                document.getElementById('zona-masivo').dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true})); }""")
            page.wait_for_selector("#tabla-masivo")
            chk("4. Arrastrar y soltar agrega archivos", page.locator("#tabla-masivo tbody tr").count() == 1)
            page.click("#btn-vaciar-masivo")

            page.set_input_files("#entrada-masivo-carpeta", str(carpeta))
            page.wait_for_function("document.querySelectorAll('#tabla-masivo tbody tr').length > 0")
            filas = page.locator("#tabla-masivo tbody tr").count()
            chk("4. Carpeta completa: 33 archivos .eml/.txt (con subcarpeta) y el .jpg ignorado", filas == 33, filas)
            rutas = page.locator("#tabla-masivo .celda-nombre__texto").evaluate_all("els => els.map(e => e.title)")
            chk("4. La carpeta incluyó la subcarpeta", any("subcarpeta" in (t or "") for t in rutas), rutas[:3])

            page.click("#btn-iniciar-masivo")
            page.wait_for_selector("#texto-progreso")
            chk("5. Se muestra el progreso del análisis", "de 33" in page.inner_text("#texto-progreso"))
            page.click('.nav__item[data-ruta="acerca"]')
            page.wait_for_selector("#acerca")
            page.click('.nav__item[data-ruta="masivo"]')
            page.wait_for_selector("#btn-nuevo-masivo", timeout=180000)
            chk("5. El análisis continúa/termina al cambiar de sección y se conserva el estado", page.locator("#tabla-masivo tbody tr").count() == 33)

            cifras = {d.locator("dt").inner_text(): d.locator("dd").inner_text() for d in page.locator("#resumen-masivo .cifra").all()}
            procesados, spam, leg, err = num(cifras["Correos procesados"]), num(cifras["SPAM"]), num(cifras["LEGÍTIMOS"]), num(cifras["Errores"])
            chk("5. Resumen: 33 procesados = SPAM + LEGÍTIMOS + errores", procesados == 33 and spam + leg + err == 33, cifras)
            nombres_err = [t for t in page.locator('#tabla-masivo tbody tr[data-estado="error"] .celda-nombre__texto').all_inner_texts()]
            chk("5. Resumen: los errores individuales (vacío y binario) no detienen el lote", err >= 2 and {"vacio.eml", "binario.eml"} <= set(nombres_err) and spam + leg == 33 - err, (cifras, nombres_err))
            chk("5. Resumen: porcentajes coherentes con los conteos",
                abs(float(re.search(r"[\d.]+", cifras["% SPAM"]).group()) - 100 * spam / (spam + leg)) < 0.06, cifras)
            filas_err = page.locator('#tabla-masivo tbody tr[data-estado="error"]')
            chk("5. Los errores se identifican por archivo con su motivo",
                filas_err.count() == err and all(len(t) > 10 for t in filas_err.locator(".celda-nombre__error").all_inner_texts()))
            primera = page.locator('#tabla-masivo tbody tr[data-estado="ok"]').first.inner_text()
            chk("5. Cada resultado individual muestra SPAM/LEGÍTIMO y P(spam)",
                re.search(r"(SPAM|LEGÍTIMO)", primera) and re.search(r"\d+\.\d\s?%", primera), primera)

            h = api("/historial?tipo=masivo&por_pagina=100").json()
            chk("5. La API tiene los 33 registros del lote guardados", h["total"] == 33, h["total"])
            lote_id = h["items"][0]["lote_id"]
            s = api(f"/lotes/{lote_id}").json()
            chk("5. GET /lotes/{id} coincide con el resumen de la pantalla",
                (s["spam"], s["legitimos"], s["errores"], s["total_procesados"]) == (spam, leg, err, 33), s)

            page.select_option("#filtro-masivo", "spam")
            chk("5. Filtro SPAM", page.locator("#tabla-masivo tbody tr").count() == spam)
            page.select_option("#filtro-masivo", "legitimo")
            chk("5. Filtro LEGÍTIMO", page.locator("#tabla-masivo tbody tr").count() == leg)
            page.select_option("#filtro-masivo", "error")
            chk("5. Filtro Con error", page.locator("#tabla-masivo tbody tr").count() == err)
            page.select_option("#filtro-masivo", "todos")
            page.fill("#buscar-masivo", "vacio")
            chk("5. Búsqueda por nombre", page.locator("#tabla-masivo tbody tr").count() == 1)
            asunto = next(i["asunto"] for i in h["items"] if i["asunto"])
            page.fill("#buscar-masivo", asunto[:12])
            chk("5. Búsqueda por asunto", page.locator("#tabla-masivo tbody tr").count() >= 1)
            page.fill("#buscar-masivo", "zzzz-no-existe")
            chk("5. Búsqueda sin coincidencias muestra aviso", "Ningún archivo coincide" in page.inner_text(".contenido"))
            page.fill("#buscar-masivo", "")
            page.locator('#tabla-masivo tbody tr[data-estado="ok"]').first.get_by_role("button", name=re.compile("Ver detalles")).click()
            page.wait_for_selector("dialog[open]")
            det = page.inner_text("dialog[open]")
            chk("5. Detalle individual (modal) con P(spam), rasgos y dominios", all(t in det for t in ("P(spam)", "Rasgos detectados", "Dominios de los enlaces")), det[:150])
            page.keyboard.press("Escape")
            chk("5. El modal se cierra con Esc", page.locator("dialog[open]").count() == 0)
            href = page.get_attribute("#btn-csv-lote", "href")
            r = ctx.request.get(base + href if href.startswith("/") else href)
            cuerpo = r.body()
            lineas = [x for x in cuerpo.decode("utf-8-sig").splitlines() if x.strip()]
            chk("5. Exportar CSV del lote: 200, BOM UTF-8 y 33 filas + encabezado", r.status == 200 and cuerpo.startswith(b"\xef\xbb\xbf") and len(lineas) == 34, (r.status, len(lineas)))
            with page.expect_download() as d:
                page.click("#btn-csv-lote")
            chk("5. El botón de CSV inicia una descarga real", d.value.suggested_filename.endswith(".csv"), d.value.suggested_filename)

            # ---------- cancelar un lote ----------
            page.click("#btn-nuevo-masivo")
            page.set_input_files("#entrada-masivo-carpeta", str(carpeta))
            page.wait_for_function("document.querySelectorAll('#tabla-masivo tbody tr').length === 33")

            def lento(route):
                time.sleep(0.35)
                route.continue_()
            page.route("**/analisis/archivo", lento)
            page.click("#btn-iniciar-masivo")
            page.wait_for_function("(() => { const t = document.getElementById('texto-progreso'); return t && /^[1-9]\\d* de 33/.test(t.textContent.trim()); })()")
            page.click("#btn-cancelar-masivo")
            page.wait_for_selector("#btn-nuevo-masivo", timeout=60000)
            page.unroute("**/analisis/archivo")
            chk("5. Cancelar: aparece el aviso de cancelación", "cancelado" in page.inner_text(".aviso").lower())
            cif2 = {d.locator("dt").inner_text(): num(d.locator("dd").inner_text()) for d in page.locator("#resumen-masivo .cifra").all()
                    if d.locator("dt").inner_text() in ("Correos procesados", "SPAM", "LEGÍTIMOS", "Errores")}
            sin = page.locator('#tabla-masivo tbody tr[data-estado="cancelado"]').count()
            chk("5. Cancelar: quedan archivos sin procesar y los procesados suman lo analizado", 0 < cif2["Correos procesados"] < 33 and sin == 33 - cif2["Correos procesados"], (cif2, sin))
            h2 = api("/historial?tipo=masivo&por_pagina=100").json()
            chk("5. Cancelar: lo mostrado coincide con lo guardado (sin registros fantasma)", h2["total"] == 33 + cif2["Correos procesados"], (h2["total"], cif2))

            # ---------- 6. Historial ----------
            page.click('.nav__item[data-ruta="historial"]')
            page.wait_for_selector("#tabla-historial")
            total_api = api("/historial").json()["total"]

            def cuenta():
                return int(re.search(r"([\d,]+) análisis", page.inner_text("#hist-cuenta")).group(1).replace(",", ""))

            def esperar_total(n):
                for _ in range(80):
                    if page.locator("#hist-cuenta").count() and cuenta() == n:
                        return True
                    page.wait_for_timeout(150)
                return False
            chk("6. El historial muestra los registros reales (coincide con la API)", cuenta() == total_api, (cuenta(), total_api))
            chk("6. Paginación: 25 por página", page.locator("#tabla-historial tbody tr").count() == 25 and "página 1 de" in page.inner_text("#hist-cuenta"))
            page.click("#hist-siguiente")
            page.wait_for_function("document.getElementById('hist-cuenta').textContent.includes('página 2')")
            chk("6. Siguiente página muestra el resto", page.locator("#tabla-historial tbody tr").count() == min(25, total_api - 25))
            page.click("#hist-anterior")
            page.wait_for_function("document.getElementById('hist-cuenta').textContent.includes('página 1')")

            page.select_option("#hist-clasif", "spam")
            n_spam = api("/historial?clasificacion=spam&por_pagina=1").json()["total"]
            chk("6. Filtro SPAM coincide con la API", esperar_total(n_spam), n_spam)
            chk("6. Filtro SPAM: todas las filas son SPAM", all(t.strip() == "SPAM" for t in page.locator("#tabla-historial tbody tr td:nth-child(5)").all_inner_texts()))
            page.select_option("#hist-clasif", "legitimo")
            n_leg = api("/historial?clasificacion=legitimo&por_pagina=1").json()["total"]
            chk("6. Filtro LEGÍTIMO coincide con la API", esperar_total(n_leg), n_leg)
            page.select_option("#hist-clasif", "error")
            n_err = api("/historial?clasificacion=error&por_pagina=1").json()["total"]
            chk("6. Filtro Con error coincide con la API", esperar_total(n_err), n_err)
            page.click("#btn-limpiar-filtros")
            chk("6. «Limpiar filtros» restablece", esperar_total(total_api) and page.input_value("#hist-clasif") == "")
            page.select_option("#hist-tipo", "individual")
            chk("6. Filtro por tipo individual", esperar_total(api("/historial?tipo=individual&por_pagina=1").json()["total"]))
            page.select_option("#hist-tipo", "")
            page.fill("#hist-buscar", "vacio")
            chk("6. Búsqueda por nombre", esperar_total(api("/historial?q=vacio&por_pagina=1").json()["total"]))
            page.fill("#hist-buscar", "Claim your free")
            chk("6. Búsqueda por asunto", esperar_total(1))
            page.fill("#hist-buscar", "")
            esperar_total(total_api)
            page.fill("#hist-desde", "2999-01-01")
            page.wait_for_selector("#tabla-historial", state="detached")
            chk("6. Filtro por fecha sin resultados muestra estado vacío", "Ningún análisis coincide" in page.inner_text(".contenido"))
            page.fill("#hist-desde", hoy)
            page.fill("#hist-hasta", hoy)
            chk("6. Filtro por fecha (hoy) muestra los de hoy", esperar_total(total_api))
            page.click("#btn-limpiar-filtros")
            esperar_total(total_api)
            href = page.get_attribute("#btn-exportar-csv", "href")
            r = ctx.request.get(base + href if href.startswith("/") else href)
            chk("6. Exportar CSV del historial completo", r.status == 200 and len([x for x in r.body().decode("utf-8-sig").splitlines() if x.strip()]) == total_api + 1)

            page.fill("#hist-buscar", "vacio")
            esperar_total(api("/historial?q=vacio&por_pagina=1").json()["total"])
            antes = api("/historial").json()["total"]
            page.locator("#tabla-historial tbody tr").first.get_by_role("button", name=re.compile("Eliminar")).click()
            page.wait_for_selector("dialog[open]")
            page.click("#btn-confirmar")
            page.wait_for_function("!document.querySelector('dialog[open]')")
            page.wait_for_timeout(500)
            chk("6. Eliminar un registro (con confirmación) lo borra de la base", api("/historial").json()["total"] == antes - 1)
            page.fill("#hist-buscar", "")
            esperar_total(antes - 1)
            page.locator("#tabla-historial tbody tr .marca-fila").nth(0).check()
            page.locator("#tabla-historial tbody tr .marca-fila").nth(1).check()
            page.click("#btn-eliminar-seleccion")
            page.wait_for_selector("dialog[open]")
            page.click("#btn-confirmar")
            page.wait_for_timeout(700)
            chk("6. Eliminar varios registros seleccionados", api("/historial").json()["total"] == antes - 3)

            # ---------- 7. Abrir un análisis anterior ----------
            ids = [i["id"] for i in api("/historial?clasificacion=spam&por_pagina=1").json()["items"]]
            id_prueba = ids[0] if ids else api("/historial?por_pagina=1").json()["items"][0]["id"]
            page.goto(f"{base}/#/historial/{id_prueba}")
            page.wait_for_selector("#tit-detalle")
            chk("7. Abrir un análisis anterior por su dirección (#/historial/<id>)", f"Análisis n.º {id_prueba}" in page.inner_text("#tit-detalle"))
            page.goto(base + "/#/historial/99999")
            page.wait_for_selector(".aviso--error")
            chk("7. Un análisis inexistente muestra un mensaje claro", "no existe" in page.inner_text(".contenido"))

            # ---------- 8. Métricas ----------
            page.click('.nav__item[data-ruta="metricas"]')
            page.wait_for_selector("#cifras-modelo")
            txt = page.inner_text("#cifras-modelo")
            chk("8. Rendimiento del modelo: 0.9533 / 0.9652 / 0.9174 / 0.9407 (de metricas.json)", all(v in txt for v in ("0.9533", "0.9652", "0.9174", "0.9407")), txt)
            celdas = [t.split("\n")[0].strip() for t in page.locator("#matriz-confusion .matriz__celda").all_inner_texts()]
            chk("8. Matriz de confusión: VN 175, FP 4, FN 10, VP 111", celdas == ["175", "4", "10", "111"], celdas)
            page.click("#conj-validacion")
            chk("8. Conjunto de validación etiquetado y distinto", "0.9600" in page.inner_text("#cifras-modelo"))
            page.click("#conj-test")
            page.click("#pest-uso")
            page.wait_for_selector("#cifras-uso")
            uso = api("/estadisticas/uso").json()
            tuso = page.inner_text("#cifras-uso").replace(",", "")
            chk("8. Estadísticas de uso coinciden con los registros reales", str(uso["analizados"]) in tuso and str(uso["spam"]) in tuso, (uso["analizados"], tuso[:120]))
            chk("8. Las estadísticas de uso no mezclan métricas del modelo", "0.9533" not in page.inner_text("#panel-metricas"))
            chk("8. Gráfico por día y distribución presentes", page.locator("#grafico-dias").count() == 1 and page.locator(".apilada").count() == 1)

            # ---------- 9. Retroalimentación ----------
            page.goto(f"{base}/#/historial/{id_prueba}")
            page.wait_for_selector("#btn-retro-detalle")
            page.click("#btn-retro-detalle")
            page.wait_for_selector("#retro-resumen")
            chk("9. Se llega con el análisis ya seleccionado", f"#/retroalimentacion?analisis={id_prueba}" in page.url)
            chk("9. Guardar está desactivado hasta elegir una opinión", page.is_disabled("#btn-guardar-retro"))
            page.check("#voto-no")
            page.fill("#retro-comentario", "No lo considero spam")
            page.click("#btn-guardar-retro")
            page.wait_for_selector("#lista-previas li")
            t1 = page.inner_text("#lista-previas")
            chk("9. La retroalimentación se guarda y aparece con fecha y hora", "En desacuerdo" in t1 and "Enviada el" in t1 and "No lo considero spam" in t1, t1[:160])
            page.check("#voto-si")
            page.click("#btn-guardar-retro")
            page.wait_for_function("document.querySelectorAll('#lista-previas li').length >= 2")
            page.check("#retro-solo")
            page.wait_for_function("document.querySelector('#lista-previas li .chip--neutro') !== null")
            primero = page.locator("#lista-previas li").first.inner_text()
            chk("9. Varias entradas por análisis; la más reciente se marca primero", "De acuerdo" in primero and "Más reciente" in primero, primero)
            a1 = api(f"/historial/{id_prueba}").json()
            chk("9. En la base: 2 retroalimentaciones ligadas al análisis y la última es «de acuerdo»", a1["retro_total"] == 2 and a1["retro_ultima"]["de_acuerdo"] is True)
            page.wait_for_timeout(600)  # deja terminar el repintado de la lista tras guardar
            otro = page.locator("#retro-lista .sel-item").evaluate_all("(els, id) => els.find(e => e.dataset.id !== String(id))?.dataset.id || null", id_prueba)
            assert otro is not None, "No hay otro análisis distinto para probar la selección"
            page.locator(f'#retro-lista .sel-item[data-id="{otro}"]').click()
            page.wait_for_function("id => { const s = document.querySelector('#retro-lista .sel-item[aria-pressed=true]'); return s && s.dataset.id === id && document.getElementById('retro-resumen'); }", arg=otro)
            chk("9. Se puede elegir otro análisis de la lista (queda seleccionado y se muestra su resumen)", otro != str(id_prueba) and page.locator("#retro-resumen").count() == 1, otro)
            page.fill("#retro-buscar", "zzzz-no-existe")
            page.wait_for_selector("#retro-vacio")
            chk("9. Buscar en la lista de análisis funciona", True)

            # ---------- 10. Acerca de ----------
            page.click('.nav__item[data-ruta="acerca"]')
            page.wait_for_selector("#acerca")
            ac = page.inner_text("#acerca")
            chk("10. Acerca de: explica qué es, cómo funciona, tecnologías, limitaciones y definiciones",
                all(t in ac for t in ("¿Qué es SyntaxGuard?", "Random Forest", "análisis sintáctico-estructural", "Tecnologías", "Limitaciones", "SPAM y LEGÍTIMO")))
            chk("10. Acerca de: no inventa una categoría de phishing", "no clasifica el phishing" in ac)

            ok_all = True
            for ruta in ("analisis", "masivo", "historial", "metricas", "retroalimentacion", "acerca"):
                page.goto(f"{base}/#/{ruta}")
                page.wait_for_timeout(500)
                if "En construcción" in page.inner_text("body"):
                    ok_all = False
            chk("Todas las secciones están implementadas (ninguna «En construcción»)", ok_all)

            # ---------- Persistencia tras reiniciar el servidor (solo servidor propio) ----------
            if propio:
                antes = api("/historial").json()["total"]
                srv.terminate()
                srv.wait(timeout=10)
                srv = arrancar_servidor(puerto, bd, real)
                page.goto(base + "/#/historial")
                page.reload()
                page.wait_for_selector("#tabla-historial")
                chk("Persistencia: tras reiniciar el servidor el historial sigue igual", cuenta() == antes, (cuenta(), antes))
                chk("Persistencia: la retroalimentación sigue ligada al análisis", api(f"/historial/{id_prueba}").json()["retro_total"] == 2)

            # ---------- Responsivo ----------
            for ancho, alto, nombre in ((390, 844, "móvil 390 px"), (768, 1024, "tableta 768 px"), (1280, 900, "escritorio 1280 px")):
                page.set_viewport_size({"width": ancho, "height": alto})
                desbordes = []
                for ruta in ("analisis", "masivo", "historial", f"historial/{id_prueba}", "metricas", f"retroalimentacion?analisis={id_prueba}", "acerca"):
                    page.goto(f"{base}/#/{ruta}")
                    page.wait_for_timeout(500)
                    ancho_doc = page.evaluate("document.documentElement.scrollWidth")
                    if ancho_doc > ancho + 1:
                        desbordes.append((ruta, ancho_doc))
                chk(f"Responsivo {nombre}: ninguna sección desborda horizontalmente", not desbordes, desbordes)
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(base + "/#/masivo")
            page.wait_for_selector("#btn-elegir-archivos")
            chk("Responsivo móvil: el menú es accesible y «Elegir archivos» visible", page.locator(".nav__item").count() == 6 and page.is_visible("#btn-elegir-archivos"))

            chk("Sin errores de JavaScript ni de consola en todo el recorrido", not errores_js, errores_js[:5])
            inesperadas = [x for x in respuestas_malas if "/historial/99999" not in x]
            chk("Sin respuestas HTTP de error inesperadas (4xx/5xx) durante el recorrido", not inesperadas, inesperadas[:6])
            nav.close()
    finally:
        if srv:
            srv.terminate()
        shutil.rmtree(tmp, ignore_errors=True)

    (AQUI / "resultados_interfaz_fase5.json").write_text(json.dumps({
        "modo": ("SERVIDOR REAL con MODELO REAL (ejecutable/run.py)" if real else "servidor de prueba con detector SIMULADO") if propio else f"servidor ya iniciado: {args.url}",
        "total": len(RESULTADOS), "fallos": len(FALLOS), "resultados": RESULTADOS}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(RESULTADOS) - len(FALLOS)}/{len(RESULTADOS)} comprobaciones superadas" + (" -- FALLARON: " + "; ".join(FALLOS) if FALLOS else ""), flush=True)
    return 1 if FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
