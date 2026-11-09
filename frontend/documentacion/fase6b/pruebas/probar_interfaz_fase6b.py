"""Prueba de la INTERFAZ de la Fase 6B en Chromium (Playwright) contra el backend de la Fase 6A.

  python probar_interfaz_fase6b.py                  Backend 6A REAL (rutas, seguridad, SQLite) con DETECTOR SIMULADO
                                                    (servidor_prueba_fase6b.py). Es lo que se puede ejecutar sin el modelo.
  python probar_interfaz_fase6b.py --servidor-real  Arranca ejecutable/run.py (API REAL + MODELO REAL) con base de datos
                                                    TEMPORAL y las mismas variables de prueba. Recomendado en tu Windows.
Requiere: pip install playwright  y  python -m playwright install chromium   (solo para esta prueba).
Crea cuentas SOLO en una base de datos temporal que se borra al terminar; contraseñas aleatorias que nunca se imprimen.
Resultados: ../evidencias/resultados_interfaz_fase6b.json y capturas en ../capturas/.
"""
import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[3]
EVIDENCIAS = AQUI.parent / "evidencias"
CAPTURAS = AQUI.parent / "capturas"
PUBLICOS = {"/", "/salud", "/openapi.json", "/metricas", "/auth/me", "/auth/login", "/auth/registro", "/auth/logout", "/favicon.ico"}
RESULTADOS = []


def chk(nombre, ok, detalle=""):
    RESULTADOS.append({"prueba": nombre, "ok": bool(ok), "detalle": detalle})
    print(f"[{'OK ' if ok else 'FALLO'}] {nombre}" + (f"  → {detalle}" if detalle and not ok else ""), flush=True)


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def clave_aleatoria():
    return "Aa1-" + secrets.token_urlsafe(12)


# ---------- Cliente HTTP del arnés (simula lo que NO hace la interfaz: revocar una sesión «desde fuera») ----------
class Http:
    def __init__(self, base):
        self.base = base

    def llamar(self, metodo, ruta, cuerpo=None, cookie=None, csrf=None):
        cab = {"Origin": self.base}
        data = None
        if cuerpo is not None:
            data = json.dumps(cuerpo).encode()
            cab["Content-Type"] = "application/json"
        if cookie:
            cab["Cookie"] = f"sg_sesion={cookie}"
        if csrf:
            cab["X-CSRF-Token"] = csrf
        req = urllib.request.Request(self.base + ruta, data=data, method=metodo, headers=cab)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, json.loads(r.read() or b"null"), r.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null"), e.headers

    def crear_usuario(self, usuario, clave):
        st, _, _ = self.llamar("POST", "/auth/registro", {"usuario": usuario, "contrasena": clave})
        assert st == 201, f"no se pudo crear el usuario de prueba ({st})"

    def revocar(self, token_cookie):
        """Cierra en el servidor la sesión con esa cookie (como si caducara o se cerrara en otro lugar)."""
        st, datos, _ = self.llamar("GET", "/auth/me", cookie=token_cookie)
        assert st == 200
        st, _, _ = self.llamar("POST", "/auth/logout", cookie=token_cookie, csrf=datos["csrf_token"])
        assert st == 200

    def estado_me(self, token_cookie):
        st, datos, _ = self.llamar("GET", "/auth/me", cookie=token_cookie)
        return st, (datos or {}).get("codigo")


def cookie_sesion(ctx):
    for c in ctx.cookies():
        if c["name"] == "sg_sesion":
            return c
    return None


class Registro:
    """Escucha de una página: peticiones, respuestas, consola y errores de JavaScript."""

    def __init__(self, page):
        self.pet, self.resp, self.consola, self.errores = [], [], [], []
        page.on("request", lambda r: self.pet.append((r.method, urlparse(r.url).path, bool(r.headers.get("x-csrf-token")))))
        page.on("response", lambda r: self.resp.append((r.request.method, urlparse(r.url).path, r.status)))
        page.on("console", lambda m: self.consola.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: self.errores.append(str(e)))

    def reiniciar(self):
        self.pet.clear(); self.resp.clear()

    def cuantas(self, metodo, ruta):
        return sum(1 for m, p, _ in self.pet if m == metodo and p == ruta)

    def privadas(self):
        return [(m, p) for m, p, _ in self.pet if p not in PUBLICOS and not p.startswith("/static")]


def entrar_ui(page, usuario, clave, registro=False):
    if registro:
        if page.locator("#pest-registro").get_attribute("aria-selected") != "true":
            page.click("#pest-registro")
        page.fill("#acc-repite", clave)
    page.fill("#acc-usuario", usuario)
    page.fill("#acc-clave", clave)
    page.click("#btn-acceso-enviar")


def texto(page, selector):
    return page.locator(selector).inner_text() if page.locator(selector).count() else ""


def correr(base, tmp):
    http = Http(base)
    CAPTURAS.mkdir(parents=True, exist_ok=True)
    ua, ub, ubq = f"ua_{secrets.token_hex(3)}", f"ub_{secrets.token_hex(3)}", f"bq_{secrets.token_hex(3)}"
    ca, cb = clave_aleatoria(), clave_aleatoria()
    secretos = [ca, cb]
    http.crear_usuario(ub, cb)  # usuario B (para probar el cambio de cuenta); A se registra desde la interfaz

    with sync_playwright() as p:
        nav = p.chromium.launch()
        ctx = nav.new_context(viewport={"width": 1280, "height": 800}, locale="es-MX")
        page = ctx.new_page()
        reg = Registro(page)

        # ---- 1. Primera carga sin sesión ----
        page.goto(base + "/")
        page.wait_for_selector("#form-acceso")
        chk("1.1 Sin sesión se muestra la pantalla de acceso", page.locator("#acceso-titulo").inner_text() == "Iniciar sesión")
        chk("1.2 Sin sesión no se muestra el menú ni vistas privadas", not page.locator(".lateral").is_visible() and page.locator("#btn-cerrar-sesion").count() == 0)
        chk("1.3 Al cargar: exactamente UNA consulta GET /auth/me", reg.cuantas("GET", "/auth/me") == 1, str(reg.cuantas("GET", "/auth/me")))
        chk("1.4 Ninguna petición privada antes de conocer la sesión", reg.privadas() == [], str(reg.privadas()))
        page.screenshot(path=str(CAPTURAS / "escritorio_acceso_login.png"))

        # ---- 2. Registro ----
        page.click("#btn-acceso-cambiar")
        chk("2.1 Se alterna a «Crear cuenta» sin recargar", page.locator("#acceso-titulo").inner_text() == "Crear cuenta" and page.locator("#acc-repite").is_visible())
        antes = reg.cuantas("POST", "/auth/registro")
        page.click("#btn-acceso-enviar")
        chk("2.2 Campos vacíos: mensajes locales y sin petición",
            "Escribe tu usuario" in texto(page, "#acc-err-usuario") and "Escribe tu contraseña" in texto(page, "#acc-err-clave")
            and reg.cuantas("POST", "/auth/registro") == antes)
        page.screenshot(path=str(CAPTURAS / "escritorio_acceso_registro_errores_locales.png"))
        page.fill("#acc-usuario", ua); page.fill("#acc-clave", ca); page.fill("#acc-repite", ca + "x")
        page.click("#btn-acceso-enviar")
        chk("2.3 Contraseñas distintas: aviso local", "no coinciden" in texto(page, "#acc-err-repite") and reg.cuantas("POST", "/auth/registro") == antes)
        page.fill("#acc-usuario", "A!"); page.fill("#acc-clave", "corta"); page.fill("#acc-repite", "corta")
        page.click("#btn-acceso-enviar")
        page.wait_for_selector("#acc-err-clave:not([hidden])")
        chk("2.4 422 del servidor: mensaje junto a cada campo (campos del contrato)",
            "al menos 10 caracteres" in texto(page, "#acc-err-clave") and "3 a 32 caracteres" in texto(page, "#acc-err-usuario")
            and page.locator("#acc-usuario").get_attribute("aria-invalid") == "true")
        page.screenshot(path=str(CAPTURAS / "escritorio_acceso_registro_422.png"))
        # mostrar / ocultar contraseña
        page.fill("#acc-clave", ca)
        page.click(".campo-ojo")
        visible = page.locator("#acc-clave").get_attribute("type") == "text"
        page.click(".campo-ojo")
        chk("2.5 Mostrar/ocultar contraseña", visible and page.locator("#acc-clave").get_attribute("type") == "password")
        page.fill("#acc-usuario", ua); page.fill("#acc-clave", ca); page.fill("#acc-repite", ca)
        page.click("#btn-acceso-enviar")
        page.wait_for_selector("#btn-cerrar-sesion")
        chk("2.6 Registro válido: sesión abierta, menú y cuenta activa visibles",
            page.locator(".lateral").is_visible() and ua in texto(page, ".chip--usuario"))
        chk("2.7 El registro se envió una sola vez", reg.cuantas("POST", "/auth/registro") == antes + 2 and reg.cuantas("GET", "/auth/me") == 1,
            f"registros={reg.cuantas('POST', '/auth/registro') - antes}")
        c = cookie_sesion(ctx)
        chk("2.8 Cookie de sesión HttpOnly y SameSite=Strict (la fija el servidor)", bool(c) and c["httpOnly"] and c["sameSite"] == "Strict")
        page.screenshot(path=str(CAPTURAS / "escritorio_app_con_sesion.png"))

        # ---- 3. Uso privado con CSRF ----
        page.goto(base + "/#/analisis"); page.wait_for_selector("#tab-pegar")
        page.click("#tab-pegar")
        page.fill("#texto-pegado", "Subject: Premio\n\nYou are a WINNER! Claim your FREE prize now.")
        reg.reiniciar()
        page.click("#btn-extraer-texto"); page.wait_for_selector("#btn-analizar")
        page.click("#btn-analizar"); page.wait_for_selector(".banner")
        privados_post = [(m, p, c) for m, p, c in reg.pet if m == "POST" and p in ("/correo/extraer", "/predecir", "/historial")]
        chk("3.1 Análisis individual funciona con sesión (extraer, predecir, historial = 200)",
            all(s == 200 or s == 201 for m, p, s in reg.resp if m == "POST" and p in ("/correo/extraer", "/predecir", "/historial")) and len(privados_post) == 3,
            str(reg.resp))
        chk("3.2 Todo POST privado lleva X-CSRF-Token", all(c for _, _, c in privados_post))
        chk("3.3 Los GET no llevan X-CSRF-Token", all(not c for m, _, c in reg.pet if m == "GET"))
        chk("3.4 El resultado muestra SPAM (detector simulado)", "SPAM" in texto(page, ".banner").upper())
        page.screenshot(path=str(CAPTURAS / "escritorio_analisis_con_sesion.png"))
        page.goto(base + "/#/historial"); page.wait_for_selector("#tabla-historial")
        chk("3.5 Historial privado del usuario muestra su análisis", page.locator("#tabla-historial tbody tr").count() == 1)

        # ---- 4. Restauración al recargar ----
        reg.reiniciar()
        page.reload(); page.wait_for_selector("#btn-cerrar-sesion")
        chk("4.1 Recarga: la sesión se restaura con UNA consulta /auth/me", reg.cuantas("GET", "/auth/me") == 1)
        chk("4.2 Se conserva la ruta (#/historial)", page.evaluate("location.hash") == "#/historial")
        idx_me = [i for i, (m, pth, _) in enumerate(reg.pet) if pth == "/auth/me"]
        idx_priv = [i for i, (m, pth, _) in enumerate(reg.pet) if pth not in PUBLICOS and not pth.startswith("/static")]
        chk("4.3 Ninguna petición privada se envió antes de /auth/me", bool(idx_me) and bool(idx_priv) and min(idx_priv) > min(idx_me),
            f"me={idx_me[:1]} primera_privada={idx_priv[:1]}")
        chk("4.4 document.cookie no expone la cookie de sesión", "sg_sesion" not in page.evaluate("document.cookie"))
        chk("4.5 localStorage y sessionStorage vacíos", page.evaluate("localStorage.length + sessionStorage.length") == 0)

        # ---- 5. Renovación de CSRF (403 csrf_invalido → /auth/me → un reintento) ----
        page.goto(base + "/#/analisis"); page.reload(); page.wait_for_selector("#tab-pegar")
        page.click("#tab-pegar")
        page.fill("#texto-pegado", "Hola, ¿comemos mañana?")
        page.click("#btn-extraer-texto"); page.wait_for_selector("#btn-analizar")
        manipulada = {"hecho": False}

        def manipular(route):
            if not manipulada["hecho"]:
                manipulada["hecho"] = True
                route.continue_(headers={**route.request.headers, "x-csrf-token": "0" * 64})
            else:
                route.continue_()
        page.route("**/predecir", manipular)
        reg.reiniciar()
        page.click("#btn-analizar"); page.wait_for_selector(".banner")
        page.unroute("**/predecir")
        chk("5.1 403 csrf_invalido: renueva con UNA llamada a /auth/me y reintenta UNA vez",
            reg.cuantas("POST", "/predecir") == 2 and reg.cuantas("GET", "/auth/me") == 1 and "LEG" in texto(page, ".banner").upper(),
            f"predecir={reg.cuantas('POST', '/predecir')} me={reg.cuantas('GET', '/auth/me')}")

        # ---- 6. Sesión expirada en otro lugar: 401, borrador y regreso ----
        page.goto(base + "/#/analisis"); page.reload(); page.wait_for_selector("#tab-pegar")
        page.click("#tab-pegar")
        borrador = "borrador-no-enviado-" + secrets.token_hex(2)
        page.fill("#texto-pegado", borrador)
        page.evaluate("window.__marca = 1")
        http.revocar(cookie_sesion(ctx)["value"])
        page.evaluate("location.hash = '#/historial'")  # acción que dispara una petición privada
        page.wait_for_selector("#form-acceso")
        chk("6.1 401 → pantalla de acceso con «Tu sesión expiró»", "Tu sesión expiró" in texto(page, "#acc-aviso"))
        chk("6.2 Sin sesión no queda menú, cuenta ni vista privada",
            not page.locator(".lateral").is_visible() and page.locator("#btn-cerrar-sesion").count() == 0 and page.locator("#tabla-historial").count() == 0)
        page.screenshot(path=str(CAPTURAS / "escritorio_sesion_expirada.png"))
        entrar_ui(page, ua, ca)
        page.wait_for_selector("#btn-cerrar-sesion")
        page.wait_for_selector("#tabla-historial")
        chk("6.3 Misma cuenta: vuelve a la ruta donde estaba (#/historial), sin recargar",
            page.evaluate("location.hash") == "#/historial" and page.evaluate("window.__marca") == 1)
        page.evaluate("location.hash = '#/analisis'"); page.wait_for_selector("#tab-pegar")
        page.click("#tab-pegar")
        chk("6.4 Se conserva lo que la persona estaba escribiendo (contrato §9.1)", page.locator("#texto-pegado").input_value() == borrador)

        # ---- 6b. Expira y entra OTRA cuenta: no se mezclan datos ----
        http.revocar(cookie_sesion(ctx)["value"])
        page.evaluate("location.hash = '#/historial'")
        page.wait_for_selector("#form-acceso")
        entrar_ui(page, ub, cb)
        page.wait_for_selector("#btn-cerrar-sesion")
        time.sleep(0.8)
        page.wait_for_selector("#btn-cerrar-sesion")
        chk("6.5 Otra cuenta tras expirar: la interfaz se recarga (memoria limpia)", page.evaluate("window.__marca") is None)
        chk("6.6 La cuenta nueva muestra su propio nombre", ub in texto(page, ".chip--usuario") and ua not in texto(page, ".chip--usuario"))
        page.wait_for_selector("#tabla-historial, .vacio, .aviso", timeout=8000)
        chk("6.7 El historial de la cuenta B no contiene los análisis de la cuenta A", page.locator("#tabla-historial tbody tr").count() == 0)
        page.evaluate("location.hash = '#/analisis'"); page.wait_for_selector("#tab-pegar"); page.click("#tab-pegar")
        chk("6.8 El borrador de A no aparece en la cuenta B", page.locator("#texto-pegado").input_value() == "")

        # ---- 7. Cierre de sesión ----
        token_b = cookie_sesion(ctx)["value"]
        reg.reiniciar()
        page.click("#btn-cerrar-sesion")
        page.wait_for_selector("#form-acceso")
        page.wait_for_selector("#acc-aviso .aviso")
        chk("7.1 Cerrar sesión: vuelve al acceso con «Cerraste sesión»", "Cerraste sesión" in texto(page, "#acc-aviso") and not page.locator(".lateral").is_visible())
        logout = [(m, p, c) for m, p, c in reg.pet if p == "/auth/logout"]
        chk("7.2 POST /auth/logout con X-CSRF-Token, una sola vez", len(logout) == 1 and logout[0][2])
        chk("7.3 La sesión quedó invalidada EN EL SERVIDOR (la cookie copiada ya no sirve)", http.estado_me(token_b) == (401, "sesion_expirada"), str(http.estado_me(token_b)))
        chk("7.4 El navegador borró la cookie", cookie_sesion(ctx) is None)
        chk("7.5 El aviso del hash se limpió de la URL", page.evaluate("location.hash") == "")
        page.screenshot(path=str(CAPTURAS / "escritorio_sesion_cerrada.png"))

        # ---- 8. Errores de acceso ----
        page.click("#btn-acceso-cambiar")
        entrar_ui(page, ua, ca, registro=True)
        page.wait_for_selector("#acc-err-usuario:not([hidden])")
        chk("8.1 409 usuario duplicado: mensaje en el campo usuario", "ya está en uso" in texto(page, "#acc-err-usuario"))
        page.click("#btn-acceso-cambiar")  # a «Iniciar sesión»
        page.fill("#acc-usuario", ua); page.fill("#acc-clave", ca + "-mala")
        page.click("#btn-acceso-enviar")
        page.wait_for_selector("#acc-aviso .aviso--error")
        chk("8.2 401 credenciales incorrectas: mensaje del contrato y contraseña vaciada",
            "Usuario o contraseña incorrectos." in texto(page, "#acc-aviso") and page.locator("#acc-clave").input_value() == "")
        # 429 con un usuario inexistente (el contrato lo aplica igual)
        for _ in range(4):
            page.fill("#acc-usuario", ubq); page.fill("#acc-clave", "incorrecta-" + secrets.token_hex(2))
            if page.locator("#btn-acceso-enviar").is_disabled():
                break
            page.click("#btn-acceso-enviar")
            page.wait_for_function("!document.querySelector('#btn-acceso-enviar').disabled || document.querySelector('#acc-aviso .aviso')")
            time.sleep(0.3)
        page.wait_for_function("document.querySelector('#btn-acceso-enviar').textContent.includes('Reintentar en')", timeout=8000)
        n_login = reg.cuantas("POST", "/auth/login")
        page.fill("#acc-clave", "otra-vez-1234"); page.press("#acc-clave", "Enter")
        time.sleep(0.4)
        chk("8.3 429: botón deshabilitado con cuenta regresiva y mensaje",
            page.locator("#btn-acceso-enviar").is_disabled() and "Reintentar en" in texto(page, "#btn-acceso-enviar") and "Demasiados intentos" in texto(page, "#acc-aviso"))
        chk("8.4 Durante el bloqueo no se envían más intentos (ni con Enter)", reg.cuantas("POST", "/auth/login") == n_login)
        page.screenshot(path=str(CAPTURAS / "escritorio_acceso_429.png"))
        page.wait_for_function("!document.querySelector('#btn-acceso-enviar').disabled", timeout=20000)
        chk("8.5 Al terminar la espera el botón se habilita de nuevo", texto(page, "#btn-acceso-enviar").strip() == "Entrar")

        # ---- 9. Análisis masivo se detiene al primer 401 ----
        entrar_ui(page, ua, ca)
        page.wait_for_selector("#btn-cerrar-sesion")
        correos = []
        for i in range(4):
            f = Path(tmp) / f"correo{i}.eml"
            f.write_text(f"From: a@b.c\nTo: d@e.f\nSubject: Prueba {i}\n\nHola, mensaje numero {i} para probar.\n", encoding="utf-8")
            correos.append(str(f))
        page.evaluate("location.hash = '#/masivo'"); page.wait_for_selector("#entrada-masivo-archivos", state="attached")
        page.set_input_files("#entrada-masivo-archivos", correos)
        revocado = {"hecho": False}

        def tras_respuesta(r):
            if r.url.endswith("/analisis/archivo") and not revocado["hecho"]:
                revocado["hecho"] = True
                http.revocar(cookie_sesion(ctx)["value"])
        page.on("response", tras_respuesta)
        reg.reiniciar()
        page.click("#btn-iniciar-masivo")
        page.wait_for_selector("#form-acceso", timeout=20000)
        enviados = reg.cuantas("POST", "/analisis/archivo")
        estados = [st for m, pth, st in reg.resp if m == "POST" and pth == "/analisis/archivo"]
        # La revocación la hace el arnés al ver la primera respuesta; Playwright puede entregar ese evento con retraso, así
        # que alguna petición más pudo salir con la sesión aún válida. Lo que exige el contrato (§9.5) es que, una vez
        # recibido el PRIMER 401, no se envíe ningún archivo más: el 401 debe ser la última respuesta de la cola.
        chk("9.1 Masivo: tras el primer 401 no se envía ningún archivo más (y no se enviaron los 4)",
            estados.count(401) == 1 and estados[-1] == 401 and enviados < 4, f"respuestas={estados} enviados={enviados}/4")
        print(f"      (POST /analisis/archivo: {enviados} de 4; respuestas {estados})")
        chk("9.2 Masivo: la sesión terminada lleva al acceso", "Tu sesión expiró" in texto(page, "#acc-aviso"))
        page.remove_listener("response", tras_respuesta)
        entrar_ui(page, ua, ca)
        page.wait_for_selector("#btn-cerrar-sesion")
        page.wait_for_selector("#tit-prog-masivo")
        chk("9.3 Masivo: tras volver a entrar se informa que el análisis se detuvo por la sesión", "Tu sesión expiró" in page.locator("#contenido").inner_text())
        page.screenshot(path=str(CAPTURAS / "escritorio_masivo_detenido_por_sesion.png"))

        # ---- 10. Móvil ----
        mov = nav.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="es-MX")
        pm = mov.new_page()
        regm = Registro(pm)
        pm.goto(base + "/"); pm.wait_for_selector("#form-acceso")
        sin_desborde = lambda: pm.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        chk("10.1 Móvil: acceso sin desbordamiento horizontal", sin_desborde())
        chk("10.2 Móvil: campos de 16 px (sin zoom en iOS) y objetivo táctil ≥ 44 px",
            pm.evaluate("getComputedStyle(document.querySelector('#acc-usuario')).fontSize") == "16px"
            and pm.locator("#btn-acceso-enviar").bounding_box()["height"] >= 44 and pm.locator(".campo-ojo").bounding_box()["width"] >= 44)
        pm.screenshot(path=str(CAPTURAS / "movil_acceso_login.png"))
        pm.click("#btn-acceso-cambiar")
        pm.screenshot(path=str(CAPTURAS / "movil_acceso_registro.png"))
        chk("10.3 Móvil: registro sin desbordamiento", sin_desborde())
        pm.click("#btn-acceso-cambiar")
        entrar_ui(pm, ua, ca)
        pm.wait_for_selector("#btn-cerrar-sesion")
        pm.wait_for_selector("#tab-pegar")
        chk("10.4 Móvil: app con sesión sin desbordamiento", sin_desborde())
        caja = pm.locator("#btn-cerrar-sesion").bounding_box()
        chk("10.5 Móvil: «Cerrar sesión» visible dentro de la pantalla", caja is not None and caja["x"] >= 0 and caja["x"] + caja["width"] <= 391)
        pm.screenshot(path=str(CAPTURAS / "movil_app_con_sesion.png"))
        pm.click("#btn-cerrar-sesion")
        pm.wait_for_selector("#form-acceso")
        chk("10.6 Móvil: cerrar sesión devuelve al acceso", "Cerraste sesión" in texto(pm, "#acc-aviso"))

        # ---- 11. Higiene global ----
        entrar_ui(page, ua, ca) if page.locator("#form-acceso").count() else None
        todo = "\n".join(reg.consola + regm.consola + reg.errores + regm.errores)
        chk("11.1 Sin errores de JavaScript (pageerror) en toda la prueba", reg.errores == [] and regm.errores == [], str(reg.errores + regm.errores))
        chk("11.2 La consola del navegador no contiene contraseñas", not any(s in todo for s in secretos))
        c_final = cookie_sesion(ctx)
        if c_final:
            st, datos, _ = http.llamar("GET", "/auth/me", cookie=c_final["value"])
            chk("11.3 La consola no contiene el token CSRF ni el valor de la cookie", st == 200 and datos["csrf_token"] not in todo and c_final["value"] not in todo)
            chk("11.4 El token CSRF no está en localStorage / sessionStorage / document.cookie / DOM",
                datos["csrf_token"] not in page.evaluate("JSON.stringify([localStorage, sessionStorage, document.cookie, document.documentElement.outerHTML])"))
        chk("11.5 localStorage y sessionStorage vacíos al final", page.evaluate("localStorage.length + sessionStorage.length") == 0
            and pm.evaluate("localStorage.length + sessionStorage.length") == 0)
        chk("11.6 Ningún campo de contraseña sigue con valor tras iniciar sesión", page.locator("input[type=password], #acc-clave").evaluate_all("els => els.every(e => e.value === '')"))
        mensajes_consola = sorted({m for m in reg.consola + regm.consola})
        nav.close()
    return mensajes_consola


def esperar(base, limite=180):
    t0 = time.time()
    while time.time() - t0 < limite:
        try:
            with urllib.request.urlopen(base + "/salud", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--servidor-real", action="store_true", help="usa ejecutable/run.py (API y modelo REALES)")
    args = ap.parse_args()
    tmp = tempfile.mkdtemp(prefix="sg_fase6b_")
    puerto = puerto_libre()
    base = f"http://127.0.0.1:{puerto}"
    env = dict(os.environ, SG_DB=str(Path(tmp) / "prueba.db"), SG_SECRET_KEY=secrets.token_urlsafe(48), SG_PBKDF2_ITER="1000",
               SG_LOGIN_MAX_INTENTOS="3", SG_LOGIN_VENTANA_SEG="8", SG_ABRIR_NAVEGADOR="0", SG_PUERTO=str(puerto), SG_HOST="127.0.0.1")
    if args.servidor_real:
        cmd = [sys.executable, str(RAIZ / "ejecutable" / "run.py")]
    else:
        cmd = [sys.executable, str(AQUI / "servidor_prueba_fase6b.py"), str(puerto)]
    modo = "BACKEND 6A REAL + MODELO REAL (run.py)" if args.servidor_real else "BACKEND 6A REAL + DETECTOR SIMULADO"
    print(f"Modo: {modo}\nServidor: {base}  ·  base de datos temporal: {tmp}\n", flush=True)
    srv = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=str(RAIZ))
    consola = []
    try:
        if not esperar(base):
            print("El servidor no arrancó:", (srv.stderr.read() or b"").decode(errors="replace")[-1500:])
            sys.exit(2)
        consola = correr(base, tmp)
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    fallos = [r for r in RESULTADOS if not r["ok"]]
    EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    (EVIDENCIAS / "resultados_interfaz_fase6b.json").write_text(json.dumps({
        "modo": modo, "total": len(RESULTADOS), "fallos": len(fallos), "resultados": RESULTADOS,
        "mensajes_de_consola_del_navegador": consola}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(RESULTADOS) - len(fallos)}/{len(RESULTADOS)} comprobaciones correctas · modo: {modo}")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
