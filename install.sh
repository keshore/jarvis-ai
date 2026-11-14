#!/bin/bash
# jarvis-ai installer (macOS, Apple Silicon). Creates ~/.jarvis-ai/venv and links the CLI.
# ./install.sh --llm   also installs mlx-lm and downloads the optional local model (~2.3 GB)
set -e
cd "$(dirname "$0")"
PY=""
for c in python3.12 python3.13 python3.11 python3.10; do command -v $c >/dev/null && PY=$c && break; done
[ -n "$PY" ] || { echo "Need Python 3.10-3.13 (brew install python@3.12)"; exit 1; }
HOME_DIR="${JARVIS_AI_HOME:-$HOME/.jarvis-ai}"
mkdir -p "$HOME_DIR" 
$PY -m venv "$HOME_DIR/venv"
"$HOME_DIR/venv/bin/pip" install -q --upgrade pip
EXTRA=""; [ "$1" = "--llm" ] && EXTRA="[llm]"
"$HOME_DIR/venv/bin/pip" install -q ".$EXTRA"
mkdir -p "$HOME/.local/bin"
ln -sf "$HOME_DIR/venv/bin/jarvis-ai" "$HOME/.local/bin/jarvis-ai"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "Add to PATH:  export PATH=\"\$HOME/.local/bin:\$PATH\"";; esac
"$HOME_DIR/venv/bin/jarvis-ai" setup $([ "$1" = "--llm" ] && echo --llm)
echo; echo "Done. Try:  jarvis-ai doctor   then   jarvis-ai"
