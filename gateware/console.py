#!/usr/bin/env python3
"""Send keys to the self-test console and print replies (pip install pyserial):  python3 gateware/console.py s"""
import serial, sys, time
s = serial.Serial('/dev/ttyUSB1', 115200, timeout=0.3)
s.reset_input_buffer()
for k in sys.argv[1]:
    s.write(k.encode()); time.sleep(0.1)
    print(repr(k), '->', s.read(64).decode(errors='replace').strip())
