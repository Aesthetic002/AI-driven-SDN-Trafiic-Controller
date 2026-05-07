# Troubleshooting
### Every error encountered during development and its fix

---

## Table of Contents

- [[#Setup Errors|Setup Errors]]
- [[#Ryu Startup Errors|Ryu Startup Errors]]
- [[#Mininet Errors|Mininet Errors]]
- [[#Training Errors|Training Errors]]
- [[#API and Dashboard Errors|API and Dashboard Errors]]
- [[#OvS Errors|OvS Errors]]
- [[#Cleanup Procedures|Cleanup Procedures]]

---

## Setup Errors

### `sudo: command not found` in VS Code terminal

**Cause:** VS Code is installed as a Flatpak. Flatpak processes run in a sandbox where `sudo` is not available.

**Fix:** Always run `sudo` commands in a **native terminal** (Konsole, xterm, etc.), not in VS Code's integrated terminal. For VS Code tasks that need host access, use `flatpak-spawn --host sudo <command>`.

---

### `No space left on device` during pip install

**Cause:** Pip uses `/tmp` for temporary download files. The root filesystem is a small tmpfs.

**Fix:** Set `TMPDIR` to a path with more space:
```bash
TMPDIR=/home/stoned/.pip-tmp pip install <package>
```

---

### `libatomic` conflict when installing Open vSwitch

**Cause:** OvS package conflicts with `gcc-libs` over `libatomic.so`.

**Fix:**
```bash
sudo pacman -S --overwrite "/usr/lib/libatomic*" \
               --overwrite "/usr/lib/libgcc*" \
               --overwrite "/usr/lib/libstdc*" \
               openvswitch
```

---

### `FileNotFoundError: [Errno 2] No such file or directory: 'mnexec'`

**Cause:** pip's `mininet` package installs the Python code but not the `mnexec` C binary that Mininet uses to run processes in namespaces.

**Fix:**
```bash
# Find the source in the AUR cache
ls ~/.cache/yay/mininet/src/mininet-*/mnexec.c

# Compile and install
gcc ~/.cache/yay/mininet/src/mininet-2.3.1b4/mnexec.c -o /tmp/mnexec
sudo cp /tmp/mnexec /usr/local/bin/mnexec
sudo chmod +x /usr/local/bin/mnexec
```

---

### Interface name too long (Mininet crash)

**Cause:** Linux enforces a 15-character limit on network interface names. Older versions of this project used `h_emergency` which created interfaces named `h_emergency-eth0` (17 chars).

**Fix (already applied):** Host renamed to `h_emerg` in both `constants.py` and `mininet/iot_topology.py`. If you see this error in your own topology, shorten the host name.

---

## Ryu Startup Errors

### `FileNotFoundError: ryu-manager`

**Cause:** `pip install ryu` installs the Python package but does not always generate the `ryu-manager` entry-point script.

**Fix:** Use the module directly:
```bash
python3 -m ryu.cmd.manager controller/ryu_controller.py
```

`train.py` already uses this form — it should never call `ryu-manager` directly.

---

### `AttributeError: collections.Callable` (or any `collections.*`)

**Cause:** Python 3.10+ moved these abstract base classes to `collections.abc`. Ryu 4.34 was written for Python 3.9.

**Fix:**
```bash
python3 scripts/patch_ryu.py
```

Run once after installing or reinstalling Ryu.

---

### `ImportError: cannot import name 'ALREADY_HANDLED' from 'eventlet.wsgi'`

**Cause:** Newer versions of eventlet removed `ALREADY_HANDLED` from `eventlet.wsgi`.

**Fix (already applied):** `scripts/patch_ryu.py` patches `ryu/app/wsgi.py`:
```python
try:
    from eventlet.wsgi import ALREADY_HANDLED as _ALREADY_HANDLED
except ImportError:
    _ALREADY_HANDLED = []
```

If you see this error after reinstalling eventlet or ryu, re-run `python3 scripts/patch_ryu.py`.

---

### `AttributeError: 'easy_install' object has no attribute 'get_script_args'`

**Cause:** setuptools ≥ 74 removed `easy_install.get_script_args` which Ryu's setup hooks use.

**Fix:** Already handled by `scripts/patch_ryu.py` (patches `ryu/hooks.py`). Re-run the patch script if you see this after a `pip install --upgrade setuptools`.

---

### `Multiple top-level packages discovered` during Ryu install

**Cause:** setuptools ≥ 61 rejects packages with multiple top-level directories unless `packages=` is explicitly specified in `setup.py`.

**Fix (already applied in patch script):** Adds `packages=setuptools.find_packages(exclude=['etc', 'etc.*'])` to Ryu's `setup.py` before installing.

---

### Ryu connects but no FlowMods installed (switches in fallback mode)

**Cause:** `failMode="secure"` drops all packets until the controller installs rules. If Ryu crashes after switch connection but before installing table-miss rules, the switch goes silent.

**Fix:** Restart Ryu. When it reconnects, `switch_features_handler` re-installs all static rules on all connected switches.

---

## Mininet Errors

### `98.9% packet loss` in `pingall` (standalone test)

**Cause:** Two causes:
1. `failMode="secure"` drops packets without controller flows
2. S3↔S4 cross-link creates a broadcast loop that OVSController cannot handle

**Fix:** The topology falls back automatically to OVSController + STP when Ryu is not reachable:
```
failMode="standalone" + stp=True
Wait 35s for STP convergence
Then run pingAll
```

If running `--test` manually:
```bash
# Make sure Ryu is NOT running, then:
sudo .venv/bin/python3 mininet/iot_topology.py --test
# Waits 35s automatically for STP
```

---

### `sch_htb: quantum of class 50001 is big` (many lines in terminal)

**Cause:** Harmless warning from the Linux `tc` traffic shaper. Appears when link bandwidth is high (the 1 Gbps S5→server links). The warning means the per-class quantum was capped to a safe value.

**Fix:** None needed. Ignore the warnings — links work correctly.

---

### Mininet crash leaves stale bridges/interfaces

After a crash (not a clean `Ctrl-C`), Mininet may leave OvS bridges and virtual interfaces behind. Subsequent runs fail with "bridge already exists" or "interface already up".

**Fix:**
```bash
# Clean all Mininet state
sudo mn -c

# If mn -c does not remove all bridges:
sudo ovs-vsctl list-br | xargs -r -I{} sudo ovs-vsctl del-br {}

# Verify clean state
sudo ovs-vsctl show   # should show empty or only non-Mininet bridges
```

---

### `ImportError: cannot import 'iot_topology' from 'mininet'`

**Cause:** Python resolves `from mininet.iot_topology import build_net` as a submodule of pip's `mininet` package, not the project's `mininet/` folder.

**Fix (already applied in train.py):**
```python
sys.path.insert(0, os.path.join(ROOT, "mininet"))
from iot_topology import build_net   # now finds project/mininet/iot_topology.py
```

---

## Training Errors

### Weights never saved in short runs

**Cause (historical, fixed):** The original code saved weights only every `SAVE_EVERY=200` gradient steps. Short runs (< 200 flows) never reached that threshold.

**Fix (applied):** Weights are now saved every stats cycle (every 2 seconds), unconditionally. The `SAVE_EVERY` constant is no longer used for the save trigger.

---

### `RuntimeError: Expected all tensors to be on the same device`

**Cause:** A tensor was created on CPU and another on GPU (or vice versa). This project always uses `DEVICE = torch.device("cpu")` — all tensors must be on CPU.

**Fix:** Ensure `device=DEVICE` is passed when creating tensors, and `.to(DEVICE)` is called on the model. The existing code does this correctly; check for manual tensor creation in custom reward functions.

---

### Loss is `None` after many gradient steps

**Cause:** Replay buffer has fewer than `BATCH_SIZE=64` transitions. This happens in very short runs or when no flows are generated.

**Fix:** Check that:
1. Traffic scenario is running (not stuck in setup)
2. Mininet hosts are sending traffic (check scenario_runner logs)
3. Ryu is receiving PacketIn events (check `[ryu]` log lines)

---

### `pickle.UnpicklingError` when loading replay buffer

**Cause:** Buffer file is corrupted — likely from a crash during a write.

**Fix:**
```bash
rm /tmp/sdn_replay_buffer.pkl
# Buffer will rebuild from scratch in the next run
```

The buffer uses atomic writes (`.tmp` + `os.replace()`) to prevent this in normal operation, but a power loss mid-write can still cause it.

---

## API and Dashboard Errors

### `localhost:5000` shows "Not Found"

**Cause (historical, fixed):** The Flask app had no root route (`/`). Any request to `/` returned 404.

**Fix (applied):** Root route now returns an HTML index page listing all endpoints.

---

### Dashboard shows "OFFLINE" badge

**Cause:** The SSE connection to `http://localhost:5000/api/stream` failed.

**Check list:**
1. Is Flask running? `curl http://localhost:5000/api/agent`
2. Is CORS enabled? It is (`flask_cors.CORS(app)` — allows any origin)
3. Is the port different? Default is 5000; check `constants.py`

---

### API returns zeros for all state features

**Cause:** Flask is running but Ryu has not written `/tmp/sdn_runtime_state.json` yet (or it does not exist).

**Expected:** On startup, `shared_state` initialises all values to 0.0. The file pump will update them within 1–2 seconds of Ryu's first stats cycle.

**If it persists:** Check that Ryu is running and writing the file:
```bash
ls -la /tmp/sdn_runtime_state.json
cat /tmp/sdn_runtime_state.json | python3 -m json.tool
```

---

### Dashboard topology graph is empty

**Cause:** The `/api/topology` endpoint returned an empty or null response.

**Fix:** This is static data defined in `api/app.py`. If it is missing, Flask is not running — check `curl http://localhost:5000/api/topology`.

---

## OvS Errors

### `ovs-vsctl: unix:/usr/local/var/run/openvswitch/db.sock: Failed to connect`

**Cause:** `ovsdb-server` is not running.

**Fix:**
```bash
sudo systemctl start ovsdb-server
sudo systemctl start ovs-vswitchd
sudo ovs-vsctl show   # verify
```

---

### OvS service not starting after reboot

**Cause:** Services not enabled for auto-start.

**Fix:**
```bash
sudo systemctl enable --now ovsdb-server ovs-vswitchd
```

---

## Cleanup Procedures

### Full clean slate (after any crash)

```bash
# 1. Kill any leftover processes
sudo pkill -f "ryu.cmd.manager" 2>/dev/null
sudo pkill -f "iot_topology" 2>/dev/null
sudo pkill -f "scenario_runner" 2>/dev/null

# 2. Clean Mininet state
sudo mn -c

# 3. Verify OvS is clean
sudo ovs-vsctl show

# 4. (Optional) Remove saved state
rm -f model_weights.pth /tmp/sdn_replay_buffer.pkl /tmp/sdn_runtime_state.json
```

### Reset training only (keep environment)

```bash
rm -f model_weights.pth /tmp/sdn_replay_buffer.pkl
```

### Check what's running

```bash
pgrep -a python3
# Look for: ryu.cmd.manager, iot_topology, api/app.py, scenario_runner
```

See also: [[How_To_Run]] · [[Environment_Setup]] · [[Architecture]]
