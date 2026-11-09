// Cola de trabajo con concurrencia limitada (Fase 5, análisis masivo).
//
// La concurrencia es 1 a propósito: el detector (spaCy + NLTK + Random Forest) es un objeto compartido y no se
// ha demostrado que dé resultados idénticos en paralelo. Subir este valor solo debe hacerse después de ejecutar
// backend/scripts/probar_concurrencia.py con el modelo real y revisar su resultado.
export const CONCURRENCIA = 1;

/**
 * Ejecuta `trabajo(item)` para cada elemento, como máximo `concurrencia` a la vez y en orden.
 * Un error dentro de `trabajo` NO detiene la cola (el llamador decide qué hacer con él).
 * Si `senal` se cancela, no se inician más elementos; los ya iniciados terminan por su cuenta.
 */
export async function ejecutarCola(items, { trabajo, senal, concurrencia = CONCURRENCIA }) {
  let siguiente = 0;
  async function obrero() {
    while (siguiente < items.length && !(senal && senal.aborted)) {
      const item = items[siguiente++];
      try { await trabajo(item); } catch (e) { console.error('[cola]', e); }
    }
  }
  const n = Math.max(1, Math.min(concurrencia, items.length || 1));
  await Promise.all(Array.from({ length: n }, obrero));
}
