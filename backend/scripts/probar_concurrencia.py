"""¿Es seguro analizar varios correos EN PARALELO con el detector compartido?  (usa el MODELO REAL)

El análisis masivo de SyntaxGuard funciona con concurrencia 1 (un correo a la vez). Este script mide si el
detector compartido (spaCy + NLTK + Random Forest) da EXACTAMENTE los mismos resultados cuando varios hilos lo
usan a la vez, y cuánto se gana en velocidad. Solo si el resultado es «sin diferencias» tendría sentido subir
la concurrencia (CONCURRENCIA en frontend/js/cola.js y quitar BLOQUEO_DETECTOR en backend/app/servicio.py).
El script NO cambia nada del proyecto.

Uso (desde la raíz del proyecto, con el entorno virtual activo):
    python backend\\scripts\\probar_concurrencia.py            (40 correos, rondas de 2 y 4 hilos)
    python backend\\scripts\\probar_concurrencia.py --n 100 --hilos 2 4 8 --rondas 3
Escribe resultados_concurrencia.json junto a este archivo.
"""
import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app import correo  # noqa: E402
from app.detector import SpamDetector  # noqa: E402


def firma(r):
    """Resultado completo y comparable: clasificación, P(spam) y todos los rasgos con su valor y estado."""
    return (r["es_spam"], r["probabilidad"], tuple((x["rasgo"], x["valor"], x["activo"]) for x in r["rasgos_detectados"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40, help="cantidad de correos reales (mitad spam, mitad legítimos)")
    ap.add_argument("--hilos", type=int, nargs="+", default=[2, 4])
    ap.add_argument("--rondas", type=int, default=2, help="repeticiones por cada número de hilos (orden aleatorio)")
    args = ap.parse_args()

    mitad = max(1, args.n // 2)
    archivos = sorted((BACKEND / "data" / "spam").iterdir())[:mitad] + sorted((BACKEND / "data" / "easy_ham").iterdir())[:mitad]
    entradas = []
    for p in archivos:
        try:
            c = correo.procesar(p.read_bytes(), p.name + ".eml")
            entradas.append((p.name, c["texto"], c["html"]))
        except correo.ErrorCorreo:
            pass
    print(f"Correos reales utilizables: {len(entradas)}")
    det = SpamDetector()
    det.predecir("warm up", None)  # carga perezosa de recursos

    t0 = time.perf_counter()
    base = {n: firma(det.predecir(t, h)) for n, t, h in entradas}
    t_sec = time.perf_counter() - t0
    # determinismo secuencial: dos pasadas seguidas deben coincidir
    de_nuevo = {n: firma(det.predecir(t, h)) for n, t, h in entradas}
    determinista = base == de_nuevo
    print(f"Secuencial: {t_sec:.2f} s ({t_sec / len(entradas) * 1000:.0f} ms por correo). Determinista entre pasadas: {determinista}")

    informe = {"correos": len(entradas), "secuencial_s": round(t_sec, 3), "determinista_secuencial": determinista, "pruebas": []}
    seguro = determinista
    for hilos in args.hilos:
        for ronda in range(1, args.rondas + 1):
            orden = entradas[:]
            random.shuffle(orden)
            diferencias, errores = [], []

            def tarea(e):
                n, t, h = e
                try:
                    return n, firma(det.predecir(t, h)), None
                except Exception as ex:  # noqa: BLE001
                    return n, None, f"{type(ex).__name__}: {ex}"
            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=hilos) as pool:
                for n, f, err in pool.map(tarea, orden):
                    if err:
                        errores.append((n, err))
                    elif f != base[n]:
                        diferencias.append(n)
            dt = time.perf_counter() - t0
            informe["pruebas"].append({"hilos": hilos, "ronda": ronda, "segundos": round(dt, 3), "aceleracion": round(t_sec / dt, 2),
                                       "diferencias": len(diferencias), "errores": len(errores), "ejemplos": (diferencias + [e[0] for e in errores])[:5]})
            print(f"{hilos} hilos, ronda {ronda}: {dt:.2f} s (x{t_sec / dt:.2f}) · diferencias: {len(diferencias)} · errores: {len(errores)}")
            if diferencias or errores:
                seguro = False

    informe["conclusion"] = ("SIN diferencias ni errores en estas pruebas. No es una garantía (la prueba es una muestra), pero la concurrencia podría "
                             "evaluarse con más correos y rondas." if seguro else
                             "HAY diferencias o errores: el detector compartido NO es seguro en paralelo. Mantén la concurrencia en 1.")
    print("\n" + informe["conclusion"])
    (Path(__file__).parent / "resultados_concurrencia.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if seguro else 2


if __name__ == "__main__":
    sys.exit(main())
