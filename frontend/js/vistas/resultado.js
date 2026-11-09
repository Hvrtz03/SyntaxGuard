// Pantalla de RESULTADOS Y EVIDENCIAS (Fase 4).
//
// Dibuja lo que ya devolvieron el backend (/correo/extraer y /predecir). No llama a /predecir ni a
// /correo/extraer: cambiar de pestaña, abrir secciones o volver a esta pantalla nunca repite el análisis.
// La única llamada propia es GET /metricas, y solo cuando la persona abre «Limitaciones del clasificador».
//
// Reglas que respeta (ver README de la Fase 4):
//   * La clasificación final es SIEMPRE `es_spam` tal como la entregó el modelo. Nunca se recalcula aquí.
//   * P(spam) es la probabilidad de la clase spam, no una medida de confianza.
//   * El «nivel de riesgo» es una lectura orientativa de P(spam) por tramos de presentación; no es una salida del modelo.
//   * Los rasgos son heurísticas del detector (umbrales fijos), no atribuciones causales del modelo.
//   * Los enlaces se muestran como texto, sin hacerlos clicables y sin llamarlos «maliciosos».
//   * Todo dato externo se inserta con h() (nodos de texto). No hay innerHTML con datos del correo.
import { api } from '../api.js';
import { h, icono, fmtNum, fmtPct, fmtBytes } from '../ui.js';
import {
  NOTA_ENLACES, datosCorreo, listaEnlaces, bloqueTexto, bloqueHtml,
  caracteristicasEstructurales, tablaDatos, faltantes, avisoConIcono,
} from '../evidencias.js';

/* ---------- Constantes ---------- */
export const UMBRAL = 0.5; // umbral de decisión del modelo (fijo). El veredicto viene de es_spam, no de esta constante.
const CERCA_DEL_UMBRAL = 0.10; // «caso límite» si |P(spam) − umbral| es menor que esto
const CATEGORIAS = { texto: 'Texto', url: 'URL', dom: 'Estructura HTML', sintactico: 'Sintaxis' };

// Tramos de PRESENTACIÓN de P(spam). Los define SyntaxGuard para dibujar la escala; el modelo no los usa.
export const NIVELES = [
  { id: 'bajo', nombre: 'Bajo', desde: 0, hasta: 0.25, rango: '0–25 %', nota: 'Muy por debajo del umbral' },
  { id: 'moderado', nombre: 'Moderado', desde: 0.25, hasta: 0.5, rango: '25–50 %', nota: 'Por debajo del umbral' },
  { id: 'alto', nombre: 'Alto', desde: 0.5, hasta: 0.75, rango: '50–75 %', nota: 'Sobre el umbral' },
  { id: 'muy-alto', nombre: 'Muy alto', desde: 0.75, hasta: 1.0000001, rango: '75–100 %', nota: 'Muy por encima del umbral' },
];

/** Tramo de la escala de riesgo para una probabilidad (0–1). */
export function nivelRiesgo(p) {
  const x = Math.max(0, Math.min(1, p));
  return NIVELES.find((n) => x >= n.desde && x < n.hasta) || NIVELES[NIVELES.length - 1];
}

/** Distancia con signo al umbral, en puntos porcentuales (redondeada a 1 decimal). */
export function distanciaUmbral(p) {
  return Math.round((Math.max(0, Math.min(1, p)) - UMBRAL) * 1000) / 10;
}

export const esCasoLimite = (p) => Math.abs(p - UMBRAL) < CERCA_DEL_UMBRAL;

/**
 * Revisa que es_spam y P(spam) concuerden con el umbral.
 *  - null: concuerdan.
 *  - 'redondeo': P(spam) llegó redondeada a exactamente 0,5 pero el valor real quedó apenas por debajo (es_spam = false).
 *  - 'incoherente': no concuerdan por otra razón (no debería ocurrir; se avisa y se respeta es_spam).
 */
export function coherencia(r) {
  const p = r.probabilidad;
  if (r.es_spam === (p >= UMBRAL)) return null;
  if (p === UMBRAL && !r.es_spam) return 'redondeo';
  return 'incoherente';
}

/* ---------- Estado local de la pantalla ---------- */
let pestanaEv = 'rasgos'; // pestaña de evidencias elegida (se conserva al volver a esta pantalla)
let metricasEstado = null; // null | 'cargando' | { ok: true, datos } | { ok: false, mensaje }

/* ---------- Banner con el veredicto ---------- */
function banner(r, acciones) {
  const spam = r.es_spam;
  return h('section', { class: `banner banner--${spam ? 'spam' : 'ok'}`, tabindex: '-1', 'aria-labelledby': 'tit-veredicto' },
    h('span', { class: 'banner__icono' }, icono(spam ? 'escudoAlerta' : 'escudo', { tam: 34 })),
    h('div', { class: 'banner__cuerpo' },
      h('p', { class: 'banner__etiqueta' }, 'Clasificación del modelo'),
      h('h2', { class: 'banner__titulo', id: 'tit-veredicto' }, spam ? 'SPAM' : 'LEGÍTIMO'),
      h('p', { class: 'banner__sub' }, spam ? 'El modelo clasifica este correo como spam.' : 'El modelo clasifica este correo como legítimo.'),
      h('p', { class: 'banner__regla' },
        `Regla de decisión: SPAM si P(spam) ≥ ${fmtPct(UMBRAL)}; LEGÍTIMO si es menor.`)),
    h('button', {
      type: 'button', class: 'btn btn--secundario banner__accion', id: 'btn-nuevo-analisis', onclick: acciones.reiniciar,
    }, icono('subir', { tam: 16 }), 'Nuevo análisis'));
}

/* ---------- Probabilidad, umbral y nivel de riesgo ---------- */
function escalaRiesgo(p) {
  const actual = nivelRiesgo(p);
  return h('div', { class: 'riesgo' },
    h('h3', { class: 'tarjeta__subtitulo' }, 'Nivel de riesgo (lectura orientativa de P(spam))'),
    h('ol', { class: 'escala', 'aria-label': 'Escala de nivel de riesgo según P(spam)' },
      NIVELES.map((n) => {
        const activo = n.id === actual.id;
        return h('li', {
          class: `escala__tramo escala__tramo--${n.id}${activo ? ' escala__tramo--activo' : ''}`,
          'aria-current': activo ? 'true' : null,
        },
        h('span', { class: 'escala__nombre' }, n.nombre, activo ? h('span', { class: 'solo-lectores' }, ' (nivel actual)') : null),
        h('span', { class: 'escala__rango' }, n.rango));
      })),
    h('p', { class: 'riesgo__texto' },
      h('strong', {}, `Nivel ${actual.nombre.toLowerCase()}`), ` · ${actual.nota}. `,
      'Esta escala solo reordena P(spam) en tramos para leerla con facilidad: no es una segunda salida del modelo ni mide su confianza, y los cortes no están calibrados. ',
      `La clasificación final depende únicamente de si P(spam) alcanza ${fmtPct(UMBRAL)}.`));
}

function notasProbabilidad(r) {
  const p = r.probabilidad;
  const notas = [];
  const coh = coherencia(r);
  if (coh === 'redondeo') {
    notas.push(avisoConIcono(
      'P(spam) se muestra redondeada a 50 %, pero el valor real quedó apenas por debajo del umbral, por eso el correo se clasifica como LEGÍTIMO.', 'info'));
  } else if (coh === 'incoherente') {
    notas.push(avisoConIcono(
      `La API devolvió una clasificación (${r.es_spam ? 'SPAM' : 'LEGÍTIMO'}) que no concuerda con P(spam) = ${fmtPct(p)} y el umbral de ${fmtPct(UMBRAL)}. Se muestra la clasificación que entregó el modelo; conviene revisar la respuesta de la API.`, 'error'));
  }
  if (esCasoLimite(p)) {
    notas.push(avisoConIcono(
      `Caso cercano al umbral: P(spam) está a menos de ${fmtNum(CERCA_DEL_UMBRAL * 100)} puntos del ${fmtPct(UMBRAL)}. Una pequeña diferencia en el contenido podría cambiar la clasificación; revísalo con criterio propio.`, 'info'));
  }
  return notas.length ? h('div', { class: 'lista-avisos' }, notas) : null;
}

function tarjetaProbabilidad(r) {
  const spam = r.es_spam;
  const p = Math.max(0, Math.min(1, r.probabilidad));
  const dist = distanciaUmbral(p);
  const distTxt = `${dist >= 0 ? '+' : '−'}${fmtNum(Math.abs(dist))} puntos`;
  const cifra = (etiqueta, valor, clase = '') => h('div', { class: 'cifra' },
    h('dt', {}, etiqueta), h('dd', { class: clase }, valor));
  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-prob' },
    h('div', { class: 'prob__cabecera' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-prob' }, 'Probabilidad de spam'),
      h('span', { class: 'prob__valor', style: `color:var(--c-${spam ? 'spam' : 'ok'})` }, fmtPct(p))),
    h('div', { class: 'medidor', role: 'img', 'aria-label': `Probabilidad de spam: ${fmtPct(p)}. El umbral de decisión es ${fmtPct(UMBRAL)}.` },
      h('div', { class: `medidor__relleno medidor__relleno--${spam ? 'spam' : 'ok'}`, style: `width:${(p * 100).toFixed(1)}%` }),
      h('span', { class: 'medidor__umbral' })),
    h('div', { class: 'medidor__marcas', 'aria-hidden': 'true' },
      h('span', {}, '0 %'), h('span', { class: 'umbral-etiqueta' }, `Umbral ${fmtPct(UMBRAL)}`), h('span', {}, '100 %')),
    h('dl', { class: 'cifras' },
      cifra('Clasificación final', spam ? 'SPAM' : 'LEGÍTIMO', spam ? 'cifra--spam' : 'cifra--ok'),
      cifra('Umbral de decisión', fmtPct(UMBRAL)),
      cifra('Distancia al umbral', distTxt)),
    h('p', { class: 'prob__explica' },
      `La probabilidad de spam es ${fmtPct(p)}: `,
      spam ? `igual o superior al umbral de decisión (${fmtPct(UMBRAL)}), por eso se clasifica como SPAM.`
        : `inferior al umbral de decisión (${fmtPct(UMBRAL)}), por eso se clasifica como LEGÍTIMO.`,
      ' Es la probabilidad que estima el modelo para la clase spam; no equivale a un porcentaje de certeza calibrado ni indica qué tan seguro está el modelo de su decisión.'),
    notasProbabilidad(r),
    escalaRiesgo(p));
}

/* ---------- Evidencias: rasgos ---------- */
function agrupar(items) {
  const orden = Object.keys(CATEGORIAS);
  const grupos = new Map();
  items.forEach((it) => {
    if (!grupos.has(it.categoria)) grupos.set(it.categoria, []);
    grupos.get(it.categoria).push(it);
  });
  const pos = (k) => { const i = orden.indexOf(k); return i < 0 ? 99 : i; };
  return [...grupos.entries()].sort((x, y) => pos(x[0]) - pos(y[0]));
}

function itemRasgo(r, inactivo = false) {
  return h('li', { class: `rasgo${inactivo ? ' rasgo--inactivo' : ''}` },
    h('div', { class: 'rasgo__desc' }, r.descripcion),
    h('div', { class: 'rasgo__id' }, r.rasgo),
    h('div', { class: 'rasgo__valor' }, h('strong', {}, fmtNum(r.valor)), h('span', {}, 'valor medido')));
}

function panelRasgos(r) {
  const activos = r.rasgos_detectados.filter((x) => x.activo);
  const inactivos = r.rasgos_detectados.filter((x) => !x.activo);
  if (!r.rasgos_detectados.length) {
    return h('p', { class: 'texto-tenue' }, 'La API no devolvió rasgos para este correo.');
  }
  const resumen = agrupar(activos).map(([cat, items]) =>
    h('span', { class: 'chip chip--categoria' }, `${CATEGORIAS[cat] || cat}: ${items.length}`));
  return h('div', {},
    h('div', { class: 'tarjeta__cabecera' },
      h('h3', { class: 'tarjeta__subtitulo tarjeta__subtitulo--sin-margen' }, 'Rasgos detectados por el sistema'),
      h('span', { class: `chip ${activos.length ? 'chip--aviso' : 'chip--neutro'}` }, `${activos.length} activo${activos.length === 1 ? '' : 's'}`)),
    resumen.length ? h('div', { class: 'chips-fila' }, resumen) : null,
    activos.length
      ? agrupar(activos).map(([cat, items]) => h('div', {},
        h('h3', { class: 'tarjeta__subtitulo' }, CATEGORIAS[cat] || cat),
        h('ul', { class: 'rasgos' }, items.map((x) => itemRasgo(x)))))
      : h('p', { class: 'tarjeta__texto' },
        'El detector no activó ninguno de sus rasgos de alerta para este correo. Aun así, el modelo usa todas sus variables (texto, URL, estructura HTML y sintaxis) para decidir; los rasgos listados son solo los que superan un umbral de alerta.'),
    h('div', { class: 'nota' },
      'Cómo leer esta lista: los rasgos son heurísticas del detector con umbrales fijos e indican qué señales están presentes en el correo. ',
      'No son atribuciones causales del modelo: no muestran cuánto pesó cada señal en la decisión, y un rasgo activo no prueba por sí solo que el correo sea spam.'),
    inactivos.length
      ? h('details', { class: 'detalles' },
        h('summary', {}, `Medidos sin activarse (${inactivos.length})`),
        h('p', { class: 'ayuda', style: 'margin-top:0;margin-bottom:8px' }, 'Valores que el detector midió pero que no superaron su umbral de alerta.'),
        agrupar(inactivos).map(([cat, items]) => h('div', {},
          h('h3', { class: 'tarjeta__subtitulo' }, CATEGORIAS[cat] || cat),
          h('ul', { class: 'rasgos' }, items.map((x) => itemRasgo(x, true))))))
      : null);
}

/* ---------- Evidencias: texto, enlaces, estructura ---------- */
function panelTexto(c) {
  return h('div', {},
    h('h3', { class: 'tarjeta__subtitulo tarjeta__subtitulo--sin-margen' }, 'Texto extraído del correo'),
    h('div', { class: 'espacio-s' }),
    bloqueTexto(c),
    bloqueHtml(c));
}

function panelEnlaces(c) {
  return h('div', {},
    h('div', { class: 'tarjeta__cabecera' },
      h('h3', { class: 'tarjeta__subtitulo tarjeta__subtitulo--sin-margen' }, 'Enlaces encontrados en el correo'),
      h('span', { class: 'chip chip--neutro' }, icono('enlace', { tam: 14 }), String(c.enlaces_total))),
    h('p', { class: 'ayuda', style: 'margin-top:0;margin-bottom:12px' }, NOTA_ENLACES),
    listaEnlaces(c, { conDominio: true }),
    c.enlaces.length
      ? h('p', { class: 'ayuda' }, 'El dominio se lee del propio texto del enlace y se muestra a modo informativo. SyntaxGuard no comprueba si el sitio es seguro: encontrar un enlace no lo vuelve sospechoso.')
      : null);
}

function panelEstructura(c) {
  return h('div', {},
    h('h3', { class: 'tarjeta__subtitulo tarjeta__subtitulo--sin-margen' }, 'Características estructurales del correo'),
    h('p', { class: 'ayuda', style: 'margin-top:4px;margin-bottom:12px' },
      'Datos que entregó la lectura del correo. Los rasgos de estructura HTML y de sintaxis que calculó el detector están en la pestaña «Rasgos».'),
    tablaDatos(caracteristicasEstructurales(c)),
    h('div', { class: 'nota' },
      'La API no devuelve el árbol HTML ni la lista completa de variables del modelo; por eso aquí solo aparece lo que sí se obtuvo del correo.'));
}

/* ---------- Evidencias: contenedor con pestañas ---------- */
function tarjetaEvidencias(a) {
  const r = a.resultado;
  const c = a.correo;
  const activos = r.rasgos_detectados.filter((x) => x.activo).length;
  const defs = [
    { id: 'rasgos', texto: `Rasgos (${activos})`, ic: 'escudo', panel: () => panelRasgos(r) },
    { id: 'texto', texto: 'Texto extraído', ic: 'archivo', panel: () => panelTexto(c) },
    { id: 'enlaces', texto: `Enlaces (${fmtNum(c.enlaces_total)})`, ic: 'enlace', panel: () => panelEnlaces(c) },
    { id: 'estructura', texto: 'Estructura', ic: 'analisis', panel: () => panelEstructura(c) },
  ];
  if (!defs.some((d) => d.id === pestanaEv)) pestanaEv = 'rasgos';

  const botones = [];
  const paneles = [];
  function elegir(id, { foco = false } = {}) {
    pestanaEv = id;
    defs.forEach((d, i) => {
      const activa = d.id === id;
      botones[i].setAttribute('aria-selected', String(activa));
      botones[i].tabIndex = activa ? 0 : -1;
      paneles[i].hidden = !activa;
      if (activa && foco) botones[i].focus();
    });
  }
  defs.forEach((d) => {
    botones.push(h('button', {
      type: 'button', class: 'pestana', role: 'tab', id: `tab-ev-${d.id}`, 'aria-controls': `panel-ev-${d.id}`,
      'aria-selected': 'false', tabindex: '-1', onclick: () => elegir(d.id),
    }, icono(d.ic, { tam: 16 }), d.texto));
    paneles.push(h('div', { role: 'tabpanel', id: `panel-ev-${d.id}`, 'aria-labelledby': `tab-ev-${d.id}`, hidden: true, tabindex: '0' }, d.panel()));
  });

  const tabs = h('div', {
    class: 'pestanas pestanas--ev', role: 'tablist', 'aria-label': 'Evidencias del correo',
    onkeydown: (ev) => {
      const i = defs.findIndex((d) => d.id === pestanaEv);
      let j = null;
      if (ev.key === 'ArrowRight') j = (i + 1) % defs.length;
      else if (ev.key === 'ArrowLeft') j = (i - 1 + defs.length) % defs.length;
      else if (ev.key === 'Home') j = 0;
      else if (ev.key === 'End') j = defs.length - 1;
      if (j === null) return;
      ev.preventDefault();
      elegir(defs[j].id, { foco: true });
    },
  }, botones);

  elegir(pestanaEv);
  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-evidencias' },
    h('h2', { class: 'tarjeta__titulo', id: 'tit-evidencias' }, 'Evidencias del correo'),
    h('p', { class: 'tarjeta__texto' }, 'Solo se muestra lo que entregaron la lectura del correo y el detector; nada se estima ni se completa aquí.'),
    h('div', { class: 'espacio-m' }),
    tabs, paneles);
}

/* ---------- Explicación del resultado ---------- */
function cargarMetricas(caja) {
  const pintar = () => {
    if (metricasEstado === 'cargando' || metricasEstado === null) {
      caja.replaceChildren(h('p', { class: 'ayuda', role: 'status' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), ' Cargando las métricas del modelo…'));
      return;
    }
    if (!metricasEstado.ok) {
      caja.replaceChildren(avisoConIcono(`No se pudieron cargar las métricas del modelo: ${metricasEstado.mensaje}`, 'aviso'));
      return;
    }
    const t = metricasEstado.datos?.test;
    const m = t?.matriz_confusion;
    const num = (v) => (typeof v === 'number' && Number.isFinite(v));
    if (!t || !m || ![t.accuracy, t.precision, t.recall, t.f1, m.tn, m.fp, m.fn, m.tp].every(num)) {
      caja.replaceChildren(avisoConIcono('El archivo de métricas no tiene el formato esperado.', 'aviso'));
      return;
    }
    const par = (p) => `${fmtPct(p)} (${fmtNum(p)})`;
    caja.replaceChildren(
      h('p', { class: 'ayuda', style: 'margin-top:0' },
        `Resultados medidos por el proyecto en su conjunto de prueba${num(t.n_muestras) ? ` (${fmtNum(t.n_muestras)} correos)` : ''}. Son cifras de prueba, no de validación, y no garantizan el mismo rendimiento con otros correos.`),
      tablaDatos([
        { etiqueta: 'Exactitud', valor: par(t.accuracy) },
        { etiqueta: 'Precisión', valor: par(t.precision) },
        { etiqueta: 'Recall', valor: par(t.recall) },
        { etiqueta: 'F1', valor: par(t.f1) },
        { etiqueta: 'Legítimos bien clasificados', valor: fmtNum(m.tn) },
        { etiqueta: 'Legítimos marcados como spam (falsos positivos)', valor: fmtNum(m.fp) },
        { etiqueta: 'Spam no detectado (falsos negativos)', valor: fmtNum(m.fn) },
        { etiqueta: 'Spam bien detectado', valor: fmtNum(m.tp) },
      ]));
  };
  pintar();
  if (metricasEstado === null || (metricasEstado !== 'cargando' && metricasEstado.ok === false)) {
    metricasEstado = 'cargando';
    pintar();
    api.metricas()
      .then((datos) => { metricasEstado = { ok: true, datos }; })
      .catch((e) => { metricasEstado = { ok: false, mensaje: e.message || 'error desconocido' }; })
      .finally(pintar);
  }
}

function punto(titulo, ...contenido) {
  return h('details', { class: 'acordeon__item' }, h('summary', {}, titulo), h('div', { class: 'acordeon__cuerpo' }, contenido));
}

function tarjetaExplicacion(r) {
  const p = Math.max(0, Math.min(1, r.probabilidad));
  const spam = r.es_spam;
  const caja = h('div', { class: 'metricas-mini' });
  const limitaciones = h('details', { class: 'acordeon__item', id: 'acordeon-limitaciones' },
    h('summary', {}, 'Limitaciones del clasificador'),
    h('div', { class: 'acordeon__cuerpo' },
      h('ul', { class: 'lista-limites' },
        h('li', {}, 'Solo distingue dos clases: spam y legítimo. No tiene una categoría independiente de phishing ni de fraude.'),
        h('li', {}, 'Se entrenó con correos en inglés del corpus público SpamAssassin; con otros idiomas o estilos su resultado puede no ser fiable.'),
        h('li', {}, 'Solo lee los primeros 3,000 caracteres del texto; los adjuntos se ignoran.'),
        h('li', {}, 'No verifica quién envió realmente el correo (por ejemplo, autenticación del remitente) ni visita los enlaces.'),
        h('li', {}, 'Los rasgos mostrados son heurísticas: explican qué señales hay, no por qué el modelo decidió lo que decidió.'),
        h('li', {}, 'Puede equivocarse en los dos sentidos: marcar como spam un correo legítimo o dejar pasar uno de spam. Es una herramienta académica de apoyo, no sustituye el criterio de una persona.')),
      h('h3', { class: 'tarjeta__subtitulo' }, 'Qué tan seguido se equivocó en las pruebas'),
      caja));
  limitaciones.addEventListener('toggle', () => { if (limitaciones.open) cargarMetricas(caja); });

  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-interp' },
    h('h2', { class: 'tarjeta__titulo', id: 'tit-interp' }, 'Cómo interpretar el resultado'),
    h('div', { class: 'espacio-s' }),
    h('div', { class: 'acordeon' },
      punto('¿Qué significa que un correo sea SPAM?',
        h('p', {}, 'Que el modelo estimó que el correo se parece más a los correos no deseados con los que aprendió que a los legítimos, según señales de texto, enlaces, estructura HTML y sintaxis.'),
        h('p', {}, 'No demuestra que el correo sea un fraude ni que un enlace sea malicioso: es una estimación estadística.')),
      punto('¿Qué significa que sea LEGÍTIMO?',
        h('p', {}, 'Que el parecido con el spam no alcanzó el umbral de decisión. No es una garantía de que el correo sea seguro: un mensaje engañoso bien redactado, o escrito en otro idioma, puede clasificarse como legítimo.')),
      punto('¿Qué representa el porcentaje P(spam)?',
        h('p', {}, 'Es la probabilidad que el modelo asigna a la clase spam; se obtiene promediando las estimaciones de los árboles del Random Forest. No es una medida de confianza ni de certeza: un 12 % significa baja probabilidad de spam, no “12 % de seguridad”.'),
        h('p', {}, `En este análisis, P(spam) = ${fmtPct(p)}.`)),
      punto('¿Por qué con menos de 50 % puede ser LEGÍTIMO?',
        h('p', {}, `La decisión es una regla simple: si P(spam) es ${fmtPct(UMBRAL)} o más, se clasifica como SPAM; si es menor, como LEGÍTIMO. Un correo con 40 % de probabilidad de spam sigue siendo LEGÍTIMO aunque tenga algunas señales de alerta.`),
        h('p', {}, spam
          ? `Aquí ocurre lo contrario: ${fmtPct(p)} alcanza el umbral, por eso el resultado es SPAM.`
          : `Aquí ${fmtPct(p)} queda por debajo del umbral, por eso el resultado es LEGÍTIMO.`)),
      limitaciones));
}

/* ---------- Columna lateral: correo analizado y avisos ---------- */
function tarjetaCorreoAnalizado(a, acciones) {
  const c = a.correo;
  const esArchivo = a.origen === 'archivo';
  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-analizado' },
    h('h2', { class: 'tarjeta__titulo', id: 'tit-analizado' }, 'Correo analizado'),
    h('div', { style: 'height:12px' }),
    h('div', { class: 'fila-archivo' },
      h('span', { class: 'fila-archivo__icono' }, icono(esArchivo ? 'archivo' : 'correo', { tam: 20 })),
      h('div', { class: 'fila-archivo__datos' },
        h('p', { class: 'fila-archivo__nombre' }, esArchivo ? a.nombre : 'Texto pegado'),
        h('p', { class: 'fila-archivo__meta' }, fmtBytes(a.tamano)))),
    datosCorreo(c),
    h('ul', { class: 'resumen' },
      h('li', {}, h('span', {}, icono('adjunto', { tam: 16 }), 'Adjuntos ignorados'), h('strong', {}, fmtNum(c.adjuntos_ignorados))),
      h('li', {}, h('span', {}, icono('enlace', { tam: 16 }), 'Enlaces encontrados'), h('strong', {}, fmtNum(c.enlaces_total)))),
    h('div', { class: 'acciones' },
      h('button', { type: 'button', class: 'btn btn--primario btn--bloque', id: 'btn-otro', onclick: acciones.reiniciar },
        icono('subir', { tam: 16 }), 'Analizar otro correo'),
      h('button', { type: 'button', class: 'btn btn--secundario btn--bloque', onclick: acciones.volverAPrevia },
        icono('reintentar', { tam: 16 }), 'Volver a la vista previa')));
}

function tarjetaAvisos(c) {
  const lista = [...c.advertencias.map((t) => ({ t, tipo: 'aviso' })), ...faltantes(c).map((t) => ({ t, tipo: 'info' }))];
  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-avisos' },
    h('div', { class: 'tarjeta__cabecera' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-avisos' }, 'Avisos sobre este análisis'),
      h('span', { class: `chip ${lista.length ? 'chip--aviso' : 'chip--ok'}` }, lista.length ? String(lista.length) : 'Sin avisos')),
    lista.length
      ? h('div', { class: 'lista-avisos', role: 'group', 'aria-label': 'Avisos sobre este análisis' }, lista.map((x) => avisoConIcono(x.t, x.tipo)))
      : h('p', { class: 'tarjeta__texto' }, 'La lectura del correo no generó advertencias ni información faltante.'));
}

/* ---------- Fase 5: historial y retroalimentación ---------- */
function tarjetaHistorial(a) {
  const guardado = a.historialId !== null && a.historialId !== undefined;
  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-hist' },
    h('div', { class: 'tarjeta__cabecera' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-hist' }, 'Historial y retroalimentación'),
      h('span', { class: `chip ${guardado ? 'chip--ok' : 'chip--aviso'}`, id: 'chip-guardado' }, guardado ? 'Guardado' : 'No guardado')),
    guardado
      ? h('p', { class: 'tarjeta__texto' }, `Este análisis quedó registrado en el historial (n.º ${a.historialId}). Solo se guardan metadatos, el resultado y los dominios de los enlaces; no el contenido del correo.`)
      : avisoConIcono(`No se pudo guardar en el historial: ${a.errorGuardado || 'error desconocido'}. El resultado mostrado es válido.`, 'aviso'),
    guardado
      ? h('div', { class: 'acciones' },
        // Botones (no enlaces): en esta pantalla no debe existir ningún <a> (regla de seguridad de la Fase 4).
        h('button', { type: 'button', class: 'btn btn--secundario btn--bloque', id: 'btn-ver-historial', onclick: () => { location.hash = `#/historial/${a.historialId}`; } }, icono('historial', { tam: 16 }), 'Abrir en el historial'),
        h('button', { type: 'button', class: 'btn btn--secundario btn--bloque', id: 'btn-dar-retro', onclick: () => { location.hash = `#/retroalimentacion?analisis=${a.historialId}`; } }, icono('retroalimentacion', { tam: 16 }), 'Enviar retroalimentación'))
      : null);
}

/* ---------- Vista completa ---------- */
export function vistaResultado(a, acciones) {
  const r = a.resultado;
  const c = a.correo;
  return [h('div', { class: 'resultado' },
    h('div', { class: 'resultado__banner' }, banner(r, acciones)),
    h('div', { class: 'resultado__prob' }, tarjetaProbabilidad(r)),
    h('div', { class: 'resultado__lado' }, tarjetaCorreoAnalizado(a, acciones), tarjetaHistorial(a), tarjetaAvisos(c)),
    h('div', { class: 'resultado__evid' }, tarjetaEvidencias(a)),
    h('div', { class: 'resultado__expl' }, tarjetaExplicacion(r)))];
}
