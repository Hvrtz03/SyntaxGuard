#!/usr/bin/env bash
# Inicia SyntaxGuard en Linux/macOS. Uso: bash iniciar.sh
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  PY=""
  for c in python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
  [ -z "$PY" ] && { echo "No encontré Python 3.10/3.11. Instálalo desde https://www.python.org/downloads/"; exit 1; }
  echo "[1/3] Creando entorno virtual con $PY ..."
  "$PY" -m venv .venv
fi

if [ ! -f ".venv/.sg_listo" ]; then
  echo "[2/3] Instalando dependencias (solo la primera vez, requiere internet) ..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m spacy download en_core_web_sm
  touch .venv/.sg_listo
fi

[ -f ".env" ] || cp .env.example .env
echo "[3/3] Iniciando SyntaxGuard ..."
exec .venv/bin/python run.py "$@"
