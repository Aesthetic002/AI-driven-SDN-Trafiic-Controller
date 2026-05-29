#!/bin/bash
# Starts OvS services then launches train.py inside a privileged container.
set -e

echo "[entrypoint] Starting Open vSwitch..."
service openvswitch-switch start || true

# Wait for ovsdb-server to be ready. ovs-vsctl only proves the database is up;
# Mininet also needs ovs-vswitchd to apply bridge and port changes.
for i in $(seq 1 10); do
    ovs-vsctl --timeout=5 show &>/dev/null && break
    echo "[entrypoint] Waiting for OvS... ($i/10)"
    sleep 1
done

ovs-vsctl --timeout=5 show &>/dev/null || {
    echo "[entrypoint] ovsdb-server failed to start"
    exit 1
}

if ! pgrep -x ovs-vswitchd >/dev/null; then
    echo "[entrypoint] ovs-vswitchd is not running; starting it manually..."
    ovs-vswitchd unix:/var/run/openvswitch/db.sock \
        --pidfile=/var/run/openvswitch/ovs-vswitchd.pid \
        --detach \
        --log-file=/var/log/openvswitch/ovs-vswitchd.log
fi

pgrep -x ovs-vswitchd >/dev/null || {
    echo "[entrypoint] ovs-vswitchd failed to start"
    tail -n 100 /var/log/openvswitch/ovs-vswitchd.log 2>/dev/null || true
    exit 1
}

# Fail fast if bridge creation cannot complete. Without this, Mininet can block
# indefinitely in net.start() while waiting on OVS operations.
ovs-vsctl --timeout=5 --may-exist add-br ovsprobe || {
    echo "[entrypoint] OvS bridge probe failed"
    tail -n 100 /var/log/openvswitch/ovs-vswitchd.log 2>/dev/null || true
    exit 1
}
ovs-vsctl --timeout=5 --if-exists del-br ovsprobe || true

echo "[entrypoint] OvS ready."

echo "[entrypoint] Cleaning up Mininet..."
mn -c &>/dev/null || true

echo "[entrypoint] Process status:"
ps aux | grep -E "ovs|db"

echo "[entrypoint] Launching train.py..."
exec python3 train.py "$@"
