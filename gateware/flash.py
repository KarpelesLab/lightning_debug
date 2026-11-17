#!/usr/bin/env python3
"""Flash a bitstream to the board without iceprog (pip install pyftdi):  python3 gateware/flash.py selftest.bin"""
# Program the W25Q128 on the Lightning debug board via FT2232H port A (iceprog pinout),
# verify by readback, then release CRESET and report CDONE.
import sys, time
from pyftdi.spi import SpiController
data = open(sys.argv[1], 'rb').read()
spi = SpiController(cs_count=1)
spi.configure('ftdi://0x0403:0x6010/1', frequency=6e6)
gpio = spi.get_gpio(); port = spi.get_port(0)
CS, CDONE, CRESET = 1 << 4, 1 << 6, 1 << 7
gpio.set_direction(CS | CDONE | CRESET, CS | CRESET)
gpio.write(CS); time.sleep(0.01)                      # FPGA held in reset
def cmd(tx, n=0):
    gpio.write(0); r = port.exchange(bytes(tx), n, start=False, stop=False); gpio.write(CS); return r
def wait():
    while cmd([0x05], 1)[0] & 1: time.sleep(0.001)
cmd([0xAB]); time.sleep(0.001)
assert cmd([0x9F], 3) == b'\xef\x40\x18', "flash ID mismatch"
for a in range(0, len(data), 0x10000):                # 64 KiB block erase
    cmd([0x06]); cmd([0xD8, a >> 16, (a >> 8) & 255, 0]); wait()
for a in range(0, len(data), 256):                    # page program
    cmd([0x06]); cmd(bytes([0x02, a >> 16, (a >> 8) & 255, 0]) + data[a:a + 256]); wait()
rb = bytearray()
for a in range(0, len(data), 4096):
    rb += cmd([0x03, a >> 16, (a >> 8) & 255, a & 255], min(4096, len(data) - a))
print("verify:", "OK" if rb == data else f"FAIL at {next(i for i in range(len(data)) if rb[i] != data[i])}", f"({len(data)} bytes)")
gpio.write(CS | CRESET)                               # release: FPGA boots from flash
t = time.time()
while not gpio.read() & CDONE and time.time() - t < 1: time.sleep(0.005)
print(f"CDONE={int(bool(gpio.read() & CDONE))} after {time.time() - t:.3f} s")
spi.terminate()
