// Utilidades de interfaz compartidas por todas las vistas.
// Regla: el texto se inserta siempre con textContent / nodos de texto (nunca innerHTML con datos externos).
import { ICONOS } from './iconos.js';

const NS_SVG = 'http://www.w3.org/2000/svg';

/** Crea un elemento. attrs: class, on<Evento>, y cualquier atributo HTML. hijos: nodos, textos o arreglos. */
export function h(etiqueta, attrs = {}, ...hijos) {
  const el = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(attrs || {})) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (clave === 'class') el.className = valor;
    else if (clave.startsWith('on') && typeof valor === 'function') el.addEventListener(clave.slice(2).toLowerCase(), valor);
    else el.setAttribute(clave, valor === true ? '' : String(valor));
  }
  for (const hijo of hijos.flat(Infinity)) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.append(hijo.nodeType ? hijo : document.createTextNode(String(hijo)));
  }
  return el;
}

/** Icono SVG decorativo (aria-hidden). */
export function icono(nombre, { tam = 18, clase = '' } = {}) {
  const svg = document.createElementNS(NS_SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(tam));
  svg.setAttribute('height', String(tam));
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  if (clase) svg.setAttribute('class', clase);
  svg.innerHTML = ICONOS[nombre] || '';
  return svg;
}

/** Encabezado de página: título (h1) y subtítulo. */
export function encabezadoPagina({ titulo, subtitulo }) {
  return h('header', { class: 'pagina__cabecera' },
    h('h1', { class: 'pagina__titulo', tabindex: '-1', id: 'titulo-pagina' }, titulo),
    subtitulo ? h('p', { class: 'pagina__sub' }, subtitulo) : null);
}

/** Pasos del flujo del prototipo: Cargar → Analizar → Entender → Explorar → Feedback. */
export const PASOS = ['Cargar', 'Analizar', 'Entender', 'Explorar', 'Feedback'];

/** actual: 1..5. Los pasos anteriores se muestran como completados. */
export function indicadorPasos(actual) {
  return h('ol', { class: 'stepper', 'aria-label': 'Progreso del flujo de análisis' },
    PASOS.map((nombre, i) => {
      const n = i + 1;
      const clase = n < actual ? 'paso paso--hecho' : n === actual ? 'paso paso--actual' : 'paso';
      return h('li', { class: clase, 'aria-current': n === actual ? 'step' : null },
        h('span', { class: 'paso__num' }, n < actual ? icono('check', { tam: 14 }) : String(n)),
        h('span', { class: 'paso__txt' }, nombre),
        n < PASOS.length ? icono('flecha', { tam: 16, clase: 'paso__flecha' }) : null);
    }));
}

/** Tarjeta para secciones que se construyen en una fase posterior del plan. */
export function tarjetaPendiente({ titulo, texto, fase }) {
  return h('section', { class: 'tarjeta pendiente' },
    h('span', { class: 'chip chip--aviso' }, icono('construccion', { tam: 14 }), `En construcción · Fase ${fase}`),
    h('h2', { class: 'tarjeta__titulo' }, titulo),
    h('p', { class: 'tarjeta__texto' }, texto));
}

/** Aviso de error con rol de alerta. */
export function avisoError(mensaje) {
  return h('div', { class: 'aviso aviso--error', role: 'alert' }, icono('alerta', { tam: 16 }), h('span', {}, mensaje));
}

// Formato mexicano (es-MX): punto decimal (0.12 · 92.7 %) y coma de millares (1,000).
const LOCALE_NUMEROS = 'es-MX';
const NUM = new Intl.NumberFormat(LOCALE_NUMEROS, { maximumFractionDigits: 4, useGrouping: 'always' });
const PCT = new Intl.NumberFormat(LOCALE_NUMEROS, { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });
/** Formatea un número (0,9407). */
export const fmtNum = (v) => (typeof v === 'number' && Number.isFinite(v) ? NUM.format(v) : '—');
/** Formatea una proporción 0–1 como porcentaje (87,0 %). */
export const fmtPct = (v) => (typeof v === 'number' && Number.isFinite(v) ? PCT.format(v).replace(/\s?%$/, ' %') : '—');

/** Tamaño legible: 842 bytes · 12,3 KB · 1,2 MB. */
export function fmtBytes(n) {
  if (typeof n !== 'number' || !Number.isFinite(n) || n < 0) return '—';
  const fmt = new Intl.NumberFormat(LOCALE_NUMEROS, { maximumFractionDigits: 1 });
  if (n < 1024) return `${fmt.format(n)} bytes`;
  if (n < 1024 * 1024) return `${fmt.format(n / 1024)} KB`;
  return `${fmt.format(n / (1024 * 1024))} MB`;
}

/** Cambia el paso resaltado del indicador (sin volver a renderizar la página). */
export function actualizarPasos(actual) {
  const viejo = document.querySelector('.stepper');
  if (viejo) viejo.replaceWith(indicadorPasos(actual));
}

/* ---------- Fase 5: fechas, clasificación, avisos emergentes y ventanas modales ---------- */
const FECHA_HORA = new Intl.DateTimeFormat('es-MX', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
const FECHA_HORA_COMPLETA = new Intl.DateTimeFormat('es-MX', { dateStyle: 'full', timeStyle: 'medium' });

/** Fecha y hora local legibles a partir de una fecha ISO (UTC) del servidor. «—» si no es válida. */
export function fmtFecha(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? FECHA_HORA.format(d) : '—';
}
/** Versión larga (día de la semana y segundos) para títulos emergentes. */
export function fmtFechaLarga(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? FECHA_HORA_COMPLETA.format(d) : '';
}

/** Chip con la clasificación de un registro del historial: SPAM, LEGÍTIMO o Error. */
export function chipClasificacion(r) {
  if (r.estado === 'error') return h('span', { class: 'chip chip--aviso' }, 'Error');
  return r.es_spam ? h('span', { class: 'chip chip--error' }, 'SPAM') : h('span', { class: 'chip chip--ok' }, 'LEGÍTIMO');
}

/** Aviso emergente (no bloquea). tipo: 'ok' | 'error' | 'info'. */
export function toast(mensaje, tipo = 'ok') {
  let caja = document.getElementById('avisos-emergentes');
  if (!caja) {
    caja = h('div', { id: 'avisos-emergentes', class: 'toasts', role: 'status', 'aria-live': 'polite' });
    document.body.append(caja);
  }
  const el = h('div', { class: `toast toast--${tipo}` }, icono(tipo === 'error' ? 'alerta' : 'check', { tam: 16 }), h('span', {}, mensaje));
  caja.append(el);
  setTimeout(() => el.remove(), tipo === 'error' ? 7000 : 4500);
}

/** Ventana modal (<dialog>). Devuelve { cerrar }. Se cierra con Esc, con el botón o al hacer clic fuera. */
export function modal({ titulo, cuerpo, ancho = 'normal', alCerrar = null }) {
  const dlg = h('dialog', { class: `modal modal--${ancho}`, 'aria-labelledby': 'titulo-modal' });
  const cerrar = () => { if (dlg.open) dlg.close(); };
  dlg.append(
    h('div', { class: 'modal__cabecera' },
      h('h2', { class: 'tarjeta__titulo', id: 'titulo-modal' }, titulo),
      h('button', { type: 'button', class: 'btn btn--secundario btn--chico', 'aria-label': 'Cerrar', onclick: cerrar }, icono('cerrar', { tam: 14 }), 'Cerrar')),
    h('div', { class: 'modal__cuerpo' }, cuerpo));
  dlg.addEventListener('click', (ev) => { if (ev.target === dlg) cerrar(); });
  dlg.addEventListener('close', () => { dlg.remove(); if (alCerrar) alCerrar(); });
  document.body.append(dlg);
  dlg.showModal();
  return { cerrar };
}

/** Pregunta de confirmación. Resuelve true si la persona acepta. */
export function confirmar({ titulo, texto, aceptar = 'Aceptar', peligro = false }) {
  return new Promise((resolver) => {
    let decidido = false;
    const decidir = (v) => { decidido = true; resolver(v); m.cerrar(); };
    const m = modal({
      titulo,
      ancho: 'chico',
      cuerpo: [
        h('p', { class: 'tarjeta__texto' }, texto),
        h('div', { class: 'acciones acciones--fila' },
          h('button', { type: 'button', class: 'btn btn--secundario', onclick: () => decidir(false) }, 'Cancelar'),
          h('button', { type: 'button', class: `btn ${peligro ? 'btn--peligro' : 'btn--primario'}`, id: 'btn-confirmar', onclick: () => decidir(true) }, aceptar)),
      ],
      alCerrar: () => { if (!decidido) resolver(false); },
    });
    document.getElementById('btn-confirmar')?.focus();
  });
}

/** Texto para un nombre de archivo y asunto en tablas (con valor de reserva). */
export const textoOGuion = (v) => (v && String(v).trim() ? String(v) : '—');
