"""Endpoints de autenticación (Fase 6A).

POST /auth/registro   Crea la cuenta e INICIA SESIÓN (201). Cuerpo JSON: {"usuario", "contrasena"}.
POST /auth/login      Inicia sesión (200). Mismo cuerpo. Limita los intentos fallidos repetidos (429).
POST /auth/logout     Cierra y revoca la sesión actual (200). Exige el token CSRF si hay una sesión válida.
GET  /auth/me         Devuelve el usuario de la sesión actual y su token CSRF (200) o 401.

La sesión viaja en la cookie HttpOnly `sg_sesion`. El token CSRF NO está en ninguna cookie: el frontend lo recibe en
el JSON de registro/login/me y lo envía en la cabecera `X-CSRF-Token` en cada solicitud que modifica datos.
Contrato completo: frontend/documentacion/FASE6_CONTRATO_API.md
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from app import seguridad, usuarios
from app.dependencias import (ErrorAuth, Usuario, borrar_cookie, exigir_origen, exigir_usuario, ip_cliente,
                              poner_cookie, validar_origen)

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_USUARIO_LOGIN = 64
MAX_CONTRASENA_LOGIN = 1024
_hash_ficticio_cache: dict = {}


class Credenciales(BaseModel):
    usuario: str
    contrasena: str


def _epoch_a_iso(valor: float) -> str:
    return datetime.fromtimestamp(valor, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sin_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Cookie"


def _cuerpo_sesion(usuario: dict, token: str, expira_en: float) -> dict:
    return {"usuario": {"id": usuario["id"], "usuario": usuario["usuario"], "creado_en": usuario["creado_en"]},
            "csrf_token": seguridad.token_csrf(token), "sesion": {"expira_en": _epoch_a_iso(expira_en)}}


def _hash_ficticio() -> str:
    if "h" not in _hash_ficticio_cache:
        _hash_ficticio_cache["h"] = seguridad.hash_ficticio()
    return _hash_ficticio_cache["h"]


def _revocar_sesion_previa(request: Request) -> None:
    """Evita la fijación de sesión: al iniciar sesión se descarta la cookie anterior, si la había."""
    previo = request.cookies.get(seguridad.NOMBRE_COOKIE)
    if previo:
        usuarios.revocar_sesion(previo)


def _limitar(segundos: int, mensaje: str) -> ErrorAuth:
    return ErrorAuth(429, "demasiados_intentos", mensaje, extra={"reintentar_en_segundos": segundos},
                     cabeceras={"Retry-After": str(segundos)})


@router.post("/registro", status_code=201, dependencies=[Depends(exigir_origen)])
def registro(cred: Credenciales, request: Request, response: Response):
    _sin_cache(response)
    ip = ip_cliente(request)
    espera = usuarios.espera_registro(ip)
    if espera:
        raise _limitar(espera, "Se crearon demasiadas cuentas desde esta dirección. Intenta más tarde.")
    nombre = seguridad.normalizar_usuario(cred.usuario)
    campos = {}
    err_u = seguridad.validar_usuario(nombre)
    if err_u:
        campos["usuario"] = err_u
    err_c = seguridad.validar_contrasena(cred.contrasena, nombre if not err_u else "")
    if err_c:
        campos["contrasena"] = err_c
    if campos:
        raise ErrorAuth(422, "datos_invalidos", "Los datos de registro no son válidos.", extra={"campos": campos})
    usuarios.registrar_registro(ip)
    usuarios.limpiar_antiguos()
    try:
        nuevo = usuarios.crear_usuario(nombre, cred.contrasena)
    except usuarios.UsuarioDuplicado:
        raise ErrorAuth(409, "usuario_duplicado", "Ese nombre de usuario ya está en uso.",
                        extra={"campos": {"usuario": "Ese nombre de usuario ya está en uso."}})
    _revocar_sesion_previa(request)
    token, expira = usuarios.crear_sesion(nuevo["id"])
    poner_cookie(response, request, token, expira)
    return _cuerpo_sesion(nuevo, token, expira)


@router.post("/login", dependencies=[Depends(exigir_origen)])
def login(cred: Credenciales, request: Request, response: Response):
    _sin_cache(response)
    ip = ip_cliente(request)
    nombre = seguridad.normalizar_usuario(cred.usuario)[:MAX_USUARIO_LOGIN]
    espera = usuarios.espera_login(nombre, ip)
    if espera:
        raise _limitar(espera, "Demasiados intentos fallidos. Espera antes de volver a intentar.")
    fila = usuarios.buscar_para_login(nombre) if seguridad.validar_usuario(nombre) is None else None
    contrasena = cred.contrasena if len(cred.contrasena) <= MAX_CONTRASENA_LOGIN else ""
    if fila is not None and fila["activo"]:
        correcta = seguridad.verificar_contrasena(contrasena, fila["clave_hash"]) and bool(contrasena)
    else:
        seguridad.verificar_contrasena(contrasena, _hash_ficticio())  # mismo tiempo que con un usuario real
        correcta = False
    if not correcta:
        usuarios.registrar_fallo_login(nombre, ip)
        raise ErrorAuth(401, "credenciales_invalidas", "Usuario o contraseña incorrectos.")
    usuarios.limpiar_fallos_login(nombre, ip)
    if seguridad.necesita_rehash(fila["clave_hash"]):
        usuarios.actualizar_hash(fila["id"], seguridad.hashear_contrasena(contrasena))
    usuarios.limpiar_antiguos()
    _revocar_sesion_previa(request)
    token, expira = usuarios.crear_sesion(fila["id"])
    poner_cookie(response, request, token, expira)
    publico = usuarios.obtener_publico(fila["id"])
    return _cuerpo_sesion(publico, token, expira)


@router.post("/logout")
def logout(request: Request, response: Response):
    _sin_cache(response)
    validar_origen(request)
    token = request.cookies.get(seguridad.NOMBRE_COOKIE)
    sesion = usuarios.validar_sesion(token) if token else None
    if sesion is not None:
        enviado = request.headers.get(seguridad.ENCABEZADO_CSRF, "")
        if not enviado or not seguridad.comparar_seguro(enviado, seguridad.token_csrf(token)):
            raise ErrorAuth(403, "csrf_invalido", "Falta el token CSRF o no es válido.")
        usuarios.revocar_sesion(token)
    borrar_cookie(response, request)
    return {"cerrada": True, "habia_sesion": sesion is not None}


@router.get("/me")
def me(request: Request, usuario: Usuario = Depends(exigir_usuario)):
    return {"usuario": {"id": usuario["id"], "usuario": usuario["usuario"], "creado_en": usuario["creado_en"]},
            "csrf_token": usuario["csrf_token"], "sesion": {"expira_en": _epoch_a_iso(usuario["expira_en"])}}
