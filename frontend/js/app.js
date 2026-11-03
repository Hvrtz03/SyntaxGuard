// Arranque del cascarón: menú lateral, barra superior con el estado real de la API y router.
import { RUTAS, iniciarRouter } from './router.js';
import { api } from './api.js';
import { actualizar, obtener, suscribir } from './state.js';
import { h, icono } from './ui.js';

const INTERVALO_SALUD_MS = 30000;

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
      h('span', {}, 'Proyecto académico')));
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

  construirLateral(lateral);
  construirTopbar(topbar);
  suscribir(pintarEstado);
  pintarEstado(obtener());

  document.getElementById('saltar')?.addEventListener('click', (ev) => {
    ev.preventDefault();
    contenido.focus();
  });

  iniciarRouter({ contenedor: contenido, alNavegar: marcarActivo });

  comprobarSalud();
  cargarVersion();
  setInterval(() => { if (!document.hidden) comprobarSalud(); }, INTERVALO_SALUD_MS);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) comprobarSalud(); });
}

iniciar();
