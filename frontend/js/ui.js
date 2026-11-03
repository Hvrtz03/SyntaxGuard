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

// Formato del prototipo: coma decimal (0,12 · 92,7 %) y punto de millares (1.000).
// Para usar punto decimal (convención de México) basta con cambiar LOCALE_NUMEROS a 'es-MX'.
const LOCALE_NUMEROS = 'es-ES';
const NUM = new Intl.NumberFormat(LOCALE_NUMEROS, { maximumFractionDigits: 4, useGrouping: 'always' });
const PCT = new Intl.NumberFormat(LOCALE_NUMEROS, { style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 });
/** Formatea un número (0,9407). */
export const fmtNum = (v) => (typeof v === 'number' && Number.isFinite(v) ? NUM.format(v) : '—');
/** Formatea una proporción 0–1 como porcentaje (87,0 %). */
export const fmtPct = (v) => (typeof v === 'number' && Number.isFinite(v) ? PCT.format(v).replace(/\s?%$/, ' %') : '—');
