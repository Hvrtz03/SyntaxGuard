"""Pruebas de la interfaz con un navegador real (Chromium/Playwright) contra el servidor en ejecución.
Uso: python probar_interfaz.py <url_base> <carpeta_capturas> <salida_resultados.json>
"""
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/")
CAPT = Path(sys.argv[2]); CAPT.mkdir(parents=True, exist_ok=True)
SALIDA = Path(sys.argv[3])

RUTAS = [
    ("analisis", "Analizar correo", "Análisis"),
    ("historial", "Historial de análisis", "Historial"),
    ("metricas", "Métricas del modelo", "Métricas"),
    ("retroalimentacion", "Retroalimentación", "Retroalimentación"),
    ("acerca", "Acerca de SyntaxGuard", "Acerca de"),
]
resultados = []


def check(nombre, ok, detalle=""):
    resultados.append({"prueba": nombre, "ok": bool(ok), "detalle": detalle})
    print(("[OK]   " if ok else "[FALLA] ") + nombre + (f" — {detalle}" if detalle else ""))


def nuevo_contexto(p, movil):
    br = p.chromium.launch()
    if movil:
        ctx = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="es-MX")
    else:
        ctx = br.new_context(viewport={"width": 1366, "height": 860}, locale="es-MX")
    page = ctx.new_page()
    errores = []
    page.on("console", lambda m: errores.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    page.on("pageerror", lambda e: errores.append(f"pageerror: {e}"))
    page.on("requestfailed", lambda r: errores.append(f"requestfailed: {r.url}"))
    return br, ctx, page, errores


def recorrer(p, movil):
    tag = "movil" if movil else "escritorio"
    br, ctx, page, errores = nuevo_contexto(p, movil)
    respuestas = []
    page.on("response", lambda r: respuestas.append((r.url, r.status)))

    page.goto(BASE + "/", wait_until="networkidle")
    check(f"[{tag}] La raíz redirige a #/analisis", page.evaluate("location.hash") == "#/analisis", page.evaluate("location.hash"))
    page.wait_for_selector("#chip-api.chip--ok", timeout=8000)
    check(f"[{tag}] Chip de la API indica modelo cargado", "Modelo cargado" in page.inner_text("#chip-api"), page.inner_text("#chip-api"))
    check(f"[{tag}] Pie muestra versión de la API", "API v1.0.0" in page.inner_text("#pie-version"), page.inner_text("#pie-version"))
    check(f"[{tag}] 5 elementos de menú", page.locator(".nav__item").count() == 5, str(page.locator(".nav__item").count()))

    for ruta, titulo, etiqueta in RUTAS:
        page.locator(f'.nav__item[data-ruta="{ruta}"]').click()
        page.wait_for_function(f"document.getElementById('titulo-pagina')?.textContent === {json.dumps(titulo)}", timeout=8000)
        check(f"[{tag}] Navega a {ruta}: título '{titulo}'", True)
        check(f"[{tag}] {ruta}: ítem activo marcado (aria-current)",
              page.locator(".nav__item[aria-current='page']").inner_text().strip() == etiqueta)
        check(f"[{tag}] {ruta}: <title> del documento", page.title() == f"{titulo} · SyntaxGuard", page.title())
        check(f"[{tag}] {ruta}: hay indicador de pasos o espacio", page.locator(".stepper").count() in (0, 1))
        desborde = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check(f"[{tag}] {ruta}: sin desplazamiento horizontal de la página", desborde <= 1, f"desborde={desborde}px")
        if ruta == "analisis":
            page.wait_for_function("document.querySelectorAll('.verif__fila .chip--ok').length >= 2", timeout=8000)
            filas = page.locator(".verif__fila").all_inner_texts()
            check(f"[{tag}] Análisis: /salud y /metricas conectados", sum("Conectado" in f for f in filas) == 2, " | ".join(x.replace("\n", " ") for x in filas))
            txt = " ".join(filas)
            check(f"[{tag}] Análisis: muestra 2.000 filas y F1 0,9407 reales de metricas.json", "2.000" in txt and "0,9407" in txt)
            page.screenshot(path=str(CAPT / f"{tag}_analisis_antes_de_probar.png"), full_page=True)
            page.locator("button", has_text="Probar /predecir").click()
            page.wait_for_function("[...document.querySelectorAll('.verif__fila')].some(f => f.textContent.includes('POST') && f.textContent.includes('Conectado'))", timeout=15000)
            fila = [f for f in page.locator(".verif__fila").all_inner_texts() if "POST" in f][0].replace("\n", " ")
            check(f"[{tag}] Análisis: /predecir responde desde la interfaz", "es_spam: sí" in fila, fila)
        page.screenshot(path=str(CAPT / f"{tag}_{ruta}.png"), full_page=True)

    # Navegación por hash directo y ruta inexistente
    page.goto(BASE + "/#/metricas", wait_until="networkidle")
    page.wait_for_function("document.getElementById('titulo-pagina')?.textContent === 'Métricas del modelo'", timeout=8000)
    check(f"[{tag}] Enlace directo #/metricas abre Métricas", True)
    page.goto(BASE + "/#/no-existe", wait_until="networkidle")
    page.wait_for_function("location.hash === '#/analisis'", timeout=8000)
    check(f"[{tag}] Ruta inexistente vuelve a #/analisis", True)
    page.go_back(); page.go_forward()
    check(f"[{tag}] Botones atrás/adelante no rompen la app", page.locator("#titulo-pagina").count() == 1)

    check(f"[{tag}] Sin errores/avisos de consola ni peticiones fallidas", not errores, "; ".join(errores)[:500])
    malas = [(u, s) for u, s in respuestas if s >= 400]
    check(f"[{tag}] Ninguna respuesta HTTP >= 400", not malas, str(malas))

    # Estado de error: API caída (se bloquean las llamadas a la API, sin tocar el servidor)
    br.close()
    br, ctx, page, _ = nuevo_contexto(p, movil)
    ctx.route("**/salud", lambda r: r.abort())
    ctx.route("**/openapi.json", lambda r: r.abort())
    ctx.route("**/metricas", lambda r: r.abort())
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_selector("#chip-api.chip--error", timeout=8000)
    check(f"[{tag}] Con la API caída el chip dice 'API sin conexión'", "API sin conexión" in page.inner_text("#chip-api"), page.inner_text("#chip-api"))
    check(f"[{tag}] Con la API caída el pie dice versión desconocida", "desconocida" in page.inner_text("#pie-version"))
    page.wait_for_function("document.querySelectorAll('.verif__fila .chip--error').length >= 2", timeout=8000)
    check(f"[{tag}] Con la API caída la vista Análisis muestra errores legibles", True)
    page.screenshot(path=str(CAPT / f"{tag}_api_caida.png"), full_page=True)
    br.close()


with sync_playwright() as p:
    recorrer(p, movil=False)
    recorrer(p, movil=True)
    # Extras
    br = p.chromium.launch(); page = br.new_page()
    r = page.goto(BASE + "/docs"); check("GET /docs sigue funcionando", r.status == 200, str(r.status))
    r = page.goto(BASE + "/salud"); check("GET /salud en el navegador", r.status == 200 and "modelo_cargado" in page.content())
    r = page.goto(BASE + "/metricas"); check("GET /metricas en el navegador", r.status == 200 and "importancia_rasgos" in page.content())
    br.close()

SALIDA.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
fallas = [r for r in resultados if not r["ok"]]
print(f"\nTotal: {len(resultados)} comprobaciones · {len(resultados) - len(fallas)} correctas · {len(fallas)} con falla")
sys.exit(1 if fallas else 0)
