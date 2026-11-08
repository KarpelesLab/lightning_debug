#!/usr/bin/env python3
"""Export fabrication + assembly files for JLCPCB and PCBWay.

    python3 tools/export_fab.py            # refuses if the board has unrouted nets
    python3 tools/export_fab.py --preview  # export anyway (files are tagged UNROUTED-PREVIEW)

Output: fab/<tag>/
    gerbers/                       Gerber + Excellon drill files
    lightning_debug-gerbers.zip    upload this to both JLCPCB and PCBWay
    jlcpcb/bom.csv, jlcpcb/cpl.csv
    pcbway/bom.csv, pcbway/centroid.csv
    assembly-excluded.txt          parts left out of assembly and why

Part numbers: tools/parts.csv maps (value, footprint) -> LCSC / manufacturer / MPN.
A symbol field named LCSC, MPN or Manufacturer overrides the table.
"""
import csv
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.abspath(os.path.join(HERE, ".."))
NAME = "lightning_debug"
PCB = os.path.join(PROJ, NAME + ".kicad_pcb")
SCH = os.path.join(PROJ, NAME + ".kicad_sch")
PARTS = os.path.join(HERE, "parts.csv")

LAYERS = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu", "F.Paste", "B.Paste", "F.Silkscreen",
          "B.Silkscreen", "F.Mask", "B.Mask", "Edge.Cuts"]

# Not placed by the assembler (reason shown in assembly-excluded.txt)
EXCLUDE = [
    (r"^J[34]$", "Lightning breakout: you fit the eLabGuy board (or 1x8 2.54mm sockets) yourself"),
    (r"^J5$", "THT pin header: hand solder (or add it as a THT part in the order)"),
    (r"^H\d+$", "mounting hole, not a part"),
    (r"^JP\d+$", "solder jumper, part of the copper"),
]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def unrouted_count(tmp):
    rpt = os.path.join(tmp, "drc.rpt")
    run(["kicad-cli", "pcb", "drc", "--refill-zones", "--save-board", "--schematic-parity",
         "-o", rpt, PCB])
    txt = open(rpt).read()
    unrouted = int(re.search(r"Found (\d+) unconnected", txt).group(1))
    fperr = int(re.search(r"Found (\d+) Footprint errors", txt).group(1))
    errors = len(re.findall(r"; error\n", txt.split("unconnected pads **")[0]))
    return unrouted, fperr, errors, rpt


def load_parts():
    table = {}
    if os.path.exists(PARTS):
        for row in csv.DictReader(l for l in open(PARTS) if not l.startswith("#")):
            table[(row["value"].strip(), row["footprint"].strip())] = row
    return table


def describe(value, fp):
    pkg = fp.split(":")[-1]
    m = re.search(r"_(0402|0603|0805|1206)_", pkg + "_")
    size = m.group(1) if m else pkg
    if fp.startswith("Resistor_SMD"):
        tol = "" if "%" in value else " 1%"
        return f"Resistor {value}{tol} {size}", size
    if fp.startswith("Capacitor_SMD"):
        v = "10V" if value in ("10u", "22u", "4.7u") else "16V"
        diel = "C0G" if value.endswith("p") else "X5R/X7R"
        return f"Capacitor {value} {v} {diel} {size}", size
    if fp.startswith("LED_SMD"):
        return f"LED {value} {size}", size
    if fp.startswith("Inductor_SMD"):
        return f"Ferrite bead {value} {size}", size
    if fp.startswith("Fuse"):
        return f"PTC resettable fuse {value} {size}", size
    return value, pkg


def main():
    preview = "--preview" in sys.argv
    os.environ.setdefault("KICAD_CONFIG_HOME", tempfile.mkdtemp())
    cfg = os.path.join(os.environ["KICAD_CONFIG_HOME"], "10.0")
    os.makedirs(cfg, exist_ok=True)
    for t in ("sym-lib-table", "fp-lib-table"):
        if not os.path.exists(os.path.join(cfg, t)):
            shutil.copy(f"/usr/share/kicad/template/{t}", cfg)

    tmp = tempfile.mkdtemp()
    unrouted, fperr, errors, rpt = unrouted_count(tmp)
    print(f"DRC: {unrouted} unrouted pads, {fperr} schematic-parity errors, {errors} DRC errors")
    if (unrouted or fperr or errors) and not preview:
        sys.exit("Board is not ready to order (route it / fix DRC first). "
                 "Use --preview to export anyway for a dry run.\nDRC report: " + rpt)
    tag = "UNROUTED-PREVIEW" if (unrouted or fperr or errors) else "release"

    out = os.path.join(PROJ, "fab", tag)
    shutil.rmtree(out, ignore_errors=True)
    gdir = os.path.join(out, "gerbers")
    os.makedirs(gdir)

    # ---------------- Gerbers + drill ----------------
    run(["kicad-cli", "pcb", "export", "gerbers", "-o", gdir + "/", "-l", ",".join(LAYERS),
         "--subtract-soldermask", "--use-drill-file-origin", PCB])
    run(["kicad-cli", "pcb", "export", "drill", "-o", gdir + "/", "--format", "excellon",
         "--excellon-units", "mm", "--excellon-zeros-format", "decimal",
         "--excellon-oval-format", "alternate", "--excellon-separate-th",
         "--generate-map", "--map-format", "gerberx2", "--drill-origin", "plot", PCB])
    zipbase = os.path.join(out, f"{NAME}-gerbers" + ("-UNROUTED-PREVIEW" if tag != "release" else ""))
    shutil.make_archive(zipbase, "zip", gdir)
    if tag != "release":
        open(os.path.join(out, "DO_NOT_ORDER.txt"), "w").write(
            f"Exported with --preview: the board has {unrouted} unrouted pads.\n"
            "These files describe a board WITHOUT tracks. Route the board, then re-run\n"
            "tools/export_fab.py without --preview.\n")

    # ---------------- BOM ----------------
    net = os.path.join(tmp, "net.xml")
    run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadxml", "-o", net, SCH])
    parts = load_parts()
    excluded = []
    groups = OrderedDict()
    for c in ET.parse(net).iter("comp"):
        ref = c.get("ref")
        props = {p.get("name"): p.get("value") for p in c.iter("property")}
        fields = {f.get("name"): (f.text or "") for f in c.iter("field")}
        if "dnp" in props:
            excluded.append((ref, "DNP in schematic"))
            continue
        if "exclude_from_bom" in props:
            excluded.append((ref, "excluded from BOM in schematic"))
            continue
        reason = next((why for pat, why in EXCLUDE if re.match(pat, ref)), None)
        if reason:
            excluded.append((ref, reason))
            continue
        value, fp = c.findtext("value"), c.findtext("footprint") or ""
        row = parts.get((value, fp), {})
        lcsc = fields.get("LCSC") or row.get("lcsc", "")
        mfr = fields.get("Manufacturer") or row.get("manufacturer", "")
        mpn = fields.get("MPN") or row.get("mpn", "") or (value if ref[0] in "UXJY" or ref.startswith("SW") else "")
        desc, pkg = describe(value, fp)
        key = (value, fp, lcsc, mpn)
        g = groups.setdefault(key, dict(refs=[], value=value, fp=fp, pkg=pkg, desc=desc,
                                        lcsc=lcsc, mfr=mfr, mpn=mpn))
        g["refs"].append(ref)

    def refkey(r):
        m = re.match(r"([A-Z#]+)(\d+)", r)
        return (m.group(1), int(m.group(2))) if m else (r, 0)

    assembled = set()
    for g in groups.values():
        g["refs"].sort(key=refkey)
        assembled.update(g["refs"])
    rows = sorted(groups.values(), key=lambda g: refkey(g["refs"][0]))

    os.makedirs(os.path.join(out, "jlcpcb"))
    os.makedirs(os.path.join(out, "pcbway"))
    with open(os.path.join(out, "jlcpcb", "bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for g in rows:
            w.writerow([g["desc"] if g["desc"] != g["value"] else g["value"], ",".join(g["refs"]),
                        g["pkg"], g["lcsc"]])
    with open(os.path.join(out, "pcbway", "bom.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Item #", "Designator", "Qty", "Manufacturer", "Mfg Part #",
                    "Description / Value", "Package/Footprint", "Type"])
        for i, g in enumerate(rows, 1):
            typ = "THT" if g["fp"].startswith(("Connector_PinHeader",)) else "SMD"
            w.writerow([i, ",".join(g["refs"]), len(g["refs"]), g["mfr"], g["mpn"], g["desc"],
                        g["pkg"], typ])

    # ---------------- placement ----------------
    pos = os.path.join(tmp, "pos.csv")
    run(["kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both",
         "--exclude-dnp", "--use-drill-file-origin", "-o", pos, PCB])
    placed = []
    for r in csv.DictReader(open(pos)):
        if r["Ref"] in assembled:
            placed.append(r)
    missing = assembled - {r["Ref"] for r in placed}
    if missing:
        print("WARNING: in BOM but not on the board:", sorted(missing))
    placed.sort(key=lambda r: refkey(r["Ref"]))
    with open(os.path.join(out, "jlcpcb", "cpl.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in placed:
            w.writerow([r["Ref"], r["PosX"] + "mm", r["PosY"] + "mm",
                        "Top" if r["Side"] == "top" else "Bottom", r["Rot"]])
    with open(os.path.join(out, "pcbway", "centroid.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Footprint", "Mid X(mm)", "Mid Y(mm)", "Layer", "Rotation"])
        for r in placed:
            w.writerow([r["Ref"], r["Package"], r["PosX"], r["PosY"],
                        "T" if r["Side"] == "top" else "B", r["Rot"]])

    with open(os.path.join(out, "assembly-excluded.txt"), "w") as f:
        for ref, why in sorted(excluded, key=lambda e: refkey(e[0])):
            f.write(f"{ref:6s} {why}\n")

    nolcsc = [g for g in rows if not g["lcsc"]]
    print(f"wrote {out}")
    print(f"  {len(rows)} BOM lines, {len(placed)} placed parts, {len(excluded)} excluded")
    print(f"  {len(nolcsc)} BOM lines without an LCSC part number (fill tools/parts.csv)")


if __name__ == "__main__":
    main()
