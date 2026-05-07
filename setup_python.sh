#!/bin/bash
# Run this from the VS Code terminal (Flatpak is fine).
# Installs Python venv + packages. No sudo needed.
#
#   bash setup_python.sh
#
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[x]${NC} $1"; exit 1; }

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PROJ_DIR/.venv"

# ── Virtual environment ───────────────────────────────────────────────────────
info "Creating .venv ..."
python3 -m venv "$VENV"
source "$VENV/bin/activate"
pip install --upgrade pip wheel setuptools --quiet

# ── Python packages ───────────────────────────────────────────────────────────
info "Installing Python packages (this may take a few minutes)..."
pip install -r "$PROJ_DIR/requirements.txt"

# ── Ryu Python 3.10+ patch ────────────────────────────────────────────────────
info "Patching Ryu for Python 3.10+ compatibility..."
python3 "$PROJ_DIR/scripts/patch_ryu.py"

# ── Smoke tests ───────────────────────────────────────────────────────────────
info "Smoke tests..."
python3 -c "import torch;  print('  torch', torch.__version__)"  || error "torch failed"
python3 -c "import flask;  print('  flask', flask.__version__)"
python3 -c "import numpy;  print('  numpy', numpy.__version__)"
python3 -c "
import collections, collections.abc
for a in ['Callable','Iterable','Iterator','Mapping','MutableMapping']:
    if not hasattr(collections, a):
        setattr(collections, a, getattr(collections.abc, a))
import ryu; print('  ryu ok')
" || warn "ryu import failing — check scripts/patch_ryu.py output above"

python3 collector/stats_collector.py --mock --once | tail -3

echo ""
info "Python setup done."
echo "  Activate venv : source .venv/bin/activate"
echo "  Test stats    : python3 collector/stats_collector.py --mock"
echo "  Test topology : (from native terminal) sudo python3 mininet/iot_topology.py --test"
