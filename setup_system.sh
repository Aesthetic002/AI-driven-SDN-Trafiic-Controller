#!/bin/bash
# Run this from a NATIVE terminal (Konsole, xterm, etc.) — NOT from VS Code.
# Installs system-level packages that need sudo: OvS, Mininet, iperf3.
#
#   bash setup_system.sh
#
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[x]${NC} $1"; exit 1; }

[ "$EUID" -eq 0 ] && error "Don't run as root. Run as your normal user with sudo access."

# ── Base packages ─────────────────────────────────────────────────────────────
info "Installing base packages..."
sudo pacman -S --noconfirm --needed git iperf3 wireshark-qt \
  iproute2 net-tools iputils python-pip

# ── Open vSwitch ──────────────────────────────────────────────────────────────
if pacman -Q openvswitch &>/dev/null; then
  info "openvswitch already installed"
elif command -v yay &>/dev/null; then
  info "Installing openvswitch via yay..."
  yay -S --noconfirm openvswitch
elif command -v paru &>/dev/null; then
  info "Installing openvswitch via paru..."
  paru -S --noconfirm openvswitch
else
  info "Building openvswitch from source..."
  sudo pacman -S --noconfirm --needed autoconf automake libtool openssl \
    python-setuptools python-six
  TMP=$(mktemp -d)
  git clone --depth=1 --branch v3.3.0 https://github.com/openvswitch/ovs.git "$TMP/ovs"
  pushd "$TMP/ovs"
  ./boot.sh && ./configure --prefix=/usr && make -j"$(nproc)"
  sudo make install
  sudo mkdir -p /usr/share/openvswitch/scripts
  popd; rm -rf "$TMP"
fi

# ── Mininet ───────────────────────────────────────────────────────────────────
if command -v mn &>/dev/null; then
  info "Mininet already installed"
else
  info "Building Mininet from source..."
  TMP=$(mktemp -d)
  git clone --depth=1 --branch 2.3.1b4 \
    https://github.com/mininet/mininet.git "$TMP/mininet"
  pushd "$TMP/mininet"
  sudo PYTHON=python3 util/install.sh -nfv 2>/dev/null || sudo python3 setup.py install
  popd; rm -rf "$TMP"
fi

# ── Start OvS services ────────────────────────────────────────────────────────
info "Starting OvS services..."
sudo systemctl enable --now ovsdb-server ovs-vswitchd 2>/dev/null || {
  sudo ovsdb-server \
    --remote=punix:/usr/local/var/run/openvswitch/db.sock \
    --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
    --pidfile --detach 2>/dev/null || true
  sudo ovs-vswitchd --pidfile --detach 2>/dev/null || true
  sudo ovs-vsctl --no-wait init 2>/dev/null || true
  warn "OvS started manually — enable the systemd service for auto-start."
}

# ── Verify ────────────────────────────────────────────────────────────────────
ovs-vsctl show &>/dev/null && info "ovs-vsctl OK" || warn "OvS not responding"
command -v mn   &>/dev/null && info "mn OK"        || warn "mn not found — try reopening terminal"

echo ""
info "System setup done. Now run setup_python.sh from inside VS Code."
