import { tarjetaPendiente } from '../ui.js';

export const meta = {
  titulo: 'Historial de análisis',
  subtitulo: 'Consulta decisiones anteriores, filtra resultados y vuelve a sus evidencias.',
  paso: 4,
};

export function render() {
  return tarjetaPendiente({
    fase: 5,
    titulo: 'Historial de análisis',
    texto: 'Aquí se listarán los correos que analices desde esta interfaz, con búsqueda, filtros y exportación a CSV.',
  });
}
