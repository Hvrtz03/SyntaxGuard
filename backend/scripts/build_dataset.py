import argparse
import os
import re
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
IGNORAR = {"cmds", "dataset.csv"}


def etiqueta_de_carpeta(nombre: str):
    n = nombre.lower()
    if "ham" in n:
        return "ham"
    if "spam" in n:
        return "spam"
    return None


def decodificar(parte) -> str:
    try:
        contenido = parte.get_content()
        if isinstance(contenido, str):
            return contenido
    except Exception:
        pass
    try:
        payload = parte.get_payload(decode=True) or b""
        return payload.decode(parte.get_content_charset() or "utf-8", errors="replace")
    except Exception:
        return ""


def leer_correo(ruta: Path):
    with open(ruta, "rb") as f:
        msg = BytesParser(policy=policy.default).parse(f)
    texto, html = [], []
    for parte in msg.walk():
        if parte.is_multipart() or parte.get_content_disposition() == "attachment":
            continue
        tipo = parte.get_content_type()
        if tipo == "text/plain":
            texto.append(decodificar(parte))
        elif tipo == "text/html":
            html.append(decodificar(parte))
    texto, html = "\n".join(texto).strip(), "\n".join(html).strip()
    if not texto and html:
        texto = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto[:20000], html[:200000]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--salida", default=str(ROOT / "data" / "dataset.csv"))
    ap.add_argument("--sin-html", action="store_true",
                    help="No guardar el HTML (entrena solo con texto)")
    args = ap.parse_args()

    base = Path(args.data_dir)
    filas, omitidos = [], 0
    for carpeta, _, archivos in os.walk(base):
        etiqueta = etiqueta_de_carpeta(Path(carpeta).name)
        if etiqueta is None:
            continue
        for nombre in archivos:
            if nombre in IGNORAR:
                continue
            try:
                texto, html = leer_correo(Path(carpeta) / nombre)
            except Exception:
                omitidos += 1
                continue
            if not texto:
                omitidos += 1
                continue
            filas.append({"text": texto, "html": "" if args.sin_html else html,
                          "label": etiqueta})

    if not filas:
        sys.exit(f"No se encontraron correos en {base}")
    df = pd.DataFrame(filas)
    print("Correos por clase:", df["label"].value_counts().to_dict(), "| omitidos:", omitidos)
    if df["label"].nunique() < 2:
        sys.exit("Solo hay una clase. Agrega las carpetas de spam (spam, spam_2) a data/")

    df.to_csv(args.salida, index=False, encoding="utf-8")
    print(f"Dataset guardado en {args.salida} ({len(df)} filas)")


if __name__ == "__main__":
    main()