"""Dependencias de FastAPI para autenticación, validación de origen y CSRF (Fase 6A).

Uso en las rutas privadas:   router = APIRouter(dependencies=[Depends(exigir_usuario)])
y en el manejador, cuando se necesita el usuario:   usuario: Usuario = Depends(exigir_usuario)
(FastAPI ejecuta la dependencia UNA sola vez por solicitud aunque se declare dos veces).

Orden de las comprobaciones en un endpoint privado:
  1. Sesión (cookie `sg_sesion`)               -> 401 no_autenticado / sesion_expirada
  2. Origen (solo métodos que modifican)       -> 403 origen_no_permitido
  3. Token CSRF (solo métodos que modifican)   -> 403 csrf_invalido

El `user_id` sale SIEMPRE de la sesión validada en el servidor. Ninguna ruta lo lee del cuerpo, de la URL ni de
cabeceras enviadas por el cliente.
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

from fastapi import Request, Response

from app import seguridad, usuarios


class ErrorAuth(Exception):
    """Error de autenticación/seguridad con código HTTP, código estable para el frontend y cabeceras opcionales."""

    def __init__(self, estado: int, codigo: str, mensaje: str, *, extra: Optional[dict] = None,
                 cabeceras: Optional[dict] = None, borrar_cookie: bool = False):
        super().__init__(mensaje)
        self.estado = estado
        self.codigo = codigo
        self.mensaje = mensaje
        self.extra = extra or {}
        self.cabeceras = cabeceras or {}
        self.borrar_cookie = borrar_cookie


class Usuario(dict):
    """Usuario autenticado de la solicitud: id, usuario, creado_en, expira_en, csrf_token (y sesion_id)."""


# ---------- Utilidades de solicitud ----------
def ip_cliente(request: Request) -> str:
    """IP del cliente. Solo se confía en X-Forwarded-For si SG_CONFIAR_PROXY=1 (detrás de un proxy propio)."""
    if seguridad.confiar_en_proxy():
        reenviado = request.headers.get("x-forwarded-for", "")
        if reenviado:
            return reenviado.split(",")[0].strip()[:64] or "desconocida"
    return (request.client.host if request.client else "desconocida")[:64]


def _es_https(request: Request) -> bool:
    if seguridad.confiar_en_proxy() and request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    return request.url.scheme == "https"


def poner_cookie(response: Response, request: Request, token: str, expira_en: float) -> None:
    """Cookie de sesión: HttpOnly, SameSite (strict por defecto), Secure en HTTPS, ruta /."""
    restante = max(0, int(expira_en - usuarios.ahora()))
    response.set_cookie(
        key=seguridad.NOMBRE_COOKIE, value=token, max_age=restante, path="/",
        httponly=True, samesite=seguridad.cookie_samesite(),
        secure=seguridad.cookie_secure_forzada() or _es_https(request))


def borrar_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(
        key=seguridad.NOMBRE_COOKIE, path="/", httponly=True, samesite=seguridad.cookie_samesite(),
        secure=seguridad.cookie_secure_forzada() or _es_https(request))


# ---------- Origen ----------
def _netloc(valor: str) -> Optional[str]:
    try:
        partes = urlsplit(valor)
    except ValueError:
        return None
    if partes.scheme not in ("http", "https") or not partes.netloc:
        return None
    return partes.netloc.lower()


def validar_origen(request: Request) -> None:
    """Para métodos que modifican datos exige un Origin (o, si falta, un Referer) del MISMO sitio.

    Permitidos: el mismo host:puerto al que se hizo la solicitud, y los orígenes de SG_ORIGENES_PERMITIDOS.
    Si no llega ni Origin ni Referer, se rechaza (los navegadores siempre envían Origin en POST/PUT/PATCH/DELETE).
    """
    if request.method in seguridad.METODOS_SEGUROS:
        return
    origen = request.headers.get("origin")
    if origen is not None:
        if origen.strip().lower() == "null":
            raise ErrorAuth(403, "origen_no_permitido", "Origen no permitido.")
        netloc = _netloc(origen)
    else:
        referer = request.headers.get("referer")
        netloc = _netloc(referer) if referer else None
        origen = referer
    if netloc is None:
        raise ErrorAuth(403, "origen_no_permitido", "Falta el encabezado Origin (o es inválido).")
    host = (request.headers.get("host") or "").lower()
    if seguridad.confiar_en_proxy() and request.headers.get("x-forwarded-host"):
        host = request.headers["x-forwarded-host"].split(",")[0].strip().lower()
    if netloc == host:
        return
    partes = urlsplit(origen)
    if f"{partes.scheme}://{partes.netloc}".lower() in seguridad.origenes_permitidos_extra():
        return
    raise ErrorAuth(403, "origen_no_permitido", "Origen no permitido.")


def exigir_origen(request: Request) -> None:
    """Dependencia para /auth/login y /auth/registro (no hay sesión que proteger con CSRF, pero sí hay que
    impedir que otro sitio inicie o cree sesiones desde el navegador de la víctima)."""
    validar_origen(request)


# ---------- Sesión ----------
def obtener_sesion(request: Request) -> Optional[dict]:
    """Sesión válida de la cookie o None. No lanza errores."""
    token = request.cookies.get(seguridad.NOMBRE_COOKIE)
    if not token:
        return None
    return usuarios.validar_sesion(token)


def exigir_usuario(request: Request, response: Response) -> Usuario:
    token = request.cookies.get(seguridad.NOMBRE_COOKIE)
    if not token:
        raise ErrorAuth(401, "no_autenticado", "Debes iniciar sesión.")
    sesion = usuarios.validar_sesion(token)
    if sesion is None:
        raise ErrorAuth(401, "sesion_expirada", "Tu sesión expiró o ya no es válida. Inicia sesión de nuevo.",
                        borrar_cookie=True)
    validar_origen(request)
    csrf = seguridad.token_csrf(token)
    if request.method not in seguridad.METODOS_SEGUROS:
        enviado = request.headers.get(seguridad.ENCABEZADO_CSRF, "")
        if not enviado or not seguridad.comparar_seguro(enviado, csrf):
            raise ErrorAuth(403, "csrf_invalido", "Falta el token CSRF o no es válido.")
    # Datos privados: nunca deben guardarse en cachés compartidas ni reutilizarse sin cookie.
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Cookie"
    return Usuario(id=sesion["user_id"], usuario=sesion["usuario"], creado_en=sesion["creado_en"],
                   expira_en=sesion["expira_en"], csrf_token=csrf, sesion_id=sesion["sesion_id"])
