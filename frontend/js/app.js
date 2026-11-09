// Arranque del cascarón: menú lateral, barra superior con el estado real de la API, sesión y router.
//
// Fase 6B: la aplicación no pinta ninguna vista privada ni hace peticiones privadas hasta conocer el estado de la
// sesión. Orden de arranque: (1) cascarón público, (2) GET /auth/me (una sola vez), (3) según el resultado:
//   verificando → «Comprobando tu sesión…» · anónimo → pantalla de acceso · error → aviso con «Reintentar» ·
//   autenticado → router (las vistas de siempre). Contrato: frontend/documentacion/FASE6_CONTRATO_API.md.
import { RUTAS, iniciarRouter } from './router.js';
import { api } from './api.js';
import { cerrarSesion, restaurarSesion } from './auth.js';
import { actualizar, obtener, suscribir } from './state.js';
import { avisoError, confirmar, h, icono, toast } from './ui.js';
import { renderAcceso } from './vistas/acceso.js';

const INTERVALO_SALUD_MS = 30000;
// Al volver a la pestaña tras este tiempo se comprueba la sesión en segundo plano (contrato §9.4). También cubre el
// caso de que en otra pestaña se haya cerrado la sesión o se haya entrado con otra cuenta.
const UMBRAL_REVERIFICAR_MS = 60000;

/* ---------- Lateral ---------- */
function construirLateral(contenedor) {
  const enlaces = RUTAS.map((r) =>
    h('li', {},
      h('a', { class: 'nav__item', href: '#' + r.ruta, 'data-ruta': r.id },
        icono(r.icono, { tam: 18 }), h('span', {}, r.etiqueta))));

  const version = h('p', { class: 'pie__linea', id: 'pie-version' }, 'API · …');
  const servidor = h('p', { class: 'pie__linea' }, location.host || 'sin servidor');

  contenedor.replaceChildren(
    h('div', { class: 'lateral__cabecera' },
      h('a', { class: 'marca', href: '#/analisis', 'aria-label': 'SyntaxGuard, ir a Análisis' },
        icono('escudo', { tam: 26 }), h('span', {}, 'SyntaxGuard'))),
    h('nav', { class: 'lateral__grupo', 'aria-labelledby': 'etiqueta-nav' },
      h('p', { class: 'lateral__etiqueta', id: 'etiqueta-nav' }, 'Espacio de trabajo'),
      h('ul', { class: 'nav' }, enlaces)),
    h('div', { class: 'lateral__pie' },
      h('p', { class: 'pie__titulo' }, 'Proyecto académico'), version, servidor));
}

function marcarActivo(definicion) {
  document.querySelectorAll('.nav__item').forEach((a) => {
    if (a.dataset.ruta === definicion.id) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
}

/* ---------- Barra superior ---------- */
function construirTopbar(contenedor) {
  contenedor.replaceChildren(
    h('div', { class: 'topbar__migas' },
      h('strong', {}, 'SyntaxGuard'), h('span', { 'aria-hidden': 'true' }, '/'), h('span', {}, 'Detección explicable de spam')),
    h('div', { class: 'topbar__acciones' },
      h('span', { class: 'chip chip--neutro', id: 'chip-api', role: 'status', 'aria-live': 'polite' }),
      h('span', { class: 'topbar__separador', 'aria-hidden': 'true' }),
      h('span', {}, 'Proyecto académico'),
      // Cuenta activa y «Cerrar sesión» (solo con sesión). El nombre se inserta como texto, nunca como HTML.
      h('span', { class: 'topbar__sesion', id: 'topbar-sesion' })));
}

const ESTADOS_API = {
  cargando: ['neutro', 'Comprobando API…'],
  ok: ['ok', 'Modelo cargado'],
  sin_modelo: ['aviso', 'Modelo no cargado'],
  error: ['error', 'API sin conexión'],
};

function pintarEstado(estado) {
  const chip = document.getElementById('chip-api');
  if (chip) {
    const [tipo, texto] = ESTADOS_API[estado.salud.fase] || ESTADOS_API.cargando;
    chip.className = `chip chip--${tipo}`;
    chip.replaceChildren(h('span', { class: 'chip__punto', 'aria-hidden': 'true' }), texto);
    if (estado.salud.detalle) chip.title = estado.salud.detalle; else chip.removeAttribute('title');
  }
  const pie = document.getElementById('pie-version');
  if (pie) pie.textContent = estado.version ? `API v${estado.version}` : 'API · versión desconocida';
}

/* ---------- Sesión: qué se muestra en cada estado ---------- */
let router = null;
let faseAnterior = null;
let acceso = null;            // vista de acceso activa (para liberar su temporizador al reemplazarla)
let avisoDeArranque = null;   // «Cerraste sesión.» que llega en el hash tras recargar al cerrar sesión
let primerPintado = true;
let recargando = false;
let cerrando = false;

/** Tras cerrar sesión se recarga con #/acceso?aviso=cerrada (no es un dato sensible); se lee una vez y se limpia. */
function leerAvisoDeArranque() {
  const m = /^#\/acceso(?:\?(.*))?$/.exec(location.hash);
  if (!m) return null;
  history.replaceState(null, '', location.pathname + location.search);
  return new URLSearchParams(m[1] || '').get('aviso') === 'cerrada' ? { tipo: 'ok', texto: 'Cerraste sesión.' } : null;
}

function pintarUsuario(sesion) {
  const caja = document.getElementById('topbar-sesion');
  if (!caja) return;
  if (sesion.fase !== 'autenticado' || !sesion.usuario) {
    if (caja.childElementCount) caja.replaceChildren();
    delete caja.dataset.usuario;
    return;
  }
  const nombre = sesion.usuario.usuario;
  if (caja.dataset.usuario === nombre && caja.childElementCount) return; // sin repintar en cada actualización de estado
  caja.dataset.usuario = nombre;
  caja.replaceChildren(
    h('span', { class: 'topbar__separador', 'aria-hidden': 'true' }),
    h('span', { class: 'chip chip--neutro chip--usuario', title: `Cuenta activa: ${nombre}` },
      icono('usuario', { tam: 14 }),
      h('span', { class: 'solo-lectores' }, 'Cuenta activa: '),
      h('span', { class: 'chip__texto' }, nombre)),
    h('button', { type: 'button', class: 'btn btn--secundario btn--chico', id: 'btn-cerrar-sesion', onclick: alCerrarSesion },
      icono('salir', { tam: 14 }), 'Cerrar sesión'));
}

async function alCerrarSesion() {
  if (cerrando) return;
  if (obtener().masivo.fase === 'analizando') {
    const seguir = await confirmar({
      titulo: 'Cerrar sesión',
      texto: 'Hay un análisis masivo en curso. Si cierras sesión se detendrá; los correos ya analizados quedan guardados.',
      aceptar: 'Cerrar sesión', peligro: true,
    });
    if (!seguir) return;
  }
  cerrando = true;
  const boton = document.getElementById('btn-cerrar-sesion');
  if (boton) boton.disabled = true;
  try {
    await cerrarSesion(); // revoca la sesión en el servidor (POST /auth/logout con X-CSRF-Token)
    // Se recarga la página para descartar TODA la memoria de la interfaz (análisis, lotes, borradores, token CSRF):
    // así una cuenta nueva no puede ver datos de la anterior.
    recargando = true;
    history.replaceState(null, '', location.pathname + location.search + '#/acceso?aviso=cerrada');
    location.reload();
  } catch (e) {
    toast(`No se pudo cerrar la sesión: ${e.message || 'error desconocido'}`, 'error');
    if (boton) boton.disabled = false;
  } finally {
    cerrando = false;
  }
}

function quitarAcceso() {
  if (acceso) { acceso.destruir(); acceso = null; }
}

function mostrarVerificando(contenido) {
  contenido.setAttribute('aria-busy', 'true');
  contenido.replaceChildren(h('div', { class: 'estado', role: 'status' },
    h('span', { class: 'spinner', 'aria-hidden': 'true' }), 'Comprobando tu sesión…'));
}

function mostrarErrorDeSesion(contenido, sesion) {
  contenido.setAttribute('aria-busy', 'false');
  contenido.replaceChildren(h('section', { class: 'acceso' },
    h('div', { class: 'tarjeta acceso__tarjeta' },
      h('h1', { class: 'acceso__titulo', id: 'titulo-pagina', tabindex: '-1' }, 'No se pudo comprobar tu sesión'),
      avisoError(sesion.detalle || 'No se pudo comprobar la sesión. Inténtalo de nuevo.'),
      h('div', { class: 'acciones' },
        h('button', { type: 'button', class: 'btn btn--primario btn--bloque', id: 'btn-reintentar-sesion', onclick: () => restaurarSesion() },
          icono('reintentar', { tam: 16 }), 'Reintentar')))));
  document.title = 'Sin conexión · SyntaxGuard';
}

function mostrarAcceso(contenido, sesion) {
  const aviso = avisoDeArranque || sesion.aviso;
  avisoDeArranque = null;
  acceso = renderAcceso({ aviso });
  contenido.replaceChildren(acceso.el);
  contenido.setAttribute('aria-busy', 'false');
  document.title = 'Acceso · SyntaxGuard';
  // En la primera carga no se roba el foco (en móvil abriría el teclado); si la pantalla aparece por un evento
  // (sesión caducada, cierre de sesión) se enfoca el título para que se anuncie.
  if (!primerPintado) acceso.enfocar();
}

function entrarEnLaApp(contenido) {
  contenido.setAttribute('aria-busy', 'true');
  if (!router) {
    router = iniciarRouter({ contenedor: contenido, alNavegar: marcarActivo, puedeNavegar: () => obtener().sesion.fase === 'autenticado' });
  } else {
    router.refrescar(); // sesión recuperada: vuelve a la ruta (y al borrador) donde estaba la persona
  }
}

function recargarPorCambioDeCuenta(contenido) {
  recargando = true;
  contenido.replaceChildren(h('div', { class: 'estado', role: 'status' },
    h('span', { class: 'spinner', 'aria-hidden': 'true' }), 'Se detectó otra cuenta en este navegador. Recargando…'));
  location.reload();
}

function pintarSesion(estado) {
  const sesion = estado.sesion;
  const fase = sesion.fase;
  if (recargando) return;
  document.querySelector('.app')?.setAttribute('data-sesion', fase);
  pintarUsuario(sesion);

  const contenido = document.getElementById('contenido');
  // Otra cuenta distinta de la que muestra esta pestaña: se recarga para no mezclar datos de dos usuarios.
  if (fase === 'autenticado' && sesion.cambioDeUsuario) { quitarAcceso(); recargarPorCambioDeCuenta(contenido); return; }
  if (fase === faseAnterior) return; // actualizaciones de salud o repetidas: no se vuelve a pintar la pantalla
  faseAnterior = fase;
  quitarAcceso();
  if (fase === 'autenticado') entrarEnLaApp(contenido);
  else if (fase === 'anonimo') mostrarAcceso(contenido, sesion);
  else if (fase === 'error') mostrarErrorDeSesion(contenido, sesion);
  else mostrarVerificando(contenido);
  if (fase !== 'verificando') primerPintado = false;
}

/* ---------- Conexión con la API ---------- */
async function comprobarSalud() {
  try {
    const r = await api.salud();
    actualizar({ salud: { fase: r.modelo_cargado ? 'ok' : 'sin_modelo', detalle: r.modelo_cargado ? '' : 'La API responde, pero el modelo no se cargó. Revisa models/clasificador.pkl.' } });
  } catch (e) {
    actualizar({ salud: { fase: 'error', detalle: e.message } });
  }
}

async function cargarVersion() {
  try { actualizar({ version: await api.version() }); } catch { /* el pie muestra "versión desconocida" */ }
}

/* ---------- Inicio ---------- */
function iniciar() {
  const lateral = document.getElementById('lateral');
  const topbar = document.getElementById('topbar');
  const contenido = document.getElementById('contenido');

  avisoDeArranque = leerAvisoDeArranque();
  construirLateral(lateral);
  construirTopbar(topbar);
  suscribir(pintarEstado);
  suscribir(pintarSesion);
  pintarEstado(obtener());
  pintarSesion(obtener()); // fase inicial «verificando»: nada privado se pinta ni se pide todavía

  document.getElementById('saltar')?.addEventListener('click', (ev) => {
    ev.preventDefault();
    contenido.focus();
  });

  restaurarSesion(); // GET /auth/me: única consulta de sesión al arrancar
  comprobarSalud(); // /salud y /openapi.json son públicos
  cargarVersion();
  setInterval(() => { if (!document.hidden) comprobarSalud(); }, INTERVALO_SALUD_MS);

  let ocultoDesde = null;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { ocultoDesde = Date.now(); return; }
    comprobarSalud();
    if (obtener().sesion.fase === 'autenticado' && ocultoDesde !== null && Date.now() - ocultoDesde >= UMBRAL_REVERIFICAR_MS) {
      restaurarSesion({ silenciosa: true });
    }
    ocultoDesde = null;
  });
}

iniciar();
