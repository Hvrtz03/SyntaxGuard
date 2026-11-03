"""Lanzador de SyntaxGuard.

Arranca la API (FastAPI + modelo entrenado) y abre la interfaz web en el navegador.
No modifica el modelo, la API ni la interfaz: solo los inicia.

Uso:
    python run.py                # arranca y abre http://127.0.0.1:8000/
    python run.py --sin-navegador
    python run.py --puerto 9000
    python run.py --verificar    # solo revisa que todo esté listo, sin arrancar

Variables opcionales (archivo .env o variables de entorno):
    SG_HOST, SG_PUERTO, SG_ABRIR_NAVEGADOR
"""
import argparse
import importlib.util
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

MODELO = ROOT / "models" / "clasificador.pkl"
FRONTEND = ROOT / "frontend" / "index.html"

# nombre del módulo a importar -> paquete a instalar
DEPENDENCIAS = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "sklearn": "scikit-learn",
    "numpy": "numpy",
    "pandas": "pandas",
    "bs4": "beautifulsoup4",
    "nltk": "nltk",
    "spacy": "spacy",
    "zss": "zss",
    "rapidfuzz": "rapidfuzz",
    "joblib": "joblib",
}


def cargar_env(ruta: Path) -> None:
    """Lee un .env sencillo (CLAVE=valor). No pisa variables ya definidas en el sistema."""
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


def revisar_entorno() -> list:
    """Devuelve la lista de problemas encontrados (vacía si todo está bien)."""
    problemas = []
    if sys.version_info < (3, 10):
        problemas.append(f"Python {sys.version_info.major}.{sys.version_info.minor} es muy antiguo; usa 3.10 o 3.11.")

    faltan = [pip for mod, pip in DEPENDENCIAS.items() if importlib.util.find_spec(mod) is None]
    if faltan:
        problemas.append(
            "Faltan paquetes: " + ", ".join(faltan) + ".\n"
            "    Ejecuta:  pip install -r requirements.txt   (o usa iniciar.bat)"
        )
    elif importlib.util.find_spec("en_core_web_sm") is None:
        problemas.append(
            "Falta el modelo de spaCy en_core_web_sm.\n"
            "    Ejecuta:  python -m spacy download en_core_web_sm"
        )

    if not MODELO.is_file():
        problemas.append("Falta models/clasificador.pkl.\n    Ejecuta:  python scripts/train.py")
    if not FRONTEND.is_file():
        problemas.append("Falta frontend/index.html (la interfaz web).")
    return problemas


def puerto_libre(host: str, puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, puerto)) != 0


def abrir_cuando_este_listo(url: str, espera_max: int = 90) -> None:
    """Espera a que /salud responda (el modelo tarda unos segundos en cargar) y abre el navegador."""
    limite = time.time() + espera_max
    while time.time() < limite:
        try:
            with urllib.request.urlopen(url + "salud", timeout=1) as r:
                if r.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.5)
    print(f"No pude confirmar que la API estuviera lista. Abre manualmente: {url}")


def main() -> int:
    cargar_env(ROOT / ".env")

    ap = argparse.ArgumentParser(description="Inicia SyntaxGuard (API + interfaz web).")
    ap.add_argument("--host", default=os.environ.get("SG_HOST", "127.0.0.1"))
    ap.add_argument("--puerto", type=int, default=int(os.environ.get("SG_PUERTO", "8000")))
    ap.add_argument("--sin-navegador", action="store_true", help="no abrir el navegador automáticamente")
    ap.add_argument("--verificar", action="store_true", help="solo revisar el entorno y salir")
    args = ap.parse_args()

    abrir = not args.sin_navegador and os.environ.get("SG_ABRIR_NAVEGADOR", "1").lower() not in ("0", "false", "no")

    print("=" * 56)
    print("  SyntaxGuard - detector de spam y phishing")
    print("=" * 56)

    problemas = revisar_entorno()
    if problemas:
        print("\nNo se puede iniciar todavía:\n")
        for p in problemas:
            print("  - " + p)
        print()
        return 1
    print("[OK] Dependencias, modelo e interfaz encontrados.")

    if args.verificar:
        print("Verificación terminada: todo listo para ejecutar.")
        return 0

    if not puerto_libre(args.host, args.puerto):
        print(f"\nEl puerto {args.puerto} ya está en uso (¿ya hay otro SyntaxGuard abierto?).")
        print(f"Cierra el otro proceso o usa otro puerto:  python run.py --puerto {args.puerto + 1}")
        return 1

    import uvicorn  # se importa aquí para poder mostrar el mensaje amable de arriba si falta

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.puerto}/"
    print(f"\nCargando el modelo... (unos segundos)\nInterfaz:       {url}\nDocumentación:  {url}docs\n")
    print("Para detener el programa presiona Ctrl+C en esta ventana.\n")

    if abrir:
        threading.Thread(target=abrir_cuando_este_listo, args=(url,), daemon=True).start()

    uvicorn.run("app.main:app", host=args.host, port=args.puerto, log_level="info")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nSyntaxGuard detenido.")
