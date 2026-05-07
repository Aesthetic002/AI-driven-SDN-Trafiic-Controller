# Now: TCP vs UDP (your core question)

---

# 🔹 TCP (Transmission Control Protocol)

> **Reliable, connection-based**

### Features:

- Connection setup (handshake)
- Guaranteed delivery
- Ordered packets
- Retransmission if lost

---

### Example uses:

- Web (HTTP/HTTPS)
- SSH
- File transfer

---

---

# 🔹 UDP (User Datagram Protocol)

> **Fast, connectionless**

### Features:

- No guarantee of delivery
- No ordering
- No retransmission
- Very low overhead

---

### Example uses:

- Video streaming
- VoIP calls
- Gaming
- IoT sensors (like yours)

---

---

# 🎮 In YOUR system

## 🔹 Data plane (IoT traffic)

- Uses **UDP**
- Why?
    - Fast
    - Low overhead
    - Occasional loss is okay

---

## 🔹 Control plane (Ryu ↔ Switch)

- Uses **TCP (port 6633 / 6653)**
- Why?
    - Must be reliable
    - Rules must be installed correctly

---

---

# 🤯 Key Insight

> **Fast ≠ correct**

- UDP → fast but unreliable
- TCP → slower but safe

---

# 🎯 Final one-line answer

> **OpenFlow uses TCP because controller-switch communication must be reliable, while UDP is used for data traffic because it prioritizes speed over reliability.**

---

# 💡 Final mental model

- UDP → “send fast, hope it arrives”
- TCP → “make sure it arrives correctly”