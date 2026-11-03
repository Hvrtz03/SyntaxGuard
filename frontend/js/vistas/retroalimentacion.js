import { tarjetaPendiente } from '../ui.js';

export const meta = {
  titulo: 'Retroalimentación',
  subtitulo: 'Si la decisión no es correcta, propón una clasificación y explica el motivo para que pueda revisarse.',
  paso: 5,
};

export function render() {
  return tarjetaPendiente({
    fase: 5,
    titulo: 'Corregir una clasificación',
    texto: 'Aquí podrás indicar la clase correcta, el motivo y un comentario sobre un análisis ya hecho.',
  });
}
