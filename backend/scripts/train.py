import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (accuracy_score, confusion_matrix, f1_score,
                             precision_score, recall_score)
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.detector import FEATURE_NAMES, extraer_rasgos  # noqa: E402

LABEL_COLS = ["label", "v1", "category", "class", "target", "spam", "labels"]
TEXT_COLS = ["text", "v2", "message", "email", "body", "emailtext", "content"]
HTML_COLS = ["html", "html_body"]


def mapear_etiqueta(v):
    s = str(v).strip().lower()
    if s in ("spam", "1", "1.0", "true"):
        return 1
    if s in ("ham", "0", "0.0", "false", "not spam"):
        return 0
    return None


def cargar_dataset(ruta: Path) -> pd.DataFrame:
    df = None
    for enc in ("utf-8", "latin-1"):
        try:
            df = pd.read_csv(ruta, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if df is None:
        sys.exit("No se pudo leer el CSV.")

    cols = {c.lower().strip(): c for c in df.columns}
    c_lab = next((cols[c] for c in LABEL_COLS if c in cols), None)
    c_txt = next((cols[c] for c in TEXT_COLS if c in cols and cols[c] != c_lab), None)
    c_html = next((cols[c] for c in HTML_COLS if c in cols), None)
    if not c_lab or not c_txt:
        sys.exit(f"No se encontraron columnas de texto/etiqueta. Columnas: {list(df.columns)}")

    out = pd.DataFrame({
        "texto": df[c_txt].astype(str).str.strip(),
        "y": df[c_lab].map(mapear_etiqueta),
        "html": df[c_html].astype(str) if c_html else None,
    })
    out = out.dropna(subset=["y"])
    out = out[out["texto"].str.len() > 0]
    antes = len(out)
    out = out.drop_duplicates(subset="texto").reset_index(drop=True)
    print(f"Duplicados eliminados: {antes - len(out)} | Filas finales: {len(out)}")
    out["y"] = out["y"].astype(int)
    return out


def calcular_metricas(modelo, X, y) -> dict:
    pred = modelo.predict(X)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "n_muestras": int(len(y)),
        "accuracy": round(float(accuracy_score(y, pred)), 4),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 4),
        "matriz_confusion": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "matriz_confusion_lista": [[int(tn), int(fp)], [int(fn), int(tp)]],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(ROOT / "data" / "dataset.csv"))
    ap.add_argument("--max-muestras", type=int, default=None)
    args = ap.parse_args()

    ruta = Path(args.dataset)
    if not ruta.exists():
        sys.exit(f"No existe {ruta}. Coloca el CSV de Kaggle en data/dataset.csv")

    df = cargar_dataset(ruta)
    if args.max_muestras and len(df) > args.max_muestras:
        df, _ = train_test_split(df, train_size=args.max_muestras,
                                 stratify=df["y"], random_state=42)
        df = df.reset_index(drop=True)
    print("Distribución de clases:", df["y"].value_counts().to_dict())

    filas, ys = [], []
    for i, r in df.iterrows():
        try:
            html = r["html"] if isinstance(r["html"], str) and r["html"] != "nan" else None
            filas.append(extraer_rasgos(r["texto"], html))
            ys.append(r["y"])
        except Exception as e:
            print(f"Fila {i} omitida: {e}")
        if (i + 1) % 500 == 0:
            print(f"Rasgos extraídos: {i + 1}/{len(df)}")

    X = pd.DataFrame(filas, columns=FEATURE_NAMES)
    y = pd.Series(ys)

    X_tr, X_tmp, y_tr, y_tmp = train_test_split(X, y, test_size=0.30, stratify=y, random_state=42)
    X_val, X_te, y_val, y_te = train_test_split(X_tmp, y_tmp, test_size=0.50,
                                                stratify=y_tmp, random_state=42)
    print(f"Train/Val/Test: {len(X_tr)}/{len(X_val)}/{len(X_te)}")

    mejor, mejor_f1, mejores_params = None, -1.0, None
    for max_depth in (None, 12, 20):
        for min_leaf in (1, 2):
            params = {"n_estimators": 300, "max_depth": max_depth, "min_samples_leaf": min_leaf,
                      "class_weight": "balanced_subsample", "random_state": 42, "n_jobs": -1}
            m = RandomForestClassifier(**params).fit(X_tr, y_tr)
            f1 = f1_score(y_val, m.predict(X_val), zero_division=0)
            print(f"max_depth={max_depth} min_samples_leaf={min_leaf} -> F1 val={f1:.4f}")
            if f1 > mejor_f1:
                mejor, mejor_f1, mejores_params = m, f1, params

    met_val = calcular_metricas(mejor, X_val, y_val)
    met_test = calcular_metricas(mejor, X_te, y_te)
    importancias = sorted(zip(FEATURE_NAMES, mejor.feature_importances_), key=lambda t: -t[1])[:15]

    metricas = {
        "modelo": "RandomForestClassifier",
        "clase_positiva": "spam",
        "balanceo": "class_weight=balanced_subsample",
        "hiperparametros": {k: v for k, v in mejores_params.items() if k != "n_jobs"},
        "dataset": {
            "archivo": ruta.name,
            "filas_utilizadas": int(len(y)),
            "spam": int((y == 1).sum()),
            "ham": int((y == 0).sum()),
            "particion": {"train": len(X_tr), "validacion": len(X_val), "test": len(X_te)},
        },
        "validacion": met_val,
        "test": met_test,
        "importancia_rasgos": [{"rasgo": n, "importancia": round(float(v), 4)} for n, v in importancias],
        "fecha_entrenamiento": datetime.now().isoformat(timespec="seconds"),
    }

    (ROOT / "models").mkdir(exist_ok=True)
    joblib.dump({"modelo": mejor, "feature_names": FEATURE_NAMES, "umbral": 0.5},
                ROOT / "models" / "clasificador.pkl")
    (ROOT / "models" / "metricas.json").write_text(
        json.dumps(metricas, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nMétricas en TEST:")
    print(json.dumps(met_test, indent=2))
    print("Modelo y métricas guardados en models/")


if __name__ == "__main__":
    main()