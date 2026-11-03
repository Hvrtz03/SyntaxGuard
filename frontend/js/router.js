// Router por hash (#/ruta). No necesita configuración en el servidor.
// Los hashes que no empiezan con "#/" (anclas internas) se ignoran a propósito.
import { h, encabezadoPagina, indicadorPasos, avisoError } from './ui.js';

/** Tabla de rutas: única fuente para el menú lateral y la navegación. */
export const RUTAS = [
  { id: 'analisis', ruta: '/analisis', etiqueta: 'Análisis', icono: 'analisis', cargar: () => import('./vistas/analizar.js') },
  { id: 'historial', ruta: '/historial', etiqueta: 'Historial', icono: 'historial', cargar: () => import('./vistas/historial.js') },
  { id: 'metricas', ruta: '/metricas', etiqueta: 'Métricas', icono: 'metricas', cargar: () => import('./vistas/metricas.js') },
  { id: 'retroalimentacion', ruta: '/retroalimentacion', etiqueta: 'Retroalimentación', icono: 'retroalimentacion', cargar: () => import('./vistas/retroalimentacion.js') },
  { id: 'acerca', ruta: '/acerca', etiqueta: 'Acerca de', icono: 'acerca', cargar: () => import('./vistas/acerca.js') },
];

const RUTA_INICIAL = '/analisis';

export function iniciarRouter({ contenedor, alNavegar }) {
  let navegacion = 0;
  let primera = true;

  async function resolver() {
    const hash = location.hash.slice(1);
    if (hash && !hash.startsWith('/')) return; // ancla interna: no es una ruta
    if (!hash) history.replaceState(null, '', '#' + RUTA_INICIAL); // URL canónica sin añadir entrada al historial

    const ruta = (hash || RUTA_INICIAL).split('?')[0].replace(/\/+$/, '') || RUTA_INICIAL;
    const definicion = RUTAS.find((r) => r.ruta === ruta);
    if (!definicion) {
      location.replace('#' + RUTA_INICIAL);
      return;
    }

    const turno = ++navegacion;
    contenedor.setAttribute('aria-busy', 'true');
    try {
      const modulo = await definicion.cargar();
      const meta = modulo.meta;
      const cuerpo = await modulo.render({ ruta, definicion });
      if (turno !== navegacion) return; // llegó una navegación más reciente
      contenedor.replaceChildren(
        encabezadoPagina(meta),
        meta.paso ? indicadorPasos(meta.paso) : h('div', { class: 'pagina__espacio' }),
        cuerpo,
      );
      document.title = `${meta.titulo} · SyntaxGuard`;
      alNavegar(definicion);
      if (!primera) {
        window.scrollTo(0, 0);
        document.getElementById('titulo-pagina')?.focus({ preventScroll: true });
      }
      primera = false;
    } catch (e) {
      if (turno !== navegacion) return;
      contenedor.replaceChildren(
        encabezadoPagina({ titulo: 'No se pudo abrir esta sección', subtitulo: '' }),
        avisoError('Ocurrió un error al cargar la vista. Recarga la página e inténtalo de nuevo.'),
      );
      console.error('[router]', e);
    } finally {
      if (turno === navegacion) contenedor.setAttribute('aria-busy', 'false');
    }
  }

  window.addEventListener('hashchange', resolver);
  resolver();
}
