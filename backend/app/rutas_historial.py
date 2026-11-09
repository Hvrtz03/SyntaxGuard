"""Historial, retroalimentación y estadísticas de uso (Fase 5). Endpoints nuevos; no tocan los originales.

POST   /historial                 Guarda un análisis individual ya hecho por el modelo (/predecir).
GET    /historial                 Lista paginada con filtros: q, clasificacion, desde, hasta, tipo, lote_id, solo_ok.
GET    /historial/exportar.csv    CSV con los mismos filtros (declarado ANTES de /historial/{id}).
GET    /historial/{id}            Detalle de un análisis (incluye sus retroalimentaciones).
DELETE /historial/{id}            Elimina un registro (y su retroalimentación).
POST   /historial/eliminar        Elimina varios: {"ids": [...]}.
POST   /retroalimentacion         Guarda una opinión sobre un análisis. NO reentrena ni modifica el modelo.
GET    /retroalimentacion         Lista (más reciente primero); filtro opcional analisis_id.
GET    /estadisticas/uso          Estadísticas de uso calculadas con los registros reales.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app import almacen, servicio
from app.almacen import ErrorAlmacen
from app.dependencias import Usuario, exigir_usuario
from app.schemas import PrediccionResponse

# Fase 6A: todas las rutas exigen sesión (y CSRF en POST/DELETE) y trabajan SOLO con los datos del usuario de la sesión.
router = APIRouter(tags=["historial"], dependencies=[Depends(exigir_usuario)])


def _http(e: ErrorAlmacen) -> HTTPException:
    return HTTPException(status_code=e.estado, detail=e.mensaje)


class RegistroIndividual(BaseModel):
    resultado: PrediccionResponse
    nombre_archivo: Optional[str] = Field(default=None, max_length=255)
    asunto: Optional[str] = Field(default=None, max_length=500)
    remitente: Optional[str] = Field(default=None, max_length=500)
    fecha: Optional[str] = Field(default=None, max_length=500)
    tamano_bytes: Optional[int] = Field(default=None, ge=0)
    enlaces: List[str] = Field(default_factory=list, max_length=200)
    enlaces_total: int = Field(default=0, ge=0)
    adjuntos_ignorados: int = Field(default=0, ge=0)
    advertencias: List[str] = Field(default_factory=list, max_length=50)


class Eliminacion(BaseModel):
    ids: List[int] = Field(..., min_length=1, max_length=almacen.MAX_IDS)


class RetroNueva(BaseModel):
    analisis_id: int = Field(..., ge=1)
    de_acuerdo: bool
    comentario: Optional[str] = Field(default=None, max_length=1000)


@router.post("/historial", status_code=201)
def registrar(req: RegistroIndividual, usuario: Usuario = Depends(exigir_usuario)):
    try:
        return servicio.registrar_individual(req.model_dump(), user_id=usuario["id"])
    except ErrorAlmacen as e:
        raise _http(e)


@router.get("/historial")
def listar(q: Optional[str] = Query(default=None, max_length=200), clasificacion: Optional[str] = None,
           desde: Optional[str] = None, hasta: Optional[str] = None, tipo: Optional[str] = None,
           lote_id: Optional[int] = None, solo_ok: bool = False, pagina: int = 1, por_pagina: int = 25,
           usuario: Usuario = Depends(exigir_usuario)):
    try:
        return almacen.listar_analisis(user_id=usuario["id"], q=q, clasificacion=clasificacion, desde=desde, hasta=hasta, tipo=tipo,
                                       lote_id=lote_id, solo_ok=solo_ok, pagina=pagina, por_pagina=por_pagina)
    except ErrorAlmacen as e:
        raise _http(e)


@router.get("/historial/exportar.csv")
def exportar(q: Optional[str] = Query(default=None, max_length=200), clasificacion: Optional[str] = None,
             desde: Optional[str] = None, hasta: Optional[str] = None, tipo: Optional[str] = None,
             lote_id: Optional[int] = None, usuario: Usuario = Depends(exigir_usuario)):
    try:
        datos = almacen.exportar_csv(user_id=usuario["id"], q=q, clasificacion=clasificacion, desde=desde, hasta=hasta, tipo=tipo,
                                     lote_id=lote_id)
    except ErrorAlmacen as e:
        raise _http(e)
    nombre = f"syntaxguard_lote_{lote_id}.csv" if lote_id is not None else "syntaxguard_historial.csv"
    return Response(content=datos, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"', "Cache-Control": "no-store",
                             "Vary": "Cookie"})


@router.get("/historial/{analisis_id}")
def detalle(analisis_id: int, usuario: Usuario = Depends(exigir_usuario)):
    try:
        return almacen.obtener_analisis(analisis_id, user_id=usuario["id"])
    except ErrorAlmacen as e:
        raise _http(e)


@router.delete("/historial/{analisis_id}")
def eliminar_uno(analisis_id: int, usuario: Usuario = Depends(exigir_usuario)):
    try:
        n = almacen.eliminar_analisis([analisis_id], user_id=usuario["id"])
    except ErrorAlmacen as e:
        raise _http(e)
    if n == 0:
        raise HTTPException(status_code=404, detail="El análisis no existe.")
    return {"eliminados": n}


@router.post("/historial/eliminar")
def eliminar_varios(req: Eliminacion, usuario: Usuario = Depends(exigir_usuario)):
    try:
        return {"eliminados": almacen.eliminar_analisis(req.ids, user_id=usuario["id"])}
    except ErrorAlmacen as e:
        raise _http(e)


@router.post("/retroalimentacion", status_code=201)
def guardar_retro(req: RetroNueva, usuario: Usuario = Depends(exigir_usuario)):
    try:
        return almacen.guardar_retro(req.analisis_id, req.de_acuerdo, req.comentario, user_id=usuario["id"])
    except ErrorAlmacen as e:
        raise _http(e)


@router.get("/retroalimentacion")
def listar_retro(analisis_id: Optional[int] = None, pagina: int = 1, por_pagina: int = 25,
                 usuario: Usuario = Depends(exigir_usuario)):
    try:
        return almacen.listar_retro(user_id=usuario["id"], analisis_id=analisis_id, pagina=pagina, por_pagina=por_pagina)
    except ErrorAlmacen as e:
        raise _http(e)


@router.get("/estadisticas/uso")
def estadisticas_uso(usuario: Usuario = Depends(exigir_usuario)):
    return almacen.estadisticas_uso(user_id=usuario["id"])
