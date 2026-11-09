"""Extracción segura de correos electrónicos para SyntaxGuard (Fase 3).

Recibe los bytes de un archivo .eml (o de un texto pegado) y devuelve los campos
del mensaje más los valores `texto` y `html` que el detector espera en /predecir.

Principios de seguridad:
  * Solo se LEE el contenido: nunca se ejecuta, renderiza ni se visita nada.
  * Los adjuntos se cuentan, pero no se abren ni se decodifican.
  * El HTML se devuelve como una cadena de texto (dato), no como página.
  * Los enlaces se devuelven como texto; no se abren ni se resuelven.
  * El nombre del archivo solo se usa como etiqueta; jamás como ruta en disco.

Este módulo NO importa el detector (no carga spaCy ni el modelo), así que se puede
probar por separado. La normalización de `texto` y `html` replica a propósito la de
scripts/build_dataset.py (leer_correo), para que el modelo reciba el mismo formato
con el que se construyó el dataset de entrenamiento.
"""
from __future__ import annotations

import re
from io import BytesIO
from email import policy
from email.header import decode_header, make_header
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath, PureWindowsPath

from bs4 import BeautifulSoup

# ---------- Límites ----------
MAX_BYTES = 5 * 1024 * 1024        # tamaño máximo del correo (5 MB)
MAX_TEXTO = 20000                  # igual que PrediccionRequest.texto (schemas.py)
MAX_HTML = 200000                  # igual que PrediccionRequest.html (schemas.py)
MAX_ENLACES = 100                  # enlaces que se devuelven para mostrar
MAX_LONG_ENLACE = 2000             # caracteres máximos por enlace mostrado
MAX_LONG_CABECERA = 500            # caracteres máximos por cabecera mostrada
LIMITE_ANALISIS = 3000             # debe coincidir con detector.MAX_CHARS (lo verifica el smoke test)

EXTENSIONES_ACEPTADAS = {".eml", ".txt"}

# Misma expresión que detector.URL_RE (copiada para no importar el detector aquí).
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"']+")
ES_HTTP_RE = re.compile(r"(?i)^(https?://|www\.)")
CABECERAS_CONOCIDAS = (
    "From", "To", "Subject", "Date", "Message-ID", "MIME-Version",
    "Content-Type", "Received", "Return-Path", "Reply-To", "Delivered-To",
)
HTML_PEGADO_RE = re.compile(r"(?i)<\s*(!doctype\s+html|html|head|body|table|div|p|br|a\s|span|font|center)\b")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ErrorCorreo(Exception):
    """Error de validación con el código HTTP que debe devolver la API."""

    def __init__(self, estado: int, mensaje: str):
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje


# ---------- Utilidades ----------
def nombre_seguro(nombre: str | None) -> str | None:
    """Deja solo el nombre del archivo (sin carpetas ni caracteres de control)."""
    if not nombre:
        return None
    base = PureWindowsPath(PurePosixPath(nombre).name).name
    base = CONTROL_RE.sub("", base).strip()
    return base[:255] or None


def _decodificar_bytes(datos: bytes, charset: str | None) -> str:
    """Decodifica con el charset declarado; si falla, prueba utf-8 y windows-1252."""
    for cs in (charset, "utf-8", "windows-1252"):
        if not cs:
            continue
        try:
            return datos.decode(cs)
        except (LookupError, UnicodeDecodeError):
            continue
    return datos.decode(charset if _charset_valido(charset) else "utf-8", errors="replace")


def _charset_valido(cs: str | None) -> bool:
    if not cs:
        return False
    try:
        "".encode(cs)
        return True
    except LookupError:
        return False


def _decodificar_parte(parte) -> str:
    """Igual que build_dataset.decodificar, con un respaldo más tolerante a charsets raros."""
    try:
        contenido = parte.get_content()
        if isinstance(contenido, str):
            return contenido
    except Exception:
        pass
    try:
        payload = parte.get_payload(decode=True) or b""
        return _decodificar_bytes(payload, parte.get_content_charset())
    except Exception:
        return ""


def _limpiar_linea(valor: str | None, limite: int = MAX_LONG_CABECERA) -> str | None:
    if valor is None:
        return None
    valor = CONTROL_RE.sub("", str(valor))
    valor = re.sub(r"\s+", " ", valor).strip()
    return valor[:limite] or None


def _cabecera(msg, nombre: str) -> str | None:
    """Lee una cabecera ya decodificada (RFC 2047); si está malformada, usa un respaldo."""
    try:
        valor = msg[nombre]
        if valor is not None:
            return _limpiar_linea(str(valor))
    except Exception:
        pass
    try:
        for clave, crudo in msg.raw_items():
            if clave.lower() == nombre.lower():
                try:
                    return _limpiar_linea(str(make_header(decode_header(str(crudo)))))
                except Exception:
                    return _limpiar_linea(str(crudo))
    except Exception:
        pass
    return None


def _fecha_iso(fecha: str | None) -> str | None:
    if not fecha:
        return None
    try:
        return parsedate_to_datetime(fecha).isoformat()
    except Exception:
        return None


def _texto_desde_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def _normalizar(texto_partes: list, html_partes: list) -> tuple:
    """Misma normalización que build_dataset.leer_correo, pero informando de lo que ocurre."""
    texto = "\n".join(texto_partes).strip()
    html = "\n".join(html_partes).strip()
    desde_html = False
    if not texto and html:
        texto = _texto_desde_html(html)
        desde_html = True
    texto = re.sub(r"\s+", " ", texto).strip()
    return CONTROL_RE.sub("", texto), CONTROL_RE.sub("", html), desde_html


def _enlaces(texto: str, html: str) -> tuple:
    """Enlaces http(s)/www del texto y de los href del HTML (sin duplicados, en orden)."""
    candidatos = [(u.rstrip(".,;:!?)"), "texto") for u in URL_RE.findall(texto)]
    if html:
        try:
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                href = str(a["href"]).strip()
                if ES_HTTP_RE.match(href):
                    candidatos.append((href, "html"))
        except Exception:
            pass
    vistos, unicos = set(), []
    for url, origen in candidatos:
        if not url or url in vistos:
            continue
        vistos.add(url)
        unicos.append({"url": CONTROL_RE.sub("", url)[:MAX_LONG_ENLACE], "origen": origen})
    return unicos[:MAX_ENLACES], len(unicos)


def _validar_entrada(datos: bytes, nombre: str | None) -> None:
    if nombre:
        sufijo = PurePosixPath(nombre).suffix.lower()
        if sufijo and sufijo not in EXTENSIONES_ACEPTADAS:
            raise ErrorCorreo(415, f"Formato no admitido ({sufijo}). Usa un archivo .eml o .txt, o pega el contenido.")
    if len(datos) > MAX_BYTES:
        raise ErrorCorreo(413, f"El correo supera el tamaño máximo de {MAX_BYTES // (1024 * 1024)} MB.")
    if not datos.strip():
        raise ErrorCorreo(400, "El archivo o el texto está vacío.")
    if b"\x00" in datos[:8192]:
        raise ErrorCorreo(415, "El contenido parece un archivo binario, no un correo en texto (.eml).")


def _tiene_cabeceras(msg) -> bool:
    try:
        return any(msg.get(c) for c in CABECERAS_CONOCIDAS)
    except Exception:
        return False


# ---------- Función principal ----------
def procesar(datos: bytes, nombre: str | None = None) -> dict:
    """Extrae los campos del correo. Lanza ErrorCorreo si el contenido no es válido."""
    nombre = nombre_seguro(nombre)
    _validar_entrada(datos, nombre)

    try:
        # Se usa .parse(archivo) (no .parsebytes) porque normaliza los saltos de línea igual que build_dataset.py.
        msg = BytesParser(policy=policy.default).parse(BytesIO(datos))
    except Exception:
        raise ErrorCorreo(400, "No se pudo leer el correo: el archivo está dañado o no tiene formato de mensaje.")

    texto_partes, html_partes = [], []
    adjuntos = 0

    if _tiene_cabeceras(msg):
        origen = "eml"
        for parte in msg.walk():
            if parte.is_multipart():
                continue
            if parte.get_content_disposition() == "attachment":
                adjuntos += 1
                continue
            tipo = parte.get_content_type()
            if tipo == "text/plain":
                texto_partes.append(_decodificar_parte(parte))
            elif tipo == "text/html":
                html_partes.append(_decodificar_parte(parte))
        remitente = _cabecera(msg, "From")
        destinatario = _cabecera(msg, "To")
        asunto = _cabecera(msg, "Subject")
        fecha = _cabecera(msg, "Date")
    else:
        # Texto pegado sin cabeceras: se trata como el cuerpo del mensaje.
        origen = "texto"
        contenido = _decodificar_bytes(datos, None)
        if HTML_PEGADO_RE.search(contenido):
            html_partes.append(contenido)
        else:
            texto_partes.append(contenido)
        remitente = destinatario = asunto = fecha = None

    texto, html, desde_html = _normalizar(texto_partes, html_partes)

    if not texto:
        extra = f" (se ignoraron {adjuntos} adjunto(s))" if adjuntos else ""
        raise ErrorCorreo(422, f"El correo no contiene texto analizable{extra}.")

    enlaces, enlaces_total = _enlaces(texto, html)

    advertencias = []
    if origen == "texto":
        advertencias.append("No se encontraron cabeceras: el contenido se trató como el cuerpo del mensaje.")
    if desde_html:
        advertencias.append("El correo no tiene parte de texto plano; el texto se obtuvo del HTML.")
    if adjuntos:
        advertencias.append(f"Se ignoraron {adjuntos} adjunto(s): no se abren ni se analizan.")
    texto_truncado = len(texto) > MAX_TEXTO
    html_truncado = len(html) > MAX_HTML
    if texto_truncado:
        advertencias.append(f"El texto se recortó a {MAX_TEXTO:,} caracteres.".replace(",", " "))
    if html_truncado:
        advertencias.append(f"El HTML se recortó a {MAX_HTML:,} caracteres.".replace(",", " "))
    if len(texto) > LIMITE_ANALISIS:
        advertencias.append(
            f"El detector solo analiza los primeros {LIMITE_ANALISIS:,} caracteres del texto.".replace(",", " "))
    if enlaces_total > MAX_ENLACES:
        advertencias.append(f"Se encontraron {enlaces_total} enlaces; se muestran los primeros {MAX_ENLACES}.")

    return {
        "origen": origen,
        "nombre_archivo": nombre,
        "tamano_bytes": len(datos),
        "remitente": remitente,
        "destinatario": destinatario,
        "asunto": asunto,
        "fecha": fecha,
        "fecha_iso": _fecha_iso(fecha),
        "texto": texto[:MAX_TEXTO],
        "html": html[:MAX_HTML] or None,
        "enlaces": enlaces,
        "enlaces_total": enlaces_total,
        "adjuntos_ignorados": adjuntos,
        "texto_desde_html": desde_html,
        "texto_truncado": texto_truncado,
        "html_truncado": html_truncado,
        "limite_analisis_caracteres": LIMITE_ANALISIS,
        "advertencias": advertencias,
    }
