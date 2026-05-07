#!/bin/bash
# Phase 0 — Environment Setup (Manjaro Linux, single machine)
# Run once: bash setup.sh
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[x]${NC} $1"; exit 1; }

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$PROJ_DIR/.venv"

# ── Flatpak detection ──────────────────────────────────────────────────────────
# VS Code installed as Flatpak runs in a sandbox: no sudo, no pacman.
# flatpak-spawn --host lets us reach the real Manjaro system for installs.
IN_FLATPAK=false
HOST=""
if [ -n "$FLATPAK_ID" ] || [ -d "/run/host" ]; then
  if flatpak-spawn --host true 2>/dev/null; then
    IN_FLATPAK=true
    HOST="flatpak-spawn --host"
    info "Flatpak sandbox detected — system commands will run via flatpak-spawn --host"
  else
    error "Running inside Flatpak but flatpak-spawn --host is not available. Open a native terminal (Konsole/xterm) and re-run setup.sh from there."
  fi
fi

# Wrapper: run a command on the host (with sudo) regardless of sandbox state
hsudo() { $HOST sudo "$@"; }
hrun()  { $HOST "$@"; }

# ── 1. System packages ────────────────────────────────────────────────────────
info "Installing system packages..."
hsudo pacman -S --noconfirm --needed iperf3 wireshark-qt python-pip git 2>/dev/null || \
  warn "Some pacman packages may already be installed"

# Open vSwitch
if ! hrun pacman -Q openvswitch &>/dev/null; then
  info "Installing openvswitch..."
  if hrun bash -c "command -v yay" &>/dev/null; then
    hrun yay -S --noconfirm openvswitch
  elif hrun bash -c "command -v paru" &>/dev/null; then
    hrun paru -S --noconfirm openvswitch
  else
    warn "No AUR helper found. Installing openvswitch from source..."
    hsudo pacman -S --noconfirm --needed autoconf automake libtool \
      openssl python-setuptools python-six
    TMP=$(hrun mktemp -d)
    hrun git clone --depth=1 --branch v3.3.0 \
      https://github.com/openvswitch/ovs.git "$TMP/ovs"
    $HOST bash -c "
      cd '$TMP/ovs'
      ./boot.sh
      ./configure --prefix=/usr
      make -j\$(nproc)
      sudo make install
      sudo mkdir -p /usr/share/openvswitch/scripts
      rm -rf '$TMP'
    "
  fi
else
  info "openvswitch already installed"
fi

# Mininet
if ! hrun bash -c "command -v mn" &>/dev/null; then
  info "Installing Mininet from source..."
  hsudo pacman -S --noconfirm --needed iproute2 net-tools iputils
  TMP=$(hrun mktemp -d)
  hrun git clone --depth=1 --branch 2.3.1b4 \
    https://github.com/mininet/mininet.git "$TMP/mininet"
  $HOST bash -c "
    cd '$TMP/mininet'
    sudo PYTHON=python3 util/install.sh -nfv 2>/dev/null || sudo python3 setup.py install
    rm -rf '$TMP'
  "
else
  info "Mininet already installed"
fi

# ── 2. Start OvS services ─────────────────────────────────────────────────────
info "Starting Open vSwitch services..."
hsudo systemctl enable --now ovsdb-server ovs-vswitchd 2>/dev/null || {
  hsudo ovsdb-server \
    --remote=punix:/usr/local/var/run/openvswitch/db.sock \
    --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
    --pidfile --detach 2>/dev/null || true
  hsudo ovs-vswitchd --pidfile --detach 2>/dev/null || true
  hsudo ovs-vsctl --no-wait init 2>/dev/null || true
  warn "OvS started manually — will not auto-start on reboot."
}

hrun ovs-vsctl show &>/dev/null && info "OvS running OK" || warn "OvS may not be running"

# ── 3. Python virtual environment ─────────────────────────────────────────────
info "Creating Python virtual environment at .venv ..."
python3 -m venv "$VENV"
source "$VENV/bin/activate"
pip install --upgrade pip wheel setuptools --quiet

# ── 4. Python packages ────────────────────────────────────────────────────────
info "Installing Python packages..."
pip install -r "$PROJ_DIR/requirements.txt"

# ── 5. Ryu compatibility patch ────────────────────────────────────────────────
info "Patching Ryu for Python 3.10+ compatibility..."
python3 "$PROJ_DIR/scripts/patch_ryu.py"

# ── 6. Smoke tests ────────────────────────────────────────────────────────────
info "Running smoke tests..."
python3 -c "import torch;  print('  torch', torch.__version__)"  || error "torch import failed"
python3 -c "import flask;  print('  flask', flask.__version__)"
python3 -c "import numpy;  print('  numpy', numpy.__version__)"
python3 -c "
import collections, collections.abc
for a in ['Callable','Iterable','Iterator','Mapping','MutableMapping']:
    if not hasattr(collections, a):
        setattr(collections, a, getattr(collections.abc, a))
import ryu; print('  ryu ok')
" || warn "ryu import failing — check scripts/patch_ryu.py"

hrun bash -c "command -v mn"    &>/dev/null && info "  mn OK"         || warn "  mn not found"
hrun ovs-vsctl show             &>/dev/null && info "  ovs-vsctl OK"  || warn "  OvS not responding"

echo ""
info "Setup complete!"
echo "  Activate venv :  source .venv/bin/activate"
echo "  Test topology :  flatpak-spawn --host sudo .venv/bin/python mininet/iot_topology.py --test"
echo "  Test stats    :  python3 collector/stats_collector.py --mock"
