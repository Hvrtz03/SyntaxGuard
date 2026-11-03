import { tarjetaPendiente } from '../ui.js';

export const meta = {
  titulo: 'Métricas del modelo',
  subtitulo: 'Evaluación sintáctico-estructural · La clase positiva es SPAM. Umbral de decisión: 0,50.',
  paso: 4,
};

export function render() {
  return tarjetaPendiente({
    fase: 5,
    titulo: 'Métricas del modelo',
    texto: 'Aquí se mostrarán las métricas reales de models/metricas.json: precisión, recall, F1, exactitud y matriz de confusión.',
  });
}
