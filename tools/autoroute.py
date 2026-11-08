#!/usr/bin/env python3
"""Autoroute lightning_debug.kicad_pcb with Freerouting (Specctra DSN -> SES round trip).

    python3 tools/autoroute.py [--jar path/to/freerouting.jar] [--passes N]

Existing tracks are kept: DSN export marks them as pre-routed, so you can hand-route
the critical nets first (USB pairs) and let Freerouting finish the rest.
Runs headless (Freerouting 2.x, --gui.enabled=false). Default jar: the newest
~/.local/share/freerouting/freerouting-2.*.jar (2.5+ needs Java 25:
found in /usr/lib/jvm or /opt, or set FREEROUTING_JAVA).
"""
import argparse
import glob
import re
import os
import subprocess
import sys
import tempfile

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.environ.get("PCB_FILE") or os.path.abspath(os.path.join(HERE, "..", "lightning_debug.kicad_pcb"))


def find_java(jar):
    m = re.search(r"freerouting-(\d+)\.(\d+)", os.path.basename(jar))
    if m and (int(m.group(1)), int(m.group(2))) >= (2, 5):    # 2.5+ is built for Java 25
        for cand in sorted(glob.glob("/usr/lib/jvm/*25*/bin/java") + glob.glob("/opt/*jdk*25*/bin/java")):
            return cand
    return "java"


def find_jar():
    cands = glob.glob(os.path.expanduser("~/.local/share/freerouting/freerouting-2.*.jar"))
    ver = lambda p: tuple(int(x) for x in re.findall(r"\d+", os.path.basename(p))[:3])
    return max(cands, key=ver) if cands else None


MIN_W = 1500   # um/10 in the session file = 0.15 mm, the fab's standard minimum


def import_ses(ses):
    # Freerouting 2.5 necks tracks down at pins (0.1124 mm); widen them to the board minimum.
    txt = open(ses).read()
    txt = re.sub(r"\(path (\S+) (\d+)", lambda m: "(path %s %d" % (m.group(1), max(int(m.group(2)), MIN_W)), txt)
    txt = re.sub(r"\(wire\s+\(path \S+ \d+\s+-?\d+ -?\d+\s*\)\s*\)", "", txt)
    fixed = ses + ".fixed"
    open(fixed, "w").write(txt)
    ses = fixed
    board = pcbnew.LoadBoard(PCB)
    if not pcbnew.ImportSpecctraSES(board, ses):
        sys.exit("SES import failed")
    board.Save(PCB)
    sys.path.insert(0, HERE)
    from gen_pcb import set_rules
    set_rules()   # pcbnew's Save() resets the net classes in the .kicad_pro


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--import-ses":
        return import_ses(sys.argv[2])
    ap = argparse.ArgumentParser()
    ap.add_argument("--jar", default=os.environ.get("FREEROUTING_JAR") or find_jar())
    ap.add_argument("--passes", type=int, default=60)
    a = ap.parse_args()
    if not a.jar or not os.path.exists(a.jar):
        sys.exit("freerouting jar not found (pass --jar or set FREEROUTING_JAR)")

    tmp = tempfile.mkdtemp()
    dsn, ses = os.path.join(tmp, "board.dsn"), os.path.join(tmp, "board.ses")
    board = pcbnew.LoadBoard(PCB)
    # Outer-layer pours would be exported as planes covering the whole layer and block
    # routing there. Leave them out of the DSN; they are refilled around the tracks later.
    for z in list(board.Zones()):
        if z.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu):
            board.Remove(z)
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        sys.exit("DSN export failed")
    print("DSN:", dsn)
    if "freerouting-1." in os.path.basename(a.jar):
        sys.exit("Freerouting 1.x always opens a window; use 2.x for headless runs")
    # Headless: no GUI, no DISPLAY, AWT headless. -mt 0 disables the multithreaded
    # optimizer, which produced incomplete session files with 2.1 on this board.
    cmd = [os.environ.get("FREEROUTING_JAVA") or find_java(a.jar), "-Djava.awt.headless=true", "-jar", a.jar, "--gui.enabled=false",
           "-de", dsn, "-do", ses, "-mp", str(a.passes), "-mt", "0"]
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    print(" ".join(cmd))
    subprocess.run(cmd, check=True, env=env)
    if not os.path.exists(ses):
        sys.exit("Freerouting produced no session file")
    # Freerouting sometimes writes single-point (degenerate) wires: 2.1 wrote 30 on this
    # board and left those nets open. They carry no copper; DRC reports any break left.
    broken = len(re.findall(r"\(path \S+ \d+\s+-?\d+ -?\d+\s*\)", open(ses).read()))
    if broken:
        print(f"WARNING: {broken} single-point wires in the session (dropped); check DRC")
    # A second LoadBoard() in the same process returns a bare SwigPyObject: import in a child.
    subprocess.run([sys.executable, os.path.abspath(__file__), "--import-ses", ses], check=True)
    print("routed ->", PCB, "(refill zones: kicad-cli pcb drc --refill-zones --save-board)")


if __name__ == "__main__":
    main()
