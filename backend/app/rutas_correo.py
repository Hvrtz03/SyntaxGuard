"""Endpoint de extracción de correos (Fase 3).

POST /correo/extraer
  Cuerpo: los bytes crudos del correo (.eml) o el texto pegado. SIN multipart.
  Cabecera opcional: X-Nombre-Archivo (nombre del archivo, codificado con encodeURIComponent).
  Respuesta: campos del mensaje + `texto` y `html` listos para enviarse a /predecir.

Este endpoint solo EXTRAE: no clasifica, no guarda nada y no usa el modelo.
No modifica ningún endpoint existente.
"""
from typing import List, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.correo import MAX_BYTES, ErrorCorreo, procesar
from app.dependencias import exigir_usuario

# Fase 6A: /correo/extraer exige sesión (y token CSRF, porque es POST).
router = APIRouter(prefix="/correo", tags=["correo"], dependencies=[Depends(exigir_usuario)])


class Enlace(BaseModel):
    url: str
    origen: str  # "texto" o "html": de dónde se tomó. NO es una evidencia del modelo.


class CorreoExtraido(BaseModel):
    origen: str  # "eml" (con cabeceras) o "texto" (pegado sin cabeceras)
    nombre_archivo: Optional[str] = None
    tamano_bytes: int
    remitente: Optional[str] = None
    destinatario: Optional[str] = None
    asunto: Optional[str] = None
    fecha: Optional[str] = None
    fecha_iso: Optional[str] = None
    texto: str
    html: Optional[str] = None
    enlaces: List[Enlace]
    enlaces_total: int
    adjuntos_ignorados: int
    texto_desde_html: bool
    texto_truncado: bool
    html_truncado: bool
    limite_analisis_caracteres: int
    advertencias: List[str]


async def _leer_cuerpo(request: Request) -> bytes:
    """Lee el cuerpo por partes y corta en cuanto supera el máximo (no llena la memoria)."""
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > MAX_BYTES:
        raise ErrorCorreo(413, f"El correo supera el tamaño máximo de {MAX_BYTES // (1024 * 1024)} MB.")
    partes, total = [], 0
    async for trozo in request.stream():
        total += len(trozo)
        if total > MAX_BYTES:
            raise ErrorCorreo(413, f"El correo supera el tamaño máximo de {MAX_BYTES // (1024 * 1024)} MB.")
        partes.append(trozo)
    return b"".join(partes)


@router.post("/extraer", response_model=CorreoExtraido)
async def extraer(request: Request, x_nombre_archivo: Optional[str] = Header(default=None)):
    tipo = (request.headers.get("content-type") or "").lower()
    if tipo.startswith("multipart/") or tipo.startswith("application/json"):
        raise HTTPException(
            status_code=415,
            detail="Envía el correo como cuerpo crudo (message/rfc822 o text/plain), no como multipart ni JSON.",
        )
    try:
        datos = await _leer_cuerpo(request)
        nombre = unquote(x_nombre_archivo) if x_nombre_archivo else None
        return await run_in_threadpool(procesar, datos, nombre)
    except ErrorCorreo as e:
        raise HTTPException(status_code=e.estado, detail=e.mensaje)
    except HTTPException:
        raise
    except Exception as e:  # error inesperado: mensaje claro, sin detalles internos
        raise HTTPException(status_code=500, detail=f"Error al procesar el correo: {type(e).__name__}")
