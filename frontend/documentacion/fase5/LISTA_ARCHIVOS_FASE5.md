# SyntaxGuard · Fase 5 — Archivos modificados y nuevos
(Comparados contra el proyecto recibido. Los archivos de capturas y de evidencias de pruebas se listan al final.)

## Archivos protegidos: INTACTOS (comparación byte a byte y SHA-256)
| Archivo | SHA-256 |
|---|---|
| `backend/app/detector.py` | `0baab83513a554f80b72d006e418bf76a25722d0529a60edb8c757c769a0351c` |
| `backend/app/schemas.py` | `61dbc2c7a716ccac5f824087ad0e781afa195eb42621e245b69a4f53b494b91b` |
| `backend/models/clasificador.pkl` | `99fa052be599b1f1ee591de036d8dc9e43a0724b41d0d5a6df58ad265453233c` |
| `backend/models/metricas.json` | `bf93833e92aaad6407e62dfed74e14b775b92f994bd731a9081df551fe02d5e5` |
| `backend/data/dataset.csv` (y todo `backend/data/`) | `e17235062818f114904adf0309d25278ea78f55cbfc04d705d66253628c71cab` |
| `requirements.txt` | `10d0def4755eb90baa91d66c7a9566f1c6d49c43c0fd7abdba47667f1490fc07` |

También intactos: `backend/app/correo.py` y `backend/app/rutas_correo.py`. El umbral 0.5 sigue definido solo en `detector.py`.
`backend/scripts/smoke_test_fase5.py` y `test_almacen_servicio.py` vuelven a comprobar estos hashes en cada ejecución.

## Archivos modificados (20)
- `README.md`
- `backend/app/main.py` (routers nuevos, inicio de la base de datos, CORS restringido; los endpoints originales no cambian)
- `ejecutable/iniciar.bat`, `ejecutable/iniciar.sh` (trabajan sobre la raíz del proyecto)
- `ejecutable/run.py` (solo el texto del banner: ya no dice «phishing»)
- `frontend/index.html` (enlaza `gestion.css`)
- `frontend/js/api.js`, `iconos.js`, `router.js`, `state.js`, `ui.js`
- `frontend/js/vistas/analizar.js`, `resultado.js` (guardado en el historial y tarjeta de historial)
- `frontend/js/vistas/acerca.js`, `historial.js`, `metricas.js`, `retroalimentacion.js` (de «En construcción» a vistas completas)
- `frontend/documentacion/fase2/pruebas/probar_interfaz.py`, `fase3/pruebas/probar_flujo_fase3.py`, `fase4/pruebas/probar_resultados_fase4.py` (expectativas a es-MX y 6 elementos de menú)

## Archivos nuevos
**Backend:** `backend/app/almacen.py`, `servicio.py`, `rutas_analisis.py`, `rutas_historial.py`; `backend/scripts/test_almacen_servicio.py`, `smoke_test_fase5.py`, `probar_concurrencia.py`
**Frontend:** `frontend/css/gestion.css`; `frontend/js/cola.js`, `detalle.js`; `frontend/js/vistas/masivo.js`
**Ejecución y repositorio:** `ejecutable/probar_todo.bat`, `.gitignore`
**Documentación:** `frontend/documentacion/fase5/` (reportes, instrucciones, `pruebas/`, `evidencias/`, `capturas/`)
**Pruebas de interfaz:** `fase5/pruebas/probar_interfaz_fase5.py`, `servidor_prueba_fase5.py`, `tomar_capturas_fase5.py`

`backend/storage/syntaxguard.db` **no** viaja en el ZIP: se crea sola al iniciar y está en `.gitignore`.
