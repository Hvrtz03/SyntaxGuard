"""Lógica de los endpoints de análisis de la Fase 5, sin depender de FastAPI.

Los routers (rutas_analisis.py, rutas_historial.py) solo reciben la solicitud HTTP y llaman a estas funciones.
Así se pueden probar sin levantar el servidor.

Reglas:
  * NO se duplica la lógica del detector: se llama a `detector.predecir(texto, html)`, la misma función que usa /predecir.
  * El detector compartido se usa de uno en uno (BLOQUEO_DETECTOR) en estos endpoints. Mientras no se demuestre con
    scripts/probar_concurrencia.py que el detector da resultados idénticos en paralelo, no se permite la concurrencia.
  * Los errores de un correo se guardan como registros (estado 'error') y no detienen un lote.
"""
from __future__ import annotations

import threading

from app import almacen, correo
from app.almacen import ErrorAlmacen

BLOQUEO_DETECTOR = threading.Lock()
MAX_ENLACES_REGISTRO = 200


def _texto_opcional(valor, limite):
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise ErrorAlmacen(422, "Los campos de texto deben ser cadenas.")
    return valor[:limite]


def _validar_rasgos(rasgos) -> list:
    if not isinstance(rasgos, list):
        raise ErrorAlmacen(422, "rasgos_detectados debe ser una lista.")
    for r in rasgos:
        if not (isinstance(r, dict) and isinstance(r.get("rasgo"), str) and isinstance(r.get("categoria"), str)
                and isinstance(r.get("descripcion"), str) and isinstance(r.get("activo"), bool)
                and isinstance(r.get("valor"), (int, float)) and not isinstance(r.get("valor"), bool)):
            raise ErrorAlmacen(422, "Cada rasgo debe tener rasgo, categoria, valor, activo y descripcion.")
    return rasgos


def registrar_individual(datos: dict, *, user_id) -> dict:
    """Guarda en el historial DEL USUARIO un análisis individual que YA hizo el modelo (/predecir).

    No vuelve a ejecutar el detector. Valida el formato y que es_spam concuerde con P(spam) y el umbral 0.5.
    De los enlaces solo se conservan los dominios.
    """
    res = datos.get("resultado")
    if not isinstance(res, dict):
        raise ErrorAlmacen(422, "Falta el resultado del análisis.")
    enlaces = datos.get("enlaces") or []
    if not isinstance(enlaces, list) or not all(isinstance(u, str) for u in enlaces):
        raise ErrorAlmacen(422, "enlaces debe ser una lista de textos.")
    advertencias = datos.get("advertencias") or []
    if not isinstance(advertencias, list):
        raise ErrorAlmacen(422, "advertencias debe ser una lista.")
    analisis_id = almacen.guardar_analisis(
        user_id=user_id, tipo="individual", estado="ok",
        nombre_archivo=_texto_opcional(datos.get("nombre_archivo"), 255),
        asunto=_texto_opcional(datos.get("asunto"), 500),
        remitente=_texto_opcional(datos.get("remitente"), 500),
        fecha_correo=_texto_opcional(datos.get("fecha"), 100),
        es_spam=res.get("es_spam"), probabilidad=res.get("probabilidad"),
        rasgos=_validar_rasgos(res.get("rasgos_detectados")),
        enlaces=enlaces[:MAX_ENLACES_REGISTRO],
        enlaces_total=datos.get("enlaces_total") or len(enlaces),
        advertencias=advertencias,
        tamano_bytes=datos.get("tamano_bytes"),
        adjuntos_ignorados=datos.get("adjuntos_ignorados") or 0)
    return almacen.obtener_analisis(analisis_id, user_id=user_id)


def registrar_error_archivo(nombre, tamano, mensaje, lote_id=None, *, user_id) -> dict:
    """Guarda un error individual de un lote como registro propio (no cuenta como SPAM ni LEGÍTIMO)."""
    analisis_id = almacen.guardar_analisis(
        user_id=user_id, tipo="masivo", estado="error", nombre_archivo=correo.nombre_seguro(nombre), lote_id=lote_id,
        error=mensaje, tamano_bytes=tamano)
    return almacen.obtener_analisis(analisis_id, user_id=user_id)


def analizar_archivo(detector, datos: bytes, nombre, lote_id=None, *, user_id) -> dict:
    """Extrae el correo, lo analiza con el modelo real y guarda el resultado (análisis masivo) a nombre del usuario.

    El lote debe pertenecer al mismo usuario; si es de otro se responde igual que si no existiera (404)."""
    if detector is None:
        raise ErrorAlmacen(503, "Modelo no cargado: no se puede analizar.")
    if lote_id is not None and not almacen.existe_lote(lote_id, user_id=user_id):
        raise ErrorAlmacen(404, "El lote indicado no existe.")
    try:
        c = correo.procesar(datos, nombre)
    except correo.ErrorCorreo as e:
        return registrar_error_archivo(nombre, len(datos), e.mensaje, lote_id, user_id=user_id)
    except Exception as e:  # error inesperado al leer: se registra y el lote continúa
        return registrar_error_archivo(nombre, len(datos), f"Error al procesar el correo: {type(e).__name__}",
                                       lote_id, user_id=user_id)
    try:
        with BLOQUEO_DETECTOR:
            r = detector.predecir(c["texto"], c["html"])
    except Exception as e:
        return registrar_error_archivo(nombre, len(datos), f"Error al analizar el mensaje: {type(e).__name__}",
                                       lote_id, user_id=user_id)
    analisis_id = almacen.guardar_analisis(
        user_id=user_id, tipo="masivo", estado="ok", lote_id=lote_id, nombre_archivo=c["nombre_archivo"], asunto=c["asunto"],
        remitente=c["remitente"], fecha_correo=c["fecha"], es_spam=r["es_spam"], probabilidad=r["probabilidad"],
        rasgos=r["rasgos_detectados"], enlaces=[e["url"] for e in c["enlaces"]], enlaces_total=c["enlaces_total"],
        advertencias=c["advertencias"], tamano_bytes=c["tamano_bytes"], adjuntos_ignorados=c["adjuntos_ignorados"])
    return almacen.obtener_analisis(analisis_id, user_id=user_id)
