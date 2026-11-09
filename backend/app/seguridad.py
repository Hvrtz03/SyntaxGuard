"""Primitivas de seguridad de SyntaxGuard (Fase 6A). Sin FastAPI y sin base de datos: se prueban por separado.

Qué hay aquí:
  * Contraseñas: PBKDF2-HMAC-SHA256 con sal aleatoria de 16 bytes (formato autodescriptivo, ver `hashear_contrasena`).
  * Tokens de sesión: 256 bits aleatorios (`secrets`). En la base de datos solo se guarda su HMAC-SHA256.
  * Token CSRF: HMAC del token de sesión con la clave del servidor; no se guarda en ningún lado.
  * Validación del nombre de usuario y de la contraseña.
  * Lectura de la configuración desde variables de entorno (SG_*). NO hay claves escritas en el código.

Secretos:
  SG_SECRET_KEY  Clave del servidor (mínimo 32 caracteres). Genera una con:
                     python -c "import secrets; print(secrets.token_urlsafe(48))"
                 Si falta y SG_ENTORNO != produccion, se genera una clave ALEATORIA EN MEMORIA al arrancar
                 (las sesiones dejan de ser válidas al reiniciar el servidor y se registra una advertencia).
                 Si falta y SG_ENTORNO=produccion, el servidor NO arranca.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import unicodedata

log = logging.getLogger("syntaxguard.seguridad")

# ---------- Configuración (se lee en cada uso para poder cambiarla en pruebas) ----------
ALGORITMO_HASH = "pbkdf2_sha256"
ITERACIONES_PREDETERMINADAS = 600_000   # OWASP (2023) para PBKDF2-HMAC-SHA256
ITERACIONES_MINIMAS = 1_000             # suelo técnico; el valor real de producción debe ser el predeterminado
ITERACIONES_MAXIMAS_ACEPTADAS = 5_000_000  # tope al VERIFICAR un hash guardado (evita cargas absurdas)
LONGITUD_SAL = 16
LONGITUD_HASH = 32

NOMBRE_COOKIE = "sg_sesion"
ENCABEZADO_CSRF = "X-CSRF-Token"

METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})

_clave_efimera: bytes | None = None


class ErrorConfiguracion(RuntimeError):
    """La configuración de seguridad es inválida o insuficiente."""


def _entero_env(nombre: str, defecto: int, minimo: int = 1) -> int:
    crudo = os.environ.get(nombre)
    if crudo is None or not crudo.strip():
        return defecto
    try:
        valor = int(crudo.strip())
    except ValueError as e:
        raise ErrorConfiguracion(f"{nombre} debe ser un entero.") from e
    if valor < minimo:
        raise ErrorConfiguracion(f"{nombre} debe ser mayor o igual que {minimo}.")
    return valor


def _booleano_env(nombre: str, defecto: bool = False) -> bool:
    crudo = os.environ.get(nombre)
    if crudo is None or not crudo.strip():
        return defecto
    return crudo.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


def es_produccion() -> bool:
    return os.environ.get("SG_ENTORNO", "desarrollo").strip().lower() == "produccion"


def iteraciones_actuales() -> int:
    return _entero_env("SG_PBKDF2_ITER", ITERACIONES_PREDETERMINADAS, ITERACIONES_MINIMAS)


def sesion_max_segundos() -> int:
    return _entero_env("SG_SESION_MAX_HORAS", 24 * 7) * 3600


def sesion_inactividad_segundos() -> int:
    return _entero_env("SG_SESION_INACTIVIDAD_HORAS", 24) * 3600


def sesiones_max_por_usuario() -> int:
    return _entero_env("SG_SESIONES_MAX", 10)


def login_max_intentos() -> int:
    return _entero_env("SG_LOGIN_MAX_INTENTOS", 5)


def login_ventana_segundos() -> int:
    return _entero_env("SG_LOGIN_VENTANA_SEG", 15 * 60)


def registro_max_por_hora() -> int:
    return _entero_env("SG_REGISTRO_MAX_POR_HORA", 10)


def confiar_en_proxy() -> bool:
    return _booleano_env("SG_CONFIAR_PROXY", False)


def cookie_secure_forzada() -> bool:
    return _booleano_env("SG_COOKIE_SECURE", False) or es_produccion()


def cookie_samesite() -> str:
    valor = os.environ.get("SG_COOKIE_SAMESITE", "strict").strip().lower()
    if valor not in ("strict", "lax"):
        raise ErrorConfiguracion("SG_COOKIE_SAMESITE debe ser strict o lax.")
    return valor


def origenes_permitidos_extra() -> frozenset:
    crudo = os.environ.get("SG_ORIGENES_PERMITIDOS", "")
    return frozenset(o.strip().rstrip("/").lower() for o in crudo.split(",") if o.strip())


# ---------- Clave del servidor ----------
def verificar_configuracion() -> None:
    """Se llama al arrancar. Falla (ErrorConfiguracion) si la configuración de seguridad no es aceptable."""
    global _clave_efimera
    clave = os.environ.get("SG_SECRET_KEY", "").strip()
    if clave:
        if len(clave) < 32:
            raise ErrorConfiguracion("SG_SECRET_KEY debe tener al menos 32 caracteres.")
        _clave_efimera = None
    elif es_produccion():
        raise ErrorConfiguracion("Falta SG_SECRET_KEY (obligatoria con SG_ENTORNO=produccion).")
    else:
        _clave_efimera = secrets.token_bytes(48)
        log.warning("SG_SECRET_KEY no está definida: se usa una clave aleatoria en memoria. "
                    "Las sesiones se perderán al reiniciar. Define SG_SECRET_KEY en .env.")
    # Valida de una vez el resto de variables para fallar al arrancar y no en la primera solicitud.
    for fn in (iteraciones_actuales, sesion_max_segundos, sesion_inactividad_segundos, sesiones_max_por_usuario,
               login_max_intentos, login_ventana_segundos, registro_max_por_hora, cookie_samesite):
        fn()


def clave_secreta() -> bytes:
    global _clave_efimera
    clave = os.environ.get("SG_SECRET_KEY", "").strip()
    if clave:
        if len(clave) < 32:
            raise ErrorConfiguracion("SG_SECRET_KEY debe tener al menos 32 caracteres.")
        return clave.encode("utf-8")
    if es_produccion():
        raise ErrorConfiguracion("Falta SG_SECRET_KEY (obligatoria con SG_ENTORNO=produccion).")
    if _clave_efimera is None:  # se llegó aquí sin pasar por verificar_configuracion (p. ej. pruebas unitarias)
        _clave_efimera = secrets.token_bytes(48)
    return _clave_efimera


# ---------- Contraseñas ----------
def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode("ascii")


def _normalizar_contrasena(contrasena: str) -> bytes:
    return unicodedata.normalize("NFKC", contrasena).encode("utf-8")


def hashear_contrasena(contrasena: str, *, iteraciones: int | None = None) -> str:
    """Devuelve 'pbkdf2_sha256$<iteraciones>$<sal base64>$<hash base64>' con una sal nueva de 16 bytes."""
    it = iteraciones or iteraciones_actuales()
    sal = secrets.token_bytes(LONGITUD_SAL)
    dk = hashlib.pbkdf2_hmac("sha256", _normalizar_contrasena(contrasena), sal, it, dklen=LONGITUD_HASH)
    return f"{ALGORITMO_HASH}${it}${_b64(sal)}${_b64(dk)}"


def _partes_hash(guardado: str):
    try:
        alg, it, sal_b64, hash_b64 = guardado.split("$")
        if alg != ALGORITMO_HASH:
            return None
        it = int(it)
        if not ITERACIONES_MINIMAS <= it <= ITERACIONES_MAXIMAS_ACEPTADAS:
            return None
        return it, base64.b64decode(sal_b64, validate=True), base64.b64decode(hash_b64, validate=True)
    except (ValueError, TypeError):
        return None


def verificar_contrasena(contrasena: str, guardado: str) -> bool:
    partes = _partes_hash(guardado or "")
    if partes is None:
        return False
    it, sal, esperado = partes
    dk = hashlib.pbkdf2_hmac("sha256", _normalizar_contrasena(contrasena), sal, it, dklen=len(esperado))
    return hmac.compare_digest(dk, esperado)


def necesita_rehash(guardado: str) -> bool:
    """True si el hash se hizo con menos iteraciones que las configuradas ahora (se actualiza al iniciar sesión)."""
    partes = _partes_hash(guardado or "")
    return partes is None or partes[0] < iteraciones_actuales()


def hash_ficticio() -> str:
    """Hash de una contraseña aleatoria (se usa para gastar el mismo tiempo cuando el usuario no existe)."""
    return hashear_contrasena(secrets.token_urlsafe(24))


# ---------- Tokens de sesión y CSRF ----------
def nuevo_token() -> str:
    """Token de sesión: 32 bytes aleatorios (256 bits) en base64url, 43 caracteres."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Lo único que se guarda en SQLite del token de sesión (HMAC-SHA256 con la clave del servidor)."""
    return hmac.new(clave_secreta(), b"sesion|" + token.encode("utf-8"), hashlib.sha256).hexdigest()


def token_csrf(token_sesion: str) -> str:
    """Token CSRF ligado a la sesión. Se recalcula en cada solicitud; no se almacena."""
    return hmac.new(clave_secreta(), b"csrf|" + token_sesion.encode("utf-8"), hashlib.sha256).hexdigest()


def comparar_seguro(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def token_con_formato_valido(token: str | None) -> bool:
    return bool(token) and TOKEN_RE.match(token) is not None


# ---------- Validación de datos de registro ----------
USUARIO_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
CONTRASENA_MIN = 10
CONTRASENA_MAX = 128
_COMUNES = frozenset({
    "password12", "password123", "1234567890", "12345678910", "qwertyuiop", "qwerty1234", "contrasena1",
    "contraseña1", "contrasena123", "iloveyou12", "abcdefghij", "abc1234567", "admin12345", "letmein123",
    "welcome123", "1q2w3e4r5t", "0123456789", "passw0rd12", "syntaxguard", "syntaxguard1",
})


def normalizar_usuario(usuario: str) -> str:
    return unicodedata.normalize("NFKC", usuario).strip().lower()


def validar_usuario(usuario) -> str | None:
    """Devuelve un mensaje de error o None si el nombre de usuario es válido (ya normalizado)."""
    if not isinstance(usuario, str):
        return "El usuario debe ser texto."
    if not USUARIO_RE.match(usuario):
        return ("El usuario debe tener de 3 a 32 caracteres: letras minúsculas sin acento, números, punto, "
                "guion o guion bajo, y empezar con letra o número.")
    return None


def validar_contrasena(contrasena, usuario: str = "") -> str | None:
    """Devuelve un mensaje de error o None si la contraseña cumple la política."""
    if not isinstance(contrasena, str):
        return "La contraseña debe ser texto."
    c = unicodedata.normalize("NFKC", contrasena)
    if len(c) < CONTRASENA_MIN:
        return f"La contraseña debe tener al menos {CONTRASENA_MIN} caracteres."
    if len(c) > CONTRASENA_MAX:
        return f"La contraseña no puede superar {CONTRASENA_MAX} caracteres."
    if not c.strip():
        return "La contraseña no puede ser solo espacios."
    if len(set(c)) == 1:
        return "La contraseña no puede repetir un solo carácter."
    bajo = c.lower()
    if bajo in _COMUNES:
        return "La contraseña es demasiado común."
    if usuario and len(usuario) >= 3 and usuario in bajo:
        return "La contraseña no puede contener el nombre de usuario."
    return None
