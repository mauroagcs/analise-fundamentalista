#!/usr/bin/env bash
# Atualiza os dados, regera o site da prévia mobile (docs/) e publica no GitHub Pages.
# Uso: ./publicar_site.sh
set -euo pipefail
cd "$(dirname "$0")"
PY=".venv/bin/python"; [ -x "$PY" ] || PY="python3"

$PY atualizar.py
$PY gerar_mobile.py --site docs
if git diff --quiet -- docs && [ -z "$(git ls-files --others --exclude-standard docs)" ]; then
  echo "Nada mudou em docs/: nada a publicar."; exit 0
fi
git add docs
git commit -m "Atualiza dados da prévia mobile ($(date +%d/%m/%Y))"
git push
echo "Publicado. O GitHub Pages leva ~1 minuto para atualizar."
