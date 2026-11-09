"""Almacenamiento persistente de SyntaxGuard (Fase 5) con SQLite de la biblioteca estándar.

Qué se guarda (decisión D1): metadatos del correo, el resultado del modelo (es_spam, P(spam), rasgos),
los DOMINIOS de los enlaces y las advertencias. NO se guarda el texto ni el HTML del correo ni las URL completas.

Fase 6A (usuarios): cada lote y cada análisis pertenece a un usuario (columna `user_id`). TODAS las funciones públicas
de este módulo que leen o escriben datos de análisis exigen `user_id` (argumento obligatorio) y lo aplican en el SQL:
un usuario nunca ve ni modifica filas de otro. Las filas anteriores a la Fase 6 conservan `user_id = NULL` y no son
visibles para ningún usuario (no se asignan a nadie automáticamente). El `user_id` sale SIEMPRE de la sesión validada
en el servidor, nunca de datos enviados por el cliente.

Diseño:
  * Una conexión nueva por operación (FastAPI atiende en hilos distintos; así no se comparte ninguna).
  * Modo WAL + claves foráneas activadas. Transacciones cortas.
  * Fechas en UTC con el formato de SQLite ('YYYY-MM-DD HH:MM:SS'); la hora local se calcula al consultar.
  * Este módulo no importa el detector ni FastAPI: se puede probar por separado.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
RUTA_BD_PREDETERMINADA = BACKEND_DIR / "storage" / "syntaxguard.db"

POR_PAGINA_MAX = 100
MAX_IDS = 1000
FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creado_en TEXT NOT NULL DEFAULT (datetime('now')),
    total_previsto INTEGER
);
CREATE TABLE IF NOT EXISTS analisis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creado_en TEXT NOT NULL DEFAULT (datetime('now')),
    tipo TEXT NOT NULL CHECK (tipo IN ('individual', 'masivo')),
    lote_id INTEGER REFERENCES lotes(id) ON DELETE SET NULL,
    nombre_archivo TEXT,
    asunto TEXT,
    remitente TEXT,
    fecha_correo TEXT,
    estado TEXT NOT NULL CHECK (estado IN ('ok', 'error')),
    error TEXT,
    es_spam INTEGER,
    probabilidad REAL,
    rasgos_json TEXT,
    dominios_json TEXT,
    enlaces_total INTEGER,
    advertencias_json TEXT,
    tamano_bytes INTEGER,
    adjuntos_ignorados INTEGER
);
CREATE INDEX IF NOT EXISTS idx_analisis_creado ON analisis(creado_en);
CREATE INDEX IF NOT EXISTS idx_analisis_lote ON analisis(lote_id);
CREATE TABLE IF NOT EXISTS retroalimentacion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analisis_id INTEGER NOT NULL REFERENCES analisis(id) ON DELETE CASCADE,
    de_acuerdo INTEGER NOT NULL CHECK (de_acuerdo IN (0, 1)),
    comentario TEXT,
    creado_en TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_retro_analisis ON retroalimentacion(analisis_id);
"""

# Fase 6A: usuarios, sesiones e intentos de acceso. Se crean con IF NOT EXISTS (idempotente).
ESQUEMA_AUTH = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT NOT NULL UNIQUE,
    clave_hash TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS sesiones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    creada_en REAL NOT NULL,
    expira_en REAL NOT NULL,
    ultimo_uso REAL NOT NULL,
    revocada_en REAL
);
CREATE TABLE IF NOT EXISTS intentos_acceso (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave TEXT NOT NULL,
    momento REAL NOT NULL
);
"""

# Índices de la Fase 6A. Se crean DESPUÉS de agregar user_id a lotes/analisis.
INDICES_AUTH = """
CREATE INDEX IF NOT EXISTS idx_sesiones_user ON sesiones(user_id);
CREATE INDEX IF NOT EXISTS idx_sesiones_expira ON sesiones(expira_en);
CREATE INDEX IF NOT EXISTS idx_intentos_clave ON intentos_acceso(clave, momento);
CREATE INDEX IF NOT EXISTS idx_lotes_user ON lotes(user_id);
CREATE INDEX IF NOT EXISTS idx_analisis_user_creado ON analisis(user_id, creado_en);
CREATE INDEX IF NOT EXISTS idx_analisis_user_lote ON analisis(user_id, lote_id);
"""

VERSION_ESQUEMA = 6  # PRAGMA user_version tras la migración de la Fase 6A


class ErrorAlmacen(Exception):
    """Error de validación o de recurso inexistente, con el código HTTP que corresponde."""

    def __init__(self, estado: int, mensaje: str):
        super().__init__(mensaje)
        self.estado = estado
        self.mensaje = mensaje


def ruta_bd() -> Path:
    """Ruta de la base de datos. SG_DB permite cambiarla (por ejemplo en las pruebas)."""
    valor = os.environ.get("SG_DB")
    return Path(valor) if valor else RUTA_BD_PREDETERMINADA


def _columnas(con: sqlite3.Connection, tabla: str) -> set:
    return {f[1] for f in con.execute(f"PRAGMA table_info({tabla})")}


def _respaldar_antes_de_migrar(con: sqlite3.Connection, ruta: Path) -> Path | None:
    """Si existe una base de la Fase 5 (con datos y sin user_id), guarda una copia ANTES de modificarla.

    Usa la API de respaldo de SQLite (correcta incluso con WAL). Solo se hace una vez: si la copia ya existe no se
    reemplaza. Devuelve la ruta de la copia o None si no hacía falta.
    """
    if not _columnas(con, "analisis") or "user_id" in _columnas(con, "analisis"):
        return None
    hay_datos = con.execute("SELECT (SELECT COUNT(*) FROM analisis) + (SELECT COUNT(*) FROM lotes)").fetchone()[0]
    if not hay_datos:
        return None
    destino = ruta.with_name(ruta.name + ".pre_fase6.bak")
    if destino.exists():
        return destino
    copia = sqlite3.connect(str(destino))
    try:
        con.backup(copia)
    finally:
        copia.close()
    return destino


def migrar(con: sqlite3.Connection, ruta: Path | None = None) -> None:
    """Migración de la Fase 6A: idempotente y atómica (una sola transacción).

    * Crea usuarios, sesiones e intentos_acceso si no existen.
    * Agrega `user_id` (NULL por defecto) a lotes y analisis solo si aún no existe.
    * Las filas anteriores conservan user_id = NULL: NO se asignan a ningún usuario.
    * Crea los índices necesarios y fija PRAGMA user_version.
    Si algo falla, se revierte todo y la base queda como estaba.
    """
    con.isolation_level = None  # control manual de la transacción
    con.execute("BEGIN IMMEDIATE")
    try:
        for sentencia in ESQUEMA.split(";"):  # esquema original de la Fase 5 (IF NOT EXISTS)
            if sentencia.strip():
                con.execute(sentencia)
        for sentencia in ESQUEMA_AUTH.split(";"):
            if sentencia.strip():
                con.execute(sentencia)
        for tabla in ("lotes", "analisis"):
            if "user_id" not in _columnas(con, tabla):
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN user_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE")
        for sentencia in INDICES_AUTH.split(";"):
            if sentencia.strip():
                con.execute(sentencia)
        if con.execute("PRAGMA user_version").fetchone()[0] < VERSION_ESQUEMA:
            con.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def iniciar() -> Path:
    """Crea la carpeta, las tablas y aplica la migración de la Fase 6A. Es seguro llamarla en cada arranque."""
    ruta = ruta_bd()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(ruta), timeout=10)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        _respaldar_antes_de_migrar(con, ruta)
        migrar(con, ruta)
    finally:
        con.close()
    return ruta


@contextmanager
def conexion():
    """Conexión con commit automático si todo sale bien y rollback si hay error."""
    con = sqlite3.connect(str(ruta_bd()), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ---------- Utilidades ----------
def _iso(valor: str | None) -> str | None:
    """'2026-11-05 14:03:09' (UTC) -> '2026-11-05T14:03:09Z'."""
    return valor.replace(" ", "T") + "Z" if valor else None


def _cargar(texto: str | None, defecto):
    if not texto:
        return defecto
    try:
        return json.loads(texto)
    except ValueError:
        return defecto


def _recortar(valor, limite: int):
    if valor is None:
        return None
    valor = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(valor)).strip()
    return valor[:limite] or None


def _uid(user_id) -> int:
    """El propietario es obligatorio y debe ser un entero positivo. Un error aquí es un fallo de programación."""
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
        raise ValueError("user_id es obligatorio (entero positivo) para acceder a los datos.")
    return user_id


ENTERO_MAX = 2 ** 62  # SQLite solo admite enteros de 64 bits: un valor mayor daba OverflowError (HTTP 500)


def _entero(valor, nombre: str, minimo: int = 0) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < minimo or valor > ENTERO_MAX:
        raise ErrorAlmacen(422, f"{nombre} debe ser un entero mayor o igual que {minimo}.")
    return valor


def _fuera_de_rango(valor) -> bool:
    return isinstance(valor, bool) or not isinstance(valor, int) or valor < 1 or valor > ENTERO_MAX


def dominios_de(urls) -> list:
    """Solo los dominios (sin ruta ni parámetros) de una lista de URL. Únicos, en minúsculas, máximo 30."""
    from urllib.parse import urlparse
    vistos, salida = set(), []
    for u in urls or []:
        u = str(u).strip()
        if not re.match(r"(?i)^[a-z][a-z0-9+.-]*://", u):
            u = "http://" + u
        try:
            host = (urlparse(u).hostname or "").lower()
        except ValueError:
            host = ""
        if host and host not in vistos:
            vistos.add(host)
            salida.append(host[:255])
    return salida[:30]


def _fila_a_dict(f: sqlite3.Row, retro: dict | None = None) -> dict:
    d = {
        "id": f["id"],
        "creado_en": _iso(f["creado_en"]),
        "tipo": f["tipo"],
        "lote_id": f["lote_id"],
        "nombre_archivo": f["nombre_archivo"],
        "asunto": f["asunto"],
        "remitente": f["remitente"],
        "fecha_correo": f["fecha_correo"],
        "estado": f["estado"],
        "error": f["error"],
        "es_spam": None if f["es_spam"] is None else bool(f["es_spam"]),
        "probabilidad": f["probabilidad"],
        "rasgos_detectados": _cargar(f["rasgos_json"], []),
        "dominios": _cargar(f["dominios_json"], []),
        "enlaces_total": f["enlaces_total"] or 0,
        "advertencias": _cargar(f["advertencias_json"], []),
        "tamano_bytes": f["tamano_bytes"],
        "adjuntos_ignorados": f["adjuntos_ignorados"] or 0,
    }
    d["retro_total"] = (retro or {}).get("total", 0)
    d["retro_ultima"] = (retro or {}).get("ultima")
    return d


def _resumen_retro(con, ids: list) -> dict:
    """Por análisis: cantidad de retroalimentaciones y la más reciente."""
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    filas = con.execute(
        f"SELECT id, analisis_id, de_acuerdo, comentario, creado_en FROM retroalimentacion "
        f"WHERE analisis_id IN ({marcas}) ORDER BY creado_en DESC, id DESC", ids).fetchall()
    res: dict = {}
    for r in filas:
        e = res.setdefault(r["analisis_id"], {"total": 0, "ultima": None})
        e["total"] += 1
        if e["ultima"] is None:
            e["ultima"] = {"id": r["id"], "de_acuerdo": bool(r["de_acuerdo"]),
                           "comentario": r["comentario"], "creado_en": _iso(r["creado_en"])}
    return res


# ---------- Lotes ----------
def crear_lote(total_previsto=None, *, user_id) -> dict:
    user_id = _uid(user_id)
    if total_previsto is not None:
        total_previsto = _entero(total_previsto, "total", 0)
    with conexion() as con:
        cur = con.execute("INSERT INTO lotes (total_previsto, user_id) VALUES (?, ?)", (total_previsto, user_id))
        fila = con.execute("SELECT id, creado_en, total_previsto FROM lotes WHERE id=?", (cur.lastrowid,)).fetchone()
    return {"id": fila["id"], "creado_en": _iso(fila["creado_en"]), "total_previsto": fila["total_previsto"]}


def existe_lote(lote_id: int, *, user_id) -> bool:
    """True solo si el lote existe Y es de este usuario (un lote ajeno se comporta como inexistente)."""
    user_id = _uid(user_id)
    if _fuera_de_rango(lote_id):
        return False
    with conexion() as con:
        return con.execute("SELECT 1 FROM lotes WHERE id=? AND user_id=?", (lote_id, user_id)).fetchone() is not None


def _porcentaje(parte: int, todo: int):
    return round(100.0 * parte / todo, 1) if todo else None


def resumen_lote(lote_id: int, *, user_id) -> dict:
    user_id = _uid(user_id)
    if _fuera_de_rango(lote_id):
        raise ErrorAlmacen(404, "El lote no existe.")
    with conexion() as con:
        lote = con.execute("SELECT id, creado_en, total_previsto FROM lotes WHERE id=? AND user_id=?",
                           (lote_id, user_id)).fetchone()
        if lote is None:
            raise ErrorAlmacen(404, "El lote no existe.")
        r = con.execute(
            "SELECT COUNT(*) AS total,"
            " SUM(estado='ok' AND es_spam=1) AS spam,"
            " SUM(estado='ok' AND es_spam=0) AS legitimos,"
            " SUM(estado='error') AS errores"
            " FROM analisis WHERE lote_id=? AND user_id=?", (lote_id, user_id)).fetchone()
    spam, leg, err, total = (r["spam"] or 0), (r["legitimos"] or 0), (r["errores"] or 0), (r["total"] or 0)
    clasificados = spam + leg
    return {
        "id": lote["id"], "creado_en": _iso(lote["creado_en"]), "total_previsto": lote["total_previsto"],
        "total_procesados": total, "spam": spam, "legitimos": leg, "errores": err,
        "clasificados": clasificados,
        "porcentaje_spam": _porcentaje(spam, clasificados),
        "porcentaje_legitimos": _porcentaje(leg, clasificados),
    }


# ---------- Análisis ----------
def guardar_analisis(*, user_id, tipo: str, estado: str, nombre_archivo=None, asunto=None, remitente=None,
                     fecha_correo=None, lote_id=None, error=None, es_spam=None, probabilidad=None,
                     rasgos=None, enlaces=None, enlaces_total=0, advertencias=None,
                     tamano_bytes=None, adjuntos_ignorados=0) -> int:
    """Inserta un análisis (o un error) del usuario y devuelve su id. `enlaces` son URL; solo se guardan sus dominios."""
    user_id = _uid(user_id)
    if tipo not in ("individual", "masivo"):
        raise ErrorAlmacen(422, "tipo no válido.")
    if estado not in ("ok", "error"):
        raise ErrorAlmacen(422, "estado no válido.")
    if estado == "ok":
        if not isinstance(es_spam, bool):
            raise ErrorAlmacen(422, "es_spam debe ser booleano.")
        if isinstance(probabilidad, bool) or not isinstance(probabilidad, (int, float)) or not 0.0 <= probabilidad <= 1.0:
            raise ErrorAlmacen(422, "probabilidad debe estar entre 0 y 1.")
        # Coherencia con el umbral 0.5 (tolera el redondeo a 4 decimales que hace el detector en el límite).
        if (probabilidad > 0.5 and not es_spam) or (probabilidad < 0.5 and es_spam):
            raise ErrorAlmacen(422, "es_spam no concuerda con la probabilidad y el umbral 0.5.")
    if lote_id is not None and not existe_lote(lote_id, user_id=user_id):
        raise ErrorAlmacen(404, "El lote indicado no existe.")
    rasgos = rasgos if isinstance(rasgos, list) else []
    advertencias = [str(a)[:500] for a in (advertencias or [])][:30]
    with conexion() as con:
        cur = con.execute(
            "INSERT INTO analisis (tipo, lote_id, nombre_archivo, asunto, remitente, fecha_correo, estado, error,"
            " es_spam, probabilidad, rasgos_json, dominios_json, enlaces_total, advertencias_json,"
            " tamano_bytes, adjuntos_ignorados, user_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (tipo, lote_id, _recortar(nombre_archivo, 255), _recortar(asunto, 500), _recortar(remitente, 500),
             _recortar(fecha_correo, 100), estado, _recortar(error, 500),
             None if es_spam is None else int(es_spam), probabilidad,
             json.dumps(rasgos, ensure_ascii=False) if estado == "ok" else None,
             json.dumps(dominios_de(enlaces), ensure_ascii=False),
             int(enlaces_total or 0), json.dumps(advertencias, ensure_ascii=False),
             tamano_bytes, int(adjuntos_ignorados or 0), user_id))
        return cur.lastrowid


def obtener_analisis(analisis_id: int, *, user_id) -> dict:
    user_id = _uid(user_id)
    if _fuera_de_rango(analisis_id):
        raise ErrorAlmacen(404, "El análisis no existe.")
    with conexion() as con:
        f = con.execute("SELECT * FROM analisis WHERE id=? AND user_id=?", (analisis_id, user_id)).fetchone()
        if f is None:
            raise ErrorAlmacen(404, "El análisis no existe.")
        retro = _resumen_retro(con, [analisis_id]).get(analisis_id)
        d = _fila_a_dict(f, retro)
        d["retroalimentaciones"] = [
            {"id": r["id"], "de_acuerdo": bool(r["de_acuerdo"]), "comentario": r["comentario"],
             "creado_en": _iso(r["creado_en"])}
            for r in con.execute(
                "SELECT id, de_acuerdo, comentario, creado_en FROM retroalimentacion "
                "WHERE analisis_id=? ORDER BY creado_en DESC, id DESC", (analisis_id,))]
    return d


def _filtros(user_id, q=None, clasificacion=None, desde=None, hasta=None, tipo=None, lote_id=None, solo_ok=False):
    """Construye el WHERE con parámetros (nunca se concatenan valores del usuario). El propietario va SIEMPRE."""
    cond, par = ["user_id=?"], [_uid(user_id)]
    if solo_ok:
        cond.append("estado='ok'")
    if q and q.strip():
        patron = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cond.append("(LOWER(COALESCE(nombre_archivo,'')) LIKE ? ESCAPE '\\' OR LOWER(COALESCE(asunto,'')) LIKE ? ESCAPE '\\')")
        par += [patron, patron]
    if clasificacion:
        c = clasificacion.lower()
        if c == "spam":
            cond.append("estado='ok' AND es_spam=1")
        elif c in ("legitimo", "legítimo", "ham"):
            cond.append("estado='ok' AND es_spam=0")
        elif c == "error":
            cond.append("estado='error'")
        else:
            raise ErrorAlmacen(422, "clasificacion debe ser spam, legitimo o error.")
    for valor, nombre, op in ((desde, "desde", ">="), (hasta, "hasta", "<=")):
        if valor:
            if not FECHA_RE.match(valor):
                raise ErrorAlmacen(422, f"{nombre} debe tener el formato AAAA-MM-DD.")
            cond.append(f"date(creado_en, 'localtime') {op} ?")
            par.append(valor)
    if desde and hasta and desde > hasta:
        raise ErrorAlmacen(422, "La fecha inicial no puede ser posterior a la final.")
    if tipo:
        if tipo not in ("individual", "masivo"):
            raise ErrorAlmacen(422, "tipo debe ser individual o masivo.")
        cond.append("tipo=?")
        par.append(tipo)
    if lote_id is not None:
        cond.append("lote_id=?")
        par.append(_entero(lote_id, "lote_id", 1))
    return " WHERE " + " AND ".join(cond), par


def listar_analisis(*, user_id, q=None, clasificacion=None, desde=None, hasta=None, tipo=None, lote_id=None,
                    solo_ok=False, pagina=1, por_pagina=25) -> dict:
    pagina = _entero(pagina, "pagina", 1)
    por_pagina = min(_entero(por_pagina, "por_pagina", 1), POR_PAGINA_MAX)
    where, par = _filtros(user_id, q, clasificacion, desde, hasta, tipo, lote_id, solo_ok)
    with conexion() as con:
        total = con.execute("SELECT COUNT(*) FROM analisis" + where, par).fetchone()[0]
        filas = con.execute(
            "SELECT * FROM analisis" + where + " ORDER BY creado_en DESC, id DESC LIMIT ? OFFSET ?",
            par + [por_pagina, (pagina - 1) * por_pagina]).fetchall()
        retro = _resumen_retro(con, [f["id"] for f in filas])
        items = [_fila_a_dict(f, retro.get(f["id"])) for f in filas]
    for it in items:  # el listado no necesita los rasgos completos
        it.pop("rasgos_detectados", None)
        it.pop("advertencias", None)
    return {"items": items, "total": total, "pagina": pagina, "por_pagina": por_pagina,
            "paginas": max(1, -(-total // por_pagina))}


def eliminar_analisis(ids: list, *, user_id) -> int:
    """Elimina SOLO los análisis de este usuario; los ids ajenos o inexistentes se ignoran (no cuentan)."""
    user_id = _uid(user_id)
    if not isinstance(ids, list) or not ids:
        raise ErrorAlmacen(422, "Indica al menos un id.")
    if len(ids) > MAX_IDS:
        raise ErrorAlmacen(422, f"Se pueden eliminar como máximo {MAX_IDS} registros por solicitud.")
    ids = [_entero(i, "id", 1) for i in ids]
    with conexion() as con:
        cur = con.execute(f"DELETE FROM analisis WHERE user_id=? AND id IN ({','.join('?' * len(ids))})",
                          [user_id] + ids)
        return cur.rowcount


# ---------- Retroalimentación ----------
def guardar_retro(analisis_id: int, de_acuerdo, comentario=None, *, user_id) -> dict:
    user_id = _uid(user_id)
    analisis_id = _entero(analisis_id, "analisis_id", 1)
    if not isinstance(de_acuerdo, bool):
        raise ErrorAlmacen(422, "de_acuerdo debe ser verdadero o falso.")
    comentario = _recortar(comentario, 1000)
    with conexion() as con:
        a = con.execute("SELECT estado FROM analisis WHERE id=? AND user_id=?", (analisis_id, user_id)).fetchone()
        if a is None:
            raise ErrorAlmacen(404, "El análisis no existe.")
        if a["estado"] != "ok":
            raise ErrorAlmacen(422, "Solo se puede opinar sobre análisis que tienen una clasificación.")
        cur = con.execute("INSERT INTO retroalimentacion (analisis_id, de_acuerdo, comentario) VALUES (?,?,?)",
                          (analisis_id, int(de_acuerdo), comentario))
        r = con.execute("SELECT * FROM retroalimentacion WHERE id=?", (cur.lastrowid,)).fetchone()
    return {"id": r["id"], "analisis_id": r["analisis_id"], "de_acuerdo": bool(r["de_acuerdo"]),
            "comentario": r["comentario"], "creado_en": _iso(r["creado_en"])}


def listar_retro(*, user_id, analisis_id=None, pagina=1, por_pagina=25) -> dict:
    user_id = _uid(user_id)
    pagina = _entero(pagina, "pagina", 1)
    por_pagina = min(_entero(por_pagina, "por_pagina", 1), POR_PAGINA_MAX)
    where, par = " WHERE a.user_id=?", [user_id]  # la propiedad de la opinión es la del análisis
    if analisis_id is not None:
        where += " AND r.analisis_id=?"
        par.append(_entero(analisis_id, "analisis_id", 1))
    with conexion() as con:
        total = con.execute("SELECT COUNT(*) FROM retroalimentacion r JOIN analisis a ON a.id=r.analisis_id" + where,
                            par).fetchone()[0]
        filas = con.execute(
            "SELECT r.id, r.analisis_id, r.de_acuerdo, r.comentario, r.creado_en, a.nombre_archivo, a.asunto,"
            " a.es_spam, a.probabilidad FROM retroalimentacion r JOIN analisis a ON a.id=r.analisis_id"
            + where + " ORDER BY r.creado_en DESC, r.id DESC LIMIT ? OFFSET ?",
            par + [por_pagina, (pagina - 1) * por_pagina]).fetchall()
    items = [{"id": r["id"], "analisis_id": r["analisis_id"], "de_acuerdo": bool(r["de_acuerdo"]),
              "comentario": r["comentario"], "creado_en": _iso(r["creado_en"]),
              "nombre_archivo": r["nombre_archivo"], "asunto": r["asunto"],
              "es_spam": None if r["es_spam"] is None else bool(r["es_spam"]),
              "probabilidad": r["probabilidad"]} for r in filas]
    return {"items": items, "total": total, "pagina": pagina, "por_pagina": por_pagina,
            "paginas": max(1, -(-total // por_pagina))}


# ---------- Estadísticas de uso ----------
def estadisticas_uso(dias: int = 30, *, user_id) -> dict:
    """Estadísticas calculadas SOLO con los registros del historial DE ESTE USUARIO. No tienen relación con metricas.json."""
    user_id = _uid(user_id)
    with conexion() as con:
        r = con.execute(
            "SELECT SUM(estado='ok') AS ok, SUM(estado='ok' AND es_spam=1) AS spam,"
            " SUM(estado='ok' AND es_spam=0) AS leg, SUM(estado='error') AS err,"
            " SUM(estado='ok' AND tipo='individual') AS ind, SUM(estado='ok' AND tipo='masivo') AS mas,"
            " (SELECT COUNT(*) FROM retroalimentacion r JOIN analisis a2 ON a2.id=r.analisis_id"
            "  WHERE a2.user_id=:u) AS retro,"
            " (SELECT COUNT(*) FROM lotes WHERE user_id=:u) AS lotes FROM analisis WHERE user_id=:u",
            {"u": user_id}).fetchone()
        filas = con.execute(
            "SELECT date(creado_en, 'localtime') AS dia, SUM(es_spam=1) AS spam, SUM(es_spam=0) AS leg "
            "FROM analisis WHERE estado='ok' AND user_id=? GROUP BY dia", (user_id,)).fetchall()
        hoy = con.execute("SELECT date('now', 'localtime')").fetchone()[0]
    ok, spam, leg = (r["ok"] or 0), (r["spam"] or 0), (r["leg"] or 0)
    por_dia_bd = {f["dia"]: (f["spam"] or 0, f["leg"] or 0) for f in filas}
    inicio = datetime.strptime(hoy, "%Y-%m-%d").date()
    serie = []
    for i in range(dias - 1, -1, -1):  # un punto por día; los días sin análisis valen 0 (dato real)
        d = (inicio - timedelta(days=i)).isoformat()
        s, l = por_dia_bd.get(d, (0, 0))
        serie.append({"dia": d, "spam": s, "legitimos": l, "total": s + l})
    return {
        "analizados": ok, "spam": spam, "legitimos": leg, "errores": (r["err"] or 0),
        "porcentaje_spam": _porcentaje(spam, ok), "porcentaje_legitimos": _porcentaje(leg, ok),
        "individuales": (r["ind"] or 0), "masivos": (r["mas"] or 0),
        "lotes": (r["lotes"] or 0), "retroalimentaciones": (r["retro"] or 0),
        "por_dia": serie, "dias_considerados": dias,
    }


# ---------- Exportación CSV ----------
COLUMNAS_CSV = ["id", "fecha_hora_local", "tipo", "lote", "archivo", "asunto", "remitente",
                "clasificacion", "p_spam", "estado", "error", "dominios_enlaces"]


def _celda(valor):
    """Neutraliza fórmulas (=, +, -, @) para que Excel no ejecute contenido de un correo."""
    if isinstance(valor, str) and valor and valor[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


def _hora_local(creado: str) -> str:
    try:
        dt = datetime.strptime(creado, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return creado


def exportar_csv(*, user_id, **filtros) -> bytes:
    where, par = _filtros(user_id, filtros.get("q"), filtros.get("clasificacion"), filtros.get("desde"),
                          filtros.get("hasta"), filtros.get("tipo"), filtros.get("lote_id"))
    with conexion() as con:
        filas = con.execute("SELECT * FROM analisis" + where + " ORDER BY creado_en DESC, id DESC", par).fetchall()
    sal = io.StringIO(newline="")
    w = csv.writer(sal, lineterminator="\r\n")
    w.writerow(COLUMNAS_CSV)
    for f in filas:
        clasif = "ERROR" if f["estado"] == "error" else ("SPAM" if f["es_spam"] else "LEGÍTIMO")
        w.writerow([f["id"], _hora_local(f["creado_en"]), f["tipo"], f["lote_id"] if f["lote_id"] is not None else "",
                    _celda(f["nombre_archivo"] or ""), _celda(f["asunto"] or ""), _celda(f["remitente"] or ""),
                    clasif, "" if f["probabilidad"] is None else f"{f['probabilidad']:.4f}", f["estado"],
                    _celda(f["error"] or ""), _celda(" ".join(_cargar(f["dominios_json"], [])))])
    return ("\ufeff" + sal.getvalue()).encode("utf-8")  # BOM para que Excel en Windows lea los acentos
