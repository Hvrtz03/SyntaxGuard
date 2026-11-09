// Estado global mínimo con suscripción. Las vistas y el cascarón se enteran de los cambios sin acoplarse.
const estado = {
  // fase: 'cargando' | 'ok' | 'sin_modelo' | 'error'
  salud: { fase: 'cargando', detalle: '' },
  version: null,
  // Sesión (Fase 6B). Solo datos para mostrar: el token CSRF NO vive aquí, lo guarda auth.js únicamente en memoria.
  // fase: 'verificando' | 'autenticado' | 'anonimo' | 'error'. aviso: { tipo: 'aviso' | 'ok', texto } | null.
  // cambioDeUsuario: true si la sesión pasó a ser de otra cuenta (la interfaz se recarga para no mezclar datos).
  sesion: { fase: 'verificando', usuario: null, aviso: null, detalle: '', cambioDeUsuario: false },
  // Flujo de la pantalla "Análisis". Vive aquí para que no se pierda al cambiar de sección.
  // fase: 'inicial' | 'extrayendo' | 'listo' | 'analizando' | 'resultado'
  analisis: { fase: 'inicial', origen: null, nombre: null, tamano: 0, correo: null, resultado: null, error: null, historialId: null, errorGuardado: null },
  // Análisis masivo (Fase 5). Vive aquí para que el proceso y sus resultados no se pierdan al cambiar de sección.
  // fase: 'seleccion' | 'analizando' | 'finalizado'. Cada archivo: { clave, archivo, nombre, ruta, tamano, tipo,
  //   estado: 'pendiente' | 'procesando' | 'ok' | 'error' | 'cancelado', r: registro del servidor | null, mensaje }
  masivo: { fase: 'seleccion', archivos: [], loteId: null, guardados: null, error: null, aviso: null, filtro: 'todos', busqueda: '' },
  // Filtros del historial: se conservan al ir y volver.
  historial: { filtros: { q: '', clasificacion: '', tipo: '', desde: '', hasta: '' }, pagina: 1 },
};
const oyentes = new Set();

export const obtener = () => estado;

export function actualizar(parcial) {
  Object.assign(estado, parcial);
  oyentes.forEach((f) => f(estado));
}

export function suscribir(oyente) {
  oyentes.add(oyente);
  return () => oyentes.delete(oyente);
}
