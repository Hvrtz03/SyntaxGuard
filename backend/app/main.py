import json
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.detector import METRICS_PATH, MODEL_PATH, SpamDetector
from app.schemas import PrediccionRequest, PrediccionResponse

estado = {"detector": None, "error": None}

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        estado["detector"] = SpamDetector(MODEL_PATH)
        estado["error"] = None
    except Exception as e:
        estado["detector"] = None
        estado["error"] = str(e)
    yield


app = FastAPI(title="SyntaxGuard", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.post("/predecir", response_model=PrediccionResponse)
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
