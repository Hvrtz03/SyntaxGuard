// Router por hash (#/ruta). No necesita configuración en el servidor.
// Los hashes que no empiezan con "#/" (anclas internas) se ignoran a propósito.
import { h, encabezadoPagina, indicadorPasos, avisoError } from './ui.js';

/** Tabla de rutas: única fuente para el menú lateral y la navegación. */
export const RUTAS = [
  { id: 'analisis', ruta: '/analisis', etiqueta: 'Análisis', icono: 'analisis', cargar: () => import('./vistas/analizar.js') },
  { id: 'masivo', ruta: '/masivo', etiqueta: 'Análisis masivo', icono: 'masivo', cargar: () => import('./vistas/masivo.js') },
  // conParametro: admite #/historial/<id> (detalle de un análisis guardado).
  { id: 'historial', ruta: '/historial', etiqueta: 'Historial', icono: 'historial', conParametro: true, cargar: () => import('./vistas/historial.js') },
  { id: 'metricas', ruta: '/metricas', etiqueta: 'Métricas', icono: 'metricas', cargar: () => import('./vistas/metricas.js') },
  { id: 'retroalimentacion', ruta: '/retroalimentacion', etiqueta: 'Retroalimentación', icono: 'retroalimentacion', cargar: () => import('./vistas/retroalimentacion.js') },
  { id: 'acerca', ruta: '/acerca', etiqueta: 'Acerca de', icono: 'acerca', cargar: () => import('./vistas/acerca.js') },
];

const RUTA_INICIAL = '/analisis';

// puedeNavegar: guardia de sesión (Fase 6B). Sin sesión el router no resuelve ni pinta vistas privadas.
// Devuelve { refrescar } para volver a resolver la ruta actual (p. ej. justo después de iniciar sesión).
export function iniciarRouter({ contenedor, alNavegar, puedeNavegar = () => true }) {
  let navegacion = 0;
  let primera = true;

  async function resolver() {
    if (!puedeNavegar()) return; // sin sesión: no se pinta ninguna vista privada
    const hash = location.hash.slice(1);
    if (hash && !hash.startsWith('/')) return; // ancla interna: no es una ruta
    if (!hash) history.replaceState(null, '', '#' + RUTA_INICIAL); // URL canónica sin añadir entrada al historial

    const [rutaCruda, consultaTxt = ''] = (hash || RUTA_INICIAL).split('?');
    const ruta = rutaCruda.replace(/\/+$/, '') || RUTA_INICIAL;
    const consulta = new URLSearchParams(consultaTxt); // p. ej. #/retroalimentacion?analisis=12
    let parametro = null; // p. ej. el «12» de #/historial/12
    let definicion = RUTAS.find((r) => r.ruta === ruta);
    if (!definicion) {
      const conParam = RUTAS.find((r) => r.conParametro && ruta.startsWith(`${r.ruta}/`));
      if (conParam) {
        definicion = conParam;
        try { parametro = decodeURIComponent(ruta.slice(conParam.ruta.length + 1).split('/')[0]); } catch { parametro = null; }
      }
    }
    if (!definicion) {
      location.replace('#' + RUTA_INICIAL);
      return;
    }

    const turno = ++navegacion;
    contenedor.setAttribute('aria-busy', 'true');
    try {
      const modulo = await definicion.cargar();
      const meta = modulo.meta;
      const cuerpo = await modulo.render({ ruta, definicion, parametro, consulta });
      // Más reciente que esta navegación, o la sesión terminó mientras cargaba: no se pisa la pantalla de acceso.
      if (turno !== navegacion || !puedeNavegar()) return;
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
  return { refrescar: resolver };
}
