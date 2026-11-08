#!/usr/bin/env python3
"""Build lightning_debug.kicad_pcb from the schematic netlist (placement only, unrouted).

Usage: python3 tools/gen_pcb.py <netlist.xml>
(netlist from: kicad-cli sch export netlist --format kicadxml lightning_debug.kicad_sch)
"""
import math
import os
import sys
import xml.etree.ElementTree as ET

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(PROJ, "lightning_debug.kicad_pcb")
FPDIRS = {"lightning_debug": os.path.join(PROJ, "lightning_debug.pretty")}
SYSFP = "/usr/share/kicad/footprints"

# Board outline (mm)
BX0, BY0, BX1, BY1 = 100.0, 100.0, 180.0, 150.0

MM = pcbnew.FromMM


def V(x, y):
    return pcbnew.VECTOR2I(MM(x), MM(y))


# Fixed placement: ref -> (x, y, rot, side)
FIXED = {
    # Lightning breakouts. J4 (V2A): breakout left edge flush with board left edge,
    # plug overhangs the board. J3 (V1AV): vertical plug, next to it.
    "J4": (BX0 + 19.05 + 0.6, 139.0, 0),
    "J3": (125.0, 123.5, 0),
    # USB-C #2 on top edge (opening up), USB-C #1 on right edge (opening right)
    "J2": (122.0, BY0 + 3.65, 180),
    "J1": (BX1 - 3.65, 127.0, 90),
    "U9": (122.0, 112.0, 90),      # ESD port 2, flow-through (vertical)
    # muxes sit right above the L0 pins they serve: B -> J4 top row, A -> J3 top row.
    # D+/D- (pins 3/4) face the connector, HSD1/HSD2 face the USB2 pair between them.
    "U11": (115.5, 117.5, 0),      # mux side B
    "U10": (128.5, 117.5, 180),    # mux side A
    "U12": (104.5, 110.0, 0),      # load switch
    "JP1": (104.5, 116.0, 0),
    # FPGA rotated: lanes (pins 25-36) face the connectors, UART (9-12) faces the FT2232H
    "U7": (150.0, 118.0, 180),
    "U8": (151.5, 106.5, 0),       # flash, above the FPGA config pins (14-17)
    "X1": (143.0, 108.5, 0),       # 12MHz osc, near CLK pin 20
    "JP2": (139.0, 104.5, 0),
    # FT2232H rotated: USB pins 7/8 line up with J1's D+/D- pads, ch.B faces the FPGA
    "U5": (161.3, 126.5, 180),
    "U1": (168.8, 127.0, 0),       # ESD port 1, flow-through between J1 and U5
    "Y1": (168.5, 135.5, 0),
    "U6": (161.5, 139.5, 90),      # EEPROM
    "U2": (158.5, 103.5, 0),
    "U3": (164.5, 103.5, 0),
    "U4": (170.5, 103.5, 0),
    "J5": (140.0, 146.5, 90),      # EXP header along bottom edge
    "SW1": (130.0, 145.5, 0),
    "H1": (103.5, 103.5, 0),
    "H2": (176.5, 103.5, 0),
    "H3": (103.5, 146.5, 0),
    "H4": (176.5, 146.5, 0),
}
# Passives placed next to a specific pad: ref -> (anchor ref, pad number). Placed in this order.
PREFER = {
    # FT2232H
    "C10": ("U5", "12"), "C11": ("U5", "37"), "C12": ("U5", "64"), "C9": ("U5", "49"),
    "C8": ("U5", "50"), "C16": ("U5", "20"), "C17": ("U5", "31"), "C18": ("U5", "42"),
    "C19": ("U5", "56"), "C14": ("U5", "4"), "C15": ("U5", "9"), "C13": ("U5", "4"),
    "FB1": ("U5", "9"), "R4": ("U5", "6"), "R5": ("U5", "14"),
    "C20": ("Y1", "1"), "C21": ("Y1", "3"),
    "R6": ("U6", "1"), "R7": ("U6", "2"), "R8": ("U6", "3"), "R9": ("U6", "4"),
    # FPGA
    "C23": ("U7", "29"), "C22": ("U7", "29"), "R10": ("U7", "29"),
    "C25": ("U7", "5"), "C26": ("U7", "30"), "C24": ("U7", "5"),
    "C28": ("U7", "33"), "C27": ("U7", "33"), "C29": ("U7", "22"), "C30": ("U7", "24"),
    "C31": ("U7", "1"),
    "R11": ("U7", "7"), "R12": ("U7", "8"), "R13": ("U7", "16"),
    "R25": ("U7", "23"), "R26": ("U7", "25"), "R27": ("U7", "26"), "R28": ("U7", "27"),
    "R21": ("U7", "28"), "R22": ("U7", "31"), "R23": ("U7", "32"), "R24": ("U7", "34"),
    "R17": ("U7", "45"), "R18": ("U7", "46"), "R19": ("U7", "47"), "R20": ("U7", "48"),
    "D3": ("U7", "39"), "D4": ("U7", "40"), "D5": ("U7", "41"),
    "R35": ("U7", "4"), "R36": ("U7", "4"),
    "C32": ("U8", "8"), "R14": ("U8", "3"), "R15": ("U8", "7"),
    "C33": ("X1", "4"), "R16": ("X1", "3"),
    # muxes / phone power
    "C35": ("U10", "1"), "C36": ("U11", "1"),
    "R37": ("U10", "10"), "R38": ("U10", "2"), "R39": ("U11", "10"), "R40": ("U11", "2"),
    "C37": ("U12", "5"), "C38": ("U12", "1"), "R41": ("U12", "4"), "R42": ("U12", "3"),
    "R43": ("U12", "1"), "D2": ("U12", "1"), "C34": ("U9", "5"),
    "R33": ("J2", "A5"), "R34": ("J2", "B5"),
    "R29": ("J3", "4"), "R30": ("J3", "8"), "R31": ("J3", "13"), "R32": ("J3", "9"),
    # USB1 / regulators
    "R1": ("J1", "A5"), "R2": ("J1", "B5"), "F1": ("J1", "A4"), "C2": ("U1", "5"),
    "C3": ("U2", "1"), "C1": ("U2", "1"), "C4": ("U2", "5"), "C5": ("U2", "5"),
    "C6": ("U3", "5"), "C7": ("U4", "5"), "R3": ("U2", "5"), "D1": ("U2", "5"),
    "R44": ("SW1", "1"),
}
POWER_NETS = {"/GND", "/+3V3", "/+5V", "/+1V8", "/+1V2"}


def load_fp(libid):
    lib, name = libid.split(":")
    path = FPDIRS.get(lib, os.path.join(SYSFP, lib + ".pretty"))
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise RuntimeError("cannot load " + libid)
    return fp


def bbox(fp):
    try:
        fp.BuildCourtyardCaches()
        poly = fp.GetCourtyard(pcbnew.F_CrtYd)
        if poly.OutlineCount() > 0:
            b = poly.BBox()
            return (pcbnew.ToMM(b.GetX()), pcbnew.ToMM(b.GetY()),
                    pcbnew.ToMM(b.GetX() + b.GetWidth()), pcbnew.ToMM(b.GetY() + b.GetHeight()))
    except Exception:
        pass
    b = fp.GetBoundingBox(False)
    return (pcbnew.ToMM(b.GetX()), pcbnew.ToMM(b.GetY()),
            pcbnew.ToMM(b.GetX() + b.GetWidth()), pcbnew.ToMM(b.GetY() + b.GetHeight()))


def main(netfile):
    t = ET.parse(netfile)
    comps = []
    for c in t.iter("comp"):
        fpid = c.findtext("footprint")
        if not fpid:
            continue
        uuids = (c.findtext("tstamps") or "").split()
        desc = [f.text for f in c.iter("field") if f.get("name") == "Description" and f.text]
        comps.append(dict(ref=c.get("ref"), value=c.findtext("value"), fp=fpid, uuid=uuids[0],
                          desc=desc[0] if desc else "",
                          dnp=any(p.get("name") == "dnp" for p in c.iter("property"))))
    padnet = {}
    nets = {}
    for n in t.iter("net"):
        name = n.get("name")
        for node in n.iter("node"):
            padnet[(node.get("ref"), node.get("pin"))] = name
            nets.setdefault(name, []).append(node.get("ref"))

    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    ds = board.GetDesignSettings()
    ds.SetBoardThickness(MM(1.6))
    ds.SetAuxOrigin(V(BX0, BY1))   # drill/place origin = board bottom-left (positive CPL coords)

    netobjs = {}
    for name in sorted(nets):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        netobjs[name] = ni

    fps = {}
    for c in comps:
        fp = load_fp(c["fp"])
        fp.SetFPID(pcbnew.LIB_ID(*c["fp"].split(":")))
        fp.SetReference(c["ref"])
        fp.SetValue(c["value"])
        if c["desc"]:
            fp.GetField(pcbnew.FIELD_T_DESCRIPTION).SetText(c["desc"]) if hasattr(pcbnew, "FIELD_T_DESCRIPTION") else fp.SetLibDescription(c["desc"])
        fp.SetPath(pcbnew.KIID_PATH("/" + c["uuid"]))
        try:
            fp.SetSheetfile("lightning_debug.kicad_sch")
            fp.SetSheetname("")
        except Exception:
            pass
        if c["dnp"]:
            try:
                fp.SetDNP(True)
            except Exception:
                pass
        if c["ref"][0] in "RCDFY" or c["ref"].startswith(("FB", "JP", "SW")):
            fp.Reference().SetTextSize(V(0.8, 0.8))
            fp.Reference().SetTextThickness(MM(0.12))
        board.Add(fp)
        fps[c["ref"]] = fp
        for pad in fp.Pads():
            num = pad.GetNumber()
            if not num:
                continue
            net = padnet.get((c["ref"], num))
            if net:
                pad.SetNet(netobjs[net])
    # check that every netlist node has a pad
    for (ref, pin), net in padnet.items():
        if ref in fps and not any(p.GetNumber() == pin for p in fps[ref].Pads()):
            print("WARNING: no pad", ref, pin, net)

    # ---------------- placement ----------------
    occupied = []

    def free(r, margin=0.25):
        x0, y0, x1, y1 = r
        if x0 < BX0 + 0.5 or y0 < BY0 + 0.5 or x1 > BX1 - 0.5 or y1 > BY1 - 0.5:
            return False
        for o in occupied:
            if x0 < o[2] + margin and x1 > o[0] - margin and y0 < o[3] + margin and y1 > o[1] - margin:
                return False
        return True

    for ref, (x, y, rot) in FIXED.items():
        fp = fps[ref]
        fp.SetPosition(V(x, y))
        fp.SetOrientationDegrees(rot)
        b = bbox(fp)
        if ref == "J4":
            # the plug overhangs the board edge: only reserve the on-board part
            b = (BX0, b[1], b[2], b[3])

        occupied.append(b)

    centers = {r: (pcbnew.ToMM(f.GetPosition().x), pcbnew.ToMM(f.GetPosition().y)) for r, f in fps.items()}

    def pad_pos(ref, num):
        for p in fps[ref].Pads():
            if p.GetNumber() == num:
                return pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)
        raise KeyError((ref, num))

    def anchor_for(ref):
        fp = fps[ref]
        score = {}
        mynets = {p.GetNetname() for p in fp.Pads() if p.GetNetname()}
        for n in mynets:
            w = 0.2 if n in POWER_NETS else 1.0
            for other in set(nets.get(n, [])):
                if other == ref or other not in FIXED:
                    continue
                score[other] = score.get(other, 0) + w
        if not score:
            return None
        return max(score, key=lambda k: score[k])

    # second-level: signal anchors through other passives (e.g. pull-up on a net with only passives)
    loose = [r for r in fps if r not in FIXED]
    order = list(PREFER)
    loose.sort(key=lambda r: (order.index(r) if r in PREFER else len(order),
                              r[0], int("".join(ch for ch in r if ch.isdigit()) or 0)))
    for ref in loose:
        fp = fps[ref]
        if ref in PREFER:
            ax, ay = pad_pos(*PREFER[ref])
        else:
            a = anchor_for(ref)
            ax, ay = centers[a] if a else ((BX0 + BX1) / 2, (BY0 + BY1) / 2)
        fp.SetOrientationDegrees(0)
        placed = False
        for rad in [i * 0.25 for i in range(4, 160)]:
            steps = max(8, int(2 * math.pi * rad / 1.0))
            for k in range(steps):
                ang = 2 * math.pi * k / steps
                for rot in (0, 90):
                    x = round((ax + rad * math.cos(ang)) * 4) / 4
                    y = round((ay + rad * math.sin(ang)) * 4) / 4
                    fp.SetOrientationDegrees(rot)
                    fp.SetPosition(V(x, y))
                    b = bbox(fp)
                    if free(b, 0.35):
                        occupied.append(b)
                        placed = True
                        break
                if placed:
                    break
            if placed:
                break
        if not placed:
            print("could not place", ref)

    # ---------------- thermal vias in exposed pads ----------------
    # 0.5/0.3 mm GND vias inside the QFN thermal pads (connect EP to the In1/B.Cu ground).
    for ref, n in (("U7", 2), ("U5", 3)):
        ep = [p for p in fps[ref].Pads() if p.GetNetname() == "/GND" and
              pcbnew.ToMM(p.GetSize(pcbnew.F_Cu).x) > 2.0][0]
        ex, ey = pcbnew.ToMM(ep.GetPosition().x), pcbnew.ToMM(ep.GetPosition().y)
        pitch = 1.2 if n == 3 else 1.3
        for i in range(n):
            for j in range(n):
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(V(ex + (i - (n - 1) / 2) * pitch, ey + (j - (n - 1) / 2) * pitch))
                v.SetWidth(MM(0.5))
                v.SetDrill(MM(0.3))
                v.SetNet(netobjs["/GND"])
                board.Add(v)

    # ---------------- outline ----------------
    def seg(x0, y0, x1, y1, layer=pcbnew.Edge_Cuts, w=0.1):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(V(x0, y0))
        s.SetEnd(V(x1, y1))
        s.SetLayer(layer)
        s.SetWidth(MM(w))
        board.Add(s)

    seg(BX0, BY0, BX1, BY0)
    seg(BX1, BY0, BX1, BY1)
    seg(BX1, BY1, BX0, BY1)
    seg(BX0, BY1, BX0, BY0)

    def text(s, x, y, size=1.0, layer=pcbnew.F_SilkS, rot=0):
        tx = pcbnew.PCB_TEXT(board)
        tx.SetText(s)
        tx.SetPosition(V(x, y))
        tx.SetLayer(layer)
        tx.SetTextSize(V(size, size))
        tx.SetTextThickness(MM(size * 0.15))
        tx.SetTextAngleDegrees(rot)
        board.Add(tx)

    text("PHONE", 123.0, 103.0, 0.8)
    text("DEBUG", BX1 - 9.5, 127.0, 0.8, rot=90)
    text("LIGHTNING DEBUG v0.1", 160.0, BY1 - 1.2, 0.8)

    # ---------------- zones ----------------
    def zone(layer, netname, prio=0):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(netobjs[netname])
        z.SetAssignedPriority(prio)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in ((BX0 + 0.3, BY0 + 0.3), (BX1 - 0.3, BY0 + 0.3), (BX1 - 0.3, BY1 - 0.3), (BX0 + 0.3, BY1 - 0.3)):
            ol.Append(MM(x), MM(y))
        z.SetLocalClearance(MM(0.25))
        z.SetMinThickness(MM(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        board.Add(z)
        return z

    zone(pcbnew.In1_Cu, "/GND")
    zone(pcbnew.In2_Cu, "/+3V3")
    zone(pcbnew.B_Cu, "/GND")
    # Zones are left unfilled (ZONE_FILLER segfaults when run standalone); press B in pcbnew.

    board.Save(OUT)
    set_rules()
    print("wrote", OUT, "footprints:", len(fps), "nets:", len(nets))


def set_rules():
    """(Re)apply net classes + rules to the .kicad_pro (pcbnew's Save() resets them)."""
    import json
    pro = os.path.join(PROJ, "lightning_debug.kicad_pro")
    d = json.load(open(pro))
    classes = d.setdefault("net_settings", {}).setdefault("classes", [])
    base = dict(classes[0]) if classes else {}

    def cls(name, prio, **kw):
        c = dict(base)
        c.update(name=name, priority=prio, clearance=0.15, track_width=0.15, via_diameter=0.5,
                 via_drill=0.3, diff_pair_width=0.2, diff_pair_gap=0.2)
        c.update(kw)
        return c

    d["net_settings"]["classes"] = [
        cls("Default", 2147483647),
        cls("Power", 1, track_width=0.5, via_diameter=0.8, via_drill=0.4),
        # 90 ohm diff, estimated (IPC-2141) for JLC04161H-7628 (0.21mm prepreg, er 4.4):
        # 0.28 / 0.2 mm. Re-check with your fab's impedance calculator.
        cls("USB_HS", 0, track_width=0.28, diff_pair_width=0.28, diff_pair_gap=0.2),
    ]
    d["net_settings"]["netclass_patterns"] = [
        {"netclass": "Power", "pattern": p} for p in ("/VBUS1", "/VBUS2", "/+5V", "/LS_IN", "/LTG_PWR")
    ] + [{"netclass": "USB_HS", "pattern": p} for p in ("/USB*_D?", "/?_L0?", "/L0?_?_M")]
    r = d.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rules", {})
    r.update(min_clearance=0.15, min_track_width=0.15, min_copper_edge_clearance=0.4,
             min_text_height=0.8, min_via_diameter=0.45, min_through_hole_diameter=0.3)
    json.dump(d, open(pro, "w"), indent=2)


if __name__ == "__main__":
    main(sys.argv[1])
