#!/usr/bin/env python3
"""Generate footprints for the two eLabGuy Lightning breakouts (from docs/*Drawing*.pdf).

Coordinates are viewed from the TOP of our board, with the breakout's
component side (silkscreen numbers readable) facing up, exactly like the drawings.
Origin = breakout pin 1.
"""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "lightning_debug.pretty")
os.makedirs(OUT, exist_ok=True)
P = 2.54
ROW = 15.24  # row spacing on both breakouts


def f(v):
    return ("%.4f" % v).rstrip("0").rstrip(".")


def line(x1, y1, x2, y2, layer, w):
    return f'\t(fp_line (start {f(x1)} {f(y1)}) (end {f(x2)} {f(y2)}) (stroke (width {w}) (type solid)) (layer "{layer}"))\n'


def rect(x1, y1, x2, y2, layer, w, fill=False):
    return (f'\t(fp_rect (start {f(x1)} {f(y1)}) (end {f(x2)} {f(y2)}) (stroke (width {w}) (type solid)) '
            f'(fill {"yes" if fill else "no"}) (layer "{layer}"))\n')


def text(kind, val, x, y, layer, size=1.0, hide=False):
    h = " (hide yes)" if hide else ""
    if kind in ("reference", "value"):
        return (f'\t(property "{kind.capitalize()}" "{val}" (at {f(x)} {f(y)} 0) (layer "{layer}"){h}\n'
                f'\t\t(effects (font (size {size} {size}) (thickness {f(size*0.15)}))))\n')
    return (f'\t(fp_text user "{val}" (at {f(x)} {f(y)} 0) (layer "{layer}")\n'
            f'\t\t(effects (font (size {size} {size}) (thickness {f(size*0.15)}))))\n')


def pad(num, x, y):
    shape = "rect" if num == 1 else "circle"
    return (f'\t(pad "{num}" thru_hole {shape} (at {f(x)} {f(y)}) (size 1.7 1.7) (drill 1.0) '
            f'(layers "*.Cu" "*.Mask"))\n')


def npth(x, y, d):
    return (f'\t(pad "" np_thru_hole circle (at {f(x)} {f(y)}) (size {d} {d}) (drill {d}) '
            f'(layers "*.Cu" "*.Mask"))\n')


def write(name, descr, body):
    s = (f'(footprint "{name}"\n\t(version 20241229)\n\t(generator "lightning_debug_gen")\n'
         f'\t(layer "F.Cu")\n\t(descr "{descr}")\n\t(tags "lightning breakout elabguy")\n'
         f'\t(attr through_hole)\n' + body + ')\n')
    open(os.path.join(OUT, name + ".kicad_mod"), "w").write(s)
    print("wrote", name)


# ---------------- APPLE-LM-BO-V1AV (vertical plug, 1.6mm PCB) -----------------
# Top row: pins 1..8 left->right. Bottom row: 9..16 left->right.
# Board 20.32 x 17.78, pins centred. 2x dia 3mm holes, 3mm from left/right edge, on centre line.
b = ""
x0, y0, x1, y1 = -1.27, -1.27, -1.27 + 20.32, -1.27 + 17.78
b += text("reference", "REF**", 8.89, -2.6, "F.SilkS")
b += text("value", "APPLE-LM-BO-V1AV", 8.89, 3.2, "F.Fab", 0.8)
b += text("user", "V1AV vertical", 8.89, 12.2, "F.SilkS", 0.8)
b += text("user", "${REFERENCE}", 8.89, 10.6, "F.Fab", 0.8)
b += rect(x0, y0, x1, y1, "F.Fab", 0.1)
b += rect(x0 - 0.12, y0 - 0.12, x1 + 0.12, y1 + 0.12, "F.SilkS", 0.12)
b += rect(x0 - 0.25, y0 - 0.25, x1 + 0.25, y1 + 0.25, "F.CrtYd", 0.05)
# plug (vertical, sticks up out of the breakout), centre of board
cx, cy = 8.89, 7.62
b += rect(cx - 3.9, cy - 0.8, cx + 3.9, cy + 0.8, "F.Fab", 0.1)
b += rect(cx - 3.9, cy - 0.8, cx + 3.9, cy + 0.8, "F.SilkS", 0.12)
b += text("user", "PLUG UP", cx, cy + 2.0, "F.Fab", 0.7)
# pin-1 marker
b += line(-1.6, -1.6, -1.6, 0.6, "F.SilkS", 0.12)
b += line(-1.6, -1.6, 0.6, -1.6, "F.SilkS", 0.12)
for i in range(8):
    b += pad(1 + i, i * P, 0)
    b += pad(9 + i, i * P, ROW)
b += npth(-1.27 + 3.0, cy, 3.2)
b += npth(x1 - 3.0, cy, 3.2)
write("eLabGuy_APPLE-LM-BO-V1AV",
      "eLabGuy APPLE-LM-BO-V1AV vertical Lightning male breakout, 2x 1x8 P2.54 rows 15.24mm apart, 2x M3 (NPTH 3.2) holes", b)

# ---------------- APPLE-LM-BO-V2A (horizontal edge plug, 0.8mm PCB) ------------
# Plug overhangs the LEFT edge of the breakout by 10.7mm.
# Top row: pins 9..16 left->right. Bottom row: pins 8..1 left->right (pin 1 bottom right).
b = ""
x0, y0 = -7 * P - 1.27, -ROW - 1.27
x1, y1 = x0 + 20.32, y0 + 17.78
b += text("reference", "REF**", -8.89, 2.6, "F.SilkS")
b += text("value", "APPLE-LM-BO-V2A", -8.89, -12.2, "F.Fab", 0.8)
b += text("user", "V2A edge", -13.5, -7.62, "F.SilkS", 0.8)
b += text("user", "${REFERENCE}", -3.8, -7.62, "F.Fab", 0.8)
b += rect(x0, y0, x1, y1, "F.Fab", 0.1)
b += rect(x0 - 0.12, y0 - 0.12, x1 + 0.12, y1 + 0.12, "F.SilkS", 0.12)
# plug: 10.7mm overhang to the left, centred vertically
cy = -ROW / 2
b += rect(x0 - 10.7, cy - 3.3, x0 - 2.6, cy + 3.3, "F.Fab", 0.1)      # boot
b += rect(x0 - 2.6, cy - 5.2, x0 - 1.5, cy + 5.2, "F.Fab", 0.1)       # flange
b += text("user", "PLUG", x0 - 6.5, cy, "F.Fab", 0.8)
# board-edge hint: plug side must hang past our board edge
b += line(x0 - 10.7, cy - 5.4, x0 - 10.7, cy + 5.4, "F.SilkS", 0.12)
b += text("user", "<- board edge here", x0 + 6, y1 + 1.6 - 19.4, "F.Fab", 0.6)
b += rect(x0 - 10.95, min(y0, cy - 5.45) - 0.25, x1 + 0.25, y1 + 0.25, "F.CrtYd", 0.05)
# pin-1 marker (bottom right)
b += line(1.6, 1.6, 1.6, -0.6, "F.SilkS", 0.12)
b += line(1.6, 1.6, -0.6, 1.6, "F.SilkS", 0.12)
for k in range(1, 9):
    b += pad(k, -(k - 1) * P, 0)
for j in range(8):
    b += pad(9 + j, x0 + 1.27 + j * P, -ROW)
b += npth(x0 + 10.16, y0 + 6.2, 2.2)
b += npth(x0 + 10.16, y1 - 6.2, 2.2)
write("eLabGuy_APPLE-LM-BO-V2A",
      "eLabGuy APPLE-LM-BO-V2A horizontal Lightning male breakout (plug overhangs left edge 10.7mm), 2x 1x8 P2.54 rows 15.24mm apart, 2x M2 (NPTH 2.2) holes", b)
