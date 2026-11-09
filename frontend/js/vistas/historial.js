// Vista «Historial» (Fase 5). Lee los registros REALES guardados en SQLite por el backend.
//   #/historial        → lista paginada con búsqueda, filtros (clasificación, tipo, fechas), selección múltiple,
//                         eliminación y exportación a CSV con los mismos filtros.
//   #/historial/<id>   → detalle de un análisis guardado (resultado, rasgos, dominios y retroalimentaciones).
// No hay datos de ejemplo: si no hay registros se muestra un estado vacío.
import { api } from '../api.js';
import { actualizar, obtener } from '../state.js';
import { h, icono, avisoError, fmtNum, fmtPct, fmtFecha, fmtFechaLarga, chipClasificacion, toast, confirmar, textoOGuion } from '../ui.js';
import { construirDetalle } from '../detalle.js';

export const meta = {
  titulo: 'Historial de análisis',
  subtitulo: 'Consulta decisiones anteriores, filtra resultados y vuelve a sus evidencias.',
  paso: 4,
};

const POR_PAGINA = 25;
const FIL = () => obtener().historial;
const fijarFiltros = (parcial, reiniciarPagina = true) => {
  const f = FIL();
  actualizar({ historial: { filtros: { ...f.filtros, ...parcial }, pagina: reiniciarPagina ? 1 : f.pagina } });
};

export function render({ parametro } = {}) {
  return parametro ? vistaDetalle(parametro) : vistaLista();
}

/* ---------- Lista ---------- */
function vistaLista() {
  let datos = null;
  let error = null;
  let cargando = true;
  let turno = 0;
  const marcados = new Set();
  const nodos = { aviso: h('div'), tabla: h('div'), pie: h('div'), barra: h('div') };

  const campo = (etiqueta, control) => h('label', { class: 'campo-etq' }, etiqueta, control);
  const f0 = FIL().filtros;
  const q = h('input', { type: 'search', id: 'hist-buscar', class: 'campo-in', placeholder: 'Nombre de archivo o asunto', 'aria-label': 'Buscar por nombre o asunto' });
  q.value = f0.q;
  const clasif = h('select', { id: 'hist-clasif', class: 'campo-in' }, [['', 'Todos'], ['spam', 'SPAM'], ['legitimo', 'LEGÍTIMO'], ['error', 'Con error']].map(([v, t]) => h('option', { value: v }, t)));
  clasif.value = f0.clasificacion;
  const tipo = h('select', { id: 'hist-tipo', class: 'campo-in' }, [['', 'Todos'], ['individual', 'Individual'], ['masivo', 'Masivo']].map(([v, t]) => h('option', { value: v }, t)));
  tipo.value = f0.tipo;
  const desde = h('input', { type: 'date', id: 'hist-desde', class: 'campo-in' });
  desde.value = f0.desde;
  const hasta = h('input', { type: 'date', id: 'hist-hasta', class: 'campo-in' });
  hasta.value = f0.hasta;
  const csv = h('a', { class: 'btn btn--secundario', id: 'btn-exportar-csv', href: api.urlCsv(f0), download: '' }, icono('descargar', { tam: 16 }), 'Exportar CSV');
  const limpiar = h('button', { type: 'button', class: 'btn btn--texto', id: 'btn-limpiar-filtros', onclick: () => {
    q.value = ''; clasif.value = ''; tipo.value = ''; desde.value = ''; hasta.value = '';
    fijarFiltros({ q: '', clasificacion: '', tipo: '', desde: '', hasta: '' }); cargar();
  } }, 'Limpiar filtros');

  let reloj = null;
  q.addEventListener('input', () => { clearTimeout(reloj); reloj = setTimeout(() => { fijarFiltros({ q: q.value }); cargar(); }, 300); });
  [[clasif, 'clasificacion'], [tipo, 'tipo'], [desde, 'desde'], [hasta, 'hasta']].forEach(([el, k]) =>
    el.addEventListener('change', () => { fijarFiltros({ [k]: el.value }); cargar(); }));

  async function cargar() {
    const mi = ++turno;
    cargando = true; error = null;
    csv.href = api.urlCsv(FIL().filtros);
    pintar();
    try {
      const r = await api.historial({ ...FIL().filtros, pagina: FIL().pagina, por_pagina: POR_PAGINA });
      if (mi !== turno) return;
      if (r.items.length === 0 && r.total > 0 && FIL().pagina > 1) { actualizar({ historial: { ...FIL(), pagina: r.paginas } }); return cargar(); }
      datos = r;
    } catch (e) {
      if (mi !== turno) return;
      error = e.message || 'No se pudo cargar el historial.';
      datos = null;
    }
    cargando = false;
    pintar();
  }

  async function eliminar(ids, etiqueta) {
    const ok = await confirmar({
      titulo: 'Eliminar del historial',
      texto: `Se eliminará ${etiqueta} del historial junto con su retroalimentación. Esta acción no se puede deshacer.`,
      aceptar: 'Eliminar', peligro: true,
    });
    if (!ok) return;
    try {
      const r = ids.length === 1 ? await api.eliminarAnalisis(ids[0]) : await api.eliminarAnalisisVarios(ids);
      ids.forEach((i) => marcados.delete(i));
      toast(`Se eliminó ${r.eliminados} registro${r.eliminados === 1 ? '' : 's'}.`, 'ok');
    } catch (e) {
      toast(e.message || 'No se pudo eliminar.', 'error');
    }
    cargar();
  }

  function filaTabla(r) {
    const retro = r.retro_ultima;
    return h('tr', { 'data-id': String(r.id) },
      h('td', {}, h('input', {
        type: 'checkbox', class: 'marca-fila', 'aria-label': `Seleccionar el análisis ${r.id}`, checked: marcados.has(r.id),
        onchange: (ev) => { if (ev.target.checked) marcados.add(r.id); else marcados.delete(r.id); pintarBarra(); },
      })),
      h('td', { class: 'num' }, h('time', { datetime: r.creado_en, title: fmtFechaLarga(r.creado_en) }, fmtFecha(r.creado_en))),
      h('td', { class: 'celda-nombre' },
        h('span', { class: 'celda-nombre__texto', title: r.nombre_archivo || '' }, r.nombre_archivo || 'Correo pegado'),
        h('span', { class: 'texto-tenue', style: 'display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' }, textoOGuion(r.asunto))),
      h('td', { class: 'celda-asunto', title: r.remitente || '' }, textoOGuion(r.remitente)),
      h('td', {}, chipClasificacion(r)),
      h('td', { class: 'num' }, r.estado === 'ok' ? fmtPct(r.probabilidad) : '—'),
      h('td', {}, r.tipo === 'masivo' ? `Masivo · lote ${r.lote_id ?? '—'}` : 'Individual'),
      h('td', {}, retro
        ? h('span', { class: `chip ${retro.de_acuerdo ? 'chip--ok' : 'chip--error'}`, title: `Enviada el ${fmtFechaLarga(retro.creado_en)}` }, retro.de_acuerdo ? 'De acuerdo' : 'En desacuerdo')
        : h('span', { class: 'texto-tenue' }, 'Sin opinión')),
      h('td', { class: 'celda-acciones' },
        h('a', { class: 'btn btn--secundario btn--chico', href: `#/historial/${r.id}`, 'aria-label': `Ver detalles del análisis ${r.id}` }, 'Ver'),
        r.estado === 'ok' ? h('a', { class: 'btn btn--secundario btn--chico', href: `#/retroalimentacion?analisis=${r.id}`, 'aria-label': `Enviar retroalimentación del análisis ${r.id}` }, 'Opinar') : null,
        h('button', { type: 'button', class: 'btn btn--texto btn--chico', 'aria-label': `Eliminar el análisis ${r.id}`, onclick: () => eliminar([r.id], 'este registro') }, icono('papelera', { tam: 14 }), 'Eliminar')));
  }

  function pintarBarra() {
    const n = marcados.size;
    nodos.barra.replaceChildren(n ? h('div', { class: 'barra-seleccion' },
      h('span', {}, `${fmtNum(n)} seleccionado${n === 1 ? '' : 's'}`),
      h('button', { type: 'button', class: 'btn btn--peligro btn--chico', id: 'btn-eliminar-seleccion', onclick: () => eliminar([...marcados], `${n} registro${n === 1 ? '' : 's'}`) }, icono('papelera', { tam: 14 }), 'Eliminar seleccionados'),
      h('button', { type: 'button', class: 'btn btn--texto btn--chico', onclick: () => { marcados.clear(); pintar(); } }, 'Quitar selección')) : h('span'));
  }

  function pintar() {
    nodos.aviso.replaceChildren(...(error ? [h('div', { class: 'lista-avisos' }, avisoError(error), h('button', { type: 'button', class: 'btn btn--secundario btn--chico', onclick: cargar }, icono('reintentar', { tam: 14 }), 'Reintentar'))] : []));
    if (cargando && !datos) { nodos.tabla.replaceChildren(h('div', { class: 'estado', role: 'status' }, h('span', { class: 'spinner' }), 'Cargando historial…')); nodos.pie.replaceChildren(); pintarBarra(); return; }
    if (!datos) { nodos.tabla.replaceChildren(); nodos.pie.replaceChildren(); pintarBarra(); return; }
    const hayFiltros = Object.values(FIL().filtros).some((v) => v);
    if (!datos.items.length) {
      nodos.tabla.replaceChildren(h('div', { class: 'vacio' }, icono('historial', { tam: 28 }),
        h('p', {}, hayFiltros ? 'Ningún análisis coincide con los filtros.' : 'Todavía no hay análisis guardados.'),
        hayFiltros ? null : h('a', { class: 'btn btn--primario', href: '#/analisis' }, 'Analizar un correo')));
      nodos.pie.replaceChildren(); pintarBarra(); return;
    }
    const todos = datos.items.every((r) => marcados.has(r.id));
    nodos.tabla.replaceChildren(h('div', { class: 'tabla-contenedor', 'aria-busy': String(cargando) },
      h('table', { class: 'tabla', id: 'tabla-historial' },
        h('caption', { class: 'solo-lectores' }, 'Análisis guardados'),
        h('thead', {}, h('tr', {},
          h('th', { scope: 'col' }, h('input', { type: 'checkbox', id: 'hist-marcar-todos', 'aria-label': 'Seleccionar todos los de esta página', checked: todos,
            onchange: (ev) => { datos.items.forEach((r) => (ev.target.checked ? marcados.add(r.id) : marcados.delete(r.id))); pintar(); } })),
          h('th', { scope: 'col' }, 'Fecha'), h('th', { scope: 'col' }, 'Archivo y asunto'), h('th', { scope: 'col' }, 'Remitente'),
          h('th', { scope: 'col' }, 'Resultado'), h('th', { scope: 'col', class: 'num' }, 'P(spam)'), h('th', { scope: 'col' }, 'Tipo'),
          h('th', { scope: 'col' }, 'Retroalimentación'), h('th', { scope: 'col' }, h('span', { class: 'solo-lectores' }, 'Acciones')))),
        h('tbody', {}, datos.items.map(filaTabla)))));
    const p = FIL().pagina;
    nodos.pie.replaceChildren(h('div', { class: 'paginacion' },
      h('span', { id: 'hist-cuenta' }, `${fmtNum(datos.total)} análisis · página ${fmtNum(datos.pagina)} de ${fmtNum(datos.paginas)}`),
      h('div', { class: 'paginacion__botones' },
        h('button', { type: 'button', class: 'btn btn--secundario btn--chico', id: 'hist-anterior', disabled: p <= 1, onclick: () => { actualizar({ historial: { ...FIL(), pagina: p - 1 } }); cargar(); } }, 'Anterior'),
        h('button', { type: 'button', class: 'btn btn--secundario btn--chico', id: 'hist-siguiente', disabled: p >= datos.paginas, onclick: () => { actualizar({ historial: { ...FIL(), pagina: p + 1 } }); cargar(); } }, 'Siguiente'))));
    pintarBarra();
  }

  const raiz = h('div', { class: 'stack' },
    h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-filtros' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-filtros' }, 'Buscar y filtrar'),
      h('div', { class: 'filtros' },
        campo('Buscar', q), campo('Resultado', clasif), campo('Tipo', tipo), campo('Desde', desde), campo('Hasta', hasta), limpiar, csv),
      h('p', { class: 'ayuda' }, 'Las fechas usan la hora local de este equipo. El CSV incluye todos los registros que cumplen los filtros, no solo los de la página visible.')),
    nodos.aviso,
    h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-lista-hist' },
      h('h2', { class: 'tarjeta__titulo solo-lectores', id: 'tit-lista-hist' }, 'Análisis guardados'),
      nodos.barra, nodos.tabla, nodos.pie));
  cargar();
  return raiz;
}

/* ---------- Detalle ---------- */
async function vistaDetalle(parametro) {
  const volver = h('a', { class: 'btn btn--secundario', id: 'btn-volver-historial', href: '#/historial' }, icono('flecha', { tam: 16, clase: 'icono-atras' }), 'Volver al historial');
  const n = Number(parametro);
  if (!Number.isInteger(n) || n < 1) {
    return h('div', { class: 'stack' }, avisoError('El identificador del análisis no es válido.'), h('div', { class: 'acciones acciones--fila' }, volver));
  }
  let r;
  try {
    r = await api.analisis(n);
  } catch (e) {
    return h('div', { class: 'stack' }, avisoError(e.estado === 404 ? `El análisis n.º ${n} no existe o fue eliminado.` : (e.message || 'No se pudo cargar el análisis.')), h('div', { class: 'acciones acciones--fila' }, volver));
  }
  const eliminar = async () => {
    const ok = await confirmar({ titulo: 'Eliminar del historial', texto: 'Se eliminará este análisis junto con su retroalimentación. Esta acción no se puede deshacer.', aceptar: 'Eliminar', peligro: true });
    if (!ok) return;
    try { await api.eliminarAnalisis(r.id); toast('Análisis eliminado.', 'ok'); location.hash = '#/historial'; } catch (e) { toast(e.message || 'No se pudo eliminar.', 'error'); }
  };
  return h('div', { class: 'stack' },
    h('div', { class: 'acciones acciones--fila' }, volver,
      r.estado === 'ok' ? h('a', { class: 'btn btn--primario', id: 'btn-retro-detalle', href: `#/retroalimentacion?analisis=${r.id}` }, icono('retroalimentacion', { tam: 16 }), 'Enviar retroalimentación') : null,
      r.lote_id ? h('a', { class: 'btn btn--secundario', href: api.urlCsv({ lote_id: r.lote_id }), download: '' }, icono('descargar', { tam: 16 }), 'CSV del lote') : null,
      h('button', { type: 'button', class: 'btn btn--texto', id: 'btn-eliminar-detalle', onclick: eliminar }, icono('papelera', { tam: 16 }), 'Eliminar')),
    h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-detalle' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-detalle' }, `Análisis n.º ${r.id}`),
      h('div', { style: 'height:14px' }), construirDetalle(r)));
}
