#!/bin/bash
# Starts OvS services then launches train.py inside a privileged container.
set -e

echo "[entrypoint] Starting Open vSwitch..."
service openvswitch-switch start

# Wait for OvS to be ready
for i in $(seq 1 10); do
    ovs-vsctl show &>/dev/null && break
    echo "[entrypoint] Waiting for OvS... ($i/10)"
    sleep 1
done

ovs-vsctl show &>/dev/null || { echo "[entrypoint] OvS failed to start"; exit 1; }
echo "[entrypoint] OvS ready."

echo "[entrypoint] Launching train.py..."
exec python3 train.py "$@"
