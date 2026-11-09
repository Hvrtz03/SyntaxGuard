"""Genera capturas de pantalla de la Fase 5 (servidor de PRUEBA con detector SIMULADO y datos del corpus real)."""
import json, shutil, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[3]
SALIDA = AQUI.parent / "capturas"
SALIDA.mkdir(exist_ok=True)

with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); P = s.getsockname()[1]
tmp = Path(tempfile.mkdtemp())
srv = subprocess.Popen([sys.executable, str(AQUI / "servidor_prueba_fase5.py"), str(P), str(tmp / "c.db")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(50):
    try: socket.create_connection(("127.0.0.1", P), 0.3).close(); break
    except OSError: time.sleep(0.2)
B = f"http://127.0.0.1:{P}"

def post(ruta, cuerpo, cab=None, json_=True):
    r = urllib.request.Request(B + ruta, data=json.dumps(cuerpo).encode() if json_ else cuerpo, headers=cab or {}, method="POST")
    return json.loads(urllib.request.urlopen(r).read())

lote = post("/lotes", {"total": 12})
for d, n in (("spam", 7), ("easy_ham", 7)):
    for i, p in enumerate(sorted((RAIZ / "backend" / "data" / d).iterdir())[:n]):
        post("/analisis/archivo", p.read_bytes(), {"X-Nombre-Archivo": f"{d}_{i:02d}.eml", "X-Lote-Id": str(lote["id"]), "Content-Type": "message/rfc822"}, json_=False)
post("/analisis/archivo", b"", {"X-Nombre-Archivo": "vacio.eml", "X-Lote-Id": str(lote["id"]), "Content-Type": "message/rfc822"}, json_=False)
post("/retroalimentacion", {"analisis_id": 2, "de_acuerdo": False, "comentario": "Es un boletín al que me suscribí."})

try:
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        for nombre, (w, h_) in {"escritorio": (1280, 900), "movil": (390, 844)}.items():
            page = nav.new_page(viewport={"width": w, "height": h_})
            for ruta, arch in (("masivo", "masivo_vacio"), ("historial", "historial"), ("historial/2", "detalle"), ("metricas", "metricas_modelo"), ("retroalimentacion?analisis=2", "retroalimentacion"), ("acerca", "acerca")):
                page.goto(f"{B}/#/{ruta}"); page.wait_for_timeout(900)
                page.screenshot(path=str(SALIDA / f"{nombre}_{arch}.png"), full_page=(nombre == "movil" or arch in ("acerca", "metricas_modelo")))
            page.goto(f"{B}/#/metricas"); page.click("#pest-uso"); page.wait_for_timeout(500)
            page.screenshot(path=str(SALIDA / f"{nombre}_metricas_uso.png"), full_page=True)
            page.goto(f"{B}/#/masivo"); page.wait_for_selector("#zona-masivo")
            page.set_input_files("#entrada-masivo-carpeta", str(RAIZ / "backend" / "data" / "spam"))
            page.wait_for_timeout(600)
            page.screenshot(path=str(SALIDA / f"{nombre}_masivo_lista.png"), full_page=False)
            page.close()
        nav.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("ok")
