// Vista "Análisis". En la Fase 2 solo contiene una verificación temporal de la conexión con la API.
// La carga de correos (pegar / subir .eml) se construye en la Fase 3.
import { api } from '../api.js';
import { h, icono, fmtNum, fmtPct } from '../ui.js';

export const meta = {
  titulo: 'Analizar correo',
  subtitulo: 'Carga un mensaje para detectar patrones sospechosos y comprender el motivo de la clasificación.',
  paso: 1,
};

const MENSAJE_PRUEBA = 'WINNER!! Claim your FREE prize now: http://bit.ly/claim-now';

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

export function render() {
  const salud = crearFila('GET', '/salud');
  const metricas = crearFila('GET', '/metricas');
  const predecir = crearFila('POST', '/predecir');

  const boton = h('button', { class: 'btn btn--secundario', type: 'button' }, 'Probar /predecir con un mensaje de ejemplo');

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

  (async () => {
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
  })();

  predecir.marcar('neutro', 'Sin probar', 'Envía un mensaje fijo de ejemplo; no guarda nada.');

  return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-verif' },
    h('span', { class: 'chip chip--aviso' }, icono('construccion', { tam: 14 }), 'En construcción · Fase 3'),
    h('h2', { class: 'tarjeta__titulo', id: 'tit-verif' }, 'Conexión con la API'),
    h('p', { class: 'tarjeta__texto' }, 'Aquí irá la carga del correo (pegar texto o subir un archivo .eml). Mientras tanto, esta comprobación confirma que la interfaz habla con el servidor.'),
    h('ul', { class: 'verif' }, salud.li, metricas.li, predecir.li),
    h('div', { class: 'verif__acciones' }, boton));
}
