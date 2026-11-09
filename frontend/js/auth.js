// Sesión de la interfaz (Fase 6B). Implementa el contrato frontend/documentacion/FASE6_CONTRATO_API.md.
//
// Reglas de seguridad de este módulo:
//   * La cookie de sesión es HttpOnly: el navegador la envía sola; aquí nunca se lee ni se escribe.
//   * El token CSRF vive SOLO en la variable `csrf` de este módulo (memoria). No va a state.js, ni a
//     localStorage / sessionStorage, ni a la consola. Tras recargar la página se recupera con GET /auth/me.
//   * Las contraseñas no se guardan: pasan de la vista a api.js y no se registran en ningún lugar.
//   * Este módulo no toca el DOM (así se puede probar con Node) y no registra nada en la consola.
//
// Solicitudes de autenticación sin duplicados:
//   * GET /auth/me al arrancar es una sola promesa compartida (restaurarSesion) aunque se llame varias veces.
//   * La renovación del token CSRF también es una sola promesa compartida, aunque fallen varias peticiones a la vez.
//   * Cambiar de vista NO consulta la sesión: solo el arranque, un 403 csrf_invalido y el regreso a la pestaña tras
//     un rato (por si en otra pestaña se cerró la sesión o se entró con otra cuenta).
import { api, ErrorApi, cancelarPendientes, configurarSesion } from './api.js';
import { actualizar, obtener } from './state.js';

const MENSAJE_EXPIRADA = 'Tu sesión expiró. Inicia sesión de nuevo.';

let csrf = null;               // token CSRF de la sesión actual. Solo memoria.
let usuarioId = null;          // id de la cuenta que usó esta pestaña (para detectar un cambio de cuenta)
let restauracion = null;       // promesa compartida de GET /auth/me
let renovacion = null;         // promesa compartida de la renovación del token CSRF

/** Respuesta válida de registro / login / me según el contrato §2. */
function esSesionValida(d) {
  return !!d && typeof d === 'object' && !!d.usuario && Number.isInteger(d.usuario.id)
    && typeof d.usuario.usuario === 'string' && d.usuario.usuario.length > 0
    && typeof d.csrf_token === 'string' && d.csrf_token.length > 0;
}

/** Guarda el token en memoria y publica solo los datos para mostrar. */
function aplicar(d) {
  csrf = d.csrf_token;
  const cambioDeUsuario = usuarioId !== null && usuarioId !== d.usuario.id;
  usuarioId = d.usuario.id;
  actualizar({
    sesion: {
      fase: 'autenticado',
      usuario: { id: d.usuario.id, usuario: d.usuario.usuario, creado_en: d.usuario.creado_en ?? null },
      aviso: null, detalle: '', cambioDeUsuario,
    },
  });
}

function pasarAAnonimo(aviso) {
  csrf = null;
  actualizar({ sesion: { fase: 'anonimo', usuario: null, aviso, detalle: '', cambioDeUsuario: false } });
}

/**
 * La sesión terminó (401 en un endpoint privado, renovación fallida, regreso a la pestaña…): borra el token y el
 * usuario de la memoria, cancela las peticiones pendientes y deja la interfaz en «anónimo». Es idempotente.
 * No borra lo que la persona estaba escribiendo (vive en la memoria de las vistas): contrato §9.1.
 */
export function invalidarSesion(motivo = 'expirada') {
  csrf = null;
  cancelarPendientes();
  if (obtener().sesion.fase === 'anonimo') return;
  pasarAAnonimo(motivo === 'expirada' ? { tipo: 'aviso', texto: MENSAJE_EXPIRADA } : null);
}

/**
 * Consulta GET /auth/me y decide la pantalla. Varias llamadas simultáneas comparten una sola solicitud.
 * silenciosa: comprobación en segundo plano (regreso a la pestaña): no muestra «verificando» y un fallo de red
 * no expulsa a la persona; solo un 401 cierra la sesión de la interfaz.
 */
export function restaurarSesion({ silenciosa = false } = {}) {
  if (restauracion) return restauracion;
  if (!silenciosa) actualizar({ sesion: { ...obtener().sesion, fase: 'verificando', detalle: '', cambioDeUsuario: false } });
  restauracion = (async () => {
    const eraAutenticado = obtener().sesion.fase === 'autenticado';
    try {
      const d = await api.me();
      if (!esSesionValida(d)) throw new ErrorApi('La API devolvió una respuesta inesperada al comprobar la sesión.', { tipo: 'http' });
      aplicar(d);
    } catch (e) {
      if (e instanceof ErrorApi && e.estado === 401) {
        // no_autenticado (sin cookie): pantalla de acceso normal. sesion_expirada: acceso con aviso (contrato §2.3).
        if (eraAutenticado) invalidarSesion('expirada');
        else pasarAAnonimo(e.codigo === 'sesion_expirada' ? { tipo: 'aviso', texto: MENSAJE_EXPIRADA } : null);
      } else if (!silenciosa) {
        csrf = null;
        actualizar({ sesion: { fase: 'error', usuario: null, aviso: null, cambioDeUsuario: false,
          detalle: (e && e.message) || 'No se pudo comprobar la sesión.' } });
      }
    } finally {
      restauracion = null;
    }
  })();
  return restauracion;
}

/** Paso común de registro e inicio de sesión. Los errores de la API (ErrorApi) los maneja la pantalla de acceso. */
async function entrar(llamada) {
  const d = await llamada();
  if (!esSesionValida(d)) throw new ErrorApi('La API devolvió una respuesta inesperada. Inténtalo de nuevo.', { tipo: 'http' });
  aplicar(d);
}

/** POST /auth/registro (crea la cuenta e inicia sesión). Lanza ErrorApi: codigo, campos, reintentarEn. */
export const registrar = (usuario, contrasena) => entrar(() => api.registro({ usuario, contrasena }));

/** POST /auth/login. Lanza ErrorApi: codigo (credenciales_invalidas, demasiados_intentos…), reintentarEn. */
export const iniciarSesion = (usuario, contrasena) => entrar(() => api.login({ usuario, contrasena }));

/**
 * POST /auth/logout (con X-CSRF-Token). Si la API no responde NO se simula el cierre: la sesión seguiría viva en
 * el servidor, así que el error se propaga para avisar a la persona. Con éxito borra todo lo de la memoria.
 */
export async function cerrarSesion() {
  try {
    await api.logout();
  } catch (e) {
    if (!(e instanceof ErrorApi && e.tipo === 'sesion')) throw e; // sesión ya inválida en el servidor = ya está cerrada
  }
  csrf = null;
  usuarioId = null;
  cancelarPendientes();
  actualizar({ sesion: { fase: 'anonimo', usuario: null, aviso: { tipo: 'ok', texto: 'Cerraste sesión.' }, detalle: '', cambioDeUsuario: false } });
}

/**
 * Renueva el token CSRF con GET /auth/me (contrato §9.2). → 'ok' | 'sesion' | 'fallo'.
 * Si /auth/me responde con OTRA cuenta (en otra pestaña se inició sesión con otro usuario) NO se reintenta nada:
 * la interfaz se marca como «cambio de usuario» y se recarga, para no ejecutar acciones con una cuenta distinta
 * de la que muestra la pantalla.
 */
function renovarCsrf() {
  if (renovacion) return renovacion;
  renovacion = (async () => {
    try {
      const d = await api.me();
      if (!esSesionValida(d)) return 'fallo';
      if (usuarioId !== null && d.usuario.id !== usuarioId) { aplicar(d); return 'sesion'; }
      csrf = d.csrf_token;
      return 'ok';
    } catch (e) {
      if (e instanceof ErrorApi && e.estado === 401) { invalidarSesion('expirada'); return 'sesion'; }
      return 'fallo';
    } finally {
      renovacion = null;
    }
  })();
  return renovacion;
}

// Conexión con api.js (token CSRF, renovación y fin de sesión).
configurarSesion({ csrf: () => csrf, renovar: renovarCsrf, expirada: () => invalidarSesion('expirada') });
