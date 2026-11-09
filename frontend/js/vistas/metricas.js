// Vista «Métricas» (Fase 5). Dos pestañas que NO se mezclan:
//   · Rendimiento del modelo → datos de models/metricas.json, tal como los guardó el entrenamiento (GET /metricas).
//                              La aplicación no los recalcula ni los modifica.
//   · Estadísticas de uso    → se calculan con los registros reales del historial (GET /estadisticas/uso).
import { api } from '../api.js';
import { h, icono, avisoError, fmtNum, fmtPct, fmtFecha } from '../ui.js';

export const meta = {
  titulo: 'Métricas del modelo',
  subtitulo: 'Rendimiento del modelo (medido al entrenarlo) y estadísticas de uso de la aplicación, por separado. Umbral de decisión: 0.50.',
  paso: 4,
};

let pestana = 'modelo'; // se conserva al cambiar de sección
let conjunto = 'test';

const cuatro = (v) => (typeof v === 'number' ? v.toFixed(4) : '—');
const NOMBRES_CONJUNTO = { test: 'Conjunto de prueba', validacion: 'Conjunto de validación' };

export function render() {
  const panel = h('div', { id: 'panel-metricas', role: 'tabpanel' });
  const barra = h('div', { class: 'pestanas', role: 'tablist', 'aria-label': 'Tipo de métricas' });
  const cache = { modelo: null, uso: null, errModelo: null, errUso: null, cargando: { modelo: true, uso: true } };

  function pintarBarra() {
    barra.replaceChildren(...[['modelo', 'Rendimiento del modelo'], ['uso', 'Estadísticas de uso']].map(([id, t]) =>
      h('button', {
        type: 'button', role: 'tab', class: 'pestana', id: `pest-${id}`, 'aria-selected': String(pestana === id), 'aria-controls': 'panel-metricas',
        onclick: () => { pestana = id; pintar(); },
      }, t)));
  }

  function pintar() {
    pintarBarra();
    panel.setAttribute('aria-labelledby', `pest-${pestana}`);
    const clave = pestana;
    if (cache.cargando[clave]) { panel.replaceChildren(h('div', { class: 'estado', role: 'status' }, h('span', { class: 'spinner' }), 'Cargando…')); return; }
    const err = clave === 'modelo' ? cache.errModelo : cache.errUso;
    if (err) { panel.replaceChildren(h('div', { class: 'lista-avisos' }, avisoError(err), h('button', { type: 'button', class: 'btn btn--secundario btn--chico', onclick: () => cargar(clave) }, icono('reintentar', { tam: 14 }), 'Reintentar'))); return; }
    panel.replaceChildren(clave === 'modelo' ? panelModelo(cache.modelo, pintar) : panelUso(cache.uso));
  }

  async function cargar(clave) {
    cache.cargando[clave] = true; pintar();
    try {
      if (clave === 'modelo') { cache.modelo = await api.metricas(); cache.errModelo = null; } else { cache.uso = await api.estadisticasUso(); cache.errUso = null; }
    } catch (e) {
      const msg = e.message || 'No se pudieron cargar los datos.';
      if (clave === 'modelo') cache.errModelo = msg; else cache.errUso = msg;
    }
    cache.cargando[clave] = false; pintar();
  }

  pintarBarra();
  cargar('modelo'); cargar('uso');
  return h('div', { class: 'stack' }, barra, panel);
}

/* ---------- Rendimiento del modelo ---------- */
function cifra(etq, valor, sub) {
  return h('div', { class: 'cifra' }, h('dt', {}, etq), h('dd', {}, valor, sub ? h('span', { class: 'cifra__sub' }, sub) : null));
}

function panelModelo(m, repintar) {
  const s = m[conjunto];
  const c = s.matriz_confusion;
  const celda = (n, etq, clase) => h('div', { class: `matriz__celda ${clase}` }, h('strong', {}, fmtNum(n)), h('span', {}, etq));
  const imp = Array.isArray(m.importancia_rasgos) ? m.importancia_rasgos : [];
  const maxImp = Math.max(...imp.map((x) => x.importancia), 0.0001);
  return h('div', { class: 'stack' },
    h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-rend' },
      h('div', { class: 'panel-tit' },
        h('h2', { class: 'tarjeta__titulo', id: 'tit-rend' }, 'Rendimiento del modelo'),
        h('span', { class: 'chip chip--neutro' }, 'Fuente: models/metricas.json')),
      h('p', { class: 'tarjeta__texto texto-largo' }, `Medido al entrenar el modelo, con correos que no se usaron para entrenarlo. Estas cifras no cambian con el uso de la aplicación y no se recalculan aquí. Mostrando: ${NOMBRES_CONJUNTO[conjunto].toLowerCase()} (${fmtNum(s.n_muestras)} correos).`),
      h('div', { style: 'height:14px' }),
      h('div', { class: 'pestanas', role: 'group', 'aria-label': 'Conjunto de datos' },
        ...['test', 'validacion'].map((k) => h('button', { type: 'button', class: 'pestana', id: `conj-${k}`, 'aria-pressed': String(conjunto === k), 'aria-selected': String(conjunto === k), onclick: () => { conjunto = k; repintar(); } }, NOMBRES_CONJUNTO[k]))),
      h('dl', { class: 'cifras cifras--cuatro', id: 'cifras-modelo' },
        cifra('Exactitud', cuatro(s.accuracy), fmtPct(s.accuracy)),
        cifra('Precisión', cuatro(s.precision), fmtPct(s.precision)),
        cifra('Recall', cuatro(s.recall), fmtPct(s.recall)),
        cifra('F1', cuatro(s.f1), fmtPct(s.f1))),
      h('p', { class: 'ayuda' }, 'Precisión: de lo que el modelo marcó como SPAM, qué fracción lo era. Recall: de todo el SPAM real, qué fracción detectó. F1 combina ambas. La clase positiva es «spam».')),
    h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-matriz' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-matriz' }, 'Matriz de confusión'),
      h('p', { class: 'tarjeta__texto' }, `${NOMBRES_CONJUNTO[conjunto]}: ${fmtNum(s.n_muestras)} correos.`),
      h('div', { style: 'height:14px' }),
      h('div', { class: 'matriz', id: 'matriz-confusion', role: 'table', 'aria-label': 'Matriz de confusión' },
        h('div', {}), h('div', { class: 'matriz__enc' }, 'Predicho LEGÍTIMO'), h('div', { class: 'matriz__enc' }, 'Predicho SPAM'),
        h('div', { class: 'matriz__enc' }, 'Real LEGÍTIMO'), celda(c.tn, 'Verdaderos negativos', 'matriz__celda--bien'), celda(c.fp, 'Falsos positivos', 'matriz__celda--mal'),
        h('div', { class: 'matriz__enc' }, 'Real SPAM'), celda(c.fn, 'Falsos negativos', 'matriz__celda--mal'), celda(c.tp, 'Verdaderos positivos', 'matriz__celda--bien')),
      h('p', { class: 'ayuda' }, `Un falso positivo es un correo legítimo marcado como SPAM; un falso negativo es un SPAM que pasó como legítimo.`)),
    h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-ficha' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-ficha' }, 'Ficha del modelo y de los datos'),
      h('dl', { class: 'datos datos--ancho' },
        h('dt', {}, 'Algoritmo'), h('dd', {}, `${m.modelo} (${fmtNum(m.hiperparametros.n_estimators)} árboles)`),
        h('dt', {}, 'Clase positiva'), h('dd', {}, m.clase_positiva),
        h('dt', {}, 'Balanceo'), h('dd', {}, m.balanceo),
        h('dt', {}, 'Umbral de decisión'), h('dd', {}, '0.5: SPAM si P(spam) ≥ 0.5 (definido en el detector)'),
        h('dt', {}, 'Correos usados'), h('dd', {}, `${fmtNum(m.dataset.filas_utilizadas)} (${fmtNum(m.dataset.spam)} spam y ${fmtNum(m.dataset.ham)} legítimos)`),
        h('dt', {}, 'Partición'), h('dd', {}, `${fmtNum(m.dataset.particion.train)} entrenamiento · ${fmtNum(m.dataset.particion.validacion)} validación · ${fmtNum(m.dataset.particion.test)} prueba`),
        h('dt', {}, 'Entrenado el'), h('dd', {}, fmtFecha(m.fecha_entrenamiento)))),
    imp.length ? h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-imp' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-imp' }, 'Importancia global de los rasgos'),
      h('p', { class: 'tarjeta__texto texto-largo' }, 'Cuánto contribuyó cada rasgo al Random Forest durante el entrenamiento (suma de importancias normalizada). Es una medida global del modelo; no explica por qué se clasificó un correo concreto.'),
      h('div', { style: 'height:12px' }),
      h('ul', { class: 'barras-h', id: 'lista-importancia' }, imp.map((x) => h('li', { class: 'barra-h' },
        h('span', { class: 'barra-h__nombre' }, h('code', {}, x.rasgo)),
        h('div', { class: 'barra-h__pista', 'aria-hidden': 'true' }, h('div', { class: 'barra-h__relleno', style: `width:${((x.importancia / maxImp) * 100).toFixed(1)}%` })),
        h('span', { class: 'barra-h__valor' }, fmtPct(x.importancia)))))) : null,
    h('div', { class: 'nota' }, 'Estas cifras provienen de 300 correos de prueba en inglés; con otros correos el rendimiento puede ser distinto.'));
}

/* ---------- Estadísticas de uso ---------- */
function panelUso(s) {
  const encabezado = h('div', { class: 'panel-tit' },
    h('h2', { class: 'tarjeta__titulo', id: 'tit-uso' }, 'Estadísticas de uso'),
    h('span', { class: 'chip chip--neutro' }, 'Fuente: historial de esta aplicación'));
  const aviso = h('p', { class: 'tarjeta__texto texto-largo' }, 'Se calculan con los análisis guardados en el historial. No miden el rendimiento del modelo (eso está en la otra pestaña) y cambian cada vez que analizas o eliminas correos.');
  if (!s.analizados) {
    return h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-uso' }, encabezado, aviso,
      h('div', { style: 'height:14px' }),
      h('div', { class: 'vacio', id: 'uso-vacio' }, icono('metricas', { tam: 28 }), h('p', {}, 'Aún no hay análisis registrados, así que no hay estadísticas de uso.'),
        h('div', { class: 'acciones acciones--fila acciones--centro' },
          h('a', { class: 'btn btn--primario', href: '#/analisis' }, 'Analizar un correo'), h('a', { class: 'btn btn--secundario', href: '#/masivo' }, 'Análisis masivo')),
        s.errores ? h('p', { class: 'texto-tenue' }, `Hay ${fmtNum(s.errores)} registro${s.errores === 1 ? '' : 's'} con error (no cuentan como análisis).`) : null));
  }
  const pSpam = s.analizados ? (s.spam / s.analizados) * 100 : 0;
  const maxDia = Math.max(...s.por_dia.map((d) => d.total), 1);
  const dias = s.por_dia;
  const conDatos = dias.filter((d) => d.total > 0);
  return h('div', { class: 'stack' },
    h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-uso' }, encabezado, aviso,
      h('dl', { class: 'cifras cifras--cuatro', id: 'cifras-uso' },
        cifra('Correos analizados', fmtNum(s.analizados), `${fmtNum(s.individuales)} individuales · ${fmtNum(s.masivos)} masivos`),
        cifra('SPAM detectados', fmtNum(s.spam)),
        cifra('Correos legítimos', fmtNum(s.legitimos)),
        cifra('Porcentaje de SPAM', fmtPct(s.porcentaje_spam / 100), 'sobre los correos clasificados')),
      h('p', { class: 'ayuda' }, s.errores ? `Además hay ${fmtNum(s.errores)} registro${s.errores === 1 ? '' : 's'} con error que no se cuenta${s.errores === 1 ? '' : 'n'} como SPAM ni como legítimo.` : 'No hay registros con error.')),
    h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-dist' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-dist' }, 'Distribución de resultados'),
      h('div', { style: 'height:12px' }),
      h('div', { class: 'apilada', role: 'img', 'aria-label': `${fmtNum(s.spam)} SPAM y ${fmtNum(s.legitimos)} legítimos` },
        h('div', { class: 'apilada__spam', style: `width:${pSpam.toFixed(2)}%` }), h('div', { class: 'apilada__ok', style: `width:${(100 - pSpam).toFixed(2)}%` })),
      h('div', { class: 'leyenda' },
        h('span', {}, h('i', { style: 'background:var(--c-spam)' }), `SPAM: ${fmtNum(s.spam)}`),
        h('span', {}, h('i', { style: 'background:var(--c-ok)' }), `LEGÍTIMO: ${fmtNum(s.legitimos)}`)),
      h('div', { style: 'height:8px' }),
      h('dl', { class: 'datos datos--ancho' },
        h('dt', {}, 'Análisis individuales'), h('dd', {}, fmtNum(s.individuales)),
        h('dt', {}, 'Análisis masivos'), h('dd', {}, `${fmtNum(s.masivos)} correos en ${fmtNum(s.lotes)} lote${s.lotes === 1 ? '' : 's'}`),
        h('dt', {}, 'Retroalimentaciones'), h('dd', {}, fmtNum(s.retroalimentaciones)))),
    h('section', { class: 'tarjeta', 'aria-labelledby': 'tit-dias' },
      h('h2', { class: 'tarjeta__titulo', id: 'tit-dias' }, `Análisis por día (últimos ${s.dias_considerados} días)`),
      h('p', { class: 'tarjeta__texto' }, 'Cada columna es un día (hora local); su altura es el total de correos clasificados ese día.'),
      h('div', { style: 'height:12px' }),
      h('div', { class: 'grafico', id: 'grafico-dias', role: 'img', 'aria-label': `Análisis por día; máximo ${fmtNum(maxDia)} en un día` },
        dias.map((d) => h('div', { class: 'grafico__col', title: `${d.dia}: ${d.total} (SPAM ${d.spam}, LEGÍTIMO ${d.legitimos})` },
          h('div', { class: 'grafico__spam', style: `height:${((d.spam / maxDia) * 100).toFixed(1)}%` }),
          h('div', { class: 'grafico__ok', style: `height:${((d.legitimos / maxDia) * 100).toFixed(1)}%` })))),
      h('div', { class: 'grafico__ejes' }, h('span', {}, dias[0].dia), h('span', {}, dias[dias.length - 1].dia)),
      h('details', { class: 'detalles', style: 'margin-top:14px' },
        h('summary', {}, `Ver los datos en tabla (${conDatos.length} día${conDatos.length === 1 ? '' : 's'} con análisis)`),
        h('div', { class: 'tabla-contenedor' }, h('table', { class: 'tabla' },
          h('thead', {}, h('tr', {}, h('th', {}, 'Día'), h('th', { class: 'num' }, 'SPAM'), h('th', { class: 'num' }, 'LEGÍTIMO'), h('th', { class: 'num' }, 'Total'))),
          h('tbody', {}, [...conDatos].reverse().map((d) => h('tr', {}, h('td', {}, d.dia), h('td', { class: 'num' }, fmtNum(d.spam)), h('td', { class: 'num' }, fmtNum(d.legitimos)), h('td', { class: 'num' }, fmtNum(d.total)))))))))
  );
}
