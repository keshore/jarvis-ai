#!/bin/bash
# localvoice-ai installer (macOS, Apple Silicon). Creates ~/.localvoice-ai/venv and links the CLI.
# ./install.sh --llm   also installs mlx-lm and downloads the optional local model (~2.3 GB)
set -e
cd "$(dirname "$0")"
PY=""
for c in python3.12 python3.13 python3.11 python3.10; do command -v $c >/dev/null && PY=$c && break; done
[ -n "$PY" ] || { echo "Need Python 3.10-3.13 (brew install python@3.12)"; exit 1; }
HOME_DIR="${LOCALVOICE_AI_HOME:-$HOME/.localvoice-ai}"
mkdir -p "$HOME_DIR"22 
$PY -m venv "$HOME_DIR/venv"
"$HOME_DIR/venv/bin/pip" install -q --upgrade pip
EXTRA=""; [ "$1" = "--llm" ] && EXTRA="[llm]"
"$HOME_DIR/venv/bin/pip" install -q -e ".$EXTRA"
mkdir -p "$HOME/.local/bin"
ln -sf "$HOME_DIR/venv/bin/localvoice-ai" "$HOME/.local/bin/localvoice-ai"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "Add to PATH:  export PATH=\"\$HOME/.local/bin:\$PATH\"";; esac
"$HOME_DIR/venv/bin/localvoice-ai" setup $([ "$1" = "--llm" ] && echo --llm)
echo; echo "Done. Try:  localvoice-ai doctor   then   localvoice-ai start"
