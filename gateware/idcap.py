#!/usr/bin/env python3
"""Read idcap.v's event stream from /dev/ttyUSB1 (12 Mbaud) and print the edges.

    python3 gateware/idcap.py [seconds] [--raw out.bin]
"""
import sys, time


NAMES = ["A_ID0", "A_ID1", "B_ID0", "B_ID1", "L1A_P", "L1A_N", "L1B_P", "L1B_N"]
TICK = 1 / 12e6


def events(buf):
    i = 0
    while i + 4 <= len(buf):
        if not buf[i] & 0x80 or any(b & 0x80 for b in buf[i + 1:i + 4]):
            i += 1
            continue
        b0, b1, b2, b3 = buf[i:i + 4]
        s = ((b0 & 0x7F) << 1) | ((b1 >> 6) & 1)
        d = ((b1 & 0x3F) << 14) | (b2 << 7) | b3
        yield s, d
        i += 4


def main():
    secs = float(next((a for a in sys.argv[1:] if not a.startswith("-") and a.replace(".", "").isdigit()), 5))
    import serial
    port = serial.Serial("/dev/ttyUSB1", 12_000_000, timeout=0.1)
    port.reset_input_buffer()
    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < secs:
        buf += port.read(65536)
    if "--raw" in sys.argv:
        open(sys.argv[sys.argv.index("--raw") + 1], "wb").write(buf)
    t, prev = 0, None
    for s, d in events(buf):
        t += d
        if prev is None:
            print(f"{t * TICK * 1e3:12.4f} ms  start  " + " ".join(f"{n}={(s >> (7 - k)) & 1}" for k, n in enumerate(NAMES)))
        elif s != prev:
            ch = [n + ("↑" if (s >> (7 - k)) & 1 else "↓") for k, n in enumerate(NAMES) if ((s ^ prev) >> (7 - k)) & 1]
            print(f"{t * TICK * 1e3:12.4f} ms  +{d * TICK * 1e6:9.2f} us  {' '.join(ch)}")
        prev = s
    print(f"# {len(buf)} bytes, {t * TICK:.3f} s covered")


if __name__ == "__main__":
    main()
