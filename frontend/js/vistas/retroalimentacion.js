// Vista «Retroalimentación» (Fase 5): la persona indica si está de acuerdo con la clasificación de un análisis del historial.
// La retroalimentación se guarda (SQLite) ligada al análisis, con fecha y hora. NO reentrena ni modifica el modelo.
//   #/retroalimentacion?analisis=<id>  abre la vista con ese análisis ya seleccionado.
import { api } from '../api.js';
import { h, icono, avisoError, fmtNum, fmtPct, fmtFecha, fmtFechaLarga, chipClasificacion, toast, textoOGuion } from '../ui.js';

export const meta = {
  titulo: 'Retroalimentación',
  subtitulo: 'Indica si la clasificación de un análisis te parece correcta. Tu opinión se guarda, pero no cambia el modelo.',
  paso: 5,
};

const POR_PAGINA_LISTA = 8;
const POR_PAGINA_PREVIAS = 10;
let seleccionId = null; // se conserva al cambiar de sección

export function render({ consulta } = {}) {
  const deUrl = Number(consulta && consulta.get('analisis'));
  if (Number.isInteger(deUrl) && deUrl > 0) seleccionId = deUrl;

  let seleccion = null; let errorSel = null; let cargandoSel = false;
  let lista = null; let errorLista = null; let paginaLista = 1; let busqueda = '';
  let previas = null; let errorPrevias = null; let paginaPrevias = 1; let soloSeleccion = false;
  let voto = null; let enviando = false; let errorEnvio = null; let textoComentario = '';
  const nodos = { lista: h('div'), form: h('div'), previas: h('div') };

  /* ---- Carga de datos ---- */
  async function cargarLista() {
    try { lista = await api.historial({ q: busqueda, solo_ok: 'true', pagina: paginaLista, por_pagina: POR_PAGINA_LISTA }); errorLista = null; }
    catch (e) { errorLista = e.message || 'No se pudo cargar la lista.'; lista = null; }
    pintarLista();
  }
  async function cargarSeleccion() {
    if (seleccionId === null) { seleccion = null; errorSel = null; pintarForm(); return; }
    cargandoSel = true; errorSel = null; pintarForm();
    try {
      const r = await api.analisis(seleccionId);
      if (r.estado !== 'ok') throw Object.assign(new Error('Ese registro es un error de lectura y no tiene clasificación sobre la que opinar.'), { estado: 422 });
      seleccion = r;
    } catch (e) {
      seleccion = null;
      errorSel = e.estado === 404 ? `El análisis n.º ${seleccionId} no existe o fue eliminado.` : (e.message || 'No se pudo cargar el análisis.');
      seleccionId = null;
    }
    cargandoSel = false; pintarForm(); pintarLista();
  }
  async function cargarPrevias() {
    try {
      previas = await api.retroalimentaciones({ analisis_id: soloSeleccion && seleccionId ? seleccionId : '', pagina: paginaPrevias, por_pagina: POR_PAGINA_PREVIAS });
      errorPrevias = null;
    } catch (e) { errorPrevias = e.message || 'No se pudieron cargar las retroalimentaciones.'; previas = null; }
    pintarPrevias();
  }

  function elegir(id) { seleccionId = id; voto = null; errorEnvio = null; textoComentario = ''; cargarSeleccion(); if (soloSeleccion) { paginaPrevias = 1; cargarPrevias(); } }

  async function enviar() {
    if (!seleccion || voto === null || enviando) return;
    const comentario = textoComentario.trim();
    enviando = true; errorEnvio = null; pintarForm();
    try {
      const r = await api.guardarRetro({ analisisId: seleccion.id, deAcuerdo: voto, comentario });
      toast(`Retroalimentación guardada el ${fmtFecha(r.creado_en)}.`, 'ok');
      voto = null; enviando = false; textoComentario = '';
      await Promise.all([cargarSeleccion(), cargarLista(), (paginaPrevias = 1, cargarPrevias())]);
    } catch (e) {
      enviando = false; errorEnvio = e.message || 'No se pudo guardar la retroalimentación.'; pintarForm();
    }
  }

  /* ---- Dibujo ---- */
  function pintarLista() {
    const filas = [];
    if (errorLista) filas.push(h('div', { class: 'lista-avisos' }, avisoError(errorLista), h('button', { type: 'button', class: 'btn btn--secundario btn--chico', onclick: cargarLista }, icono('reintentar', { tam: 14 }), 'Reintentar')));
    else if (!lista) filas.push(h('div', { class: 'estado', role: 'status' }, h('span', { class: 'spinner' }), 'Cargando análisis…'));
    else if (!lista.items.length) {
      filas.push(h('div', { class: 'vacio', id: 'retro-vacio' }, icono('historial', { tam: 28 }),
        h('p', {}, busqueda ? 'Ningún análisis coincide con la búsqueda.' : 'Aún no hay análisis en el historial para opinar.'),
        busqueda ? null : h('a', { class: 'btn btn--primario', href: '#/analisis' }, 'Analizar un correo')));
    } else {
      filas.push(h('ul', { class: 'lista-sel', id: 'retro-lista' }, lista.items.map((r) => h('li', {},
        h('button', { type: 'button', class: 'sel-item', 'data-id': String(r.id), 'aria-pressed': String(r.id === seleccionId), onclick: () => elegir(r.id) },
          h('span', { class: 'sel-item__cuerpo' },
            h('span', { class: 'sel-item__nombre' }, r.nombre_archivo || r.asunto || 'Correo pegado'),
            h('span', { class: 'sel-item__meta' }, `${fmtFecha(r.creado_en)} · P(spam) ${fmtPct(r.probabilidad)}${r.retro_total ? ` · ${r.retro_total} opinión${r.retro_total === 1 ? '' : 'es'}` : ''}`)),
          chipClasificacion(r))))),
      h('div', { class: 'paginacion' },
        h('span', {}, `${fmtNum(lista.total)} análisis · página ${fmtNum(lista.pagina)} de ${fmtNum(lista.paginas)}`),
        h('div', { class: 'paginacion__botones' },
          h('button', { type: 'button', class: 'btn btn--secundario btn--chico', id: 'retro-lista-ant', disabled: paginaLista <= 1, onclick: () => { paginaLista--; cargarLista(); } }, 'Anterior'),
          h('button', { type: 'button', class: 'btn btn--secundario btn--chico', id: 'retro-lista-sig', disabled: paginaLista >= lista.paginas, onclick: () => { paginaLista++; cargarLista(); } }, 'Siguiente'))));
    }
    nodos.lista.replaceChildren(...filas);
  }

  function pintarForm() {
    if (cargandoSel) { nodos.form.replaceChildren(h('div', { class: 'estado', role: 'status' }, h('span', { class: 'spinner' }), 'Cargando análisis…')); return; }
    const avisos = [errorSel ? avisoError(errorSel) : null].filter(Boolean);
    if (!seleccion) {
      nodos.form.replaceChildren(...avisos, h('div', { class: 'vacio', id: 'retro-sin-seleccion' }, icono('retroalimentacion', { tam: 28 }), h('p', {}, 'Elige un análisis de la lista para dar tu opinión.')));
      return;
    }
    const ultima = seleccion.retro_ultima;
    const clasif = seleccion.es_spam ? 'SPAM' : 'LEGÍTIMO';
    nodos.form.replaceChildren(...avisos,
      h('div', { class: 'resumen-sel', id: 'retro-resumen' },
        h('p', {}, h('strong', {}, seleccion.nombre_archivo || 'Correo pegado'), ' ', chipClasificacion(seleccion)),
        h('p', { class: 'texto-tenue' }, `Asunto: ${textoOGuion(seleccion.asunto)}`),
        h('p', { class: 'texto-tenue' }, `P(spam) ${fmtPct(seleccion.probabilidad)} · analizado el ${fmtFecha(seleccion.creado_en)}`),
        ultima ? h('p', { class: 'texto-tenue' }, `Última retroalimentación: ${ultima.de_acuerdo ? 'de acuerdo' : 'en desacuerdo'}, enviada el `, h('time', { datetime: ultima.creado_en, title: fmtFechaLarga(ultima.creado_en) }, fmtFecha(ultima.creado_en)), '.') : null),
      h('fieldset', { class: 'opciones-voto' },
        h('legend', {}, `El modelo clasificó este correo como ${clasif}. ¿Qué opinas?`),
        h('label', { class: 'voto' }, h('input', { type: 'radio', name: 'voto', id: 'voto-si', value: 'si', checked: voto === true, onchange: () => { voto = true; pintarBoton(); } }), 'Estoy de acuerdo'),
        h('label', { class: 'voto' }, h('input', { type: 'radio', name: 'voto', id: 'voto-no', value: 'no', checked: voto === false, onchange: () => { voto = false; pintarBoton(); } }), 'No estoy de acuerdo')),
      h('label', { class: 'campo__etiqueta', for: 'retro-comentario' }, 'Comentario (opcional)'),
      areaComentario(),
      h('div', { class: 'campo__pie' },
        h('span', { class: 'campo__contador', id: 'retro-contador' }, `${textoComentario.length} / 1,000`),
        h('button', { type: 'button', class: 'btn btn--primario', id: 'btn-guardar-retro', disabled: voto === null || enviando, onclick: enviar }, enviando ? 'Guardando…' : 'Guardar retroalimentación')),
      errorEnvio ? avisoError(errorEnvio) : null,
      h('p', { class: 'ayuda' }, 'Tu opinión se guarda con su fecha y hora y queda ligada a este análisis. No reentrena ni modifica el modelo.'));
  }
  function areaComentario() {
    const ta = h('textarea', { id: 'retro-comentario', class: 'campo__area', rows: 4, maxlength: 1000, placeholder: 'Por ejemplo: es un boletín que sí me suscribí a recibir.',
      oninput: (ev) => { textoComentario = ev.target.value; document.getElementById('retro-contador').textContent = `${textoComentario.length} / 1,000`; } });
    ta.value = textoComentario;
    return ta;
  }
  function pintarBoton() { const b = document.getElementById('btn-guardar-retro'); if (b) b.disabled = voto === null || enviando; }

  function pintarPrevias() {
    if (errorPrevias) { nodos.previas.replaceChildren(h('div', { class: 'lista-avisos' }, avisoError(errorPrevias), h('button', { type: 'button', class: 'btn btn--secundario btn--chico', onclick: cargarPrevias }, icono('reintentar', { tam: 14 }), 'Reintentar'))); return; }
    if (!previas) { nodos.previas.replaceChildren(h('div', { class: 'estado', role: 'status' }, h('span', { class: 'spinner' }), 'Cargando…')); return; }
    if (!previas.items.length) {
      nodos.previas.replaceChildren(h('div', { class: 'vacio', id: 'previas-vacio' }, h('p', {}, soloSeleccion ? 'Este análisis aún no tiene retroalimentación.' : 'Todavía no has enviado retroalimentación.')));
      return;
    }
    nodos.previas.replaceChildren(
      h('ul', { class: 'retro-lista', id: 'lista-previas' }, previas.items.map((x, i) => h('li', { class: 'retro-item', 'data-id': String(x.id) },
        h('span', { class: `chip ${x.de_acuerdo ? 'chip--ok' : 'chip--error'}` }, x.de_acuerdo ? 'De acuerdo' : 'En desacuerdo'),
        h('time', { datetime: x.creado_en, title: fmtFechaLarga(x.creado_en) }, `Enviada el ${fmtFecha(x.creado_en)}`),
        soloSeleccion && paginaPrevias === 1 && i === 0 ? h('span', { class: 'chip chip--neutro' }, 'Más reciente') : null,
        h('span', { class: 'texto-tenue' }, `Modelo: ${x.es_spam ? 'SPAM' : 'LEGÍTIMO'} (P(spam) ${fmtPct(x.probabilidad)})`),
        h('a', { href: `#/historial/${x.analisis_id}`, class: 'btn btn--texto btn--chico' }, x.nombre_archivo || x.asunto || `Análisis n.º ${x.analisis_id}`),
        x.comentario ? h('p', { class: 'retro-item__texto' }, x.comentario) : null))),
      h('div', { class: 'paginacion' },
        h('span', {}, `${fmtNum(previas.total)} retroalimentación${previas.total === 1 ? '' : 'es'} · página ${fmtNum(previas.pagina)} de ${fmtNum(previas.paginas)}`),
        h('div', { class: 'paginacion__botones' },
          h('button', { type: 'button', class: 'btn btn--secundario btn--chico', id: 'previas-ant', disabled: paginaPrevias <= 1, onclick: () => { paginaPrevias--; cargarPrevias(); } }, 'Anterior'),
          h('button', { type: 'button', class: 'btn btn--secundario btn--chico', id: 'previas-sig', disabled: paginaPrevias >= previas.paginas, onclick: () => { paginaPrevias++; cargarPrevias(); } }, 'Siguiente'))));
  }

  /* ---- Estructura ---- */
  let reloj = null;
  const buscar = h('input', { type: 'search', id: 'retro-buscar', class: 'campo-in', placeholder: 'Buscar por nombre o asunto', 'aria-label': 'Buscar un análisis por nombre o asunto', style: 'width:100%',
    oninput: (ev) => { clearTimeout(reloj); reloj = setTimeout(() => { busqueda = ev.target.value; paginaLista = 1; cargarLista(); }, 300); } });
  const solo = h('input', { type: 'checkbox', id: 'retro-solo', onchange: (ev) => { soloSeleccion = ev.target.checked; paginaPrevias = 1; cargarPrevias(); } });

  const raiz = h('div', { class: 'stack' },
    h('div', { class: 'rejilla rejilla--2' },
      h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-retro-lista' },
        h('h2', { class: 'tarjeta__titulo', id: 'tit-retro-lista' }, '1. Elige un análisis del historial'),
        h('div', { style: 'height:12px' }), buscar, nodos.lista),
      h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-retro-form' },
        h('h2', { class: 'tarjeta__titulo', id: 'tit-retro-form' }, '2. Tu opinión'),
        h('div', { style: 'height:12px' }), nodos.form)),
    h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-previas' },
      h('div', { class: 'panel-tit' },
        h('h2', { class: 'tarjeta__titulo', id: 'tit-previas' }, 'Retroalimentaciones anteriores'),
        h('label', { class: 'sello', for: 'retro-solo' }, solo, 'Solo del análisis seleccionado')),
      h('div', { style: 'height:12px' }), nodos.previas));

  pintarLista(); pintarForm(); pintarPrevias();
  cargarLista(); cargarSeleccion(); cargarPrevias();
  return raiz;
}
