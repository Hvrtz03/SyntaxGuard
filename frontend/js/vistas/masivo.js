// Vista «Análisis masivo» (Fase 5): varios archivos o una carpeta completa, analizados con el modelo real.
//
// Flujo (todo contra la API real, sin simulaciones):
//   1. Se agregan archivos .eml/.txt (selector, carpeta o arrastrar y soltar). Se listan con nombre y tamaño y se pueden quitar.
//   2. «Iniciar análisis» crea un lote (POST /lotes) y envía los archivos UNO POR UNO (concurrencia 1, ver cola.js)
//      a POST /analisis/archivo, que extrae, analiza con el modelo real y guarda el resultado en el historial.
//   3. Un correo con error se marca y se guarda como error; el proceso continúa con el siguiente.
//   4. Al terminar: resumen, filtros, búsqueda, detalle de cada correo y exportación a CSV (GET /historial/exportar.csv?lote_id=).
//
// El estado vive en state.js: si cambias de sección, el proceso sigue y al volver ves el avance.
import { api } from '../api.js';
import { actualizar, obtener } from '../state.js';
import { h, icono, avisoError, fmtBytes, fmtNum, fmtPct, chipClasificacion, modal, toast, textoOGuion, confirmar } from '../ui.js';
import { ejecutarCola, CONCURRENCIA } from '../cola.js';
import { construirDetalle } from '../detalle.js';

export const meta = {
  titulo: 'Análisis masivo',
  subtitulo: 'Analiza muchos correos (.eml o .txt) o una carpeta completa. Un correo con error no detiene el proceso.',
  paso: 0,
};

/* ---------- Constantes (mismos límites que el backend) ---------- */
const EXTENSIONES = ['.eml', '.txt'];
const MAX_BYTES = 5 * 1024 * 1024;
const MAX_ARCHIVOS = 1000; // por lote
const MAX_EXPLORADOS = 5000; // archivos que se revisan al soltar una carpeta
const SOPORTA_CARPETA = typeof document !== 'undefined' && 'webkitdirectory' in document.createElement('input');

const M = () => obtener().masivo;
let raiz = null;
let nodos = null;
let ctrl = null; // AbortController de la cola actual: solo impide iniciar archivos nuevos
let cancelando = false;
let pintando = false;

function fijar(parcial) {
  actualizar({ masivo: { ...M(), ...parcial } });
  programarPintado();
}

function programarPintado() {
  if (pintando || !raiz || !raiz.isConnected) return;
  pintando = true;
  requestAnimationFrame(() => { pintando = false; pintar(); });
}

/* ---------- Agregar y quitar archivos ---------- */
const extension = (nombre) => { const i = nombre.lastIndexOf('.'); return i >= 0 ? nombre.slice(i).toLowerCase() : ''; };

function agregar(entradas) {
  if (M().fase === 'analizando') return;
  if (M().fase === 'finalizado') reiniciarLote(); // empezar de nuevo: se descartan los resultados anteriores de la pantalla
  const existentes = new Map(M().archivos.map((a) => [a.clave, a]));
  let ignorados = 0; let duplicados = 0; let excedidos = 0; let nuevos = 0;
  for (const { file, ruta } of entradas) {
    const ext = extension(file.name);
    if (!EXTENSIONES.includes(ext)) { ignorados++; continue; }
    const clave = `${ruta}|${file.size}|${file.lastModified}`;
    if (existentes.has(clave)) { duplicados++; continue; }
    if (existentes.size >= MAX_ARCHIVOS) { excedidos++; continue; }
    existentes.set(clave, {
      clave, archivo: file, nombre: file.name, ruta, tamano: file.size,
      tipo: ext === '.eml' ? 'message/rfc822' : 'text/plain', estado: 'pendiente', r: null, mensaje: null,
    });
    nuevos++;
  }
  const partes = [`Se agregaron ${fmtNum(nuevos)} archivo${nuevos === 1 ? '' : 's'}.`];
  if (ignorados) partes.push(`${fmtNum(ignorados)} se ignoraron por no ser .eml ni .txt.`);
  if (duplicados) partes.push(`${fmtNum(duplicados)} ya estaban en la lista.`);
  if (excedidos) partes.push(`${fmtNum(excedidos)} no se agregaron: el máximo es ${fmtNum(MAX_ARCHIVOS)} por análisis.`);
  fijar({ archivos: [...existentes.values()], error: null, aviso: { tipo: nuevos ? 'info' : 'aviso', texto: nuevos || ignorados || duplicados || excedidos ? partes.join(' ') : 'No se encontraron archivos.' } });
}

function quitar(clave) {
  if (M().fase !== 'seleccion') return;
  fijar({ archivos: M().archivos.filter((a) => a.clave !== clave), aviso: null });
}

function vaciar() {
  if (M().fase !== 'seleccion') return;
  fijar({ archivos: [], aviso: null, error: null });
}

function reiniciarLote() {
  cancelando = false;
  actualizar({ masivo: { fase: 'seleccion', archivos: [], loteId: null, guardados: null, error: null, aviso: null, filtro: 'todos', busqueda: '' } });
  if (nodos) { nodos.busqueda.value = ''; nodos.filtro.value = 'todos'; }
}

/* ---------- Carpetas soltadas (recorrido de directorios) ---------- */
async function archivosDeDrop(dt) {
  // Las entradas deben leerse de forma síncrona: después de un await la lista del DataTransfer queda vacía.
  const entradas = Array.from(dt.items || []).map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null)).filter(Boolean);
  if (!entradas.length) return Array.from(dt.files || []).map((f) => ({ file: f, ruta: f.name }));
  const salida = [];
  const leer = (fn) => new Promise((ok, mal) => fn(ok, mal));
  async function recorrer(e, base) {
    if (salida.length >= MAX_EXPLORADOS) return;
    if (e.isFile) {
      const file = await leer((ok, mal) => e.file(ok, mal));
      salida.push({ file, ruta: base + file.name });
    } else if (e.isDirectory) {
      const lector = e.createReader();
      let tanda;
      do {
        tanda = await leer((ok, mal) => lector.readEntries(ok, mal));
        for (const hijo of tanda) await recorrer(hijo, `${base}${e.name}/`);
      } while (tanda.length && salida.length < MAX_EXPLORADOS);
    }
  }
  for (const e of entradas) await recorrer(e, '');
  return salida;
}

let guardaInstalada = false;
function instalarGuarda() {
  // Evita que el navegador abra un archivo soltado fuera de la zona mientras se está en esta sección.
  if (guardaInstalada) return;
  guardaInstalada = true;
  const hayArchivos = (ev) => Array.from(ev.dataTransfer?.types || []).includes('Files');
  const enMasivo = () => location.hash.slice(1).split('?')[0].replace(/\/+$/, '') === '/masivo';
  ['dragover', 'drop'].forEach((tipo) => window.addEventListener(tipo, (ev) => { if (enMasivo() && hayArchivos(ev)) ev.preventDefault(); }));
}

/* ---------- Análisis ---------- */
async function iniciar() {
  if (M().fase !== 'seleccion') return;
  const pendientes = M().archivos.filter((a) => a.estado === 'pendiente');
  if (!pendientes.length) return;
  ctrl = new AbortController();
  const mi = ctrl;
  cancelando = false;
  fijar({ fase: 'analizando', error: null, aviso: null, guardados: null, loteId: null });

  let lote;
  try {
    lote = await api.crearLote(pendientes.length);
  } catch (e) {
    ctrl = null;
    fijar({ fase: 'seleccion', error: `No se pudo iniciar el análisis: ${e.message}` });
    return;
  }
  fijar({ loteId: lote.id });

  let fallosRed = 0;
  let fatal = null;
  await ejecutarCola(pendientes, {
    senal: mi.signal,
    concurrencia: CONCURRENCIA,
    trabajo: async (item) => {
      item.estado = 'procesando';
      programarPintado();
      try {
        const r = await api.analizarArchivo({ archivo: item.archivo, nombre: item.nombre, tipo: item.tipo, loteId: lote.id });
        if (!r || (r.estado !== 'ok' && r.estado !== 'error')) throw new Error('La API devolvió una respuesta inesperada.');
        fallosRed = 0;
        item.r = r;
        item.estado = r.estado;
        item.mensaje = r.error || null;
      } catch (e) {
        item.estado = 'error';
        item.mensaje = e.message || 'Error desconocido.';
        if (e.tipo === 'red') {
          fallosRed++;
          if (fallosRed >= 3) { fatal = 'Se perdió la conexión con la API. El análisis se detuvo; los correos ya analizados quedaron guardados.'; mi.abort(); }
        } else if (e.tipo === 'http' && e.estado === 503) {
          fatal = e.message; mi.abort();
        } else if (e.tipo === 'sesion') {
          // Fase 6B (contrato §9.5): al primer 401 no se siguen enviando archivos.
          fatal = 'Tu sesión expiró. El análisis se detuvo; los correos ya analizados quedaron guardados. Inicia sesión de nuevo para continuar.';
          mi.abort();
        }
      }
      programarPintado();
    },
  });

  M().archivos.forEach((a) => { if (a.estado === 'pendiente' || a.estado === 'procesando') a.estado = 'cancelado'; });
  let guardados = null;
  try { guardados = (await api.resumenLote(lote.id)).total_procesados; } catch { /* el resumen se calcula igual con lo recibido */ }
  ctrl = null;
  fijar({
    fase: 'finalizado', guardados, error: fatal,
    aviso: !fatal && cancelando ? { tipo: 'aviso', texto: 'Análisis cancelado. Los correos ya analizados quedaron guardados; el resto no se procesó.' } : null,
  });
  cancelando = false;
  if (raiz && raiz.isConnected && !fatal) toast('Análisis masivo terminado.', 'ok');
}

function cancelar() {
  if (!ctrl || cancelando) return;
  cancelando = true; // el correo en curso termina; no se inician más
  ctrl.abort();
  programarPintado();
}

/* ---------- Conteos ---------- */
function conteos() {
  const a = M().archivos;
  const n = (f) => a.filter(f).length;
  const spam = n((x) => x.estado === 'ok' && x.r.es_spam === true);
  const leg = n((x) => x.estado === 'ok' && x.r.es_spam === false);
  const errores = n((x) => x.estado === 'error');
  const clasificados = spam + leg;
  return {
    total: a.length, spam, leg, errores, clasificados, procesados: clasificados + errores,
    sinAnalizar: n((x) => x.estado === 'pendiente' || x.estado === 'procesando' || x.estado === 'cancelado'),
    pctSpam: clasificados ? spam / clasificados : null,
    pctLeg: clasificados ? leg / clasificados : null,
  };
}

/* ---------- Dibujo ---------- */
function zona() {
  const bloqueada = M().fase === 'analizando';
  const entradaArchivos = h('input', {
    type: 'file', multiple: true, id: 'entrada-masivo-archivos', class: 'oculto-visual', tabindex: '-1', 'aria-hidden': 'true',
    accept: '.eml,.txt,message/rfc822,text/plain',
    onchange: (ev) => { const fs = Array.from(ev.target.files || []); ev.target.value = ''; agregar(fs.map((f) => ({ file: f, ruta: f.name }))); },
  });
  const entradaCarpeta = h('input', {
    type: 'file', webkitdirectory: true, multiple: true, id: 'entrada-masivo-carpeta', class: 'oculto-visual', tabindex: '-1', 'aria-hidden': 'true',
    onchange: (ev) => { const fs = Array.from(ev.target.files || []); ev.target.value = ''; agregar(fs.map((f) => ({ file: f, ruta: f.webkitRelativePath || f.name }))); },
  });
  const z = h('div', {
    class: `zona${bloqueada ? ' zona--bloqueada' : ''}`, id: 'zona-masivo',
    ondragover: (ev) => { if (!Array.from(ev.dataTransfer?.types || []).includes('Files')) return; ev.preventDefault(); ev.stopPropagation(); ev.dataTransfer.dropEffect = bloqueada ? 'none' : 'copy'; if (!bloqueada) z.classList.add('zona--activa'); },
    ondragleave: () => z.classList.remove('zona--activa'),
    ondrop: async (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      z.classList.remove('zona--activa');
      if (bloqueada) return;
      try { agregar(await archivosDeDrop(ev.dataTransfer)); } catch { fijar({ error: 'No se pudo leer lo que soltaste. Usa los botones para elegir archivos o una carpeta.' }); }
    },
  },
  h('span', { class: 'zona__icono' }, icono('masivo', { tam: 24 })),
  h('p', { class: 'zona__titulo' }, 'Arrastra aquí archivos o una carpeta completa'),
  h('p', { class: 'zona__sub' }, 'o elígelos desde tu computadora'),
  h('div', { class: 'acciones acciones--fila acciones--centro' },
    h('button', { type: 'button', class: 'btn btn--primario', id: 'btn-elegir-archivos', disabled: bloqueada, onclick: () => entradaArchivos.click() }, icono('archivo', { tam: 16 }), 'Elegir archivos'),
    h('button', {
      type: 'button', class: 'btn btn--secundario', id: 'btn-elegir-carpeta', disabled: bloqueada || !SOPORTA_CARPETA, onclick: () => entradaCarpeta.click(),
      title: SOPORTA_CARPETA ? 'Selecciona una carpeta; se incluyen sus subcarpetas' : 'Tu navegador no permite elegir carpetas; usa «Elegir archivos»',
    }, icono('carpeta', { tam: 16 }), 'Elegir carpeta')),
  entradaArchivos, entradaCarpeta);
  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-sel-masivo' },
    h('h2', { class: 'tarjeta__titulo', id: 'tit-sel-masivo' }, 'Seleccionar correos'),
    h('p', { class: 'tarjeta__texto' }, 'Se aceptan archivos .eml y .txt de hasta 5 MB cada uno (máximo 1,000 por análisis). Los demás archivos de una carpeta se ignoran.'),
    h('div', { style: 'height:14px' }), z);
}

function tarjetaProgreso() {
  const m = M();
  if (m.fase === 'seleccion') return null;
  const c = conteos();
  const pct = c.total ? Math.round((c.procesados / c.total) * 100) : 0;
  const actual = m.archivos.find((a) => a.estado === 'procesando');
  const cifra = (etiqueta, valor, clase = '') => h('div', { class: 'cifra' }, h('dt', {}, etiqueta), h('dd', { class: clase }, valor));
  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-prog-masivo' },
    h('div', { class: 'tarjeta__cabecera' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-prog-masivo' }, m.fase === 'analizando' ? 'Análisis en curso' : 'Resumen del análisis'),
      m.fase === 'analizando'
        ? h('button', { type: 'button', class: 'btn btn--secundario btn--chico', id: 'btn-cancelar-masivo', disabled: cancelando, onclick: cancelar }, icono('cerrar', { tam: 14 }), cancelando ? 'Cancelando…' : 'Cancelar')
        : h('span', { class: 'chip chip--ok' }, icono('check', { tam: 14 }), 'Terminado')),
    h('div', {
      class: 'barra-avance', role: 'progressbar', 'aria-label': 'Progreso del análisis masivo',
      'aria-valuemin': '0', 'aria-valuemax': String(c.total), 'aria-valuenow': String(c.procesados),
    }, h('div', { class: 'barra-avance__relleno', style: `width:${pct}%` })),
    h('p', { class: 'ayuda', id: 'texto-progreso', role: 'status', 'aria-live': 'polite' },
      `${fmtNum(c.procesados)} de ${fmtNum(c.total)} procesados (${fmtNum(pct)} %)`,
      m.fase === 'analizando' && actual ? ` · analizando «${actual.nombre}»` : '',
      cancelando && m.fase === 'analizando' ? ' · se detendrá al terminar el correo actual' : ''),
    h('dl', { class: 'cifras cifras--resumen', id: 'resumen-masivo' },
      cifra('Correos procesados', fmtNum(c.procesados)),
      cifra('SPAM', fmtNum(c.spam), 'cifra--spam'),
      cifra('LEGÍTIMOS', fmtNum(c.leg), 'cifra--ok'),
      cifra('Errores', fmtNum(c.errores)),
      cifra('% SPAM', c.pctSpam === null ? '—' : fmtPct(c.pctSpam)),
      cifra('% LEGÍTIMOS', c.pctLeg === null ? '—' : fmtPct(c.pctLeg))),
    h('p', { class: 'ayuda' },
      'Los porcentajes se calculan sobre los correos clasificados (SPAM + LEGÍTIMOS); los errores se cuentan aparte. P(spam) no es una medida de confianza.',
      c.sinAnalizar && m.fase === 'finalizado' ? ` ${fmtNum(c.sinAnalizar)} archivo${c.sinAnalizar === 1 ? '' : 's'} no se procesaron.` : '',
      m.guardados != null ? ` Registros guardados en el historial para este lote: ${fmtNum(m.guardados)}.` : ''));
}

function visibles() {
  const { archivos, filtro, busqueda } = M();
  const q = busqueda.trim().toLowerCase();
  return archivos.filter((a) => {
    if (filtro === 'spam' && !(a.estado === 'ok' && a.r.es_spam)) return false;
    if (filtro === 'legitimo' && !(a.estado === 'ok' && !a.r.es_spam)) return false;
    if (filtro === 'error' && a.estado !== 'error') return false;
    if (filtro === 'sin_analizar' && !['pendiente', 'procesando', 'cancelado'].includes(a.estado)) return false;
    if (q && !`${a.ruta} ${a.r?.asunto || ''}`.toLowerCase().includes(q)) return false;
    return true;
  });
}

function verDetalle(a) {
  const cuerpo = [
    construirDetalle(a.r),
    h('div', { class: 'acciones acciones--fila' },
      h('a', { class: 'btn btn--secundario', href: `#/historial/${a.r.id}`, onclick: () => d.cerrar() }, icono('historial', { tam: 16 }), 'Abrir en el historial'),
      a.r.estado === 'ok'
        ? h('a', { class: 'btn btn--secundario', href: `#/retroalimentacion?analisis=${a.r.id}`, onclick: () => d.cerrar() }, icono('retroalimentacion', { tam: 16 }), 'Enviar retroalimentación')
        : null),
  ];
  const d = modal({ titulo: a.nombre, cuerpo, ancho: 'ancho' });
}

function celdaEstado(a) {
  if (a.estado === 'ok') return chipClasificacion(a.r);
  if (a.estado === 'error') return h('span', { class: 'chip chip--aviso', title: a.mensaje || '' }, 'Error');
  if (a.estado === 'procesando') return h('span', { class: 'chip chip--neutro' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), 'Analizando…');
  if (a.estado === 'cancelado') return h('span', { class: 'chip chip--neutro' }, 'No procesado');
  return h('span', { class: 'chip chip--neutro' }, 'Pendiente');
}

function tablaArchivos() {
  const m = M();
  if (!m.archivos.length) {
    return h('div', { class: 'vacio' }, icono('masivo', { tam: 28 }), h('p', {}, 'Aún no hay archivos. Elige archivos o una carpeta para empezar.'));
  }
  const lista = visibles();
  if (!lista.length) return h('div', { class: 'vacio' }, h('p', {}, 'Ningún archivo coincide con el filtro o la búsqueda.'));
  const filas = lista.map((a) => h('tr', { 'data-estado': a.estado },
    h('td', { class: 'celda-nombre' },
      h('span', { class: 'celda-nombre__texto', title: a.ruta }, a.nombre),
      a.estado === 'error' && a.mensaje ? h('span', { class: 'celda-nombre__error' }, a.mensaje) : null),
    h('td', { class: 'num' }, fmtBytes(a.tamano)),
    h('td', {}, celdaEstado(a)),
    h('td', { class: 'num' }, a.estado === 'ok' ? fmtPct(a.r.probabilidad) : '—'),
    h('td', { class: 'celda-asunto' }, textoOGuion(a.r && a.r.asunto)),
    h('td', { class: 'celda-acciones' },
      m.fase === 'seleccion'
        ? h('button', { type: 'button', class: 'btn btn--texto btn--chico', 'aria-label': `Quitar ${a.nombre}`, onclick: () => quitar(a.clave) }, icono('cerrar', { tam: 14 }), 'Quitar')
        : (a.r ? h('button', { type: 'button', class: 'btn btn--secundario btn--chico', 'aria-label': `Ver detalles de ${a.nombre}`, onclick: () => verDetalle(a) }, 'Detalles') : null))));
  return h('div', { class: 'tabla-contenedor' },
    h('table', { class: 'tabla', id: 'tabla-masivo' },
      h('caption', { class: 'solo-lectores' }, 'Archivos del análisis masivo y sus resultados'),
      h('thead', {}, h('tr', {},
        h('th', { scope: 'col' }, 'Archivo'), h('th', { scope: 'col', class: 'num' }, 'Tamaño'), h('th', { scope: 'col' }, 'Resultado'),
        h('th', { scope: 'col', class: 'num' }, 'P(spam)'), h('th', { scope: 'col' }, 'Asunto'), h('th', { scope: 'col' }, h('span', { class: 'solo-lectores' }, 'Acciones')))),
      h('tbody', {}, filas)));
}

function accionesLista() {
  const m = M();
  const c = conteos();
  const botones = [];
  if (m.fase === 'seleccion') {
    botones.push(
      h('button', { type: 'button', class: 'btn btn--primario', id: 'btn-iniciar-masivo', disabled: !m.archivos.length, onclick: iniciar }, icono('analisis', { tam: 16 }), `Iniciar análisis${m.archivos.length ? ` (${fmtNum(m.archivos.length)})` : ''}`),
      h('button', { type: 'button', class: 'btn btn--secundario', id: 'btn-vaciar-masivo', disabled: !m.archivos.length, onclick: vaciar }, icono('papelera', { tam: 16 }), 'Vaciar lista'));
  } else if (m.fase === 'finalizado') {
    if (m.guardados > 0) {
      botones.push(h('a', { class: 'btn btn--primario', id: 'btn-csv-lote', href: api.urlCsv({ lote_id: m.loteId }), download: '' }, icono('descargar', { tam: 16 }), 'Exportar resultados a CSV'));
    }
    botones.push(
      h('a', { class: 'btn btn--secundario', id: 'btn-ver-historial-lote', href: '#/historial' }, icono('historial', { tam: 16 }), 'Ver historial'),
      h('button', { type: 'button', class: 'btn btn--secundario', id: 'btn-nuevo-masivo', onclick: () => { reiniciarLote(); programarPintado(); } }, icono('subir', { tam: 16 }), 'Nuevo análisis masivo'));
  }
  return h('div', { class: 'acciones acciones--fila' }, botones, c.total ? h('span', { class: 'texto-tenue' }, `${fmtNum(c.total)} archivo${c.total === 1 ? '' : 's'} en la lista`) : null);
}

function pintar() {
  if (!nodos) return;
  const m = M();
  nodos.aviso.replaceChildren(...[
    m.error ? avisoError(m.error) : null,
    m.aviso ? h('div', { class: `aviso aviso--${m.aviso.tipo === 'info' ? 'info' : 'aviso'}`, role: 'status' }, icono(m.aviso.tipo === 'info' ? 'check' : 'alerta', { tam: 16 }), h('span', {}, m.aviso.texto)) : null,
  ].filter(Boolean));
  nodos.zona.replaceChildren(zona());
  const prog = tarjetaProgreso();
  nodos.progreso.replaceChildren(...(prog ? [prog] : []));
  nodos.acciones.replaceChildren(accionesLista());
  nodos.filtros.hidden = !m.archivos.length;
  nodos.tabla.replaceChildren(tablaArchivos());
  const total = m.archivos.length;
  nodos.cuenta.textContent = total ? `Mostrando ${fmtNum(visibles().length)} de ${fmtNum(total)}` : '';
}

/* ---------- Punto de entrada ---------- */
export function render() {
  instalarGuarda();
  const busqueda = h('input', {
    type: 'search', id: 'buscar-masivo', class: 'campo-in', placeholder: 'Buscar por nombre o asunto', 'aria-label': 'Buscar por nombre de archivo o asunto',
    oninput: (ev) => { actualizar({ masivo: { ...M(), busqueda: ev.target.value } }); nodos.tabla.replaceChildren(tablaArchivos()); nodos.cuenta.textContent = `Mostrando ${fmtNum(visibles().length)} de ${fmtNum(M().archivos.length)}`; },
  });
  busqueda.value = M().busqueda;
  const filtro = h('select', {
    id: 'filtro-masivo', class: 'campo-in', 'aria-label': 'Filtrar por clasificación',
    onchange: (ev) => { actualizar({ masivo: { ...M(), filtro: ev.target.value } }); nodos.tabla.replaceChildren(tablaArchivos()); nodos.cuenta.textContent = `Mostrando ${fmtNum(visibles().length)} de ${fmtNum(M().archivos.length)}`; },
  }, [['todos', 'Todos'], ['spam', 'SPAM'], ['legitimo', 'LEGÍTIMO'], ['error', 'Con error'], ['sin_analizar', 'Sin analizar']].map(([v, t]) => h('option', { value: v }, t)));
  filtro.value = M().filtro;
  const cuenta = h('span', { class: 'texto-tenue', id: 'cuenta-masivo' });
  const filtros = h('div', { class: 'filtros', hidden: true }, busqueda, filtro, cuenta);

  nodos = { aviso: h('div', { class: 'lista-avisos' }), zona: h('div'), progreso: h('div'), acciones: h('div'), filtros, tabla: h('div'), busqueda, filtro, cuenta };
  raiz = h('div', { class: 'masivo' },
    nodos.aviso, nodos.zona, nodos.progreso,
    h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-arch-masivo' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-arch-masivo' }, 'Archivos y resultados'),
      h('div', { style: 'height:12px' }), nodos.acciones, nodos.filtros, nodos.tabla));
  pintar();
  return raiz;
}
