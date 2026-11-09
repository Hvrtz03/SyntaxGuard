"""Endpoints del análisis masivo (Fase 5). No modifican /salud, /metricas, /predecir ni /correo/extraer.

POST /lotes            Crea un lote (agrupa los correos de un análisis masivo).
GET  /lotes/{id}       Resumen del lote calculado con los registros guardados.
POST /analisis/archivo Cuerpo crudo (.eml/.txt) + cabeceras X-Nombre-Archivo y X-Lote-Id.
                       Extrae, analiza con el modelo real (el mismo detector que /predecir) y guarda el resultado.
                       Un correo inválido NO devuelve error HTTP: se guarda como registro con estado "error".
"""
from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app import almacen, correo, servicio
from app.almacen import ErrorAlmacen
from app.dependencias import Usuario, exigir_usuario
from app.rutas_correo import _leer_cuerpo

# Fase 6A: todas las rutas de este módulo exigen sesión (y CSRF en POST). El dueño de los datos es SIEMPRE
# el usuario de la sesión: el cliente no puede indicar otro.
router = APIRouter(tags=["analisis"], dependencies=[Depends(exigir_usuario)])


class LoteNuevo(BaseModel):
    total: Optional[int] = Field(default=None, ge=0, le=100000)


def _detector():
    # Importación diferida: main importa este módulo, así que no se puede importar main al cargar.
    from app import main
    return main.estado["detector"]


def _http(e: ErrorAlmacen) -> HTTPException:
    return HTTPException(status_code=e.estado, detail=e.mensaje)


@router.post("/lotes", status_code=201)
def crear_lote(req: LoteNuevo, usuario: Usuario = Depends(exigir_usuario)):
    try:
        return almacen.crear_lote(req.total, user_id=usuario["id"])
    except ErrorAlmacen as e:
        raise _http(e)


@router.get("/lotes/{lote_id}")
def resumen_lote(lote_id: int, usuario: Usuario = Depends(exigir_usuario)):
    try:
        return almacen.resumen_lote(lote_id, user_id=usuario["id"])
    except ErrorAlmacen as e:
        raise _http(e)


@router.post("/analisis/archivo")
async def analizar_archivo(request: Request, x_nombre_archivo: Optional[str] = Header(default=None),
                           x_lote_id: Optional[int] = Header(default=None),
                           usuario: Usuario = Depends(exigir_usuario)):
    tipo = (request.headers.get("content-type") or "").lower()
    if tipo.startswith("multipart/") or tipo.startswith("application/json"):
        raise HTTPException(status_code=415, detail="Envía el correo como cuerpo crudo, no como multipart ni JSON.")
    detector = _detector()
    if detector is None:
        raise HTTPException(status_code=503, detail="Modelo no cargado: no se puede analizar.")
    nombre = unquote(x_nombre_archivo) if x_nombre_archivo else None
    try:
        try:
            datos = await _leer_cuerpo(request)
        except correo.ErrorCorreo as e:  # demasiado grande: queda registrado como error del lote
            declarado = request.headers.get("content-length")
            tam = int(declarado) if declarado and declarado.isdigit() else None
            return await run_in_threadpool(servicio.registrar_error_archivo, nombre, tam, e.mensaje, x_lote_id,
                                           user_id=usuario["id"])
        return await run_in_threadpool(servicio.analizar_archivo, detector, datos, nombre, x_lote_id,
                                       user_id=usuario["id"])
    except ErrorAlmacen as e:
        raise _http(e)
