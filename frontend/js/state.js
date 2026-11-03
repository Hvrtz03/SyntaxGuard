// Estado global mínimo con suscripción. Las vistas y el cascarón se enteran de los cambios sin acoplarse.
const estado = {
  // fase: 'cargando' | 'ok' | 'sin_modelo' | 'error'
  salud: { fase: 'cargando', detalle: '' },
  version: null,
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
