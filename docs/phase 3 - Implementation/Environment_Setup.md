# Environment Setup
### Phase 0 — Full Installation Log and Fixes

---

## Table of Contents

- [[#Platform Constraints|Platform Constraints]]
- [[#Stack Installed|Stack Installed]]
- [[#Installation Steps|Installation Steps]]
- [[#Errors and Fixes|Errors and Fixes]]
- [[#Verification|Verification]]

---

## Platform Constraints

| Constraint | Detail |
|------------|--------|
| OS | Manjaro Linux (kernel 6.12.64) |
| VS Code | Installed as Flatpak — no `sudo`, no `pacman` inside sandbox |
| Root filesystem | 3.8 GB tmpfs — `/tmp` fills instantly with large pip downloads |
| Python | 3.13 — Ryu 4.34 uses APIs removed in 3.10+ |
| Solution | Split setup into two terminals: native (sudo) and VS Code (venv) |

Because VS Code is a Flatpak, any command that needs sudo must be run in the native terminal. `flatpak-spawn --host` was used to bridge between the two environments during setup.

---

## Stack Installed

| Package | Version | How |
|---------|---------|-----|
| Open vSwitch | 3.7.1 | `pacman -S openvswitch` |
| Mininet | 2.3.1b4 | pip + compiled `mnexec` binary |
| Ryu | 4.34 | pip from local patched tarball |
| PyTorch | 2.11.0+cpu | pip from `download.pytorch.org/whl/cpu` |
| Flask | latest | pip |
| NumPy / Pandas / Matplotlib | latest | pip |
| eventlet / flask-socketio | latest | pip |

**Virtual environment:** `.venv/` at project root  
**Activation:** `source .venv/bin/activate`

---

## Installation Steps

### 1. Open vSwitch

```bash
# Native terminal (sudo available)
sudo pacman -S --overwrite "/usr/lib/libatomic*" \
               --overwrite "/usr/lib/libgcc*" \
               --overwrite "/usr/lib/libstdc*" \
               openvswitch

sudo systemctl enable --now ovsdb-server
sudo systemctl enable --now ovs-vswitchd
sudo ovs-vsctl show   # verify
```

The `--overwrite` flags were needed because the AUR `gcc-libs` package conflicted with existing `libgcc/libstdc++` shared objects.

### 2. Mininet

```bash
pip install mininet
# pip's mininet does NOT include the mnexec C binary
# Build it from the AUR source cache:
gcc -o mnexec ~/.cache/yay/mininet/src/mininet-2.3.1b4/mnexec.c -o mnexec
sudo make install-mnexec   # copies to /usr/local/bin
```

### 3. Ryu (patched for Python 3.13)

```bash
# Download tarball manually (pip install ryu would fail)
TMPDIR=/home/stoned/.pip-tmp pip download ryu==4.34 --no-deps -d /home/stoned/.pip-tmp

# Patch 1: collections.Callable → collections.abc.Callable
python3 scripts/patch_ryu.py

# Patch 2: hooks.py get_script_args (removed in setuptools ≥ 74)
# Patch 3: setup.py explicit packages= argument (fixes flat-layout error)
# (both in scripts/patch_ryu.py)

TMPDIR=/home/stoned/.pip-tmp pip install --no-build-isolation \
    /home/stoned/.pip-tmp/ryu-4.34/
```

### 4. PyTorch (CPU-only)

```bash
# Must use custom index — default wheel is 530 MB (fills tmpfs)
# CPU-only wheel is 190 MB
TMPDIR=/home/stoned/.pip-tmp \
  pip install torch --index-url https://download.pytorch.org/whl/cpu \
              --cache-dir /home/stoned/.pip-cache
```

### 5. NOPASSWD sudoers

Added to `/etc/sudoers.d/stoned-dev` (native terminal) to allow passwordless sudo for project-specific commands:

```
stoned ALL=(ALL) NOPASSWD: /usr/bin/pacman, /usr/bin/systemctl, \
    /usr/bin/make, /usr/bin/ovs-vsctl, /usr/sbin/ovs-vswitchd, \
    /usr/sbin/ovsdb-server, /home/stoned/Skills/Projects/2026/EL2k26/.venv/bin/python3
```

---

## Errors and Fixes

### `sudo: command not found` in setup script
VS Code is a Flatpak — no `sudo` inside the sandbox.  
**Fix:** Detect Flatpak via `$FLATPAK_ID`, use `flatpak-spawn --host` for host commands. Split setup into two scripts: `setup_system.sh` (native) and `setup_python.sh` (VS Code).

### `No space left on device` during pip download
Root `/` is a 3.8 GB tmpfs. Pip uses `/tmp` for downloads.  
**Fix:** `TMPDIR=/home/stoned/.pip-tmp pip install ...` — redirects all temp files to home directory.

### `libatomic` conflict when installing OvS
OvS package conflicts with `gcc-libs` libatomic.  
**Fix:** `pacman -S --overwrite "/usr/lib/libatomic*" openvswitch`

### `FileNotFoundError: mnexec` when running Mininet
pip's Mininet package doesn't include the compiled C binary.  
**Fix:** Compiled from AUR source at `~/.cache/yay/mininet/src/`, installed via `sudo make install-mnexec`.

### Interface name `h_emergency-eth0` too long (16 chars, limit 15)
Linux kernel enforces 15-character limit on network interface names.  
**Fix:** Renamed host `h_emergency` → `h_emerg`, constant `IP_EMERGENCY` → `IP_EMERG` in both `constants.py` and `iot_topology.py`.

### 98.9% packet loss in pingall (OVSController fallback)
Two causes: (1) `failMode="secure"` drops all packets without controller flows; (2) S3↔S4 cross-link creates a loop that OVSController cannot handle.  
**Fix:** Parameterised `IoTTopo.build(fail_mode, stp)` — when Ryu is not running, `fail_mode="standalone"` (built-in learning switch) and `stp=True` (Rapid Spanning Tree to break the loop). Wait 35 s for STP convergence before `pingAll`.

### Ryu `easy_install.get_script_args` AttributeError
`setuptools ≥ 74` removed `get_script_args`.  
**Fix:** Patched `ryu/hooks.py` to use `getattr(easy_install, 'get_script_args', None)` — skips gracefully if absent.

### Ryu `collections.Callable` AttributeError (Python 3.10+)
`collections.Callable` was removed in Python 3.10; must use `collections.abc.Callable`.  
**Fix:** `scripts/patch_ryu.py` scans all `.py` files in the ryu package and replaces all removed `collections.*` aliases with their `collections.abc.*` equivalents.

### Ryu flat-layout `Multiple top-level packages discovered` error
`setuptools ≥ 61` rejects packages with multiple top-level directories unless explicitly listed.  
**Fix:** Patched `setup.py` to add `packages=setuptools.find_packages(exclude=['etc', 'etc.*'])`.

---

## Verification

```bash
# OvS running
sudo systemctl is-active ovsdb-server   # → active
sudo systemctl is-active ovs-vswitchd   # → active

# Python imports
source .venv/bin/activate
python3 -c "import torch; print(torch.__version__)"   # → 2.11.0+cpu
python3 -c "import ryu; print('ryu ok')"              # → ryu ok
python3 -c "import flask; print(flask.__version__)"

# Stats collector mock (no Mininet needed)
python3 collector/stats_collector.py --mock --once

# Topology test (native terminal, takes ~40s)
sudo .venv/bin/python3 mininet/iot_topology.py --test
# → *** Results: 0% dropped (90/90 received)
```

See also: [[Topology]] · [[Implementation_Overview]]
