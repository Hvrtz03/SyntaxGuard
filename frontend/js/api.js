// Cliente de la API de SyntaxGuard. Único punto de contacto del frontend con el backend.
// Solo usa endpoints que existen en app/main.py: GET /salud, GET /metricas, POST /predecir (y GET /openapi.json).

// Mismo origen por defecto (FastAPI sirve el frontend). Se puede sobreescribir en pruebas.
const BASE = globalThis.SYNTAXGUARD_API_BASE ?? '';
const TIEMPO_MAX_MS = 20000;

export class ErrorApi extends Error {
  /** tipo: 'red' | 'timeout' | 'http' */
  constructor(mensaje, { tipo = 'red', estado = 0, detalle = null } = {}) {
    super(mensaje);
    this.name = 'ErrorApi';
    this.tipo = tipo;
    this.estado = estado;
    this.detalle = detalle;
  }
}

/** Convierte las respuestas de error de FastAPI (422 con lista, o `detail` en texto) en un mensaje legible. */
function mensajeDeError(estado, datos) {
  const detalle = datos && datos.detail;
  if (Array.isArray(detalle) && detalle.length) {
    return detalle
      .map((d) => {
        const campo = Array.isArray(d.loc) ? d.loc.filter((p) => p !== 'body').join('.') : '';
        const msg = String(d.msg || 'Valor no válido').replace(/^Value error,\s*/i, '');
        return campo ? `${campo}: ${msg}` : msg;
      })
      .join(' · ');
  }
  if (typeof detalle === 'string' && detalle) return detalle;
  if (estado === 404) return 'El recurso solicitado no existe en la API.';
  if (estado === 503) return 'El modelo no está disponible en este momento.';
  if (estado >= 500) return 'La API tuvo un error interno al procesar la solicitud.';
  return `La API respondió con el estado ${estado}.`;
}

async function pedir(ruta, { metodo = 'GET', cuerpo } = {}) {
  const control = new AbortController();
  const reloj = setTimeout(() => control.abort(), TIEMPO_MAX_MS);
  try {
    const resp = await fetch(BASE + ruta, {
      method: metodo,
      headers: cuerpo === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
      signal: control.signal,
    });
    const texto = await resp.text();
    let datos = null;
    if (texto) {
      try { datos = JSON.parse(texto); } catch { datos = null; }
    }
    if (!resp.ok) {
      throw new ErrorApi(mensajeDeError(resp.status, datos), { tipo: 'http', estado: resp.status, detalle: datos });
    }
    return datos;
  } catch (e) {
    if (e instanceof ErrorApi) throw e;
    if (e && e.name === 'AbortError') {
      throw new ErrorApi('La API tardó demasiado en responder. Inténtalo de nuevo.', { tipo: 'timeout' });
    }
    throw new ErrorApi('No se pudo conectar con la API. Verifica que el servidor esté en ejecución.', { tipo: 'red' });
  } finally {
    clearTimeout(reloj);
  }
}

export const api = {
  /** → { estado: 'ok', modelo_cargado: boolean } */
  salud: () => pedir('/salud'),
  /** → contenido de models/metricas.json */
  metricas: () => pedir('/metricas'),
  /** → { es_spam, probabilidad, rasgos_detectados: [{rasgo, categoria, valor, activo, descripcion}] } */
  predecir: ({ texto, html = null }) => pedir('/predecir', { metodo: 'POST', cuerpo: { texto, html } }),
  /** Versión de la API (campo info.version del esquema OpenAPI que genera FastAPI). */
  version: async () => (await pedir('/openapi.json'))?.info?.version ?? null,
};
