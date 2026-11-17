#!/usr/bin/env python3
"""Decode 8N1 UART from an idcap.v raw capture.  python3 uartdec.py cap.bin [line] [baud]"""
import sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from idcap import events, NAMES, TICK

buf = open(sys.argv[1], "rb").read()
line = sys.argv[2] if len(sys.argv) > 2 else "L1B_P"
baud = float(sys.argv[3]) if len(sys.argv) > 3 else 115200
k = 7 - NAMES.index(line)
# edge list for the line: (t_seconds, level after edge)
edges, t, prev = [], 0, None
for s, d in events(buf):
    t += d
    lv = (s >> k) & 1
    if prev is None or lv != prev:
        edges.append((t * TICK, lv))
    prev = lv
bit = 1 / baud
def level_at(x, i):
    while i + 1 < len(edges) and edges[i + 1][0] <= x:
        i += 1
    return edges[i][1], i
out, i, j = bytearray(), 0, 0
errors = 0
while j < len(edges):
    tf, lv = edges[j]
    if lv != 0:
        j += 1
        continue
    # start bit at tf
    b, idx = 0, j
    for n in range(8):
        v, idx = level_at(tf + (1.5 + n) * bit, idx)
        b |= v << n
    stop, idx = level_at(tf + 9.5 * bit, idx)
    if not stop:
        errors += 1
    out.append(b)
    # next start bit: first falling edge after the stop bit's middle
    end = tf + 9.5 * bit
    j = idx
    while j < len(edges) and (edges[j][0] <= end or edges[j][1] != 0):
        j += 1
print(f"# {len(out)} bytes, {errors} framing errors", file=sys.stderr)
sys.stdout.buffer.write(bytes(out))
