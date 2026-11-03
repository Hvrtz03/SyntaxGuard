# Lista de archivos — Fase 2

Comparación SHA-256 entre el proyecto original (ZIP recibido) y el proyecto integrado.

- Archivos eliminados respecto al original: **0**

## Modificados (2)

| Archivo | Qué cambió | SHA-256 original | SHA-256 nuevo |
|---|---|---|---|
| `README.md` | Texto original íntegro + sección nueva 'Interfaz web (Fase 2)' al final. | `86b9ee7008f3298990e07cbb5d0579e4826a846e582cd471d1277d134e3a6305` | `5412fce647f6cbd0977601907222067ca7dfd94bc1859b31d02badceb00f7093` |
| `app/main.py` | Solo añadidos: imports, `FRONTEND_DIR`, tipos MIME, montaje de `/static` y ruta `/`. Endpoints originales intactos. | `df0f957881a4bbc68ead77c1917cfff57608148ab54098012bcdfaa00266e60b` | `8c141b1d09b78ef472848dc722e7d2af46ba4ecc2529e96698f9b4f374b3d97b` |

Copia del original de ambos: carpeta de respaldo del asistente (`_respaldo_original`, no incluida en el ZIP; el original sigue siendo tu ZIP/proyecto local).

## Nuevos de la Fase 2 (16)

| Archivo | SHA-256 |
|---|---|
| `frontend/css/componentes.css` | `6b2cdbe4f17ee1eb9e370ce0f715a0999e3937af26ba730ea4f95add3bd2626a` |
| `frontend/css/layout.css` | `e59c20d82c74d27c3f85415d1b1b9a99d3e554827e4cc9486eb061a400715cc6` |
| `frontend/css/tokens.css` | `af1458ca417b50fedb2fc87b3409ce59ef8c38e54817e087040a55b69817ac28` |
| `frontend/index.html` | `bf7704eb9eede968cb6657ff5882e470a3d1f8f60c822870165ecca2025edc50` |
| `frontend/js/api.js` | `e9bbaefbbcd7769597729643ef88405c584078bd9f628b770ac5320406ce4d4a` |
| `frontend/js/app.js` | `8ef508842979ec0bda01fa557af91fab4be786c83ff5c5d3e29acde06561a78a` |
| `frontend/js/iconos.js` | `0426ef67a432467e9552fbb88e1bf7266d19d4a04491f64b7b5e000ea4a3d5e2` |
| `frontend/js/router.js` | `ecc34ca97bfd7804d3e9bc113ce096ac7472af29492745f6482ca6bd2540e24a` |
| `frontend/js/state.js` | `1ed703346e1e440315095995c85291ec693d5f3f996ea95f2b135dc06e47c4f2` |
| `frontend/js/ui.js` | `0a97716d35ba98010d352dd7339867c24d0afa7ae767ef9e87f9165751730cbc` |
| `frontend/js/vistas/acerca.js` | `a3b237917182547d60efc13da382aac8caf5117aa7e0f6aa9b7d1230ec9dccce` |
| `frontend/js/vistas/analizar.js` | `d6b666063d8880adf3aa5109196184be9740ceb1a3a2545cdea0393a0d90d5ad` |
| `frontend/js/vistas/historial.js` | `7205d11271bec571c85a5ae2a73e6217f4f22c076ca9095877d4bc1d0289ad90` |
| `frontend/js/vistas/metricas.js` | `b2265a464c89c6c224ccd838e5c9b857591bb23611c2b8e24e68e9ea66b7f204` |
| `frontend/js/vistas/retroalimentacion.js` | `bd88cea89dfaaa91f4e210c87fd19f58d2b767387fbdd07b193ba742b6ff5bc2` |
| `scripts/smoke_test_frontend.py` | `f89f249d2f1f0e7f0fcaa21424a509cf48d182a795bab6aad9541ffd7c32c6c6` |

## Nuevos de documentación y pruebas, en `docs/fase2/` (26)

- `docs/fase2/INSTRUCCIONES_INTEGRACION.md`
- `docs/fase2/LISTA_ARCHIVOS.md` (este archivo)
- `docs/fase2/REPORTE_PRUEBAS_FASE2.md`
- `docs/fase2/pruebas/capturar_respuestas.py`
- `docs/fase2/pruebas/probar_interfaz.py`
- `docs/fase2/pruebas/respuestas_integrado.json`
- `docs/fase2/pruebas/respuestas_linea_base.json`
- `docs/fase2/pruebas/resultados_interfaz.json`
- `docs/fase2/pruebas/salida_probar_interfaz.txt`
- `docs/fase2/pruebas/salida_smoke_test_frontend.txt`
- `docs/fase2/pruebas/salida_smoke_test_integrado.txt`
- `docs/fase2/pruebas/salida_smoke_test_linea_base.txt`
- 14 capturas PNG en `docs/fase2/capturas/`

## Intactos (4458)

Mismo SHA-256 que el original. Incluye `data/` completa (4450 archivos) y:

| Archivo | SHA-256 |
|---|---|
| `app/detector.py` | `69519a80807e19d1a3ee5a259795a54b953a62cacfffc5a68a43e37279bb369b` |
| `app/schemas.py` | `e33c8592b34d109798563019babb6890cb2befe041c02953c96b7566f9357c28` |
| `models/clasificador.pkl` | `99fa052be599b1f1ee591de036d8dc9e43a0724b41d0d5a6df58ad265453233c` |
| `models/metricas.json` | `2277423ac74a657cbfc3782457c5ac38d4477d064383cae5605f328dfc939df7` |
| `requirements.txt` | `a63d1b530d719f7a3c551e4b757487b8a3e7e04afcaecedf6e233139ff61cc57` |
| `scripts/build_dataset.py` | `ea93a2821b61d6d0471dc9c1c83fe3c83e53355a4fea0a253af3847648fedd0a` |
| `scripts/smoke_test.py` | `eaa0c50be00eb42e6f6afb6156e00fc9e5d720c2e5f6ad493991581ecbd5baea` |
| `scripts/train.py` | `51789bc1b9a302676a28c819615bfc287562e19f6cd5817d66a1a7cf032a20ac` |

## No incluido en el ZIP (a propósito)

`.venv`, `.venv_respaldo`, `__pycache__`, `*.pyc`, la carpeta de respaldo del asistente y cualquier temporal. El original traía 3 archivos `.pyc` en `app/__pycache__` que se omitieron.
