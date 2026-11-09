// Piezas de presentación de las EVIDENCIAS de un correo (Fase 4).
// Las usan la vista previa (analizar.js) y la pantalla de resultados (vistas/resultado.js),
// para que el mismo dato no se dibuje con dos implementaciones distintas.
//
// Regla de seguridad: todo lo que viene del correo se inserta con h() (nodos de texto).
// Nunca se usa innerHTML con datos externos y los enlaces NO son clicables.
import { h, icono, fmtNum, fmtBytes } from './ui.js';

export const MAX_HTML_VISIBLE = 20000;
export const NOTA_ENLACES = 'Son los enlaces que aparecen en el correo. Se muestran como texto: no se abren ni se visitan, y no son por sí mismos rasgos que el modelo haya utilizado.';

export const textoONoDisponible = (valor) => (valor
  ? valor
  : h('span', { class: 'no-disponible' }, 'No disponible'));

/** Remitente, destinatario, asunto y fecha tal como los entregó /correo/extraer (o «No disponible»). */
export function datosCorreo(c) {
  return h('dl', { class: 'datos' },
    h('dt', {}, 'Remitente'), h('dd', {}, textoONoDisponible(c.remitente)),
    h('dt', {}, 'Destinatario'), h('dd', {}, textoONoDisponible(c.destinatario)),
    h('dt', {}, 'Asunto'), h('dd', {}, textoONoDisponible(c.asunto)),
    h('dt', {}, 'Fecha'), h('dd', {}, textoONoDisponible(c.fecha)));
}

/** Dominio de una URL SOLO como texto informativo (no se visita nada). Devuelve null si no se puede interpretar. */
export function dominioDe(url) {
  try {
    const u = /^[a-z][a-z0-9+.-]*:\/\//i.test(url) ? url : `http://${url}`;
    return new URL(u).hostname || null;
  } catch {
    return null;
  }
}

/** Lista de enlaces como texto plano. conDominio añade el dominio interpretado (dato informativo, sin juicio). */
export function listaEnlaces(c, { conDominio = false } = {}) {
  if (!c.enlaces.length) return h('p', { class: 'texto-tenue' }, 'No se encontraron enlaces http(s) ni www en el correo.');
  return h('div', {},
    h('ul', { class: 'enlaces' }, c.enlaces.map((e) => {
      const dominio = conDominio ? dominioDe(e.url) : null;
      return h('li', {},
        h('div', { class: 'enlaces__dato' },
          h('code', {}, e.url),
          conDominio ? h('span', { class: 'enlaces__dominio' }, 'Dominio: ', dominio || 'no se pudo interpretar') : null),
        h('span', { class: 'chip chip--neutro' }, e.origen === 'html' ? 'En un enlace HTML' : 'En el texto'));
    })),
    c.enlaces_total > c.enlaces.length
      ? h('p', { class: 'ayuda' }, `Se muestran ${fmtNum(c.enlaces.length)} de ${fmtNum(c.enlaces_total)} enlaces.`)
      : null);
}

/** Texto extraído, con la marca del punto donde el detector deja de leer. Siempre dentro de <pre> (texto). */
export function bloqueTexto(c) {
  const limite = c.limite_analisis_caracteres || 3000;
  const hijos = c.texto.length > limite
    ? [c.texto.slice(0, limite),
      h('span', { class: 'previa__corte' }, `El detector analiza solo hasta aquí (primeros ${fmtNum(limite)} caracteres)`),
      h('span', { class: 'previa__resto' }, c.texto.slice(limite))]
    : [c.texto];
  return [
    h('pre', { class: 'previa', tabindex: '0', 'aria-label': 'Texto del correo' }, hijos),
    h('p', { class: 'ayuda' },
      `${fmtNum(c.texto.length)} caracteres de texto`,
      c.texto_desde_html ? ' · obtenido del HTML del correo' : '',
      c.texto_truncado ? ' · recortado al límite permitido' : ''),
  ];
}

/** Código HTML del correo como texto (desplegable). Si no hay HTML lo dice. Nunca se renderiza. */
export function bloqueHtml(c) {
  if (!c.html) return h('p', { class: 'ayuda' }, 'Este correo no incluye parte HTML.');
  const visible = c.html.slice(0, MAX_HTML_VISIBLE);
  return h('details', { class: 'detalles' },
    h('summary', {}, 'Ver código HTML del correo (se muestra como texto; no se ejecuta)'),
    h('pre', { class: 'previa', tabindex: '0', 'aria-label': 'Código HTML del correo' }, visible),
    c.html.length > MAX_HTML_VISIBLE
      ? h('p', { class: 'ayuda' }, `Se muestran los primeros ${fmtNum(MAX_HTML_VISIBLE)} de ${fmtNum(c.html.length)} caracteres.`)
      : null);
}

/**
 * Características estructurales que SÍ entregó /correo/extraer (no se inventa ninguna).
 * Devuelve filas { etiqueta, valor } listas para mostrar.
 */
export function caracteristicasEstructurales(c, tamanoBytes) {
  const campos = ['remitente', 'destinatario', 'asunto', 'fecha'];
  const conCabecera = campos.filter((k) => c[k]).length;
  const deHtml = c.enlaces.filter((e) => e.origen === 'html').length;
  const deTexto = c.enlaces.length - deHtml;
  const limite = c.limite_analisis_caracteres || 3000;
  const nota = c.enlaces_total > c.enlaces.length ? ' (entre los enlaces mostrados)' : '';
  return [
    { etiqueta: 'Origen del contenido', valor: c.origen === 'eml' ? 'Correo con cabeceras (.eml)' : 'Texto pegado sin cabeceras' },
    { etiqueta: 'Cabeceras principales leídas', valor: `${conCabecera} de ${campos.length} (remitente, destinatario, asunto, fecha)` },
    { etiqueta: 'Tamaño del contenido', valor: fmtBytes(typeof tamanoBytes === 'number' ? tamanoBytes : c.tamano_bytes) },
    { etiqueta: 'Parte de texto plano', valor: c.texto_desde_html ? 'No · el texto se obtuvo del HTML' : 'Sí' },
    { etiqueta: 'Parte HTML', valor: c.html ? `Sí · ${fmtNum(c.html.length)} caracteres${c.html_truncado ? ' (recortado)' : ''}` : 'No' },
    { etiqueta: 'Adjuntos ignorados', valor: fmtNum(c.adjuntos_ignorados) },
    { etiqueta: 'Enlaces encontrados', valor: fmtNum(c.enlaces_total) },
    { etiqueta: 'Enlaces por origen', valor: c.enlaces.length ? `${fmtNum(deTexto)} en el texto · ${fmtNum(deHtml)} en HTML${nota}` : 'No hay enlaces' },
    { etiqueta: 'Caracteres de texto', valor: fmtNum(c.texto.length) },
    { etiqueta: 'Caracteres que lee el detector', valor: `${fmtNum(Math.min(c.texto.length, limite))} (límite ${fmtNum(limite)})` },
  ];
}

/** Tabla descriptiva simple (dl) a partir de filas { etiqueta, valor }. */
export function tablaDatos(filas) {
  return h('dl', { class: 'tabla-datos' }, filas.flatMap((f) => [h('dt', {}, f.etiqueta), h('dd', {}, f.valor)]));
}

/**
 * Información que NO está disponible y que conviene decir de forma explícita
 * (además de las advertencias que ya entrega el backend).
 */
export function faltantes(c) {
  const avisos = [];
  const sinCabeceras = ['remitente', 'destinatario', 'asunto', 'fecha'].filter((k) => !c[k]);
  if (sinCabeceras.length) {
    avisos.push(`No disponible en este correo: ${sinCabeceras.join(', ')}.`);
  }
  if (!c.html) {
    avisos.push('El correo no incluye HTML: el detector no evaluó rasgos de estructura HTML (DOM) y no hay código HTML que mostrar.');
  }
  if (!c.enlaces_total) {
    avisos.push('No se encontraron enlaces: no hay rasgos de URL que evaluar.');
  }
  return avisos;
}

/** Aviso con icono. tipo: 'aviso' | 'info' | 'error'. */
export function avisoConIcono(texto, tipo = 'aviso') {
  return h('div', { class: `aviso aviso--${tipo}`, role: tipo === 'error' ? 'alert' : null },
    icono(tipo === 'info' ? 'acerca' : 'alerta', { tam: 16 }), h('span', {}, texto));
}
