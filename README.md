# Lightning debug board

A carrier board for an eLabGuy Lightning male breakout. Use it to talk to (early)
iPhones from Linux: an FPGA reaches every Lightning signal pin, one USB-C port
programs the FPGA and streams logs, and a second USB-C port passes the phone's
USB through to a host.

KiCad 10 project: `lightning_debug.kicad_pro`.

![3D render, isometric](renders/iso.png)

![3D render, top](renders/top.png)

*Placement only, not routed yet. KiCad's stock libraries have no 3D models for
the HRO USB-C receptacles or the ASE oscillator, so those show only their pads.*

## Architecture

```
 USB-C #1 (debug) ──► FT2232H ──ch.A (MPSSE/SPI)──► W25Q128 flash + iCE40 CRESET/CDONE   (iceprog)
       │                  └────ch.B (UART/MPSSE)──► iCE40UP5K bank 1
       └─ 5V ─► AP2112K 3.3 / 1.2 / 1.8

 USB-C #2 (phone) ─D+/D-─► FSUSB42 mux A ─► Lightning side A L0
                       └─► FSUSB42 mux B ─► Lightning side B L0
                                │ (other mux port = FPGA)
                VBUS2 ─► TPS2065C (FPGA PWR_EN, 1A) ─► Lightning PWR (pins 5/12)

 iCE40 bank 0 (VCCIO0, JP2: 3.3V default / 1.8V): L0 A/B (via the muxes), L1 A/B, EXP0-5
 iCE40 bank 2 (1.8V):                             ID0/ID1 A/B, button, PWR fault, VBUS2 detect, EXP6
 iCE40 bank 1 (3.3V):                             SPI flash, 12 MHz clock, FT2232H ch.B, mux/power control
```

- **Both sides of the plug go to the FPGA.** That's 12 signal lines. Gateware
  handles orientation. GND (pins 1/16) and PWR (pins 5/12) are hard-wired.
- **Lightning pin map** (same on both breakouts). Side A: 1 GND, 2 L0p, 3 L0n,
  4 ID0, 5 PWR, 6 L1n, 7 L1p, 8 ID1. Side B is mirrored, so pin 17‑k carries
  the same signal as pin k (16 GND, 15 L0p, 14 L0n, 13 ID0, 12 PWR, 11 L1n,
  10 L1p, 9 ID1).
- **USB passthrough** keeps the full 480 Mb/s because it goes through analog
  muxes, not the FPGA. Each mux works like this:

  | OE#  | SEL | Lightning L0 connected to |
  |------|-----|---------------------------|
  | 1    | x   | nothing (power-up default: 10k pull-up) |
  | 0    | 0   | FPGA (HSD1, rated for UART/USB) |
  | 0    | 1   | USB-C #2 (HSD2, USB only) |

  Enable at most one mux toward USB-C #2 at a time: the side the phone is touching.
- **Phone power** comes from USB-C #2 VBUS through the load switch. It is off
  by default (100k pull-down on PWR_EN). Close JP1 on 2‑3 instead of 1‑2 to
  power the phone from port 1.
- Series 33Ω resistors sit on every FPGA ↔ Lightning line. Pull-ups on the ID
  lines are footprinted but not fitted.

### Solder jumpers

| JP  | default (1-2) | 2-3 |
|-----|---------------|-----|
| JP1 | phone PWR from USB-C #2 VBUS | from USB-C #1 (+5V) |
| JP2 | bank 0 (lanes) at 3.3V | bank 0 at 1.8V |

## Breakout install points (fit only ONE)

- **J3: APPLE-LM-BO-V1AV** (vertical plug). Top row is pins 1→8, bottom row 9→16.
- **J4: APPLE-LM-BO-V2A** (horizontal plug). Top row is 9→16, bottom row is
  8→1 with pin 1 at the bottom right. The plug hangs 10.7 mm past the board's
  left edge.

The footprints come from the drawings in `docs/` and are seen from the top,
with the breakout's silkscreen readable. **Before ordering, check one against a
real breakout:** print the PCB 1:1 and confirm the pin‑1 square pad position
and the plug direction. Both footprints have M3/M2 NPTH holes that line up with
the breakouts' own holes, for standoffs.

## Software

- Program the flash: `iceprog top.bin` (FT2232H default VID/PID 0403:6010; the
  EEPROM is optional).
- Logs: channel B shows up as `/dev/ttyUSB1`. UART runs up to 12 Mbaud, with
  RTS/CTS on BDBUS2/3. For more bandwidth, put channel B in MPSSE mode (SPI-like,
  30 MHz) on the same 4 pins.
- Pin constraints for nextpnr: `gateware/lightning_debug.pcf`.

## Status / TODO

- [x] Schematic: ERC clean (0 errors, 0 warnings).
- [x] PCB: 80×50 mm, 4 layers (In1 GND, In2 +3V3, B.Cu GND pour). Parts are
      placed and the board matches the schematic, but **nothing is routed yet**.
- [ ] Route. Do USB1/USB2 D± and the L0 lanes first as 90Ω differential pairs.
      Get trace width and gap from your fab's impedance calculator for the real
      stackup (the `USB_HS` netclass is a placeholder). Keep the L0 stubs to
      J3/J4 short.
- [ ] Clean up silkscreen and tidy placement.
- [x] Checked: the iCE40 VCCPLL RC filter (100Ω + 10µ + 100n) is the
      datasheet's recommendation ("RC-based noise filter", TN1252). The RGB
      sink pins are rated 0–3.5 V regardless of VCCIO (unlike normal I/O,
      VCCIO+0.2 V), so 3.3 V LED anodes are fine with bank 0 at 1.8 V.
      VPP_2V5 is at 3.3 V, which the RGB driver and HFOSC require (≥ 2.3 V).

## Ordering (JLCPCB / PCBWay)

```
python3 tools/export_fab.py            # refuses while the board has unrouted nets / DRC errors
python3 tools/export_fab.py --preview  # dry run -> fab/UNROUTED-PREVIEW/ (DO NOT ORDER)
```

When the board is routed and DRC is clean, the script writes `fab/release/`:

| File | JLCPCB | PCBWay |
|------|--------|--------|
| `lightning_debug-gerbers.zip` | "Add gerber file" | "Quick-order PCB" upload |
| `jlcpcb/bom.csv`, `jlcpcb/cpl.csv` | Assembly → BOM / CPL | – |
| `pcbway/bom.csv`, `pcbway/centroid.csv` | – | Assembly → BOM / Centroid |
| `assembly-excluded.txt` | parts you fit yourself (breakout, J5 header, DNP) | same |

PCB options to select:
- 4 layers, 1.6 mm thick, 80 × 50 mm, FR-4, 1 oz outer copper.
- Min track/space 0.15 mm, min via 0.3/0.6 mm. These fit both fabs' standard 4-layer process.
- Impedance control on, for the USB pairs. Choose the fab's stackup (for
  JLCPCB, e.g. JLC04161H-7628), then set the `USB_HS` netclass to the width and
  gap their calculator gives for 90 Ω differential **before routing**.
- Assembly on the top side only. Every SMD part is on top.

Before you pay:
- **Part numbers.** Fill `tools/parts.csv`. JLCPCB uses the `lcsc` column;
  PCBWay uses `manufacturer`/`mpn`. Only FSUSB42MUX → C11355 has been
  verified. Rows without a number have to be matched by hand in the fab's BOM tool.
- **Rotation.** Check part rotation in the fab's placement preview, especially
  for the QFNs, SOT-23s, SOICs and USB-C connectors. KiCad's zero orientation
  and JLCPCB/PCBWay's don't always agree, and both let you fix it in their viewer.
- **Origin.** CPL coordinates use the board's bottom-left corner as origin
  (drill/place origin), with Y pointing up.

## Regenerating

The KiCad files were bootstrapped by scripts in `tools/`. You can edit the
schematic and PCB in KiCad directly. If you'd rather keep everything in the
scripts:

```
python3 tools/gen_symlib.py && python3 tools/gen_footprints.py
python3 tools/gen_schematic.py && kicad-cli sch upgrade lightning_debug.kicad_sch
kicad-cli sch export netlist --format kicadxml -o /tmp/net.xml lightning_debug.kicad_sch
python3 tools/gen_pcb.py /tmp/net.xml        # WARNING: overwrites the PCB (placement/routing)
```

Refresh the 3D renders:

```
kicad-cli pcb render -o renders/top.png --side top --quality high --background opaque -w 1600 -h 1000 --zoom 1.1 lightning_debug.kicad_pcb
kicad-cli pcb render -o renders/iso.png --quality high --background opaque --perspective --rotate '-50,0,-30' -w 1600 -h 1000 --zoom 0.9 lightning_debug.kicad_pcb
```
