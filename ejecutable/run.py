
"""Lanzador de SyntaxGuard.

Inicia la API FastAPI y abre la interfaz web.
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

# La raíz real está un nivel arriba de ejecutable/
ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"

os.chdir(ROOT)
sys.path.insert(0, str(BACKEND))

MODELO = BACKEND / "models" / "clasificador.pkl"
FRONTEND = ROOT / "frontend" / "index.html"

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
    if not ruta.is_file():
        return

    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()

        if not linea or linea.startswith("#") or "=" not in linea:
            continue

        clave, valor = linea.split("=", 1)
        os.environ.setdefault(
            clave.strip(),
            valor.strip().strip('"').strip("'")
        )


def revisar_entorno() -> list:
    problemas = []

    if sys.version_info < (3, 10):
        problemas.append("Se requiere Python 3.10 o superior.")

    faltan = [
        pip for mod, pip in DEPENDENCIAS.items()
        if importlib.util.find_spec(mod) is None
    ]

    if faltan:
        problemas.append(
            "Faltan paquetes: " + ", ".join(faltan) +
            ". Ejecuta: pip install -r requirements.txt"
        )
    elif importlib.util.find_spec("en_core_web_sm") is None:
        problemas.append(
            "Falta el modelo spaCy en_core_web_sm. "
            "Ejecuta: python -m spacy download en_core_web_sm"
        )

    if not MODELO.is_file():
        problemas.append(
            f"No se encontró el modelo: {MODELO}"
        )

    if not FRONTEND.is_file():
        problemas.append(
            f"No se encontró la interfaz: {FRONTEND}"
        )

    return problemas


def puerto_libre(host: str, puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, puerto)) != 0


def abrir_cuando_este_listo(url: str, espera_max: int = 90) -> None:
    limite = time.time() + espera_max

    while time.time() < limite:
        try:
            with urllib.request.urlopen(url + "salud", timeout=1) as r:
                if r.status == 200:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.5)

    print(f"No pude confirmar que la API esté lista. Abre: {url}")


def main() -> int:
    cargar_env(ROOT / ".env")

    ap = argparse.ArgumentParser(
        description="Inicia SyntaxGuard (API + interfaz web)."
    )
    ap.add_argument(
        "--host",
        default=os.environ.get("SG_HOST", "127.0.0.1")
    )
    ap.add_argument(
        "--puerto",
        type=int,
        default=int(os.environ.get("SG_PUERTO", "8000"))
    )
    ap.add_argument("--sin-navegador", action="store_true")
    ap.add_argument("--verificar", action="store_true")

    args = ap.parse_args()

    abrir = (
        not args.sin_navegador
        and os.environ.get("SG_ABRIR_NAVEGADOR", "1").lower()
        not in ("0", "false", "no")
    )

    print("=" * 56)
    print("  SyntaxGuard - detector de spam")
    print("=" * 56)

    problemas = revisar_entorno()

    if problemas:
        print("\nNo se puede iniciar todavía:\n")

        for problema in problemas:
            print("  - " + problema)

        return 1

    print("[OK] Dependencias, modelo e interfaz encontrados.")

    if args.verificar:
        print("Verificación terminada: todo listo para ejecutar.")
        return 0

    if not puerto_libre(args.host, args.puerto):
        print(f"El puerto {args.puerto} ya está en uso.")
        return 1

    import uvicorn

    url = (
        f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}"
        f":{args.puerto}/"
    )

    print(f"\nCargando SyntaxGuard...")
    print(f"Interfaz: {url}")
    print(f"Documentación: {url}docs")
    print("\nPresiona Ctrl+C para detener el servidor.\n")

    if abrir:
        threading.Thread(
            target=abrir_cuando_este_listo,
            args=(url,),
            daemon=True
        ).start()

    uvicorn.run(
        "app.main:app",
        app_dir=str(BACKEND),
        host=args.host,
        port=args.puerto,
        log_level="info"
    )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nSyntaxGuard detenido.")
