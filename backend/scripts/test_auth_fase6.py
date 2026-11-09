"""Pruebas de autenticación y seguridad de la Fase 6A, con la API REAL (FastAPI TestClient) y el MODELO REAL.

Uso (desde la raíz del proyecto, con el entorno virtual activo):   python backend\\scripts\\test_auth_fase6.py

Qué cubre:
  A. Primitivas: PBKDF2 (formato, sal aleatoria, 600000 iteraciones por defecto), tokens, HMAC del token, CSRF, configuración.
  B. Registro: correcto, usuario duplicado, usuario y contraseña inválidos, cookie (HttpOnly/SameSite/Secure), sin texto
     plano ni token en la base de datos.
  C. Inicio de sesión: correcto, incorrecto (mismo mensaje que usuario inexistente), rotación de sesión.
  D. /auth/me, cierre de sesión (revocación REAL en el servidor, no solo borrar la cookie).
  E. Sesión expirada (absoluta e inactividad), revocación, tope de sesiones.
  F. CSRF y validación de origen.
  G. Límite de intentos de inicio de sesión (por usuario+IP, por usuario, por IP) y de registro; persistencia.
  H. Rutas: TODAS las rutas de la aplicación se enumeran; las privadas devuelven 401 sin sesión; /salud y /metricas siguen públicos.
  I. El servidor no arranca con una configuración de seguridad inválida.
La base de datos es TEMPORAL (no toca backend/storage). No evalúa el aislamiento entre usuarios: eso es test_aislamiento_fase6.py.
"""
import contextlib
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PROYECTO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import auth_helper  # noqa: E402  (SG_DB temporal, SG_SECRET_KEY aleatoria, SG_PBKDF2_ITER=1000 para la velocidad)
from auth_helper import CONTRASENA, ORIGEN  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import almacen, seguridad, usuarios  # noqa: E402
from app.main import app  # noqa: E402

GRUPOS = 0
TEXTO = "WINNER!! Claim your FREE prize now: http://bit.ly/claim-now"
H = {"Origin": ORIGEN}


def ok(msg):
    global GRUPOS
    GRUPOS += 1
    print(f"[OK] {msg}")


def comprobar(cond, msg):
    assert cond, msg


@contextlib.contextmanager
def entorno(**cambios):
    """Cambia variables de entorno SG_* solo dentro del bloque."""
    antes = {k: os.environ.get(k) for k in cambios}
    try:
        for k, v in cambios.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in antes.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def cliente(**kw):
    return TestClient(app, **kw)


def registrar(c, usuario, contrasena=CONTRASENA, **extra):
    return c.post("/auth/registro", json={"usuario": usuario, "contrasena": contrasena}, headers={**H, **extra})


def entrar(c, usuario, contrasena=CONTRASENA, **extra):
    return c.post("/auth/login", json={"usuario": usuario, "contrasena": contrasena}, headers={**H, **extra})


def sesion_nueva(usuario):
    """Cliente nuevo con sesión iniciada. Devuelve (cliente, json de sesión, token de la cookie)."""
    c = cliente()
    r = registrar(c, usuario)
    assert r.status_code == 201, r.text
    return c, r.json(), c.cookies.get("sg_sesion")


def con_cookie(token, csrf=None, **extra):
    """Cabeceras de un 'atacante' que reutiliza un token robado (sin el cliente que lo recibió)."""
    cab = {**H, "Cookie": f"sg_sesion={token}", **extra}
    if csrf:
        cab["X-CSRF-Token"] = csrf
    return cab


def bd():
    con = sqlite3.connect(os.environ["SG_DB"])
    con.row_factory = sqlite3.Row
    return con


def sql(consulta, par=()):
    con = bd()
    try:
        filas = con.execute(consulta, par).fetchall()
        con.commit()
        return filas
    finally:
        con.close()


def main():
    # ===================== A. Primitivas =====================
    h1 = seguridad.hashear_contrasena("una clave larga 123")
    h2 = seguridad.hashear_contrasena("una clave larga 123")
    alg, it, sal, dk = h1.split("$")
    comprobar(alg == "pbkdf2_sha256" and int(it) == int(os.environ["SG_PBKDF2_ITER"]), f"formato del hash {h1}")
    comprobar(h1 != h2 and h1.split("$")[2] != h2.split("$")[2], "dos hashes de la misma contraseña usan sal distinta")
    import base64
    comprobar(len(base64.b64decode(sal)) == 16 and len(base64.b64decode(dk)) == 32, "sal de 16 bytes y hash de 32 bytes")
    comprobar(seguridad.verificar_contrasena("una clave larga 123", h1) and not seguridad.verificar_contrasena("otra", h1), "verificación")
    # El hash debe ser exactamente PBKDF2-HMAC-SHA256 estándar (verificable con hashlib de forma independiente).
    esperado = hashlib.pbkdf2_hmac("sha256", b"una clave larga 123", base64.b64decode(sal), int(it), dklen=32)
    comprobar(base64.b64decode(dk) == esperado, "el hash coincide con hashlib.pbkdf2_hmac('sha256', ...)")
    comprobar(not seguridad.verificar_contrasena("x", "basura") and not seguridad.verificar_contrasena("x", ""), "hash corrupto -> False")
    comprobar(not seguridad.verificar_contrasena("x", f"pbkdf2_sha256$999999999$AAAA$AAAA"), "iteraciones absurdas rechazadas")
    with entorno(SG_PBKDF2_ITER=None):
        comprobar(seguridad.iteraciones_actuales() == 600_000, "por defecto 600000 iteraciones (OWASP 2023)")
        comprobar(seguridad.necesita_rehash(h1), "un hash con menos iteraciones se marca para actualizar")
    comprobar(seguridad.verificar_contrasena("clave-ñandú-123456", seguridad.hashear_contrasena("clave-ñandú-123456")), "unicode")
    tok = seguridad.nuevo_token()
    comprobar(re.fullmatch(r"[A-Za-z0-9_-]{43}", tok) and tok != seguridad.nuevo_token(), "token: 43 caracteres base64url (256 bits), distinto cada vez")
    comprobar(seguridad.hash_token(tok) != tok and tok not in seguridad.hash_token(tok) and len(seguridad.hash_token(tok)) == 64, "hash del token")
    comprobar(seguridad.hash_token(tok) == seguridad.hash_token(tok), "hash del token determinista")
    comprobar(seguridad.token_csrf(tok) != seguridad.hash_token(tok), "CSRF y hash de sesión usan dominios distintos")
    with entorno(SG_SECRET_KEY="otra-clave-de-prueba-que-tiene-mas-de-32-caracteres"):
        otra = seguridad.hash_token(tok)
    comprobar(otra != seguridad.hash_token(tok), "el HMAC depende de la clave del servidor")
    ok("Primitivas: PBKDF2-HMAC-SHA256 con sal de 16 bytes, 600000 iteraciones por defecto, token de 256 bits, HMAC con clave del servidor")

    # ===================== I. Configuración (antes de arrancar nada más) =====================
    with entorno(SG_ENTORNO="produccion", SG_SECRET_KEY=None):
        try:
            with TestClient(app):
                raise AssertionError("debía fallar sin SG_SECRET_KEY en producción")
        except seguridad.ErrorConfiguracion as e:
            comprobar("SG_SECRET_KEY" in str(e), str(e))
    with entorno(SG_SECRET_KEY="corta"):
        try:
            with TestClient(app):
                raise AssertionError("debía fallar con una clave corta")
        except seguridad.ErrorConfiguracion as e:
            comprobar("32" in str(e), str(e))
    with entorno(SG_COOKIE_SAMESITE="none"):
        try:
            with TestClient(app):
                raise AssertionError("SameSite=None no se permite")
        except seguridad.ErrorConfiguracion:
            pass
    ok("Configuración: sin SG_SECRET_KEY en producción, con clave corta o con SameSite=None el servidor NO arranca")

    with TestClient(app) as base:  # arranca la aplicación (lifespan: modelo real + migración)
        comprobar(base.get("/salud").json() == {"estado": "ok", "modelo_cargado": True}, "/salud")

        # ===================== B. Registro =====================
        c1 = cliente()
        r = registrar(c1, "Ana.Lopez")
        comprobar(r.status_code == 201, r.text)
        j = r.json()
        comprobar(set(j) == {"usuario", "csrf_token", "sesion"} and j["usuario"]["usuario"] == "ana.lopez", j)
        comprobar(set(j["usuario"]) == {"id", "usuario", "creado_en"} and set(j["sesion"]) == {"expira_en"}, j)
        comprobar(re.fullmatch(r"[0-9a-f]{64}", j["csrf_token"]), "formato del token CSRF")
        comprobar("contrasena" not in json.dumps(j) and "clave" not in json.dumps(j), "la respuesta no contiene la contraseña ni su hash")
        sc = r.headers["set-cookie"]
        comprobar(sc.startswith("sg_sesion=") and "HttpOnly" in sc and "samesite=strict" in sc.lower() and "Path=/" in sc, sc)
        comprobar("Max-Age=" in sc and "secure" not in sc.lower(), "cookie con Max-Age y sin Secure en http: " + sc)
        comprobar(r.headers["cache-control"] == "no-store", "las respuestas de /auth no se guardan en caché")
        token_ana = c1.cookies.get("sg_sesion")
        comprobar(re.fullmatch(r"[A-Za-z0-9_-]{43}", token_ana), "token de sesión de 43 caracteres")
        # Secure cuando corresponde: HTTPS (directo), SG_COOKIE_SECURE=1, y proxy que declara https solo si se confía en él.
        c_https = TestClient(app, base_url="https://testserver")
        r_https = c_https.post("/auth/registro", json={"usuario": "segura1", "contrasena": CONTRASENA}, headers={"Origin": "https://testserver"})
        comprobar("secure" in r_https.headers["set-cookie"].lower(), "Secure en HTTPS: " + r_https.headers["set-cookie"])
        with entorno(SG_COOKIE_SECURE="1"):
            r_f = registrar(cliente(), "segura2")
            comprobar("secure" in r_f.headers["set-cookie"].lower(), "SG_COOKIE_SECURE=1 fuerza Secure")
        r_p = registrar(cliente(), "proxy1", **{"X-Forwarded-Proto": "https"})
        comprobar("secure" not in r_p.headers["set-cookie"].lower(), "X-Forwarded-Proto se ignora si no se confía en el proxy")
        with entorno(SG_CONFIAR_PROXY="1"):
            r_p2 = registrar(cliente(), "proxy2", **{"X-Forwarded-Proto": "https"})
            comprobar("secure" in r_p2.headers["set-cookie"].lower(), "con SG_CONFIAR_PROXY=1 se respeta X-Forwarded-Proto")
        with entorno(SG_COOKIE_SAMESITE="lax"):
            r_l = registrar(cliente(), "laxa1")
            comprobar("samesite=lax" in r_l.headers["set-cookie"].lower(), "SG_COOKIE_SAMESITE=lax")
        ok("Registro correcto: 201, usuario normalizado, cookie HttpOnly + SameSite=Strict + Path=/ (+Secure en HTTPS o por configuración)")

        # Nada en texto plano en la base de datos
        fila = sql("SELECT usuario, clave_hash FROM usuarios WHERE usuario='ana.lopez'")[0]
        comprobar(fila["clave_hash"].startswith("pbkdf2_sha256$") and CONTRASENA not in fila["clave_hash"], "hash en la base")
        ses = sql("SELECT token_hash FROM sesiones")
        comprobar(all(re.fullmatch(r"[0-9a-f]{64}", s["token_hash"]) for s in ses) and token_ana not in [s["token_hash"] for s in ses], "solo hashes de token")
        crudo = b"".join(p.read_bytes() for p in Path(os.environ["SG_DB"]).parent.glob("prueba.db*"))
        comprobar(CONTRASENA.encode() not in crudo and token_ana.encode() not in crudo and j["csrf_token"].encode() not in crudo,
                  "ni la contraseña, ni el token de sesión, ni el CSRF aparecen en los archivos de la base de datos")
        ok("Base de datos: sin contraseñas en texto plano, sin tokens de sesión (solo su HMAC) y sin token CSRF")

        # Duplicado
        r = registrar(cliente(), "ana.lopez")
        comprobar(r.status_code == 409 and r.json()["codigo"] == "usuario_duplicado" and "usuario" in r.json()["campos"], r.text)
        comprobar(registrar(cliente(), "ANA.LOPEZ").status_code == 409, "duplicado sin distinguir mayúsculas")
        comprobar(registrar(cliente(), "  Ana.Lopez ").status_code == 409, "duplicado con espacios")
        comprobar(sql("SELECT COUNT(*) AS n FROM usuarios WHERE usuario='ana.lopez'")[0]["n"] == 1, "un solo registro")
        ok("Usuario duplicado: 409 usuario_duplicado (sin distinguir mayúsculas ni espacios)")

        # Datos inválidos
        malos_usuario = ["", "ab", "a" * 33, "con espacio", "Ñandú", "-inicio", "a;b", "admin'--", "<script>"]
        for u in malos_usuario:
            r = registrar(cliente(), u)
            comprobar(r.status_code == 422 and r.json()["codigo"] == "datos_invalidos" and "usuario" in r.json()["campos"], (u, r.text))
        malas = {"corta": "abc123", "nueve": "abcdefg12", "comun": "password123", "solo_espacios": " " * 12,
                 "repetida": "a" * 20, "larga": "x" * 129, "contiene_usuario": "ana.lopez-2026!"}
        for nombre, pw in malas.items():
            usuario = "ana.lopez" if nombre == "contiene_usuario" else "valido" + nombre.replace("_", "")
            r = registrar(cliente(), usuario, pw)
            comprobar(r.status_code == 422 and "contrasena" in r.json()["campos"], (nombre, r.status_code, r.text))
        comprobar(sql("SELECT COUNT(*) AS n FROM usuarios WHERE usuario LIKE 'valido%'")[0]["n"] == 0, "no se crearon cuentas con datos inválidos")
        for cuerpo in ({}, {"usuario": "solo"}, {"contrasena": "x" * 12}, {"usuario": 5, "contrasena": ["a"]}, None):
            r = cliente().post("/auth/registro", json=cuerpo, headers=H) if cuerpo is not None else \
                cliente().post("/auth/registro", content=b"{no es json", headers={**H, "Content-Type": "application/json"})
            comprobar(r.status_code == 422 and r.json()["codigo"] == "datos_invalidos", (cuerpo, r.status_code, r.text))
        r = registrar(cliente(), "a" * 33, "corta")
        comprobar(set(r.json()["campos"]) == {"usuario", "contrasena"}, "informa todos los campos inválidos juntos")
        ok("Contraseña y usuario inválidos: 422 datos_invalidos con el detalle por campo; cuerpos mal formados también")

        # ===================== C. Login =====================
        c2 = cliente()
        r = entrar(c2, "ANA.LOPEZ")
        comprobar(r.status_code == 200 and r.json()["usuario"]["usuario"] == "ana.lopez" and "set-cookie" in r.headers, r.text)
        token2 = c2.cookies.get("sg_sesion")
        comprobar(token2 != token_ana, "cada inicio de sesión crea un token nuevo")
        comprobar(c2.get("/auth/me").status_code == 200, "con la sesión nueva /auth/me funciona")
        comprobar(c1.get("/auth/me").status_code == 200, "la otra sesión sigue válida (varios dispositivos)")
        ok("Login correcto: 200, usuario sin distinguir mayúsculas, token nuevo por sesión")

        malo1 = entrar(cliente(), "ana.lopez", "contraseña-equivocada-1")
        malo2 = entrar(cliente(), "no.existe.nadie", "contraseña-equivocada-1")
        comprobar(malo1.status_code == malo2.status_code == 401 and malo1.json() == malo2.json(), (malo1.text, malo2.text))
        comprobar(malo1.json()["codigo"] == "credenciales_invalidas" and "set-cookie" not in malo1.headers, malo1.text)
        for u, p_ in (("ana.lopez", ""), ("ana.lopez", "x" * 5000), ("' OR '1'='1", "' OR '1'='1"), ("ana.lopez' --", "x"), ("", "x")):
            rr = entrar(cliente(), u, p_)
            comprobar(rr.status_code == 401 and rr.json()["codigo"] == "credenciales_invalidas", (u, rr.status_code, rr.text))
        comprobar(sql("SELECT COUNT(*) AS n FROM usuarios")[0]["n"] >= 1, "la inyección SQL no afectó la tabla")
        ok("Login incorrecto: 401 con el MISMO mensaje para contraseña errónea y usuario inexistente; inyección SQL inofensiva")

        # Fijación de sesión: iniciar sesión con una cookie previa la revoca
        cfix = cliente()
        entrar(cfix, "ana.lopez")
        previo = cfix.cookies.get("sg_sesion")
        entrar(cfix, "ana.lopez")
        comprobar(cfix.cookies.get("sg_sesion") != previo, "token rotado")
        comprobar(cliente().get("/auth/me", headers=con_cookie(previo)).status_code == 401, "la cookie anterior quedó revocada")
        ok("Rotación: al iniciar sesión la cookie anterior se revoca (sin fijación de sesión)")

        # ===================== D. /auth/me y logout =====================
        r = base.get("/auth/me")
        comprobar(r.status_code == 401 and r.json() == {"detail": "Debes iniciar sesión.", "codigo": "no_autenticado"}, r.text)
        r = c1.get("/auth/me")
        comprobar(r.status_code == 200 and r.json()["csrf_token"] == j["csrf_token"] and r.json()["usuario"]["id"] == j["usuario"]["id"], r.text)
        comprobar(r.headers["cache-control"] == "no-store", "me no se guarda en caché")
        falso = "A" * 43
        r = cliente().get("/auth/me", headers=con_cookie(falso))
        comprobar(r.status_code == 401 and r.json()["codigo"] == "sesion_expirada", r.text)
        comprobar("sg_sesion=" in r.headers["set-cookie"] and ("Max-Age=0" in r.headers["set-cookie"] or "expires" in r.headers["set-cookie"].lower()), "la cookie inválida se borra: " + r.headers["set-cookie"])
        for basura in ("x", "a" * 500, "%00", "'; DROP TABLE sesiones;--"):
            comprobar(cliente().get("/auth/me", headers=con_cookie(basura)).status_code == 401, f"cookie basura {basura!r}")
        comprobar(sql("SELECT COUNT(*) AS n FROM sesiones")[0]["n"] > 0, "la tabla de sesiones sigue intacta")
        ok("/auth/me: 200 con usuario y token CSRF; 401 no_autenticado sin cookie; 401 sesion_expirada (y cookie borrada) con token inválido")

        csrf_ana = j["csrf_token"]
        # logout sin CSRF -> 403 y la sesión sigue viva
        r = c1.post("/auth/logout", headers=H)
        comprobar(r.status_code == 403 and r.json()["codigo"] == "csrf_invalido", r.text)
        comprobar(c1.get("/auth/me").status_code == 200, "logout rechazado: la sesión sigue activa")
        r = c1.post("/auth/logout", headers={**H, "X-CSRF-Token": "0" * 64})
        comprobar(r.status_code == 403, "logout con CSRF falso")
        r = c1.post("/auth/logout", headers={**H, "X-CSRF-Token": csrf_ana})
        comprobar(r.status_code == 200 and r.json() == {"cerrada": True, "habia_sesion": True}, r.text)
        comprobar("max-age=0" in r.headers["set-cookie"].lower(), "logout borra la cookie: " + r.headers["set-cookie"])
        # REVOCACIÓN REAL: un atacante que copió el token antes del logout ya no puede usarlo.
        rr = cliente().get("/auth/me", headers=con_cookie(token_ana))
        comprobar(rr.status_code == 401 and rr.json()["codigo"] == "sesion_expirada", "el token copiado ya no sirve: " + rr.text)
        comprobar(cliente().post("/predecir", json={"texto": TEXTO}, headers=con_cookie(token_ana, csrf_ana)).status_code == 401, "ni en rutas privadas")
        comprobar(sql("SELECT revocada_en FROM sesiones WHERE token_hash=?", (seguridad.hash_token(token_ana),))[0]["revocada_en"] is not None, "revocada_en guardado")
        r = cliente().post("/auth/logout", headers=H)
        comprobar(r.status_code == 200 and r.json() == {"cerrada": True, "habia_sesion": False}, "logout sin sesión es idempotente: " + r.text)
        ok("Logout: exige CSRF, revoca la sesión EN EL SERVIDOR (un token copiado deja de servir), borra la cookie y es idempotente")

        # ===================== E. Expiración y revocación =====================
        ce, je, te = sesion_nueva("expira1")
        comprobar(ce.get("/auth/me").status_code == 200, "sesión viva")
        sql("UPDATE sesiones SET expira_en=? WHERE token_hash=?", (time.time() - 5, seguridad.hash_token(te)))
        r = ce.get("/auth/me")
        comprobar(r.status_code == 401 and r.json()["codigo"] == "sesion_expirada", r.text)
        ci, ji, ti = sesion_nueva("inactivo1")
        sql("UPDATE sesiones SET ultimo_uso=? WHERE token_hash=?", (time.time() - 25 * 3600, seguridad.hash_token(ti)))
        comprobar(ci.get("/auth/me").status_code == 401, "inactividad > 24 h")
        cu, ju, tu = sesion_nueva("activo1")
        sql("UPDATE sesiones SET ultimo_uso=? WHERE token_hash=?", (time.time() - 3 * 3600, seguridad.hash_token(tu)))
        comprobar(cu.get("/auth/me").status_code == 200, "3 h de inactividad sigue válida")
        comprobar(sql("SELECT ultimo_uso FROM sesiones WHERE token_hash=?", (seguridad.hash_token(tu),))[0]["ultimo_uso"] > time.time() - 60, "el uso reciente renueva la inactividad")
        with entorno(SG_SESION_MAX_HORAS="1"):
            cm, jm, tm = sesion_nueva("corta1")
            exp = sql("SELECT expira_en, creada_en FROM sesiones WHERE token_hash=?", (seguridad.hash_token(tm),))[0]
            comprobar(abs((exp["expira_en"] - exp["creada_en"]) - 3600) < 2, "SG_SESION_MAX_HORAS configura la expiración absoluta")
        ok("Sesión expirada: expiración absoluta e inactividad (>24 h) -> 401 sesion_expirada; el uso reciente la mantiene")

        # revocación de todas las sesiones de un usuario
        ca, ja, ta = sesion_nueva("revoca1")
        cb = cliente(); entrar(cb, "revoca1"); tb = cb.cookies.get("sg_sesion")
        uid = ja["usuario"]["id"]
        comprobar(usuarios.revocar_sesiones_usuario(uid) == 2, "revoca las dos sesiones activas")
        comprobar(ca.get("/auth/me").status_code == 401 and cb.get("/auth/me").status_code == 401, "ambas dejan de servir")
        comprobar(entrar(cliente(), "revoca1").status_code == 200, "pero el usuario puede iniciar sesión de nuevo")
        # usuario desactivado
        cd, jd, td = sesion_nueva("desactivado1")
        sql("UPDATE usuarios SET activo=0 WHERE usuario='desactivado1'")
        comprobar(cd.get("/auth/me").status_code == 401, "usuario desactivado: la sesión deja de servir")
        comprobar(entrar(cliente(), "desactivado1").status_code == 401, "ni puede iniciar sesión")
        # tope de sesiones
        with entorno(SG_SESIONES_MAX="3"):
            cx = cliente(); registrar(cx, "tope1"); toks = [cx.cookies.get("sg_sesion")]
            for _ in range(4):
                cz = cliente(); entrar(cz, "tope1"); toks.append(cz.cookies.get("sg_sesion"))
            vivas = [cliente().get("/auth/me", headers=con_cookie(t)).status_code == 200 for t in toks]
            comprobar(vivas == [False, False, True, True, True], f"solo las 3 más recientes siguen vivas: {vivas}")
        ok("Revocación: todas las sesiones del usuario, usuario desactivado y tope de sesiones simultáneas")

        # ===================== F. CSRF y origen =====================
        cc, jc, tc = sesion_nueva("csrf1")
        csrf = jc["csrf_token"]
        ct = cliente(); registrar(ct, "csrf2")
        csrf_otro = ct.cookies.get("sg_sesion") and ct.get("/auth/me").json()["csrf_token"]
        cuerpo = {"texto": TEXTO}
        r = cc.post("/predecir", json=cuerpo, headers=H)
        comprobar(r.status_code == 403 and r.json()["codigo"] == "csrf_invalido", r.text)
        comprobar(cc.post("/predecir", json=cuerpo, headers={**H, "X-CSRF-Token": "x"}).status_code == 403, "CSRF basura")
        comprobar(cc.post("/predecir", json=cuerpo, headers={**H, "X-CSRF-Token": csrf_otro}).status_code == 403, "el CSRF de OTRA sesión no sirve")
        comprobar(cc.post("/predecir", json=cuerpo, headers={**H, "X-CSRF-Token": csrf.upper()}).status_code == 403, "el CSRF distingue mayúsculas")
        r = cc.post("/predecir", json=cuerpo, headers={**H, "X-CSRF-Token": csrf})
        comprobar(r.status_code == 200 and set(r.json()) == {"es_spam", "probabilidad", "rasgos_detectados"} and r.json()["es_spam"] is True, r.text)
        comprobar(r.headers["cache-control"] == "no-store" and "Cookie" in r.headers["vary"], "respuestas privadas con Cache-Control: no-store")
        # Todas las rutas que modifican datos exigen CSRF; las de lectura no.
        h_csrf = {**H}
        for metodo, ruta, kw in (("POST", "/predecir", {"json": cuerpo}), ("POST", "/correo/extraer", {"content": b"Subject: hola\n\nhola mundo", "headers": {"Content-Type": "text/plain"}}),
                                 ("POST", "/lotes", {"json": {"total": 1}}), ("POST", "/analisis/archivo", {"content": b"hola", "headers": {"Content-Type": "text/plain"}}),
                                 ("POST", "/historial", {"json": {}}), ("DELETE", "/historial/1", {}), ("POST", "/historial/eliminar", {"json": {"ids": [1]}}),
                                 ("POST", "/retroalimentacion", {"json": {"analisis_id": 1, "de_acuerdo": True}})):
            kw = dict(kw); cab = {**h_csrf, **kw.pop("headers", {})}
            r = cc.request(metodo, ruta, headers=cab, **kw)
            comprobar(r.status_code == 403 and r.json()["codigo"] == "csrf_invalido", (metodo, ruta, r.status_code, r.text))
        for ruta in ("/historial", "/historial/exportar.csv", "/retroalimentacion", "/estadisticas/uso", "/auth/me"):
            comprobar(cc.get(ruta).status_code == 200, f"GET {ruta} no necesita CSRF")
        ok("CSRF: toda solicitud que modifica datos sin el token (o con el de otra sesión) -> 403 csrf_invalido; las lecturas no lo necesitan")

        # Origen
        for origen in ("http://sitio-malicioso.example", "http://testserver.evil.com", "http://testserver:9999", "null", "file://", "javascript:alert(1)", ""):
            r = cc.post("/predecir", json=cuerpo, headers={"Origin": origen, "X-CSRF-Token": csrf})
            comprobar(r.status_code == 403 and r.json()["codigo"] == "origen_no_permitido", (origen, r.status_code, r.text))
        r = cc.post("/predecir", json=cuerpo, headers={"X-CSRF-Token": csrf})
        comprobar(r.status_code == 403 and r.json()["codigo"] == "origen_no_permitido", "sin Origin ni Referer: " + r.text)
        comprobar(cc.post("/predecir", json=cuerpo, headers={"Referer": "http://testserver/pagina", "X-CSRF-Token": csrf}).status_code == 200, "Referer del mismo sitio como alternativa")
        comprobar(cc.post("/predecir", json=cuerpo, headers={"Referer": "http://malo.example/x", "X-CSRF-Token": csrf}).status_code == 403, "Referer de otro sitio")
        # Login / registro / logout también validan el origen (CSRF de inicio de sesión)
        for ruta, cuerpo_a in (("/auth/login", {"usuario": "csrf1", "contrasena": CONTRASENA}), ("/auth/registro", {"usuario": "nuevo.origen", "contrasena": CONTRASENA}), ("/auth/logout", None)):
            r = cliente().post(ruta, json=cuerpo_a, headers={"Origin": "http://sitio-malicioso.example"}) if cuerpo_a else cliente().post(ruta, headers={"Origin": "http://sitio-malicioso.example"})
            comprobar(r.status_code == 403 and r.json()["codigo"] == "origen_no_permitido", (ruta, r.status_code, r.text))
            r = cliente().post(ruta, json=cuerpo_a) if cuerpo_a else cliente().post(ruta)
            comprobar(r.status_code == 403, f"{ruta} sin Origin")
        comprobar(sql("SELECT COUNT(*) AS n FROM usuarios WHERE usuario='nuevo.origen'")[0]["n"] == 0, "no se creó la cuenta desde un origen ajeno")
        with entorno(SG_ORIGENES_PERMITIDOS="https://app.ejemplo.com, http://127.0.0.1:5500"):
            comprobar(cc.post("/predecir", json=cuerpo, headers={"Origin": "https://app.ejemplo.com", "X-CSRF-Token": csrf}).status_code == 200, "origen adicional configurado")
            comprobar(cc.post("/predecir", json=cuerpo, headers={"Origin": "http://app.ejemplo.com", "X-CSRF-Token": csrf}).status_code == 403, "http != https")
        comprobar(cc.get("/historial", headers={"Origin": "http://sitio-malicioso.example"}).status_code == 200, "las lecturas no dependen del Origin (las protege SameSite + CORS)")
        # CORS: no se concede acceso con credenciales a ningún origen
        pre = cc.options("/predecir", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
        comprobar(pre.headers.get("access-control-allow-credentials") is None, "CORS no permite credenciales")
        ok("Origen: POST/DELETE desde otro sitio, sin Origin, con Origin null o malformado -> 403 origen_no_permitido (también login/registro/logout)")

        # ===================== G. Límite de intentos =====================
        with entorno(SG_LOGIN_MAX_INTENTOS="3", SG_CONFIAR_PROXY="1"):
            registrar(cliente(), "limite1"); registrar(cliente(), "limite2")
            ip_a = {"X-Forwarded-For": "10.0.0.1"}
            for i in range(3):
                r = entrar(cliente(), "limite1", f"equivocada-{i}-xx", **ip_a)
                comprobar(r.status_code == 401, f"intento {i + 1}: {r.status_code}")
            r = entrar(cliente(), "limite1", CONTRASENA, **ip_a)  # ya con la contraseña CORRECTA
            comprobar(r.status_code == 429 and r.json()["codigo"] == "demasiados_intentos", r.text)
            comprobar(int(r.headers["retry-after"]) == r.json()["reintentar_en_segundos"] and 1 <= int(r.headers["retry-after"]) <= 900, "Retry-After: " + r.headers["retry-after"])
            comprobar("set-cookie" not in r.headers, "un intento bloqueado no abre sesión")
            ok("Límite de intentos: tras 3 fallos desde la misma IP, el 4.º (aunque sea correcto) -> 429 con Retry-After")
            comprobar(entrar(cliente(), "limite2", CONTRASENA, **ip_a).status_code == 200, "otro usuario desde la misma IP no se ve afectado")
            comprobar(entrar(cliente(), "limite1", CONTRASENA, **{"X-Forwarded-For": "10.0.0.2"}).status_code == 200, "el usuario legítimo desde otra IP puede entrar (no se le puede bloquear la cuenta desde fuera)")
            # usuario inexistente: se limita igual (sin pistas para enumerar cuentas)
            for i in range(3):
                entrar(cliente(), "fantasma.x", "equivocada-xx-xx", **ip_a)
            rf = entrar(cliente(), "fantasma.x", "equivocada-xx-xx", **ip_a)
            comprobar(rf.status_code == 429, "un usuario inexistente se bloquea igual")
            # ataque distribuido: muchas IPs contra un mismo usuario (límite por usuario = 4 x 3 = 12)
            registrar(cliente(), "distribuido1")
            for i in range(12):
                entrar(cliente(), "distribuido1", f"mala-{i}-clave", **{"X-Forwarded-For": f"10.1.0.{i}"})
            r = entrar(cliente(), "distribuido1", CONTRASENA, **{"X-Forwarded-For": "10.1.9.9"})
            comprobar(r.status_code == 429, "12 fallos desde IPs distintas bloquean al usuario: " + r.text)
            # una IP probando muchos usuarios (límite por IP = 6 x 3 = 18)
            for i in range(18):
                entrar(cliente(), f"rociado{i}", "mala-clave-xxx", **{"X-Forwarded-For": "10.2.0.1"})
            r = entrar(cliente(), "limite2", CONTRASENA, **{"X-Forwarded-For": "10.2.0.1"})
            comprobar(r.status_code == 429, "18 fallos de una IP con usuarios distintos la bloquean: " + r.text)
            ok("Límite por usuario+IP, por usuario (ataque distribuido) y por IP (rociado); el usuario legítimo desde otra IP no queda bloqueado")
            # persistencia y expiración del bloqueo
            comprobar(sql("SELECT COUNT(*) AS n FROM intentos_acceso")[0]["n"] > 0, "los intentos se guardan en la base de datos")
            with TestClient(app) as reinicio:  # "reinicio" del servidor: el bloqueo se conserva
                comprobar(entrar(reinicio, "limite1", CONTRASENA, **ip_a).status_code == 429, "el bloqueo sobrevive al reinicio")
            sql("UPDATE intentos_acceso SET momento = momento - 1000")
            r = entrar(cliente(), "limite1", CONTRASENA, **ip_a)
            comprobar(r.status_code == 200, "pasada la ventana (15 min) vuelve a poder entrar: " + r.text)
            comprobar(sql("SELECT COUNT(*) AS n FROM intentos_acceso WHERE clave LIKE 'login:par:10.0.0.1|limite1'")[0]["n"] == 0, "un login correcto limpia los fallos del par usuario+IP")
            ok("Los bloqueos se guardan en SQLite (sobreviven al reinicio), caducan a los 15 min y un login correcto limpia los fallos")
        with entorno(SG_REGISTRO_MAX_POR_HORA="2", SG_CONFIAR_PROXY="1"):
            ip_r = {"X-Forwarded-For": "10.3.0.1"}
            comprobar(registrar(cliente(), "masa1", **ip_r).status_code == 201 and registrar(cliente(), "masa2", **ip_r).status_code == 201, "2 altas")
            r = registrar(cliente(), "masa3", **ip_r)
            comprobar(r.status_code == 429 and r.json()["codigo"] == "demasiados_intentos" and "retry-after" in r.headers, r.text)
            comprobar(registrar(cliente(), "masa4", **{"X-Forwarded-For": "10.3.0.2"}).status_code == 201, "otra IP no se ve afectada")
        ok("Límite de registros por IP y hora (429)")

        # ===================== H. Rutas públicas y privadas =====================
        PUBLICAS = {("GET", "/"), ("GET", "/salud"), ("GET", "/metricas"), ("POST", "/auth/registro"), ("POST", "/auth/login"),
                    ("POST", "/auth/logout"), ("GET", "/docs"), ("GET", "/redoc"), ("GET", "/openapi.json"), ("GET", "/docs/oauth2-redirect")}
        ESPERADAS_PRIVADAS = {
            ("POST", "/predecir"), ("POST", "/correo/extraer"), ("POST", "/lotes"), ("GET", "/lotes/{lote_id}"),
            ("POST", "/analisis/archivo"), ("POST", "/historial"), ("GET", "/historial"), ("GET", "/historial/exportar.csv"),
            ("GET", "/historial/{analisis_id}"), ("DELETE", "/historial/{analisis_id}"), ("POST", "/historial/eliminar"),
            ("POST", "/retroalimentacion"), ("GET", "/retroalimentacion"), ("GET", "/estadisticas/uso"), ("GET", "/auth/me")}
        encontradas = set()
        for ruta in app.routes:
            for metodo in getattr(ruta, "methods", None) or ():
                if metodo not in ("HEAD", "OPTIONS"):
                    encontradas.add((metodo, ruta.path))
        encontradas = {e for e in encontradas if not e[1].startswith("/static")}
        privadas = encontradas - PUBLICAS
        comprobar(privadas == ESPERADAS_PRIVADAS, f"rutas privadas inesperadas o faltantes: {privadas ^ ESPERADAS_PRIVADAS}")
        for metodo, ruta in sorted(privadas):
            url = re.sub(r"\{[^}]+\}", "1", ruta)
            kw = {"headers": {**H}}
            if metodo == "POST":
                if ruta in ("/analisis/archivo", "/correo/extraer"):
                    kw.update(content=b"hola", headers={**H, "Content-Type": "text/plain"})
                else:
                    kw.update(json={})
            r = cliente().request(metodo, url, **kw)
            comprobar(r.status_code == 401 and r.json()["codigo"] == "no_autenticado", f"{metodo} {ruta} sin sesión -> {r.status_code} {r.text[:120]}")
            r = cliente().request(metodo, url, **{**kw, "headers": {**kw["headers"], "Cookie": "sg_sesion=" + "B" * 43}})
            comprobar(r.status_code == 401 and r.json()["codigo"] == "sesion_expirada", f"{metodo} {ruta} con token falso -> {r.status_code}")
        ok(f"Enumeración de rutas: las {len(privadas)} rutas privadas devuelven 401 sin sesión y con token falso; ninguna ruta nueva quedó sin protección")
        m = json.loads((BACKEND / "models" / "metricas.json").read_text(encoding="utf-8"))
        sin = cliente()
        comprobar(sin.get("/salud").json() == {"estado": "ok", "modelo_cargado": True}, "/salud público")
        comprobar(sin.get("/metricas").status_code == 200 and sin.get("/metricas").json() == m, "/metricas público y sin cambios")
        comprobar(sin.get("/").status_code == 200 and sin.get("/static/css/tokens.css").status_code == 200, "interfaz estática pública")
        ok("/salud y /metricas siguen públicos; /metricas devuelve exactamente metricas.json")

    # Archivos protegidos
    esperado = {
        "backend/app/detector.py": "0baab83513a554f80b72d006e418bf76a25722d0529a60edb8c757c769a0351c",
        "backend/app/schemas.py": "61dbc2c7a716ccac5f824087ad0e781afa195eb42621e245b69a4f53b494b91b",
        "backend/models/clasificador.pkl": "99fa052be599b1f1ee591de036d8dc9e43a0724b41d0d5a6df58ad265453233c",
        "backend/models/metricas.json": "bf93833e92aaad6407e62dfed74e14b775b92f994bd731a9081df551fe02d5e5",
        "backend/data/dataset.csv": "e17235062818f114904adf0309d25278ea78f55cbfc04d705d66253628c71cab",
        "requirements.txt": "10d0def4755eb90baa91d66c7a9566f1c6d49c43c0fd7abdba47667f1490fc07",
    }
    for rel, h in esperado.items():
        comprobar(hashlib.sha256((PROYECTO / rel).read_bytes()).hexdigest() == h, f"¡{rel} CAMBIÓ!")
    ok("Archivos protegidos idénticos (SHA-256): detector, schemas, modelo, métricas, dataset y requirements")
    print(f"\n{GRUPOS} grupos de comprobaciones superados (API real y modelo real).")


if __name__ == "__main__":
    main()
