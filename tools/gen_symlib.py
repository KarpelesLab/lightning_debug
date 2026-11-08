#!/usr/bin/env python3
"""Generate the project symbol library (lightning_debug.kicad_sym)."""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "lightning_debug.kicad_sym")

# Lightning plug pinout on the eLabGuy breakouts (side B mirrored: pin 17-k == pin k)
SIDE_A = {1: "GND", 2: "A_L0P", 3: "A_L0N", 4: "A_ID0", 5: "PWR", 6: "A_L1N", 7: "A_L1P", 8: "A_ID1"}
SIDE_B = {17 - k: n.replace("A_", "B_") for k, n in SIDE_A.items()}

def ptype(name):
    return "power_in" if name in ("GND", "PWR") else "passive"

def pin(num, name, x, y, ang):
    return (f'\t\t\t(pin {ptype(name)} line (at {x} {y} {ang}) (length 5.08)\n'
            f'\t\t\t\t(name "{name}" (effects (font (size 1.27 1.27))))\n'
            f'\t\t\t\t(number "{num}" (effects (font (size 1.27 1.27))))\n\t\t\t)\n')

pins = ""
for r in range(8):
    y = 10.16 - r * 2.54
    pins += pin(r + 1, SIDE_A[r + 1], -15.24, round(y, 2), 0)
    pins += pin(16 - r, SIDE_B[16 - r], 15.24, round(y, 2), 180)
# GND/PWR are repeated on both sides; make the symbol pins passive so they can be stacked nets
pins = pins.replace("power_in", "passive")

txt = f'''(kicad_symbol_lib
\t(version 20251024)
\t(generator "lightning_debug_gen")
\t(symbol "Lightning_Breakout"
\t\t(pin_names (offset 1.016))
\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)
\t\t(property "Reference" "J" (at 0 13.97 0) (effects (font (size 1.27 1.27))))
\t\t(property "Value" "Lightning_Breakout" (at 0 -10.16 0) (effects (font (size 1.27 1.27))))
\t\t(property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
\t\t(property "Description" "eLabGuy APPLE-LM-BO Lightning male breakout (2x 1x8 2.54mm rows, 15.24mm apart). Pins 1-8 = plug side A, 9-16 = side B (mirrored: pin 17-k = pin k)" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))
\t\t(symbol "Lightning_Breakout_0_1"
\t\t\t(rectangle (start -10.16 12.7) (end 10.16 -8.89) (stroke (width 0.254) (type default)) (fill (type background)))
\t\t\t(text "side A" (at -5.08 -7.62 0) (effects (font (size 1.016 1.016))))
\t\t\t(text "side B" (at 5.08 -7.62 0) (effects (font (size 1.016 1.016))))
\t\t)
\t\t(symbol "Lightning_Breakout_1_1"
{pins}\t\t)
\t\t(embedded_fonts no)
\t)
)
'''
open(OUT, "w").write(txt)
print("wrote", OUT)
