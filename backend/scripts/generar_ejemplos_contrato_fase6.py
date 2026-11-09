"""Ejecuta el backend REAL de la Fase 6A y muestra las solicitudes/respuestas que aparecen en
frontend/documentacion/FASE6_CONTRATO_API.md. Sirve para comprobar que los ejemplos del contrato siguen siendo reales.

Uso (desde la raíz del proyecto):   python backend\\scripts\\generar_ejemplos_contrato_fase6.py
Usa una base de datos temporal. Los valores aleatorios (token de sesión, CSRF) se muestran abreviados.
"""
import json
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import auth_helper  # noqa: E402,F401
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

O = {"Origin": "http://testserver"}


def abreviar(txt):
    txt = re.sub(r'("csrf_token": ?")([0-9a-f]{8})[0-9a-f]{56}"', r'\1\2…(64 hex)"', txt)
    txt = re.sub(r"(sg_sesion=)([A-Za-z0-9_-]{6})[A-Za-z0-9_-]{37}", r"\1\2…(43 caracteres)", txt)
    return re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", "2026-11-07T20:15:00Z", txt)


def mostrar(titulo, metodo, ruta, cuerpo, r, cab_req=None, cab_resp=("set-cookie", "retry-after", "cache-control")):
    print(f"\n### {titulo}")
    print(f"{metodo} {ruta}")
    for k, v in (cab_req or {}).items():
        print(f"{k}: {v}")
    if cuerpo is not None:
        print(json.dumps(cuerpo, ensure_ascii=False))
    print(f"--> HTTP {r.status_code}")
    for k in cab_resp:
        for v in r.headers.get_list(k):
            print(f"{k}: {abreviar(v)}")
    try:
        txt = json.dumps(r.json(), ensure_ascii=False, indent=2)
        if len(txt) > 700:
            j = r.json()
            if "rasgos_detectados" in j:
                j["rasgos_detectados"] = j["rasgos_detectados"][:1] + ["…"]
            txt = json.dumps(j, ensure_ascii=False, indent=2)
        print(abreviar(txt))
    except Exception:
        print(r.text[:200])


with TestClient(app) as base:
    c = TestClient(app)
    cred = {"usuario": "ana", "contrasena": "una-clave-larga-2026"}
    mostrar("Registro correcto", "POST", "/auth/registro", {**cred, "contrasena": "***"}, c.post("/auth/registro", json=cred, headers=O), O)
    csrf = c.get("/auth/me").json()["csrf_token"]
    mostrar("Registro: usuario repetido", "POST", "/auth/registro", {"usuario": "Ana", "contrasena": "***"}, TestClient(app).post("/auth/registro", json={**cred, "usuario": "Ana"}, headers=O), O)
    mostrar("Registro: datos inválidos", "POST", "/auth/registro", {"usuario": "a b", "contrasena": "corta"}, TestClient(app).post("/auth/registro", json={"usuario": "a b", "contrasena": "corta"}, headers=O), O)
    mostrar("Registro: cuerpo incompleto", "POST", "/auth/registro", {"usuario": "ana2"}, TestClient(app).post("/auth/registro", json={"usuario": "ana2"}, headers=O), O)
    c2 = TestClient(app)
    mostrar("Login correcto", "POST", "/auth/login", {"usuario": "ana", "contrasena": "***"}, c2.post("/auth/login", json=cred, headers=O), O)
    mostrar("Login incorrecto", "POST", "/auth/login", {"usuario": "ana", "contrasena": "***"}, TestClient(app).post("/auth/login", json={**cred, "contrasena": "otra-clave-xxxx"}, headers=O), O)
    csrf2 = c2.get("/auth/me").json()["csrf_token"]
    mostrar("Sesión actual", "GET", "/auth/me", None, c2.get("/auth/me"))
    mostrar("Sin sesión", "GET", "/auth/me", None, TestClient(app).get("/auth/me"))
    mostrar("Cookie inválida o expirada", "GET", "/auth/me", None, TestClient(app).get("/auth/me", headers={"Cookie": "sg_sesion=" + "A" * 43}))
    mostrar("Endpoint privado sin token CSRF", "POST", "/predecir", {"texto": "WINNER!! Claim your FREE prize now"}, c2.post("/predecir", json={"texto": "WINNER!! Claim your FREE prize now"}, headers=O), O)
    cab = {**O, "X-CSRF-Token": csrf2}
    mostrar("Endpoint privado correcto", "POST", "/predecir", {"texto": "WINNER!! Claim your FREE prize now"}, c2.post("/predecir", json={"texto": "WINNER!! Claim your FREE prize now"}, headers=cab), {**O, "X-CSRF-Token": "<csrf_token>"})
    mostrar("Origen no permitido", "POST", "/predecir", {"texto": "x"}, c2.post("/predecir", json={"texto": "x"}, headers={"Origin": "http://sitio-malicioso.example", "X-CSRF-Token": csrf2}), {"Origin": "http://sitio-malicioso.example", "X-CSRF-Token": "<csrf_token>"})
    mostrar("Historial (lectura, sin CSRF)", "GET", "/historial", None, c2.get("/historial"))
    mostrar("Historial sin sesión", "GET", "/historial", None, TestClient(app).get("/historial"))
    mostrar("Detalle de un id ajeno o inexistente", "GET", "/historial/999", None, c2.get("/historial/999"))
    mostrar("Cierre de sesión", "POST", "/auth/logout", None, c2.post("/auth/logout", headers=cab), {**O, "X-CSRF-Token": "<csrf_token>"})
    os.environ["SG_LOGIN_MAX_INTENTOS"] = "3"
    for _ in range(3):
        TestClient(app).post("/auth/login", json={**cred, "contrasena": "equivocada-xxx"}, headers=O)
    mostrar("Demasiados intentos (con la contraseña correcta)", "POST", "/auth/login", {"usuario": "ana", "contrasena": "***"}, TestClient(app).post("/auth/login", json=cred, headers=O), O)
