// Cliente de la API de SyntaxGuard. Único punto de contacto del frontend con el backend.
// Fases 2 a 5: /salud, /metricas, /predecir, /correo/extraer, lotes, historial, retroalimentación y estadísticas.
// Fase 6B (contrato: frontend/documentacion/FASE6_CONTRATO_API.md):
//   * La cookie de sesión HttpOnly la gestiona el navegador (fetch con credentials: 'same-origin'); aquí no se toca.
//   * El token CSRF NO se guarda aquí: lo conserva auth.js solo en memoria y api.js lo pide con `sesion.csrf()`.
//     Se envía en X-CSRF-Token en toda petición que no sea GET/HEAD (§1 y §5 del contrato).
//   * 401 en un endpoint privado = sesión terminada: se avisa a auth.js y se cancelan las peticiones pendientes (§9.1).
//   * 403 con codigo «csrf_invalido»: se renueva el token con GET /auth/me y se reintenta UNA sola vez (§9.2).
//   * 429: no se reintenta; el mensaje informa la espera (§9.3).
//   * Los endpoints /auth/* se piden con `auth: true`: su 401 (p. ej. credenciales incorrectas) no cierra ninguna sesión.
// api.js no importa auth.js (evita un ciclo): auth.js se conecta con configurarSesion().

// Mismo origen por defecto (FastAPI sirve el frontend). Se puede sobreescribir en pruebas.
const BASE = globalThis.SYNTAXGUARD_API_BASE ?? '';
const TIEMPO_MAX_MS = 20000;
const ENCABEZADO_CSRF = 'X-CSRF-Token';
const METODOS_SIN_CSRF = new Set(['GET', 'HEAD']);
const MSG_SESION_EXPIRADA = 'Tu sesión expiró. Inicia sesión de nuevo.';
const MSG_ERROR_SERVIDOR_AUTH = 'El servidor tuvo un problema al procesar la solicitud. Inténtalo de nuevo en unos momentos.';

export class ErrorApi extends Error {
  /**
   * tipo: 'red' | 'timeout' | 'http' | 'cancelado' | 'sesion'
   * codigo / campos / reintentarEn: datos estables del contrato (§8) cuando la API los envía.
   */
  constructor(mensaje, { tipo = 'red', estado = 0, detalle = null, codigo = null, campos = null, reintentarEn = null } = {}) {
    super(mensaje);
    this.name = 'ErrorApi';
    this.tipo = tipo;
    this.estado = estado;
    this.detalle = detalle;
    this.codigo = codigo;
    this.campos = campos;
    this.reintentarEn = reintentarEn;
  }
}

/** Enlaces con la sesión. Los define auth.js; por defecto no hacen nada. renovar() → 'ok' | 'sesion' | 'fallo'. */
const sesion = { csrf: () => null, renovar: async () => 'fallo', expirada: () => {} };
export function configurarSesion(enlaces) { Object.assign(sesion, enlaces); }

/** Peticiones privadas en curso: se cancelan todas cuando la sesión termina. */
const enCurso = new Set();
export function cancelarPendientes() {
  for (const p of [...enCurso]) { p.porSesion = true; p.control.abort(); }
}

/** «45 s», «15 min». */
function fmtEspera(seg) {
  if (!Number.isFinite(seg) || seg <= 0) return '';
  return seg < 60 ? `${Math.ceil(seg)} s` : `${Math.ceil(seg / 60)} min`;
}

/** Convierte las respuestas de error de FastAPI (422 con lista, o `detail` en texto) en un mensaje legible. */
function mensajeDeError(estado, datos, espera = null) {
  const detalle = datos && datos.detail;
  const codigo = datos && typeof datos.codigo === 'string' ? datos.codigo : null;
  // Textos propios para los errores de seguridad: el `detail` del servidor es técnico (cabeceras Origin, CSRF).
  if (codigo === 'csrf_invalido') return 'No se pudo validar la solicitud de seguridad. Actualiza la página e inténtalo de nuevo.';
  if (codigo === 'origen_no_permitido') return 'La solicitud fue rechazada por seguridad. Abre SyntaxGuard desde la dirección del servidor e inténtalo de nuevo.';
  if (estado === 429) {
    const base = typeof detalle === 'string' && detalle ? detalle : 'Demasiadas solicitudes. Espera antes de volver a intentar.';
    const t = fmtEspera(espera);
    return t ? `${base} Podrás reintentar en ${t}.` : base;
  }
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

/**
 * Petición genérica. Opciones:
 *  - cuerpo: objeto que se envía como JSON (para /predecir).
 *  - crudo + tipo: bytes/archivo/texto que se envían tal cual con ese Content-Type (para /correo/extraer).
 *  - cabeceras: cabeceras extra. tiempoMax: tiempo límite en ms.
 *  - auth: true en los endpoints /auth/*: un 401 aquí NO significa «sesión expirada» y no se guarda el cuerpo del error.
 */
async function pedir(ruta, opciones = {}, reintentoCsrf = true) {
  const { metodo = 'GET', cuerpo, crudo, tipo, cabeceras = {}, tiempoMax = TIEMPO_MAX_MS, senal, auth = false } = opciones;
  const verbo = metodo.toUpperCase();
  const control = new AbortController();
  const peticion = { control, porSesion: false };
  if (!auth) enCurso.add(peticion);
  const reloj = setTimeout(() => control.abort(), tiempoMax);
  // `senal` permite cancelar desde fuera (Fase 5: botón «Cancelar» del análisis masivo).
  const alCancelar = () => control.abort();
  if (senal) { if (senal.aborted) control.abort(); else senal.addEventListener('abort', alCancelar, { once: true }); }
  let renovarYReintentar = false;
  try {
    const headers = { Accept: 'application/json', ...cabeceras };
    let body;
    if (crudo !== undefined) {
      body = crudo;
      headers['Content-Type'] = tipo || 'application/octet-stream';
    } else if (cuerpo !== undefined) {
      body = JSON.stringify(cuerpo);
      headers['Content-Type'] = 'application/json';
    }
    if (!METODOS_SIN_CSRF.has(verbo)) {
      const token = sesion.csrf();
      if (token) headers[ENCABEZADO_CSRF] = token; // el navegador agrega solo Origin y la cookie
    }
    const resp = await fetch(BASE + ruta, {
      method: metodo, headers, body, signal: control.signal,
      credentials: 'same-origin', // contrato §1: la cookie HttpOnly viaja sola; el JavaScript no la ve
      ...(auth ? { cache: 'no-store' } : {}),
    });
    const texto = await resp.text();
    let datos = null;
    if (texto) {
      try { datos = JSON.parse(texto); } catch { datos = null; }
    }
    if (resp.ok) return datos;

    const codigo = datos && typeof datos.codigo === 'string' ? datos.codigo : null;
    if (resp.status === 401 && !auth) {
      sesion.expirada(); // borra el token y el usuario de la memoria, cancela lo pendiente y muestra el acceso
      throw new ErrorApi(MSG_SESION_EXPIRADA, { tipo: 'sesion', estado: 401, codigo });
    }
    if (resp.status === 403 && codigo === 'csrf_invalido' && reintentoCsrf) {
      renovarYReintentar = true; // se resuelve fuera del try, cuando esta petición ya liberó sus recursos
    } else {
      let espera = datos && Number.isFinite(datos.reintentar_en_segundos) ? datos.reintentar_en_segundos : null;
      if (espera === null) { const r = Number(resp.headers.get('Retry-After')); espera = Number.isFinite(r) && r > 0 ? r : null; }
      const mensaje = auth && resp.status >= 500 ? MSG_ERROR_SERVIDOR_AUTH : mensajeDeError(resp.status, datos, espera);
      throw new ErrorApi(mensaje, {
        tipo: 'http', estado: resp.status, codigo, reintentarEn: espera,
        campos: datos && datos.campos && typeof datos.campos === 'object' ? datos.campos : null,
        detalle: auth ? null : datos, // en /auth/* no se conserva el cuerpo de la respuesta
      });
    }
  } catch (e) {
    if (e instanceof ErrorApi) throw e;
    if (e && e.name === 'AbortError') {
      if (peticion.porSesion) throw new ErrorApi(MSG_SESION_EXPIRADA, { tipo: 'sesion' });
      if (senal && senal.aborted) throw new ErrorApi('Análisis cancelado.', { tipo: 'cancelado' });
      throw new ErrorApi('La API tardó demasiado en responder. Inténtalo de nuevo.', { tipo: 'timeout' });
    }
    throw new ErrorApi('No se pudo conectar con la API. Verifica que el servidor esté en ejecución.', { tipo: 'red' });
  } finally {
    clearTimeout(reloj);
    enCurso.delete(peticion);
    if (senal) senal.removeEventListener('abort', alCancelar);
  }

  // Contrato §9.2: token CSRF inválido → GET /auth/me una vez y un único reintento.
  if (renovarYReintentar) {
    const r = await sesion.renovar();
    if (r === 'ok') return pedir(ruta, opciones, false);
    if (r === 'sesion') throw new ErrorApi(MSG_SESION_EXPIRADA, { tipo: 'sesion', estado: 401 });
    throw new ErrorApi(mensajeDeError(403, { codigo: 'csrf_invalido' }), { tipo: 'http', estado: 403, codigo: 'csrf_invalido' });
  }
  return null;
}

/** Convierte un objeto en query string omitiendo valores vacíos. */
function consulta(params = {}) {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && String(v).trim() !== '') q.set(k, String(v)); });
  const s = q.toString();
  return s ? `?${s}` : '';
}

export const api = {
  /* ---------- Fase 6B: autenticación (contrato FASE6_CONTRATO_API.md §2) ---------- */
  /** Sesión actual. → { usuario: {id, usuario, creado_en}, csrf_token, sesion: {expira_en} }. 401: no_autenticado | sesion_expirada. */
  me: () => pedir('/auth/me', { auth: true }),
  /** Crea la cuenta e inicia sesión (201). Misma forma de respuesta que `me`. Errores: 409, 422 (campos), 429, 403. */
  registro: ({ usuario, contrasena }) => pedir('/auth/registro', { metodo: 'POST', cuerpo: { usuario, contrasena }, auth: true }),
  /** Inicia sesión (200). Errores: 401 credenciales_invalidas, 429 (reintentar_en_segundos), 422, 403. */
  login: ({ usuario, contrasena }) => pedir('/auth/login', { metodo: 'POST', cuerpo: { usuario, contrasena }, auth: true }),
  /** Cierra y revoca la sesión (lleva X-CSRF-Token). → { cerrada: true, habia_sesion } */
  logout: () => pedir('/auth/logout', { metodo: 'POST', auth: true }),
  /* ---------- Fases 2 a 5 ---------- */
  /** → { estado: 'ok', modelo_cargado: boolean } */
  salud: () => pedir('/salud'),
  /** → contenido de models/metricas.json */
  metricas: () => pedir('/metricas'),
  /** → { es_spam, probabilidad, rasgos_detectados: [{rasgo, categoria, valor, activo, descripcion}] } */
  predecir: ({ texto, html = null }) => pedir('/predecir', { metodo: 'POST', cuerpo: { texto, html } }),
  /**
   * Extrae los campos de un correo. `datos` son los bytes crudos (File, Uint8Array o texto), SIN multipart.
   * → { origen, nombre_archivo, tamano_bytes, remitente, destinatario, asunto, fecha, fecha_iso, texto, html,
   *     enlaces: [{url, origen}], enlaces_total, adjuntos_ignorados, texto_desde_html, texto_truncado,
   *     html_truncado, limite_analisis_caracteres, advertencias: [] }
   */
  extraerCorreo: ({ datos, nombre = null, tipo = 'message/rfc822' }) => pedir('/correo/extraer', {
    metodo: 'POST',
    crudo: datos,
    tipo,
    // El nombre viaja codificado (encodeURIComponent); el servidor lo decodifica y solo lo usa como etiqueta.
    cabeceras: nombre ? { 'X-Nombre-Archivo': encodeURIComponent(nombre.length > 200 ? nombre.slice(-200) : nombre) } : {},
    tiempoMax: 60000,
  }),
  /* ---------- Fase 5: análisis masivo, historial, retroalimentación y estadísticas de uso ---------- */
  /** Crea un lote. → { id, creado_en, total_previsto } */
  crearLote: (total) => pedir('/lotes', { metodo: 'POST', cuerpo: { total } }),
  /** → { id, total_procesados, spam, legitimos, errores, clasificados, porcentaje_spam, porcentaje_legitimos } */
  resumenLote: (id) => pedir(`/lotes/${encodeURIComponent(id)}`),
  /** Extrae, analiza con el modelo real y guarda un correo del lote. Un correo inválido vuelve con estado «error» (200). */
  analizarArchivo: ({ archivo, nombre, tipo = 'message/rfc822', loteId = null, senal }) => pedir('/analisis/archivo', {
    metodo: 'POST',
    crudo: archivo,
    tipo,
    cabeceras: {
      'X-Nombre-Archivo': encodeURIComponent(nombre.length > 200 ? nombre.slice(-200) : nombre),
      ...(loteId ? { 'X-Lote-Id': String(loteId) } : {}),
    },
    tiempoMax: 120000,
    senal,
  }),
  /** Guarda en el historial un análisis individual que ya hizo /predecir. */
  registrarAnalisis: (datos) => pedir('/historial', { metodo: 'POST', cuerpo: datos }),
  /** Filtros: q, clasificacion, tipo, desde, hasta, lote_id, pagina, por_pagina. */
  historial: (filtros) => pedir(`/historial${consulta(filtros)}`),
  analisis: (id) => pedir(`/historial/${encodeURIComponent(id)}`),
  eliminarAnalisis: (id) => pedir(`/historial/${encodeURIComponent(id)}`, { metodo: 'DELETE' }),
  eliminarAnalisisVarios: (ids) => pedir('/historial/eliminar', { metodo: 'POST', cuerpo: { ids } }),
  /** URL de descarga del CSV (la descarga la hace el navegador con un enlace). */
  urlCsv: (filtros) => `${BASE}/historial/exportar.csv${consulta(filtros)}`,
  guardarRetro: ({ analisisId, deAcuerdo, comentario }) => pedir('/retroalimentacion', {
    metodo: 'POST', cuerpo: { analisis_id: analisisId, de_acuerdo: deAcuerdo, comentario: comentario || null } }),
  retroalimentaciones: (params) => pedir(`/retroalimentacion${consulta(params)}`),
  estadisticasUso: () => pedir('/estadisticas/uso'),
  /** Versión de la API (campo info.version del esquema OpenAPI que genera FastAPI). */
  version: async () => (await pedir('/openapi.json'))?.info?.version ?? null,
};
