import { tarjetaPendiente } from '../ui.js';

export const meta = {
  titulo: 'Acerca de SyntaxGuard',
  subtitulo: 'Reconocimiento de patrones sintáctico-estructural para una detección de spam interpretable.',
  paso: 0,
};

export function render() {
  return tarjetaPendiente({
    fase: 5,
    titulo: 'Acerca de SyntaxGuard',
    texto: 'Aquí se describirán el enfoque, las cinco capas de procesamiento y los límites de uso responsable.',
  });
}
