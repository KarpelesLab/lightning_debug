#!/usr/bin/env python3
"""Generate lightning_debug.kicad_sch.

Every part is placed with a net label on each of its pins, so the whole design
is described by the declarative tables below. Re-run after editing, then open
in KiCad (or edit the schematic by hand from then on).
"""
import os
import sys
import uuid
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sexpr import parse, dump, find, findall, Str  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.join(PROJ, "lightning_debug.kicad_sch")
SYMDIR = "/usr/share/kicad/symbols"
LOCAL_LIBS = {"lightning_debug": os.path.join(PROJ, "lightning_debug.kicad_sym")}

ROOT_UUID = "4c1d0b6e-2f7a-4f0e-9d51-6a1e0c5b7d10"
PROJECT = "lightning_debug"


def U():
    return str(uuid.uuid4())


# ----------------------------------------------------------------------------
# Library handling
# ----------------------------------------------------------------------------
_libcache = {}


def load_lib(lib):
    if lib not in _libcache:
        path = LOCAL_LIBS.get(lib) or os.path.join(SYMDIR, lib + ".kicad_sym")
        _libcache[lib] = parse(open(path).read())
    return _libcache[lib]


def get_symbol(lib, name):
    tree = load_lib(lib)
    for s in findall(tree, "symbol"):
        if s[1] == name:
            return s
    raise KeyError(f"{lib}:{name}")


def flatten(lib, name):
    """Return a flattened copy of the symbol named 'lib:name' for lib_symbols."""
    s = get_symbol(lib, name)
    ext = find(s, "extends")
    if ext:
        parent = flatten(lib, ext[1])
        pname = ext[1]
        out = [x for x in parent if not (isinstance(x, list) and x and x[0] == "property")]
        props = findall(s, "property")
        # keep parent props not overridden
        child_keys = {p[1] for p in props}
        pprops = [p for p in findall(parent, "property") if p[1] not in child_keys]
        body = []
        for x in out[2:]:
            if isinstance(x, list) and x and x[0] == "symbol":
                x = list(x)
                x[1] = Str(x[1].replace(pname.split(":")[-1], name, 1))
            body.append(x)
        res = ["symbol", Str(f"{lib}:{name}")]
        # header items (pin_names, exclude_from_sim...) come before properties
        head = [x for x in body if not (isinstance(x, list) and x[0] == "symbol")]
        subs = [x for x in body if isinstance(x, list) and x[0] == "symbol"]
        res += head[:]
        # insert properties after header flags
        res = res[:2] + [h for h in head if h[0] != "embedded_fonts"] + props + pprops + subs
        ef = [h for h in head if h[0] == "embedded_fonts"]
        res += ef
        return res
    s = list(s)
    s[1] = Str(f"{lib}:{name}")
    return s


def sym_pins(lib, name):
    """pins: list of dict(num,name,type,x,y,a,unit)"""
    s = flatten(lib, name)
    pins = []
    for sub in findall(s, "symbol"):
        nm = sub[1]
        parts = nm.rsplit("_", 2)
        unit = int(parts[-2])
        for p in findall(sub, "pin"):
            at = find(p, "at")
            pins.append(dict(num=str(find(p, "number")[1]), name=str(find(p, "name")[1]),
                             type=p[1], x=float(at[1]), y=float(at[2]), a=int(float(at[3])),
                             unit=unit))
    return pins


# ----------------------------------------------------------------------------
# Schematic items
# ----------------------------------------------------------------------------
lib_symbols = {}
items = []
parts = []  # for verification: (ref, lib_id, unit, {pin: net})
refcount = {}
all_nets = {}


def nextref(prefix):
    refcount[prefix] = refcount.get(prefix, 0) + 1
    return f"{prefix}{refcount[prefix]}"


def xf(x, y, rot):
    r = math.radians(rot)
    xr = x * math.cos(r) - y * math.sin(r)
    yr = x * math.sin(r) + y * math.cos(r)
    return round(xr, 2), round(yr, 2)


def label(net, x, y, outward):
    ang = {"L": 180, "R": 0, "U": 90, "D": 270}[outward]
    just = "left" if ang in (0, 90) else "right"
    items.append(["label", Str(net), ["at", x, y, ang],
                  ["effects", ["font", ["size", 1.27, 1.27]], ["justify", just, "bottom"]],
                  ["uuid", Str(U())]])
    all_nets.setdefault(net, 0)
    all_nets[net] += 1


def noconn(x, y):
    items.append(["no_connect", ["at", x, y], ["uuid", Str(U())]])


def text(s, x, y, size=2.0):
    items.append(["text", Str(s), ["exclude_from_sim", "no"], ["at", x, y, 0],
                  ["effects", ["font", ["size", size, size], ["thickness", 0.4], ["bold", "yes"]],
                   ["justify", "left", "bottom"]], ["uuid", Str(U())]])


def note(s, x, y, size=1.27):
    items.append(["text", Str(s), ["exclude_from_sim", "no"], ["at", x, y, 0],
                  ["effects", ["font", ["size", size, size]], ["justify", "left", "top"]],
                  ["uuid", Str(U())]])


def place(ref, libid, value, fp, x, y, pins=None, rot=0, unit=1, dnp=False, desc=None,
          prefix=None, extra_props=None, in_bom=True, on_board=True):
    lib, name = libid.split(":")
    if libid not in lib_symbols:
        lib_symbols[libid] = flatten(lib, name)
    pins = pins or {}
    if fp is None:
        fpp = [q for q in findall(lib_symbols[libid], "property") if q[1] == "Footprint"]
        fp = str(fpp[0][2]) if fpp else ""
    allp = [p for p in sym_pins(lib, name) if p["unit"] in (0, unit)]
    pinnums = {p["num"] for p in allp}
    for k in pins:
        if k not in pinnums:
            raise ValueError(f"{ref}: pin {k} not in {libid} unit {unit}")
    done = set()
    xs, ys = [x], [y]
    for p in allp:
        px, py = xf(p["x"], p["y"], rot)
        sx, sy = round(x + px, 2), round(y - py, 2)
        xs.append(sx)
        ys.append(sy)
        a = (p["a"] + rot) % 360
        outward = {0: "L", 180: "R", 90: "D", 270: "U"}[a]
        key = (sx, sy)
        if p["num"] in pins:
            net = pins[p["num"]]
        elif p["type"] == "no_connect":
            continue
        elif key in done:
            continue
        else:
            raise ValueError(f"{ref}: pin {p['num']} ({p['name']}) of {libid} unconnected")
        if key in done:
            continue
        done.add(key)
        if net is None:
            noconn(sx, sy)
        else:
            label(net, sx, sy, outward)
    parts.append((ref, libid, unit, dict(pins)))
    top, bot = min(ys), max(ys)
    has_down = any((p["a"] + rot) % 360 == 90 for p in allp)
    if rot != 0:
        ry, vy = y - 2.54, y + 2.54
    elif has_down:
        ry, vy = bot + 7.62, bot + 10.16
    else:
        ry, vy = top - 3.81, bot + 3.81
    props = [
        ("Reference", ref, x, ry, False),
        ("Value", value, x, vy, False),
        ("Footprint", fp or "", x, y, True),
        ("Datasheet", "", x, y, True),
    ]
    if desc:
        props.append(("Description", desc, x, y, True))
    for k, v in (extra_props or {}).items():
        props.append((k, v, x, y, True))
    node = ["symbol", ["lib_id", Str(libid)], ["at", x, y, rot], ["unit", unit],
            ["exclude_from_sim", "no"], ["in_bom", "yes" if in_bom else "no"],
            ["on_board", "yes" if on_board else "no"], ["dnp", "yes" if dnp else "no"],
            ["uuid", Str(U())]]
    for k, v, px, py, hide in props:
        eff = ["effects", ["font", ["size", 1.27, 1.27]]]
        if hide:
            eff.append(["hide", "yes"])
        node.append(["property", Str(k), Str(v), ["at", px, py, FIELD_ANGLE.get(rot, 0)], eff])
    for p in allp:
        node.append(["pin", Str(p["num"]), ["uuid", Str(U())]])
    node.append(["instances", ["project", Str(PROJECT),
                               ["path", Str("/" + ROOT_UUID), ["reference", Str(ref)], ["unit", unit]]]])
    items.append(node)


FIELD_ANGLE = {90: 90}

FP = {
    "R": "Resistor_SMD:R_0603_1608Metric",
    "C": "Capacitor_SMD:C_0603_1608Metric",
    "C0805": "Capacitor_SMD:C_0805_2012Metric",
    "LED": "LED_SMD:LED_0603_1608Metric",
    "FB": "Inductor_SMD:L_0603_1608Metric",
}


class Col:
    """A vertical column of horizontally placed 2-pin passives."""

    def __init__(self, x, y, dy=7.62):
        self.x, self.y, self.dy = x, y, dy

    def _next(self):
        y = self.y
        self.y += self.dy
        return y

    def R(self, value, n1, n2, dnp=False, fp=None, desc=None):
        ref = nextref("R")
        place(ref, "Device:R", value, fp or FP["R"], self.x, self._next(), {"1": n1, "2": n2},
              rot=90, dnp=dnp, desc=desc)
        return ref

    def C(self, value, n1, n2="GND", fp=None, dnp=False):
        ref = nextref("C")
        if fp is None:
            fp = FP["C0805"] if value in ("10u", "22u", "4.7u") else FP["C"]
        place(ref, "Device:C", value, fp, self.x, self._next(), {"1": n1, "2": n2}, rot=90, dnp=dnp)
        return ref

    def FB(self, value, n1, n2):
        ref = nextref("FB")
        place(ref, "Device:FerriteBead_Small", value, FP["FB"], self.x, self._next(),
              {"1": n1, "2": n2}, rot=90)

    def F(self, value, n1, n2):
        ref = nextref("F")
        place(ref, "Device:Polyfuse", value, "Fuse:Fuse_1206_3216Metric", self.x, self._next(),
              {"1": n1, "2": n2}, rot=90)

    def LED(self, value, k, a):
        ref = nextref("D")
        place(ref, "Device:LED", value, FP["LED"], self.x, self._next(), {"1": k, "2": a})

    def gap(self, n=1):
        self.y += self.dy * n


def flag(net, x, y):
    ref = "#FLG" + str(len([p for p in parts if p[0].startswith("#FLG")]) + 1).zfill(2)
    place(ref, "power:PWR_FLAG", "PWR_FLAG", "", x, y, {"1": net}, in_bom=False, on_board=False)


# ============================================================================
#                                 DESIGN
# ============================================================================
G = "GND"

# ---------------------------------------------------------------- Block A ---
text("USB-C #1 : debug / programming / power", 20, 22, 2.5)
note("Port 1 powers the board. FT2232H: ch.A = MPSSE SPI -> flash/FPGA (iceprog compatible),\n"
     "ch.B = UART (or MPSSE, up to 30MHz) to the FPGA for log streaming.", 20, 25)
place("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB_C_Receptacle_USB2.0_16P",
      "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", 40.64, 66.04,
      {"A4": "VBUS1", "A9": "VBUS1", "B4": "VBUS1", "B9": "VBUS1",
       "A5": "J1_CC1", "B5": "J1_CC2", "A6": "USB1_DP", "B6": "USB1_DP",
       "A7": "USB1_DM", "B7": "USB1_DM", "A8": None, "B8": None,
       "A1": G, "A12": G, "B1": G, "B12": G, "SH": G},
      desc="USB-C port 1 (debug): power + FT2232H")
c = Col(93.98, 45.72)
c.R("5.1k", "J1_CC1", G)
c.R("5.1k", "J1_CC2", G)
c.F("1.5A hold", "VBUS1", "+5V")
c.C("10u", "+5V")
c.C("100n", "+5V")
place("U1", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
      40.64, 114.3, {"1": "USB1_DP", "6": "USB1_DP", "3": "USB1_DM", "4": "USB1_DM",
                     "5": "+5V", "2": G})

text("Power", 130, 22, 2.5)
place("U2", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", None, 144.78, 43.18,
      {"1": "+5V", "3": "+5V", "5": "+3V3", "2": G})
place("U3", "Regulator_Linear:AP2112K-1.2", "AP2112K-1.2", None, 144.78, 71.12,
      {"1": "+3V3", "3": "+3V3", "5": "+1V2", "2": G})
place("U4", "Regulator_Linear:AP2112K-1.8", "AP2112K-1.8", None, 144.78, 99.06,
      {"1": "+3V3", "3": "+3V3", "5": "+1V8", "2": G})
c = Col(180.34, 38.1)
c.C("1u", "+5V")
c.C("10u", "+3V3")
c.C("1u", "+3V3")
c.C("10u", "+1V2")
c.C("10u", "+1V8")
c.gap()
c.R("1k", "+3V3", "LED_PWR_A")
c.LED("green PWR", G, "LED_PWR_A")

text("FPGA bank 0 (Lightning lanes) voltage", 125, 122, 1.8)
note("JP2: 1-2 (default) = 3.3V, 2-3 = 1.8V.\nAffects L0/L1 lanes of both sides + EXP0..5.", 125, 124)
place("JP2", "Jumper:SolderJumper_3_Bridged12", "VCCIO0 sel",
      "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm", 147.32, 139.7,
      {"1": "+3V3", "2": "VCCIO0", "3": "+1V8"}, in_bom=False)

text("Power flags", 20, 150, 1.5)
for i, n in enumerate(["+5V", "GND", "VCCIO0", "LS_IN", "FT_VPHY", "VBUS1"]):
    flag(n, 25.4 + i * 22.86, 162.56)

# ---------------------------------------------------------------- Block B ---
text("FT2232H USB bridge", 215, 22, 2.5)
place("U5", "Interface_USB:FT2232HQ", "FT2232HQ", None, 279.4, 93.98, {
    "50": "+3V3", "49": "FT_VCORE", "12": "FT_VCORE", "37": "FT_VCORE", "64": "FT_VCORE",
    "20": "+3V3", "31": "+3V3", "42": "+3V3", "56": "+3V3",
    "4": "FT_VPHY", "9": "FT_VPHY",
    "1": G, "5": G, "10": G, "11": G, "15": G, "25": G, "35": G, "47": G, "51": G, "65": G,
    "2": "FT_OSCI", "3": "FT_OSCO", "6": "FT_REF", "7": "USB1_DM", "8": "USB1_DP",
    "13": G, "14": "FT_RESET#",
    "61": "FT_EEDATA", "62": "FT_EECLK", "63": "FT_EECS",
    # channel A : SPI programmer (iceprog pinout)
    "16": "FLASH_SCK", "17": "FLASH_MOSI", "18": "FLASH_MISO", "19": None,
    "21": "FLASH_CS#", "22": None, "23": "FPGA_CDONE", "24": "FPGA_CRESET#",
    "26": None, "27": None, "28": None, "29": None, "30": None, "32": None, "33": None, "34": None,
    # channel B : UART / MPSSE to FPGA
    "38": "FT_TXD", "39": "FT_RXD", "40": "FT_RTS#", "41": "FT_CTS#",
    "43": None, "44": None, "45": None, "46": None,
    "48": None, "52": None, "53": None, "54": None, "55": None, "57": None, "58": None, "59": None,
    "36": None, "60": None,
})
note("ch.A: ADBUS0 SCK, 1 MOSI, 2 MISO, 4 CS#, 6 CDONE, 7 CRESET#  (iceprog default)\n"
     "ch.B: BDBUS0 TXD->FPGA, 1 RXD<-FPGA, 2 RTS#, 3 CTS#  (MPSSE: SCK/MOSI/MISO/CS)",
     215, 166)
place("Y1", "Device:Crystal_GND24", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
      226.06, 190.5, {"1": "FT_OSCI", "3": "FT_OSCO", "2": G, "4": G},
      desc="12MHz crystal, CL=18pF, +-30ppm")
place("U6", "Memory_EEPROM:93LCxxB", "93LC56B", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
      226.06, 220.98, {"1": "FT_EECS", "2": "FT_EECLK", "3": "FT_EEDATA", "4": "FT_EEDO",
                       "6": None, "7": None, "5": G, "8": "+3V3"},
      desc="Optional: FT2232H config EEPROM (custom descriptors / FIFO mode). Board works without it")
c = Col(264.16, 182.88)
c.C("4.7u", "+3V3")
c.C("4.7u", "FT_VCORE")
c.C("100n", "FT_VCORE")
c.C("100n", "FT_VCORE")
c.C("100n", "FT_VCORE")
c.FB("600R@100MHz", "+3V3", "FT_VPHY")
c.C("4.7u", "FT_VPHY")
c.C("100n", "FT_VPHY")
c.C("100n", "FT_VPHY")
c = Col(309.88, 182.88)
c.C("100n", "+3V3")
c.C("100n", "+3V3")
c.C("100n", "+3V3")
c.C("100n", "+3V3")
c.R("12k 1%", "FT_REF", G)
c.R("10k", "FT_RESET#", "+3V3")
c.C("27p", "FT_OSCI")
c.C("27p", "FT_OSCO")
c = Col(264.16, 259.08)
c.R("10k", "FT_EECS", "+3V3")
c.R("10k", "FT_EECLK", "+3V3")
c.R("10k", "FT_EEDATA", "+3V3")
c.R("2.2k", "FT_EEDO", "FT_EEDATA")

# ---------------------------------------------------------------- Block C ---
text("iCE40UP5K FPGA", 350, 22, 2.5)
FX = 406.4
place("U7", "FPGA_Lattice:ICE40UP5K-SG48ITR", "ICE40UP5K-SG48ITR", None, FX, 66.04, unit=2, pins={
    "7": "FPGA_CDONE", "8": "FPGA_CRESET#",
    "14": "FLASH_MOSI", "15": "FLASH_SCK", "16": "FLASH_CS#", "17": "FLASH_MISO",
    "20": "CLK12",
    "9": "FT_TXD", "10": "FT_RXD", "11": "FT_RTS#", "12": "FT_CTS#",
    "13": "MUXA_SEL", "18": "MUXA_OE#", "19": "MUXB_SEL", "21": "MUXB_OE#",
    "6": "PWR_EN",
    "22": "+3V3",
})
note("Bank 1 = 3.3V : config SPI, clock, FT2232H ch.B, mux + power control", 350, 100)
place("U7", "FPGA_Lattice:ICE40UP5K-SG48ITR", "ICE40UP5K-SG48ITR", None, FX, 142.24, unit=1, pins={
    "23": "L0A_P_F", "25": "L0A_N_F", "26": "L0B_P_F", "27": "L0B_N_F",
    "28": "L1A_P_F", "31": "L1A_N_F", "32": "L1B_P_F", "34": "L1B_N_F",
    "35": "EXP0", "36": "EXP1", "37": "EXP2", "38": "EXP3", "42": "EXP4", "43": "EXP5",
    "39": "LED_R_K", "40": "LED_G_K", "41": "LED_B_K",
    "33": "VCCIO0",
})
note("Bank 0 = VCCIO0 (JP2: 3.3V / 1.8V) : Lightning L0 (via mux) + L1 lanes", 350, 172)
place("U7", "FPGA_Lattice:ICE40UP5K-SG48ITR", "ICE40UP5K-SG48ITR", None, FX, 203.2, unit=3, pins={
    "45": "A_ID0_F", "46": "A_ID1_F", "47": "B_ID0_F", "48": "B_ID1_F",
    "2": "BTN#", "3": "PWR_FLT#", "4": "VBUS2_DET", "44": "EXP6",
    "1": "+1V8",
})
note("Bank 2 = 1.8V : Lightning ID0/ID1 (both sides), button, status", 350, 222)
place("U7", "FPGA_Lattice:ICE40UP5K-SG48ITR", "ICE40UP5K-SG48ITR", None, FX, 243.84, unit=4, pins={
    "5": "+1V2", "30": "+1V2", "24": "+3V3", "29": "VCCPLL", "49": G,
})
c = Col(431.8, 238.76)
c.R("100", "+1V2", "VCCPLL")
c.C("10u", "VCCPLL")
c.C("100n", "VCCPLL")

c = Col(345.44, 271.78)
c.C("10u", "+1V2")
c.C("100n", "+1V2")
c.C("100n", "+1V2")
c.C("1u", "VCCIO0")
c.C("100n", "VCCIO0")
c.C("100n", "+3V3")   # SPI_VCCIO1
c.C("100n", "+3V3")   # VPP_2V5
c.C("100n", "+1V8")   # VCCIO_2
c.gap()
c.R("10k", "FPGA_CDONE", "+3V3")
c.R("10k", "FPGA_CRESET#", "+3V3")
c.R("10k", "FLASH_CS#", "+3V3")

text("Config flash + clock", 440, 22, 2.0)
place("U8", "Memory_Flash:W25Q128JVS", "W25Q128JVS", None, 459.74, 48.26,
      {"1": "FLASH_CS#", "6": "FLASH_SCK", "5": "FLASH_MOSI", "2": "FLASH_MISO",
       "3": "FLASH_WP#", "7": "FLASH_HOLD#", "8": "+3V3", "4": G})
place("X1", "Oscillator:ASE-xxxMHz", "ASE-12.000MHz", None, 459.74, 86.36,
      {"1": "+3V3", "4": "+3V3", "2": G, "3": "CLK12_O"})
c = Col(490.22, 38.1)
c.R("10k", "FLASH_WP#", "+3V3")
c.R("10k", "FLASH_HOLD#", "+3V3")
c.C("100n", "+3V3")
c.C("100n", "+3V3")
c.R("33", "CLK12_O", "CLK12")

# Series resistors between Lightning pins and FPGA
text("Lightning <-> FPGA series resistors", 390, 271, 1.8)
c = Col(397.51, 279.4)
for s in "AB":
    c.R("33", f"{s}_ID0", f"{s}_ID0_F")
    c.R("33", f"{s}_ID1", f"{s}_ID1_F")
c = Col(444.5, 279.4)
for s in "AB":
    c.R("33", f"{s}_L1P", f"L1{s}_P_F")
    c.R("33", f"{s}_L1N", f"L1{s}_N_F")
c = Col(491.49, 279.4)
for s in "AB":
    c.R("33", f"L0{s}_P_M", f"L0{s}_P_F")
    c.R("33", f"L0{s}_N_M", f"L0{s}_N_F")
c = Col(397.51, 312.42)
for s in "AB":
    c.R("10k", f"{s}_ID0", "+1V8", dnp=True)
    c.R("10k", f"{s}_ID1", "+1V8", dnp=True)
note("ID pull-ups to 1.8V: DNP (use FPGA internal pull-ups / open-drain emulation)", 380, 345)

# ---------------------------------------------------------------- Block D ---
text("USB-C #2 : passthrough to the Lightning device", 530, 22, 2.5)
note("Port 2 = UFP (Rd). D+/D- -> HS 2:1 muxes -> Lightning L0 lane of side A or B.\n"
     "Mux: SEL=0 -> FPGA (HSD1), SEL=1 -> port 2 (HSD2, 480Mb/s passthrough). OE# high (default) = disconnected.\n"
     "VBUS2 -> TPS2065C load switch (FPGA PWR_EN) -> Lightning PWR.",
     530, 25)
place("J2", "Connector:USB_C_Receptacle_USB2.0_16P", "USB_C_Receptacle_USB2.0_16P",
      "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", 548.64, 76.2,
      {"A4": "VBUS2", "A9": "VBUS2", "B4": "VBUS2", "B9": "VBUS2",
       "A5": "J2_CC1", "B5": "J2_CC2", "A6": "USB2_DP", "B6": "USB2_DP",
       "A7": "USB2_DM", "B7": "USB2_DM", "A8": None, "B8": None,
       "A1": G, "A12": G, "B1": G, "B12": G, "SH": G},
      desc="USB-C port 2 (passthrough to the iPhone)")
c = Col(601.98, 55.88)
c.R("5.1k", "J2_CC1", G)
c.R("5.1k", "J2_CC2", G)
c.C("4.7u", "VBUS2")
c.R("10k", "VBUS2", "VBUS2_DET")
c.R("4.7k", "VBUS2_DET", G)
place("U9", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
      548.64, 121.92, {"1": "USB2_DP", "6": "USB2_DP", "3": "USB2_DM", "4": "USB2_DM",
                       "5": "VBUS2", "2": G})

for i, s in enumerate("AB"):
    y = 160.02 + i * 40.64
    place(f"U{10 + i}", "Interface_USB:FSUSB42MUX", "FSUSB42MUX", None, 566.42, y, {
        "3": f"{s}_L0P", "4": f"{s}_L0N",
        "9": "USB2_DP", "8": "USB2_DM",          # HSD2 (USB-only path) -> port 2
        "7": f"L0{s}_P_M", "6": f"L0{s}_N_M",    # HSD1 (UART/USB capable) -> FPGA
        "2": f"MUX{s}_SEL", "10": f"MUX{s}_OE#",
        "1": "+3V3", "5": G,
    }, desc=f"Lightning side {s} L0 lane: HSD1 = FPGA, HSD2 = USB-C #2")
    note(f"Side {s} L0 lane mux", 530, y - 15)
c = Col(612.14, 152.4)
c.R("10k", "MUXA_OE#", "+3V3")
c.R("10k", "MUXA_SEL", G)
c.C("100n", "+3V3")
c.gap(2)
c.R("10k", "MUXB_OE#", "+3V3")
c.R("10k", "MUXB_SEL", G)
c.C("100n", "+3V3")

text("Lightning PWR switch", 530, 236, 2.0)
note("JP1: 1-2 (default) = from port 2 VBUS, 2-3 = from port 1 (+5V)", 530, 239)
place("JP1", "Jumper:SolderJumper_3_Bridged12", "LTG PWR src",
      "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm", 543.56, 254.0,
      {"1": "VBUS2", "2": "LS_IN", "3": "+5V"}, in_bom=False)
place("U12", "Power_Management:TPS2065CDBV", "TPS2065CDBV", None, 576.58, 269.24,
      {"5": "LS_IN", "4": "PWR_EN", "1": "LTG_PWR", "3": "PWR_FLT#", "2": G},
      desc="1A current limited switch, active-high EN")
c = Col(612.14, 259.08)
c.C("10u", "LS_IN")
c.C("10u", "LTG_PWR")
c.R("100k", "PWR_EN", G)
c.R("10k", "PWR_FLT#", "+1V8")
c.R("2.2k", "LTG_PWR", "LED_LTG_A")
c.LED("yellow LTG PWR", G, "LED_LTG_A")

# ---------------------------------------------------------------- Block E ---
text("Lightning breakout install points (populate ONE)", 20, 190, 2.5)
note("Both footprints carry the same nets. Pin N = same Lightning contact on both boards:\n"
     "side A 1..8 = GND, L0p, L0n, ID0, PWR, L1n, L1p, ID1 ; side B mirrored (pin 17-k = pin k).\n"
     "J3 = APPLE-LM-BO-V1AV (vertical plug), J4 = APPLE-LM-BO-V2A (plug overhangs board edge).",
     20, 193)
LTG = {"1": G, "16": G, "5": "LTG_PWR", "12": "LTG_PWR",
       "2": "A_L0P", "3": "A_L0N", "4": "A_ID0", "6": "A_L1N", "7": "A_L1P", "8": "A_ID1",
       "15": "B_L0P", "14": "B_L0N", "13": "B_ID0", "11": "B_L1N", "10": "B_L1P", "9": "B_ID1"}
place("J3", "lightning_debug:Lightning_Breakout", "APPLE-LM-BO-V1AV",
      "lightning_debug:eLabGuy_APPLE-LM-BO-V1AV", 50.8, 223.52, LTG)
place("J4", "lightning_debug:Lightning_Breakout", "APPLE-LM-BO-V2A",
      "lightning_debug:eLabGuy_APPLE-LM-BO-V2A", 124.46, 223.52, LTG)

text("User I/O", 20, 255, 2.5)
place("J5", "Connector:Conn_01x10_Pin", "EXP", "Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical",
      30.48, 284.48, {"1": G, "2": "VCCIO0", "3": "EXP0", "4": "EXP1", "5": "EXP2", "6": "EXP3",
                      "7": "EXP4", "8": "EXP5", "9": "EXP6", "10": "+1V8"},
      desc="Spare FPGA I/O: EXP0-5 on bank 0 (VCCIO0), EXP6 on bank 2 (1.8V, global clock capable)")
place("SW1", "Switch:SW_Push", "USER", "Button_Switch_SMD:SW_SPST_PTS810", 78.74, 269.24,
      {"1": "BTN#", "2": G})
c = Col(124.46, 264.16)
c.R("10k", "BTN#", "+1V8")
c.gap()
c.LED("red", "LED_R_K", "+3V3")
c.LED("green", "LED_G_K", "+3V3")
c.LED("blue", "LED_B_K", "+3V3")
note("RGB0..2 are the UP5K constant-current LED sinks (use SB_RGBA_DRV)", 100, 300)

for i in range(4):
    place(f"H{i + 1}", "Mechanical:MountingHole", "MountingHole", "MountingHole:MountingHole_3.2mm_M3",
          30.48 + i * 15.24, 322.58, in_bom=False)


# ============================================================================
def build():
    # sanity: every net used at least twice
    single = [n for n, c in all_nets.items() if c < 2]
    if single:
        print("WARNING single-use nets:", single)
    sch = ["kicad_sch", ["version", 20250114], ["generator", Str("eeschema")],
           ["generator_version", Str("9.0")], ["uuid", Str(ROOT_UUID)], ["paper", Str("A1")],
           ["title_block", ["title", Str("Lightning debug board")], ["date", Str("2026-11-08")],
            ["rev", Str("0.1")], ["company", Str("")],
            ["comment", 1, Str("iCE40UP5K + FT2232H, USB-C x2, eLabGuy Lightning breakout")]],
           ["lib_symbols"] + list(lib_symbols.values())]
    sch += items
    sch.append(["sheet_instances", ["path", Str("/"), ["page", Str("1")]]])
    sch.append(["embedded_fonts", "no"])
    open(OUT, "w").write(dump(sch) + "\n")
    print("wrote", OUT, "parts:", len({p[0] for p in parts}), "nets:", len(all_nets))


if __name__ == "__main__":
    build()
