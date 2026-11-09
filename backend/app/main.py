import json
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.detector import METRICS_PATH, MODEL_PATH, SpamDetector
from app.schemas import PrediccionRequest, PrediccionResponse
from app.rutas_correo import router as router_correo
from app import almacen, seguridad
from app.dependencias import ErrorAuth, borrar_cookie, exigir_usuario
from app.rutas_analisis import router as router_analisis
from app.rutas_auth import router as router_auth
from app.rutas_historial import router as router_historial

estado = {"detector": None, "error": None, "almacen_error": None}

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fase 6A: la configuración de seguridad se valida PRIMERO. Si es inválida (p. ej. SG_SECRET_KEY demasiado
    # corta, o ausente con SG_ENTORNO=produccion) el servidor no arranca: es preferible a funcionar sin seguridad.
    seguridad.verificar_configuracion()
    try:
        estado["detector"] = SpamDetector(MODEL_PATH)
        estado["error"] = None
    except Exception as e:
        estado["detector"] = None
        estado["error"] = str(e)
    # Fase 5: base de datos del historial (SQLite). Un fallo aquí no impide usar /predecir ni /correo/extraer.
    try:
        almacen.iniciar()
        estado["almacen_error"] = None
    except Exception as e:
        estado["almacen_error"] = str(e)
    yield


app = FastAPI(title="SyntaxGuard", version="1.0.0", lifespan=lifespan)
# Fase 5: la aplicación se usa en local. CORS solo admite páginas servidas desde localhost / 127.0.0.1,
# para que otra página web abierta en el navegador no pueda leer ni borrar el historial.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Errores de autenticación (Fase 6A) ----------
# Formato estable para el frontend: {"detail": "mensaje", "codigo": "<codigo_estable>", ...campos extra}.
@app.exception_handler(ErrorAuth)
async def manejar_error_auth(request: Request, exc: ErrorAuth):
    respuesta = JSONResponse({"detail": exc.mensaje, "codigo": exc.codigo, **exc.extra}, status_code=exc.estado,
                             headers={**exc.cabeceras, "Cache-Control": "no-store"})
    if exc.borrar_cookie:
        borrar_cookie(respuesta, request)
    return respuesta


@app.exception_handler(RequestValidationError)
async def manejar_validacion(request: Request, exc: RequestValidationError):
    """En /auth/* los errores de validación usan el mismo formato que el resto de errores de autenticación.
    En el resto de rutas se conserva el formato original de FastAPI (los contratos anteriores no cambian)."""
    if request.url.path.startswith("/auth/"):
        campos = {}
        for e in exc.errors():
            ruta = [str(x) for x in e.get("loc", ()) if x not in ("body", "query")]
            campos[".".join(ruta) or "cuerpo"] = "Dato ausente o con formato inválido."
        return JSONResponse({"detail": "Los datos enviados no son válidos.", "codigo": "datos_invalidos",
                             "campos": campos}, status_code=422, headers={"Cache-Control": "no-store"})
    return await request_validation_exception_handler(request, exc)


@app.get("/salud")
def salud():
    return {"estado": "ok", "modelo_cargado": estado["detector"] is not None}


@app.get("/metricas")
def metricas():
    if not METRICS_PATH.exists():
        raise HTTPException(status_code=404, detail="metricas.json no existe. Ejecuta scripts/train.py")
    try:
        return json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="metricas.json no es un JSON válido")


# Fase 6A: /predecir exige sesión (y token CSRF). El contrato de entrada y salida NO cambia.
@app.post("/predecir", response_model=PrediccionResponse, dependencies=[Depends(exigir_usuario)])
def predecir(req: PrediccionRequest):
    if estado["detector"] is None:
        raise HTTPException(
            status_code=503,
            detail=f"Modelo no cargado: {estado['error'] or 'ejecuta scripts/train.py'}",
        )
    try:
        return estado["detector"].predecir(req.texto, req.html)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al analizar el mensaje: {e}")


# ---------- Autenticación (Fase 6A) ----------
# POST /auth/registro, POST /auth/login, POST /auth/logout, GET /auth/me
app.include_router(router_auth)

# ---------- Extracción de correos (Fase 3) ----------
# Endpoint nuevo: POST /correo/extraer. No modifica los endpoints anteriores.
app.include_router(router_correo)

# ---------- Análisis masivo, historial, retroalimentación y estadísticas (Fase 5) ----------
# Endpoints nuevos. No modifican /salud, /metricas, /predecir ni /correo/extraer.
app.include_router(router_analisis)
app.include_router(router_historial)


# ---------- Interfaz web (frontend estático) ----------
# Solo se activa si existe la carpeta frontend/. No modifica ningún endpoint anterior.
if FRONTEND_DIR.is_dir():
    # En Windows el registro del sistema a veces asigna text/plain a .js y el navegador rechaza los módulos.
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="frontend")

    @app.get("/", include_in_schema=False)
    def interfaz():
        return FileResponse(FRONTEND_DIR / "index.html")
