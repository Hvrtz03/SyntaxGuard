"""Ayuda común de las pruebas (Fase 6A). Solo para pruebas: la aplicación NO importa este archivo.

Al importarlo (antes de crear el TestClient) deja la configuración lista:
  * SG_DB            Una base de datos TEMPORAL, para no tocar backend/storage/syntaxguard.db (si no estaba definida).
  * SG_SECRET_KEY    Una clave aleatoria de esta ejecución (las sesiones sobreviven a "reiniciar" la app en la prueba).
  * SG_PBKDF2_ITER   1000 iteraciones: solo para que las pruebas sean rápidas. La aplicación usa 600000 por defecto;
                     test_auth_fase6.py comprueba ese valor y el formato del hash.
"""
import os
import secrets
import tempfile

os.environ.setdefault("SG_DB", os.path.join(tempfile.mkdtemp(prefix="sg_auth_"), "prueba.db"))
os.environ.setdefault("SG_SECRET_KEY", secrets.token_urlsafe(48))
os.environ.setdefault("SG_PBKDF2_ITER", "1000")
os.environ.setdefault("SG_REGISTRO_MAX_POR_HORA", "1000")

ORIGEN = "http://testserver"  # el TestClient de Starlette usa este host
CONTRASENA = "Contrasena-de-prueba-2026"


def iniciar_sesion(cliente, usuario="regresion", contrasena=CONTRASENA):
    """Registra (o inicia sesión con) un usuario y deja Origin y X-CSRF-Token como cabeceras predeterminadas del
    cliente, igual que hará el frontend. Devuelve el JSON de la sesión."""
    cliente.headers.update({"Origin": ORIGEN})
    r = cliente.post("/auth/registro", json={"usuario": usuario, "contrasena": contrasena})
    if r.status_code == 409:
        r = cliente.post("/auth/login", json={"usuario": usuario, "contrasena": contrasena})
    assert r.status_code in (200, 201), r.text
    datos = r.json()
    cliente.headers["X-CSRF-Token"] = datos["csrf_token"]
    return datos
