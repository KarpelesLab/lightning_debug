#!/usr/bin/env python3
"""Decode Lightning ID (SDQ-style) traffic from an idcap.v raw capture.

    python3 gateware/sdq.py capture.bin [line]      line = A_ID0 (default B_ID0) ...
Idle high; each bit is a low pulse on a ~10 us period: short (~1.7 us) = 1,
long (~7 us) = 0, LSB first; a long low (>11 us) is a break that starts a transaction.
"""
import sys, collections
sys.path.insert(0, __import__("os").path.dirname(__file__))
from idcap import events, NAMES, TICK

buf = open(sys.argv[1], "rb").read()
line = sys.argv[2] if len(sys.argv) > 2 else "B_ID0"
k = 7 - NAMES.index(line)
t, prev, fall = 0, None, None
others = collections.Counter()
lows = []                                   # (t_fall_us, low_us)
for s, d in events(buf):
    t += d
    if prev is not None:
        ch = s ^ prev
        for j, n in enumerate(NAMES):
            if (ch >> (7 - j)) & 1 and n != line:
                others[n] += 1
        if (ch >> k) & 1:
            if not (s >> k) & 1:
                fall = t
            elif fall is not None:
                lows.append((fall * TICK * 1e6, (t - fall) * TICK * 1e6))
    prev = s
print("edges on other lines:", dict(others) or "none")
txs, cur, last = [], None, None
for tf, lw in lows:
    if lw > 11:
        cur = {"t": tf, "break": lw, "bits": [], "gaps": []}
        txs.append(cur)
    elif cur is not None:
        if cur["bits"]:
            cur["gaps"].append(tf - last)
        cur["bits"].append(1 if lw < 4 else 0)
    last = tf
pat = collections.Counter()
for tx in txs:
    b = tx["bits"]
    # split into bytes; a bigger gap between pulses marks a byte boundary (and a turnaround)
    by, cur8 = [], []
    for i, bit in enumerate(b):
        if i and tx["gaps"][i - 1] > 14 and cur8:
            by.append(cur8); cur8 = []
        cur8.append(bit)
    by.append(cur8)
    s = " ".join(f"{sum(v << j for j, v in enumerate(x)):02x}" + ("" if len(x) == 8 else f"/{len(x)}b") for x in by)
    pat[s] += 1
    tx["s"] = s
for tx in txs[:5]:
    print(f"{tx['t'] / 1e3:10.3f} ms  break {tx['break']:.2f} us  {tx['s']}")
print("distinct transactions:")
for s, n in pat.most_common():
    print(f"  {n:5} x  {s}")
if len(txs) > 1:
    iv = [b["t"] - a["t"] for a, b in zip(txs, txs[1:])]
    print(f"repeat interval: min {min(iv)/1e3:.2f} ms, median {sorted(iv)[len(iv)//2]/1e3:.2f} ms")
