// Detalle de un análisis GUARDADO (registro del historial). Lo usan Historial y Análisis masivo.
// Muestra solo lo que el servidor guardó: metadatos, resultado del modelo, rasgos, dominios y advertencias.
// El contenido del correo y las URL completas no se guardan (decisión D1), así que no aparecen aquí.
// Todo dato externo se inserta con h() (nodos de texto); no hay innerHTML con datos.
import { h, icono, fmtPct, fmtNum, fmtBytes, fmtFecha, fmtFechaLarga, chipClasificacion, textoOGuion } from './ui.js';

const UMBRAL = 0.5; // umbral del detector; la clasificación mostrada es siempre la guardada (es_spam)
const CATEGORIAS = { texto: 'Texto', url: 'URL', dom: 'Estructura HTML', sintactico: 'Sintaxis' };

const fila = (dt, dd) => [h('dt', {}, dt), h('dd', {}, dd)];
const noDisponible = (v) => (v && String(v).trim() ? String(v) : h('span', { class: 'no-disponible' }, 'No disponible'));

function itemRasgo(x, inactivo = false) {
  return h('li', { class: `rasgo${inactivo ? ' rasgo--inactivo' : ''}` },
    h('div', { class: 'rasgo__desc' }, x.descripcion),
    h('div', { class: 'rasgo__id' }, x.rasgo),
    h('div', { class: 'rasgo__valor' }, h('strong', {}, fmtNum(x.valor)), h('span', {}, 'valor medido')));
}

function gruposRasgos(items, inactivo = false) {
  const orden = Object.keys(CATEGORIAS);
  const m = new Map();
  items.forEach((x) => { if (!m.has(x.categoria)) m.set(x.categoria, []); m.get(x.categoria).push(x); });
  return [...m.entries()]
    .sort((a, b) => (orden.indexOf(a[0]) + 1 || 99) - (orden.indexOf(b[0]) + 1 || 99))
    .map(([cat, lista]) => h('div', {},
      h('h3', { class: 'tarjeta__subtitulo' }, CATEGORIAS[cat] || cat),
      h('ul', { class: 'rasgos' }, lista.map((x) => itemRasgo(x, inactivo)))));
}

function medidor(r) {
  const p = Math.max(0, Math.min(1, r.probabilidad));
  const spam = r.es_spam;
  return h('div', {},
    h('div', { class: 'prob__cabecera' },
      h('h3', { class: 'tarjeta__subtitulo tarjeta__subtitulo--sin-margen' }, 'Probabilidad de spam, P(spam)'),
      h('span', { class: 'prob__valor', style: `color:var(--c-${spam ? 'spam' : 'ok'})` }, fmtPct(p))),
    h('div', { class: 'medidor', role: 'img', 'aria-label': `P(spam): ${fmtPct(p)}. Umbral de decisión: ${fmtPct(UMBRAL)}.` },
      h('div', { class: `medidor__relleno medidor__relleno--${spam ? 'spam' : 'ok'}`, style: `width:${(p * 100).toFixed(1)}%` }),
      h('span', { class: 'medidor__umbral' })),
    h('div', { class: 'medidor__marcas', 'aria-hidden': 'true' },
      h('span', {}, '0 %'), h('span', { class: 'umbral-etiqueta' }, `Umbral ${fmtPct(UMBRAL)}`), h('span', {}, '100 %')),
    h('p', { class: 'ayuda' },
      `SPAM si P(spam) ≥ ${fmtPct(UMBRAL)}; LEGÍTIMO si es menor. Es la probabilidad que estima el modelo para la clase spam; no es una medida de confianza.`));
}

function bloqueRetro(r) {
  const lista = Array.isArray(r.retroalimentaciones) ? r.retroalimentaciones : null;
  if (!r.retro_total) return h('p', { class: 'texto-tenue' }, 'Este análisis aún no tiene retroalimentación.');
  const fila1 = (x) => h('li', { class: 'retro-item' },
    h('span', { class: `chip ${x.de_acuerdo ? 'chip--ok' : 'chip--error'}` }, x.de_acuerdo ? 'De acuerdo' : 'En desacuerdo'),
    h('time', { datetime: x.creado_en, title: fmtFechaLarga(x.creado_en) }, `Enviada el ${fmtFecha(x.creado_en)}`),
    x.comentario ? h('p', { class: 'retro-item__texto' }, x.comentario) : null);
  return lista
    ? h('ul', { class: 'retro-lista' }, lista.map(fila1))
    : h('ul', { class: 'retro-lista' }, fila1(r.retro_ultima));
}

/** Contenido completo del detalle de un registro del historial. */
export function construirDetalle(r) {
  const meta = h('dl', { class: 'datos datos--ancho' },
    fila('Archivo', noDisponible(r.nombre_archivo)),
    fila('Asunto', noDisponible(r.asunto)),
    fila('Remitente', noDisponible(r.remitente)),
    fila('Fecha del correo', noDisponible(r.fecha_correo)),
    fila('Analizado el', h('time', { datetime: r.creado_en, title: fmtFechaLarga(r.creado_en) }, fmtFecha(r.creado_en))),
    fila('Tipo de análisis', r.tipo === 'masivo' ? `Masivo (lote n.º ${r.lote_id ?? '—'})` : 'Individual'),
    fila('Tamaño', r.tamano_bytes != null ? fmtBytes(r.tamano_bytes) : '—'),
    fila('Identificador', `n.º ${r.id}`));

  if (r.estado === 'error') {
    return h('div', { class: 'detalle' },
      h('div', { class: 'detalle__cabecera' }, chipClasificacion(r), h('span', { class: 'texto-tenue' }, 'No se pudo clasificar este correo.')),
      h('div', { class: 'aviso aviso--error', role: 'alert' }, icono('alerta', { tam: 16 }), h('span', {}, r.error || 'Error desconocido.')),
      meta,
      h('p', { class: 'ayuda' }, 'Los errores se guardan como registros propios y no cuentan como SPAM ni como LEGÍTIMO en las estadísticas.'));
  }

  const activos = (r.rasgos_detectados || []).filter((x) => x.activo);
  const inactivos = (r.rasgos_detectados || []).filter((x) => !x.activo);
  return h('div', { class: 'detalle' },
    h('div', { class: 'detalle__cabecera' },
      chipClasificacion(r),
      h('span', { class: 'detalle__titulo' }, r.es_spam ? 'El modelo clasificó este correo como SPAM' : 'El modelo clasificó este correo como LEGÍTIMO')),
    medidor(r),
    meta,
    h('section', { class: 'detalle__bloque' },
      h('div', { class: 'tarjeta__cabecera' },
        h('h3', { class: 'tarjeta__subtitulo tarjeta__subtitulo--sin-margen' }, 'Rasgos detectados por el sistema'),
        h('span', { class: `chip ${activos.length ? 'chip--aviso' : 'chip--neutro'}` }, `${activos.length} activo${activos.length === 1 ? '' : 's'}`)),
      activos.length ? gruposRasgos(activos) : h('p', { class: 'tarjeta__texto' }, 'El detector no activó ninguno de sus rasgos de alerta para este correo.'),
      inactivos.length
        ? h('details', { class: 'detalles' }, h('summary', {}, `Medidos sin activarse (${inactivos.length})`), gruposRasgos(inactivos, true))
        : null,
      h('div', { class: 'nota' }, 'Los rasgos son heurísticas del detector con umbrales fijos: indican qué señales están presentes, no cuánto pesó cada una en la decisión del modelo.')),
    h('section', { class: 'detalle__bloque' },
      h('div', { class: 'tarjeta__cabecera' },
        h('h3', { class: 'tarjeta__subtitulo tarjeta__subtitulo--sin-margen' }, 'Dominios de los enlaces'),
        h('span', { class: 'chip chip--neutro' }, icono('enlace', { tam: 14 }), String(r.enlaces_total))),
      r.dominios && r.dominios.length
        ? h('ul', { class: 'enlaces' }, r.dominios.map((d) => h('li', {}, h('div', { class: 'enlaces__dato' }, h('code', {}, d)))))
        : h('p', { class: 'texto-tenue' }, 'No se guardaron dominios (el correo no tenía enlaces http(s) o www).'),
      h('p', { class: 'ayuda' }, 'Por privacidad solo se guardan los dominios, no las direcciones completas. Encontrar un enlace no lo vuelve sospechoso.')),
    r.advertencias && r.advertencias.length
      ? h('section', { class: 'detalle__bloque' },
        h('h3', { class: 'tarjeta__subtitulo' }, 'Advertencias de la lectura del correo'),
        h('div', { class: 'lista-avisos' }, r.advertencias.map((t) => h('div', { class: 'aviso aviso--aviso' }, icono('alerta', { tam: 16 }), h('span', {}, t)))))
      : null,
    h('section', { class: 'detalle__bloque' },
      h('h3', { class: 'tarjeta__subtitulo' }, 'Retroalimentación'),
      bloqueRetro(r)),
    h('div', { class: 'nota' }, 'Por privacidad, SyntaxGuard no guarda el texto ni el HTML del correo. Esta vista muestra solo los metadatos, el resultado del modelo, los rasgos y los dominios de los enlaces.'));
}

export { textoOGuion };
