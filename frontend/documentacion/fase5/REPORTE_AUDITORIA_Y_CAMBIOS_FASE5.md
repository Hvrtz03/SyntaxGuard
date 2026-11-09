# SyntaxGuard · Fase 5 — Reporte de auditoría inicial y de cambios

## 1. Auditoría inicial (estado recibido, fase 3 + interfaz de la fase 4)

| Área | Estado encontrado |
|---|---|
| Endpoints `/salud`, `/metricas`, `/predecir`, `/correo/extraer` | Terminados y estables |
| Análisis individual (cargar, vista previa, resultado, evidencias) | Terminado |
| Menú, barra superior, router por hash, estado global | Terminados |
| Historial, Métricas, Retroalimentación, Acerca de | **Solo diseño**: tarjeta «En construcción» |
| Análisis masivo, SQLite, historial, estadísticas de uso, retroalimentación, CSV | **Inexistentes** |
| Lanzadores `iniciar.bat/.sh` | Esperaban `requirements.txt`, `run.py` y `.env.example` en su misma carpeta; con tu estructura (`ejecutable\`) fallaban |
| CORS | `allow_origins=["*"]`: con historial y borrado, cualquier página web abierta en el navegador habría podido leer o borrar datos locales |
| Archivos del corpus | No tienen extensión `.eml`; el extractor los rechaza (se copian con `.eml` para probar) |

## 2. Decisiones aplicadas (D1–D8)

| Decisión | Cómo se cumplió |
|---|---|
| D1 Qué se guarda | Solo metadatos, resultado del modelo, rasgos y **dominios** de enlaces. La prueba verifica que el archivo `.db` no contiene el texto, el HTML ni las URL completas |
| D2 Sección independiente | «Análisis masivo» en el menú lateral; archivos múltiples, carpeta completa y arrastrar/soltar |
| D3 CORS | Solo `localhost` y `127.0.0.1` (`allow_origin_regex`) |
| D4 Retroalimentación | Varias entradas por análisis; la más reciente primero; fecha y hora visibles |
| D5 Errores en lote | Se guardan como registros con estado «error»; no cuentan como SPAM ni LEGÍTIMO |
| D6 Formato | es-MX: `95.3 %`, `1,000` |
| D7 Formatos | `.eml` y `.txt`, con los mismos límites del backend (5 MB, validaciones existentes) |
| D8 Estructura | No se movió ningún archivo; `iniciar.bat/.sh` trabajan sobre la raíz y llaman a `ejecutable\run.py` |

## 3. Funcionalidades implementadas

**Backend (endpoints nuevos; los originales no cambiaron)**
`POST /lotes` · `GET /lotes/{id}` · `POST /analisis/archivo` · `POST /historial` · `GET /historial` · `GET /historial/exportar.csv` · `GET /historial/{id}` · `DELETE /historial/{id}` · `POST /historial/eliminar` · `POST /retroalimentacion` · `GET /retroalimentacion` · `GET /estadisticas/uso`.

- `almacen.py`: SQLite (biblioteca estándar), una conexión por operación, WAL, claves foráneas, consultas parametrizadas (sin inyección SQL), CSV con BOM UTF-8 y neutralización de fórmulas (`= + - @`).
- `servicio.py`: lógica sin FastAPI. **No duplica el detector**: llama a `detector.predecir`, la misma función que usa `/predecir`. Un candado serializa el detector en estos endpoints (concurrencia 1).
- El análisis individual **conserva su flujo** (`/correo/extraer` → `/predecir`); después se guarda el resultado ya obtenido con `POST /historial` (sin segunda inferencia; el servidor valida que `es_spam` concuerde con P(spam) y el umbral 0.5).

**Frontend**
- **Análisis masivo**: lista con nombre y tamaño, quitar archivos, progreso, cancelar (termina el correo en curso, no deja registros fantasma), resultado por correo, errores individuales sin detener el lote, resumen (procesados, SPAM, LEGÍTIMOS, errores, % SPAM, % LEGÍTIMOS sobre los clasificados), filtros, búsqueda por nombre o asunto, detalle por correo y CSV. El estado se conserva al cambiar de sección. **Concurrencia 1** (`frontend/js/cola.js`).
- **Historial**: búsqueda, filtros (resultado, tipo, fechas), paginación (25), selección múltiple y eliminación con confirmación, detalle `#/historial/<id>`, CSV con los mismos filtros.
- **Métricas**: pestaña «Rendimiento del modelo» (solo `/metricas`: 0.9533 / 0.9652 / 0.9174 / 0.9407, matriz 175/4/10/111, ficha del modelo, importancia global de rasgos) y pestaña «Estadísticas de uso» (solo registros del historial). No se mezclan.
- **Retroalimentación**: elegir un análisis, de acuerdo / en desacuerdo, comentario opcional, historial de opiniones. No reentrena ni modifica el modelo.
- **Acerca de**: contenido redactado a partir del detector real (33 rasgos en 5 familias, Random Forest de 300 árboles, entradas texto+HTML, limitaciones, definiciones). No inventa una categoría de phishing.
- La pantalla de resultados del análisis individual muestra «Guardado» y botones hacia el historial y la retroalimentación (botones, no enlaces `<a>`, por la regla de seguridad de la Fase 4).

## 3.1 Correcciones detectadas durante las pruebas
- El campo «Buscar» del historial se estiraba a 240 px de alto (CSS); corregido.
- Mis primeros enlaces `<a>` en la pantalla de resultados rompían la regla «cero `<a>`» de la Fase 4; ahora son botones.
- Las suites de las fases 2–4 esperaban coma decimal y 5 elementos de menú; se actualizaron a es-MX y 6 elementos (anotado en cada archivo).
- `run.py` y los lanzadores decían «spam y phishing»; el modelo solo distingue SPAM y LEGÍTIMO.

## 4. Fuera de alcance / decisiones de diseño
- No se creó `.env.example`: no es necesario (las variables están documentadas en el README y los lanzadores lo copian solo si existe).
- Concurrencia mayor que 1: **no habilitada**. `backend/scripts/probar_concurrencia.py` mide con el modelo real si el detector compartido da resultados idénticos en paralelo.
