// Vista "Análisis": cargar → extraer → vista previa → analizar → resultado.
//
// Flujo (todo contra la API real, sin simulaciones):
//   1. El usuario elige/arrastra un .eml o pega texto  → POST /correo/extraer (cuerpo crudo)
//   2. Se muestra la vista previa segura                → solo texto (textContent), nunca HTML renderizado
//   3. Botón «Analizar correo»                          → POST /predecir con { texto, html } extraídos
//   4. Se muestra lo que devuelve el modelo             → es_spam, probabilidad (P(spam)) y rasgos_detectados
//
// Seguridad: todo lo que viene del correo se inserta con h() (nodos de texto). No hay innerHTML con datos
// externos, el HTML del correo solo se muestra como código dentro de <pre>, y los enlaces son texto no clicable.
import { api, ErrorApi } from '../api.js';
import { actualizar, obtener } from '../state.js';
import { h, icono, avisoError, actualizarPasos, fmtNum, fmtPct, fmtBytes } from '../ui.js';
// Fase 4: las piezas de evidencias y la pantalla de resultados viven en módulos propios (sin duplicar código).
import { datosCorreo, listaEnlaces, bloqueTexto, bloqueHtml, NOTA_ENLACES } from '../evidencias.js';
import { vistaResultado as dibujarResultado } from './resultado.js';

export const meta = {
  titulo: 'Analizar correo',
  subtitulo: 'Carga un mensaje para detectar patrones sospechosos y comprender el motivo de la clasificación.',
  paso: 1,
};

/* ---------- Constantes ---------- */
const MAX_BYTES = 5 * 1024 * 1024; // igual que backend/app/correo.py (MAX_BYTES)
const EXTENSIONES = ['.eml', '.txt']; // igual que el backend
const MENSAJE_PRUEBA = 'WINNER!! Claim your FREE prize now: http://bit.ly/claim-now';
const PASO = { inicial: 1, extrayendo: 1, listo: 2, analizando: 2, resultado: 3 };
const VISTA = { inicial: 'carga', extrayendo: 'extrayendo', listo: 'previa', analizando: 'previa', resultado: 'resultado' };

/* ---------- Estado local de la vista (el del flujo vive en state.js) ---------- */
let raiz = null; // contenedor de la vista actual
let turno = 0; // identifica la petición vigente: las respuestas viejas se descartan
let pestana = 'archivo'; // 'archivo' | 'pegar'
let textoPegado = ''; // se conserva al cambiar de pestaña o de sección
let ultimaVista = null;
let panelDiagnostico = null; // se crea una vez por visita para no repetir las comprobaciones

const A = () => obtener().analisis;

function fijar(parcial, opciones) {
  actualizar({ analisis: { ...obtener().analisis, ...parcial } });
  pintar(opciones);
}

function pintar({ foco } = {}) {
  if (!raiz) return;
  const a = A();
  const vista = VISTA[a.fase];
  const nodos = {
    carga: vistaCarga, extrayendo: vistaExtrayendo, previa: vistaPrevia, resultado: vistaResultado,
  }[vista](a);
  if (vista !== ultimaVista) nodos.forEach((n) => n.classList.add('entra'));
  ultimaVista = vista;
  raiz.replaceChildren(...nodos);
  if (raiz.isConnected) {
    actualizarPasos(PASO[a.fase]);
    if (foco) raiz.querySelector(foco)?.focus();
  }
}

/* ---------- Acciones ---------- */
function reiniciar() {
  turno++; // descarta cualquier petición en curso
  textoPegado = '';
  fijar({ fase: 'inicial', origen: null, nombre: null, tamano: 0, correo: null, resultado: null, error: null, historialId: null, errorGuardado: null },
    { foco: pestana === 'archivo' ? '#btn-elegir' : '#texto-pegado' });
}

function correoValido(c) {
  return c && typeof c.texto === 'string' && Array.isArray(c.enlaces) && Array.isArray(c.advertencias);
}

async function extraer({ datos, nombre, tipo, origen, tamano }) {
  const mi = ++turno;
  fijar({ fase: 'extrayendo', origen, nombre, tamano, correo: null, resultado: null, error: null });
  try {
    const correo = await api.extraerCorreo({ datos, nombre, tipo });
    if (mi !== turno) return;
    if (!correoValido(correo)) throw new ErrorApi('La API devolvió una respuesta inesperada al leer el correo.', { tipo: 'http' });
    fijar({ fase: 'listo', correo }, { foco: '#btn-analizar' });
  } catch (e) {
    if (mi !== turno) return;
    fijar({ fase: 'inicial', origen: null, nombre: null, tamano: 0, correo: null, error: e.message || 'No se pudo leer el correo.' });
  }
}

function procesarArchivo(archivo) {
  const nombre = archivo.name || 'archivo';
  const punto = nombre.lastIndexOf('.');
  const ext = punto >= 0 ? nombre.slice(punto).toLowerCase() : '';
  let error = null;
  if (!EXTENSIONES.includes(ext)) error = `El formato «${ext || 'sin extensión'}» no es compatible. Usa un archivo .eml o .txt.`;
  else if (archivo.size === 0) error = `El archivo «${nombre}» está vacío.`;
  else if (archivo.size > MAX_BYTES) error = `El archivo «${nombre}» pesa ${fmtBytes(archivo.size)}; el máximo permitido es 5 MB.`;
  if (error) { fijar({ error }); return; }
  extraer({ datos: archivo, nombre, tipo: ext === '.eml' ? 'message/rfc822' : 'text/plain', origen: 'archivo', tamano: archivo.size });
}

function procesarTexto(texto) {
  if (!texto.trim()) { fijar({ error: 'Pega el contenido del correo antes de continuar.' }, { foco: '#texto-pegado' }); return; }
  const bytes = new TextEncoder().encode(texto);
  if (bytes.length > MAX_BYTES) {
    fijar({ error: `El texto pegado pesa ${fmtBytes(bytes.length)}; el máximo permitido es 5 MB.` }, { foco: '#texto-pegado' });
    return;
  }
  extraer({ datos: bytes, nombre: null, tipo: 'text/plain; charset=utf-8', origen: 'texto', tamano: bytes.length });
}

function respuestaValida(r) {
  return r && typeof r.es_spam === 'boolean' && typeof r.probabilidad === 'number' && Number.isFinite(r.probabilidad)
    && Array.isArray(r.rasgos_detectados)
    && r.rasgos_detectados.every((x) => x && typeof x.descripcion === 'string' && typeof x.activo === 'boolean');
}

async function analizar() {
  const a = A();
  if (a.fase !== 'listo' || !a.correo) return; // evita envíos duplicados por clics repetidos
  const mi = ++turno;
  fijar({ fase: 'analizando', error: null });
  try {
    const r = await api.predecir({ texto: a.correo.texto, html: a.correo.html });
    if (mi !== turno) return;
    if (!respuestaValida(r)) throw new ErrorApi('La API respondió con un formato inesperado. Inténtalo de nuevo.', { tipo: 'http' });
    // Fase 5: se guarda en el historial el resultado que YA entregó el modelo (no se vuelve a analizar).
    // Si el guardado falla, el resultado se muestra igual y se avisa.
    let historialId = null;
    let errorGuardado = null;
    try {
      const c = a.correo;
      const reg = await api.registrarAnalisis({
        resultado: { es_spam: r.es_spam, probabilidad: r.probabilidad, rasgos_detectados: r.rasgos_detectados },
        nombre_archivo: a.origen === 'archivo' ? a.nombre : null,
        asunto: c.asunto, remitente: c.remitente, fecha: c.fecha, tamano_bytes: a.tamano,
        enlaces: c.enlaces.map((e) => e.url), enlaces_total: c.enlaces_total,
        adjuntos_ignorados: c.adjuntos_ignorados, advertencias: c.advertencias,
      });
      historialId = reg && Number.isInteger(reg.id) ? reg.id : null;
      if (historialId === null) errorGuardado = 'la API devolvió una respuesta inesperada';
    } catch (e) {
      errorGuardado = e.message || 'error desconocido';
    }
    if (mi !== turno) return;
    fijar({ fase: 'resultado', resultado: r, historialId, errorGuardado }, { foco: '.banner' });
  } catch (e) {
    if (mi !== turno) return;
    fijar({ fase: 'listo', error: `${e.message || 'No se pudo analizar el correo.'} Puedes intentarlo de nuevo.` });
  }
}

function volverAPrevia() {
  fijar({ fase: 'listo', resultado: null, error: null, historialId: null, errorGuardado: null }, { foco: '#btn-analizar' });
}

/* ---------- Arrastrar y soltar (un único registro para toda la sesión) ---------- */
let arrastreInstalado = false;
function instalarArrastre() {
  if (arrastreInstalado) return;
  arrastreInstalado = true;
  const hayArchivos = (ev) => Array.from(ev.dataTransfer?.types || []).includes('Files');
  const enAnalisis = () => {
    const ruta = location.hash.slice(1).split('?')[0].replace(/\/+$/, '');
    return ruta === '' || ruta === '/analisis';
  };
  const puedeCargar = () => enAnalisis() && ['inicial', 'listo'].includes(A().fase);
  const marcar = (on) => raiz?.querySelectorAll('.zona').forEach((z) => z.classList.toggle('zona--activa', on));

  window.addEventListener('dragover', (ev) => {
    if (!hayArchivos(ev)) return;
    ev.preventDefault(); // evita que el navegador abra el archivo soltado
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = puedeCargar() ? 'copy' : 'none';
    marcar(puedeCargar());
  });
  window.addEventListener('dragleave', (ev) => { if (!ev.relatedTarget) marcar(false); });
  window.addEventListener('drop', (ev) => {
    if (!hayArchivos(ev)) return;
    ev.preventDefault();
    marcar(false);
    if (!puedeCargar()) return;
    const archivos = Array.from(ev.dataTransfer.files || []);
    if (archivos.length === 0) return;
    if (archivos.length > 1) { fijar({ error: 'Suelta un solo archivo a la vez.' }); return; }
    procesarArchivo(archivos[0]);
  });
}

/* ---------- Vista: carga ---------- */
function vistaCarga(a) {
  const entrada = h('input', {
    type: 'file', id: 'entrada-archivo', class: 'oculto-visual', tabindex: '-1', 'aria-hidden': 'true',
    accept: '.eml,.txt,message/rfc822,text/plain',
    onchange: (ev) => {
      const archivo = ev.target.files && ev.target.files[0];
      ev.target.value = ''; // permite volver a elegir el mismo archivo
      if (archivo) procesarArchivo(archivo);
    },
  });

  const pestanaBtn = (id, texto, ic) => h('button', {
    type: 'button', class: 'pestana', role: 'tab', id: `tab-${id}`, 'aria-controls': `panel-${id}`,
    'aria-selected': String(pestana === id), tabindex: pestana === id ? null : '-1',
    onclick: () => { pestana = id; fijar({ error: null }); },
  }, icono(ic, { tam: 16 }), texto);

  const tabs = h('div', {
    class: 'pestanas', role: 'tablist', 'aria-label': 'Forma de cargar el correo',
    onkeydown: (ev) => {
      if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
      ev.preventDefault();
      pestana = pestana === 'archivo' ? 'pegar' : 'archivo';
      fijar({ error: null }, { foco: `#tab-${pestana}` });
    },
  }, pestanaBtn('archivo', 'Subir archivo', 'subir'), pestanaBtn('pegar', 'Pegar contenido', 'archivo'));

  let panel;
  if (pestana === 'archivo') {
    panel = h('div', { role: 'tabpanel', id: 'panel-archivo', 'aria-labelledby': 'tab-archivo' },
      h('div', {
        class: 'zona',
        onclick: (ev) => { if (!ev.target.closest('button')) entrada.click(); },
      },
        h('span', { class: 'zona__icono' }, icono('subir', { tam: 24 })),
        h('p', { class: 'zona__titulo' }, 'Arrastra y suelta tu correo aquí'),
        h('p', { class: 'zona__sub' }, 'o selecciónalo desde tu computadora'),
        h('button', { type: 'button', class: 'btn btn--primario', id: 'btn-elegir', onclick: () => entrada.click() },
          icono('archivo', { tam: 16 }), 'Elegir archivo'),
        entrada),
      h('p', { class: 'ayuda' },
        h('strong', {}, 'Formatos aceptados: '), '.eml (también .txt) · ',
        h('strong', {}, 'Tamaño máximo: '), '5 MB.'));
  } else {
    const contador = h('span', { class: 'campo__contador', id: 'contador-pegado', 'aria-live': 'off' });
    const actualizarContador = () => { contador.textContent = `${fmtNum(textoPegado.length)} caracteres`; };
    const area = h('textarea', {
      id: 'texto-pegado', class: 'campo__area', rows: '12', spellcheck: 'false', 'aria-describedby': 'ayuda-pegar',
      placeholder: 'Pega aquí el correo completo (con cabeceras From, To, Subject…) o solo el cuerpo del mensaje.',
      oninput: (ev) => { textoPegado = ev.target.value; actualizarContador(); },
    });
    area.value = textoPegado;
    actualizarContador();
    panel = h('div', { role: 'tabpanel', id: 'panel-pegar', 'aria-labelledby': 'tab-pegar' },
      h('label', { class: 'campo__etiqueta', for: 'texto-pegado' }, 'Contenido del correo'),
      area,
      h('p', { class: 'ayuda', id: 'ayuda-pegar' },
        'Puedes pegar el correo completo (con cabeceras) o solo el cuerpo. Máximo 5 MB. Para conservar el HTML original, mejor sube el archivo .eml.'),
      h('div', { class: 'campo__pie' }, contador,
        h('button', { type: 'button', class: 'btn btn--primario', id: 'btn-extraer-texto', onclick: () => procesarTexto(area.value) },
          'Extraer y previsualizar')));
  }

  const izquierda = h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-carga' },
    h('h2', { class: 'tarjeta__titulo', id: 'tit-carga' }, 'Carga un correo electrónico'),
    h('p', { class: 'tarjeta__texto' }, 'Sube un archivo .eml o pega su contenido. Antes de analizar verás una vista previa.'),
    h('div', { style: 'height:16px' }),
    tabs, panel,
    a.error ? avisoError(a.error) : null);

  const info = (ic, titulo, texto) => h('li', {}, icono(ic, { tam: 18 }), h('div', {}, h('strong', {}, titulo), h('span', {}, texto)));
  const derecha = h('aside', { class: 'tarjeta', 'aria-labelledby': 'tit-info' },
    h('h2', { class: 'tarjeta__titulo', id: 'tit-info' }, 'Antes de empezar'),
    h('ul', { class: 'lista-info' },
      info('archivo', 'Formatos y tamaño', 'Archivos .eml o .txt de hasta 5 MB, o texto pegado.'),
      info('escudo', 'Vista previa segura', 'El HTML del correo nunca se ejecuta ni se dibuja; solo se muestra como texto.'),
      info('adjunto', 'Adjuntos', 'Se ignoran: no se abren ni se analizan.'),
      info('correo', 'Privacidad', 'El correo se procesa en el servidor local. Su contenido no se guarda: el historial conserva solo metadatos, el resultado y los dominios de los enlaces.'),
      info('acerca', 'Alcance del modelo', 'Se entrenó con correos en inglés y analiza los primeros 3,000 caracteres del texto.')));

  return [h('div', { class: 'rejilla rejilla--2' }, izquierda, derecha), panelDiagnostico];
}

/* ---------- Vista: extrayendo ---------- */
function vistaExtrayendo(a) {
  return [h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-extr' },
    h('div', { class: 'centrado', role: 'status', 'aria-live': 'polite' },
      h('span', { class: 'spinner', 'aria-hidden': 'true' }),
      h('div', {},
        h('h2', { class: 'tarjeta__titulo', id: 'tit-extr' }, 'Leyendo el correo…'),
        h('p', { class: 'tarjeta__texto' },
          a.origen === 'archivo' ? `${a.nombre} · ${fmtBytes(a.tamano)}` : `Texto pegado · ${fmtBytes(a.tamano)}`)),
      h('button', { type: 'button', class: 'btn btn--secundario btn--chico', onclick: reiniciar }, 'Cancelar')))];
}

/* ---------- Vista: vista previa ---------- */
function tarjetaCorreo(a, bloqueado) {
  const c = a.correo;
  const esArchivo = a.origen === 'archivo';
  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-correo' },
    h('div', { class: 'tarjeta__cabecera' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-correo' }, 'Correo seleccionado'),
      h('span', { class: 'chip chip--ok' }, icono('check', { tam: 14 }), 'Leído correctamente')),
    h('div', { class: 'fila-archivo' },
      h('span', { class: 'fila-archivo__icono' }, icono(esArchivo ? 'archivo' : 'correo', { tam: 20 })),
      h('div', { class: 'fila-archivo__datos' },
        h('p', { class: 'fila-archivo__nombre', title: esArchivo ? a.nombre : 'Texto pegado' }, esArchivo ? a.nombre : 'Texto pegado'),
        h('p', { class: 'fila-archivo__meta' }, `${fmtBytes(a.tamano)} · ${esArchivo ? 'Archivo' : 'Pegado en el área de texto'}`)),
      h('button', {
        type: 'button', class: 'btn btn--secundario btn--chico', id: 'btn-quitar', disabled: bloqueado, onclick: reiniciar,
        'aria-label': esArchivo ? `Quitar el archivo ${a.nombre}` : 'Quitar el texto pegado',
      }, icono('cerrar', { tam: 14 }), 'Quitar')),
    datosCorreo(c));
}

function tarjetaContenido(c) {
  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-contenido' },
    h('div', { class: 'tarjeta__cabecera' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-contenido' }, 'Contenido del mensaje'),
      h('span', { class: 'chip chip--neutro' }, icono('escudo', { tam: 14 }), 'Vista segura · solo texto')),
    bloqueTexto(c),
    bloqueHtml(c));
}

function tarjetaEnlaces(c) {
  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-enlaces' },
    h('div', { class: 'tarjeta__cabecera' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-enlaces' }, 'Enlaces encontrados'),
      h('span', { class: 'chip chip--neutro' }, icono('enlace', { tam: 14 }), String(c.enlaces_total))),
    h('p', { class: 'ayuda', style: 'margin-top:0;margin-bottom:12px' }, NOTA_ENLACES),
    listaEnlaces(c));
}

function tarjetaAccion(a) {
  const c = a.correo;
  const analizando = a.fase === 'analizando';
  const fila = (ic, texto, valor) => h('li', {}, h('span', {}, icono(ic, { tam: 16 }), texto), h('strong', {}, valor));
  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-accion' },
    h('h2', { class: 'tarjeta__titulo', id: 'tit-accion' }, 'Listo para analizar'),
    h('p', { class: 'tarjeta__texto' }, 'Se enviará el texto y el HTML extraídos al modelo de SyntaxGuard.'),
    h('ul', { class: 'resumen' },
      fila('adjunto', 'Adjuntos ignorados', fmtNum(c.adjuntos_ignorados)),
      fila('enlace', 'Enlaces encontrados', fmtNum(c.enlaces_total)),
      fila('archivo', 'Contiene HTML', c.html ? 'Sí' : 'No'),
      fila('correo', 'Caracteres de texto', fmtNum(c.texto.length))),
    c.advertencias.length
      ? h('div', { class: 'lista-avisos', role: 'group', 'aria-label': 'Advertencias de la lectura del correo' },
        c.advertencias.map((t) => h('div', { class: 'aviso aviso--aviso' }, icono('alerta', { tam: 16 }), h('span', {}, t))))
      : null,
    a.error ? avisoError(a.error) : null,
    analizando
      ? h('div', { class: 'estado', role: 'status', 'aria-live': 'polite' },
        h('span', { class: 'spinner', 'aria-hidden': 'true' }),
        h('div', { style: 'flex:1' }, 'Analizando con el modelo…', h('div', { class: 'progreso', 'aria-hidden': 'true' })))
      : null,
    h('div', { class: 'acciones' },
      h('button', {
        type: 'button', class: 'btn btn--primario btn--grande btn--bloque', id: 'btn-analizar',
        disabled: analizando, 'aria-busy': analizando ? 'true' : null, onclick: analizar,
      }, analizando ? h('span', { class: 'spinner', 'aria-hidden': 'true' }) : icono('analisis', { tam: 18 }),
      analizando ? 'Analizando…' : 'Analizar correo'),
      h('button', { type: 'button', class: 'btn btn--secundario btn--bloque', disabled: analizando, onclick: reiniciar },
        'Elegir otro correo')));
}

function vistaPrevia(a) {
  const bloqueado = a.fase === 'analizando';
  return [h('div', { class: 'rejilla rejilla--2' },
    h('div', { class: 'analisis__columna' }, tarjetaCorreo(a, bloqueado), tarjetaContenido(a.correo), tarjetaEnlaces(a.correo)),
    h('div', { class: 'sticky' }, tarjetaAccion(a)))];
}

/* ---------- Vista: resultado (Fase 4: ver vistas/resultado.js) ---------- */
function vistaResultado(a) {
  return dibujarResultado(a, { reiniciar, volverAPrevia });
}

/* ---------- Diagnóstico de conexión (de la Fase 2, ahora plegable) ---------- */
function crearFila(metodo, ruta) {
  const estado = h('span', { class: 'chip chip--neutro' }, 'Pendiente');
  const detalle = h('span', { class: 'verif__detalle' });
  const li = h('li', { class: 'verif__fila' }, h('code', {}, `${metodo} ${ruta}`), detalle, estado);
  const marcar = (tipo, etiqueta, texto = '') => {
    estado.className = `chip chip--${tipo}`;
    estado.textContent = etiqueta;
    detalle.textContent = texto;
  };
  return { li, marcar };
}

function diagnostico() {
  const salud = crearFila('GET', '/salud');
  const metricas = crearFila('GET', '/metricas');
  const predecir = crearFila('POST', '/predecir');
  const boton = h('button', { class: 'btn btn--secundario btn--chico', type: 'button' }, 'Probar /predecir con un mensaje de ejemplo');
  predecir.marcar('neutro', 'Sin probar', 'Envía un mensaje fijo de ejemplo; no guarda nada.');

  async function probarPrediccion() {
    boton.disabled = true;
    predecir.marcar('neutro', 'Probando…');
    try {
      const r = await api.predecir({ texto: MENSAJE_PRUEBA });
      predecir.marcar('ok', 'Conectado',
        `es_spam: ${r.es_spam ? 'sí' : 'no'} · probabilidad ${fmtPct(r.probabilidad)} · ${r.rasgos_detectados.length} rasgos devueltos`);
    } catch (e) {
      predecir.marcar('error', 'Error', e.message);
    } finally {
      boton.disabled = false;
    }
  }
  boton.addEventListener('click', probarPrediccion);

  async function probarBasicos() {
    salud.marcar('neutro', 'Probando…');
    metricas.marcar('neutro', 'Probando…');
    try {
      const r = await api.salud();
      salud.marcar(r.modelo_cargado ? 'ok' : 'aviso', r.modelo_cargado ? 'Conectado' : 'Sin modelo', `estado: ${r.estado} · modelo_cargado: ${r.modelo_cargado}`);
    } catch (e) { salud.marcar('error', 'Error', e.message); }
    try {
      const m = await api.metricas();
      metricas.marcar('ok', 'Conectado',
        `${m.modelo ?? 'modelo'} · ${fmtNum(m.dataset?.filas_utilizadas)} filas de entrenamiento · F1 en prueba: ${fmtNum(m.test?.f1)}`);
    } catch (e) { metricas.marcar('error', 'Error', e.message); }
  }

  const det = h('details', { class: 'tarjeta diagnostico' },
  h('summary', {}, 'Diagnóstico de conexión con la API'),
  h('p', { class: 'tarjeta__texto' }, 'Confirma que la interfaz habla con el servidor: estado de la API, métricas y una predicción de ejemplo.'),
  h('ul', { class: 'verif' }, salud.li, metricas.li, predecir.li),
  h('div', { class: 'verif__acciones' }, boton));
  probarBasicos(); // como en la Fase 2: comprueba /salud y /metricas al abrir la pantalla
  return det;
}

/* ---------- Punto de entrada de la vista ---------- */
export function render() {
  instalarArrastre();
  raiz = h('div', { class: 'analisis' });
  ultimaVista = null;
  panelDiagnostico = diagnostico();
  pintar();
  // El router inserta la vista y su indicador de pasos después de render(): se corrige el paso al terminar.
  setTimeout(() => { if (raiz && raiz.isConnected) actualizarPasos(PASO[A().fase]); }, 0);
  return raiz;
}
