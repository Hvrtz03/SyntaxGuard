"""Usuarios, sesiones e intentos de acceso (Fase 6A) sobre SQLite. Sin FastAPI.

Reglas:
  * Del token de sesión SOLO se guarda su HMAC (seguridad.hash_token). El token real solo vive en la cookie.
  * Una sesión es válida si: no está revocada, no pasó su expiración absoluta, no superó el tiempo de inactividad
    y su usuario sigue activo.
  * Los intentos fallidos de inicio de sesión se guardan en la base (sobreviven a un reinicio del servidor).
  * Este módulo no decide nada sobre HTTP: las rutas (rutas_auth.py) y las dependencias (dependencias.py) lo usan.
"""
from __future__ import annotations

import sqlite3
import time

from app import seguridad
from app.almacen import _iso, conexion

ACTUALIZAR_USO_CADA_SEG = 60  # no se escribe en la base en cada solicitud


class UsuarioDuplicado(Exception):
    pass


def ahora() -> float:
    return time.time()


def _usuario_publico(fila) -> dict:
    return {"id": fila["id"], "usuario": fila["usuario"], "creado_en": _iso(fila["creado_en"])}


# ---------- Usuarios ----------
def crear_usuario(usuario: str, contrasena: str) -> dict:
    """`usuario` ya validado y normalizado. Lanza UsuarioDuplicado si ya existe."""
    clave_hash = seguridad.hashear_contrasena(contrasena)
    try:
        with conexion() as con:
            cur = con.execute("INSERT INTO usuarios (usuario, clave_hash) VALUES (?, ?)", (usuario, clave_hash))
            fila = con.execute("SELECT id, usuario, creado_en FROM usuarios WHERE id=?", (cur.lastrowid,)).fetchone()
    except sqlite3.IntegrityError as e:
        raise UsuarioDuplicado(usuario) from e
    return _usuario_publico(fila)


def buscar_para_login(usuario: str):
    """Devuelve (id, usuario, clave_hash, activo) o None."""
    with conexion() as con:
        return con.execute("SELECT id, usuario, clave_hash, activo FROM usuarios WHERE usuario=?",
                           (usuario,)).fetchone()


def actualizar_hash(user_id: int, nuevo_hash: str) -> None:
    with conexion() as con:
        con.execute("UPDATE usuarios SET clave_hash=? WHERE id=?", (nuevo_hash, user_id))


def obtener_publico(user_id: int) -> dict | None:
    with conexion() as con:
        fila = con.execute("SELECT id, usuario, creado_en FROM usuarios WHERE id=?", (user_id,)).fetchone()
    return _usuario_publico(fila) if fila else None


# ---------- Sesiones ----------
def crear_sesion(user_id: int) -> tuple[str, float]:
    """Crea una sesión nueva. Devuelve (token en claro, expira_en epoch). El token en claro NO se guarda."""
    token = seguridad.nuevo_token()
    t = ahora()
    expira = t + seguridad.sesion_max_segundos()
    with conexion() as con:
        con.execute("INSERT INTO sesiones (user_id, token_hash, creada_en, expira_en, ultimo_uso) VALUES (?,?,?,?,?)",
                    (user_id, seguridad.hash_token(token), t, expira, t))
        # Tope de sesiones activas por usuario: se revocan las más antiguas.
        activas = con.execute(
            "SELECT id FROM sesiones WHERE user_id=? AND revocada_en IS NULL AND expira_en > ? "
            "ORDER BY creada_en DESC, id DESC", (user_id, t)).fetchall()
        sobran = [f["id"] for f in activas[seguridad.sesiones_max_por_usuario():]]
        if sobran:
            con.execute(f"UPDATE sesiones SET revocada_en=? WHERE id IN ({','.join('?' * len(sobran))})",
                        [t] + sobran)
    return token, expira


def validar_sesion(token: str):
    """Devuelve {'user_id','usuario','creado_en','expira_en','sesion_id'} o None si el token no sirve.

    Motivos de rechazo (todos devuelven None): formato inválido, desconocido, revocada, expirada, inactiva, usuario
    desactivado. No distingue el motivo para no dar pistas.
    """
    if not seguridad.token_con_formato_valido(token):
        return None
    t = ahora()
    with conexion() as con:
        f = con.execute(
            "SELECT s.id AS sesion_id, s.user_id, s.expira_en, s.ultimo_uso, s.revocada_en, "
            "u.usuario, u.creado_en, u.activo FROM sesiones s JOIN usuarios u ON u.id=s.user_id "
            "WHERE s.token_hash=?", (seguridad.hash_token(token),)).fetchone()
        if f is None or f["revocada_en"] is not None or not f["activo"]:
            return None
        if f["expira_en"] <= t or (t - f["ultimo_uso"]) > seguridad.sesion_inactividad_segundos():
            return None
        if t - f["ultimo_uso"] >= ACTUALIZAR_USO_CADA_SEG:
            con.execute("UPDATE sesiones SET ultimo_uso=? WHERE id=?", (t, f["sesion_id"]))
    return {"sesion_id": f["sesion_id"], "user_id": f["user_id"], "usuario": f["usuario"],
            "creado_en": _iso(f["creado_en"]), "expira_en": f["expira_en"]}


def revocar_sesion(token: str) -> bool:
    """Revoca la sesión de este token. True si había una sesión activa."""
    if not seguridad.token_con_formato_valido(token):
        return False
    with conexion() as con:
        cur = con.execute("UPDATE sesiones SET revocada_en=? WHERE token_hash=? AND revocada_en IS NULL",
                          (ahora(), seguridad.hash_token(token)))
        return cur.rowcount > 0


def revocar_sesiones_usuario(user_id: int) -> int:
    """Revoca todas las sesiones activas del usuario (p. ej. tras cambiar la contraseña)."""
    with conexion() as con:
        cur = con.execute("UPDATE sesiones SET revocada_en=? WHERE user_id=? AND revocada_en IS NULL",
                          (ahora(), user_id))
        return cur.rowcount


def limpiar_antiguos() -> None:
    """Borra sesiones vencidas/revocadas hace más de un día e intentos de más de un día."""
    t = ahora()
    corte = t - 86400
    with conexion() as con:
        con.execute("DELETE FROM sesiones WHERE expira_en < ? OR (revocada_en IS NOT NULL AND revocada_en < ?)",
                    (corte, corte))
        con.execute("DELETE FROM intentos_acceso WHERE momento < ?", (corte,))


# ---------- Límite de intentos ----------
def _claves_login(usuario: str, ip: str) -> dict:
    return {"par": f"login:par:{ip}|{usuario}", "usuario": f"login:usuario:{usuario}", "ip": f"login:ip:{ip}"}


def _limites_login() -> dict:
    base = seguridad.login_max_intentos()
    return {"par": base, "usuario": base * 4, "ip": base * 6}


def _espera(con, clave: str, limite: int, ventana: int, t: float) -> int:
    """Segundos que faltan para poder reintentar (0 si no está bloqueado)."""
    momentos = [f["momento"] for f in con.execute(
        "SELECT momento FROM intentos_acceso WHERE clave=? AND momento > ? ORDER BY momento ASC",
        (clave, t - ventana))]
    if len(momentos) < limite:
        return 0
    # El bloqueo termina cuando el intento (len - limite) sale de la ventana.
    return max(1, int(momentos[len(momentos) - limite] + ventana - t) + 1)


def espera_login(usuario: str, ip: str) -> int:
    """Segundos de bloqueo vigentes para este intento de inicio de sesión (0 = puede intentar)."""
    ventana, t = seguridad.login_ventana_segundos(), ahora()
    claves, limites = _claves_login(usuario, ip), _limites_login()
    with conexion() as con:
        return max(_espera(con, claves[k], limites[k], ventana, t) for k in claves)


def registrar_fallo_login(usuario: str, ip: str) -> None:
    t = ahora()
    with conexion() as con:
        for clave in _claves_login(usuario, ip).values():
            con.execute("INSERT INTO intentos_acceso (clave, momento) VALUES (?, ?)", (clave, t))


def limpiar_fallos_login(usuario: str, ip: str) -> None:
    """Tras un inicio de sesión correcto se olvidan los fallos de este usuario desde esta IP."""
    with conexion() as con:
        con.execute("DELETE FROM intentos_acceso WHERE clave=?", (_claves_login(usuario, ip)["par"],))


def espera_registro(ip: str) -> int:
    """Segundos de espera si esta IP ya creó demasiadas cuentas en la última hora."""
    t = ahora()
    with conexion() as con:
        return _espera(con, f"registro:ip:{ip}", seguridad.registro_max_por_hora(), 3600, t)


def registrar_registro(ip: str) -> None:
    with conexion() as con:
        con.execute("INSERT INTO intentos_acceso (clave, momento) VALUES (?, ?)", (f"registro:ip:{ip}", ahora()))
