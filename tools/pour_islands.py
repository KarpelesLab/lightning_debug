#!/usr/bin/env python3
"""Keep reference copper under the routing: rescue pour islands with GND vias.

    python3 tools/pour_islands.py [board.kicad_pcb]

KiCad deletes pour islands that touch no pad or via of their net. On this board that
left large holes in the B.Cu GND pour and the In2 +3V3 pour wherever traces fence a
region in, so the In2 / B.Cu tracks above or below those holes had no adjacent plane.

  1. add a GND zone on In2 below the +3V3 pour (it fills what the +3V3 pour can't reach)
  2. fill the GND zones on B.Cu and In2 keeping all islands
  3. drop a GND via (to the solid In1 plane) into every island that has none, where a
     via fits; one via serves an In2 island and a B.Cu island at the same spot
  4. restore island removal and refill; islands too small for a via still get removed
"""
import os
import sys

import numpy as np
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import finish_route as fr  # noqa: E402

MM, TOMM = pcbnew.FromMM, pcbnew.ToMM
MIN_ISLAND_MM2 = 1.5            # smaller islands are left to be removed


def gnd_zone(board, layer):
    for z in board.Zones():
        if z.IsOnLayer(layer) and z.GetNetname() == "/GND" and not z.GetIsRuleArea():
            return z
    return None


def ensure_in2_gnd(board):
    z = gnd_zone(board, pcbnew.In2_Cu)
    if z:
        return z
    src = [z for z in board.Zones() if z.IsOnLayer(pcbnew.In2_Cu) and z.GetNetname() == "/+3V3"][0]
    src.SetAssignedPriority(max(1, src.GetAssignedPriority()))
    z = pcbnew.ZONE(board)
    z.SetLayer(pcbnew.In2_Cu)
    z.SetNet(board.FindNet("/GND"))
    z.SetAssignedPriority(0)
    ol = src.Outline()
    z.Outline().Append(ol)
    z.SetLocalClearance(src.GetLocalClearance())
    z.SetMinThickness(src.GetMinThickness())
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    board.Add(z)
    return z


def gnd_points(board):
    """Positions of GND vias and through-hole GND pads (connect every copper layer)."""
    pts = []
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA) and t.GetNetname() == "/GND":
            pts.append(t.GetPosition())
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() == "/GND" and p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                pts.append(p.GetPosition())
    return pts


def islands(zone, layer):
    """Filled polygons of the zone that contain no GND via / PTH pad."""
    ps = zone.GetFilledPolysList(layer)
    anchors = gnd_points(zone.GetBoard())
    out = []
    for k in range(ps.OutlineCount()):
        single = pcbnew.SHAPE_POLY_SET()
        single.AddOutline(ps.Outline(k))
        for h in range(ps.HoleCount(k)):
            single.AddHole(ps.Hole(k, h))
        if any(single.Contains(a) for a in anchors):
            continue
        # SMD GND pads on B.Cu also anchor a B.Cu island
        if layer == pcbnew.B_Cu and any(
                p.GetNetname() == "/GND" and p.IsOnLayer(layer) and single.Contains(p.GetPosition())
                for fp in zone.GetBoard().GetFootprints() for p in fp.Pads()):
            continue
        if single.Area() / 1e12 < MIN_ISLAND_MM2:
            continue
        out.append(single)
    return out


def main():
    path = next((a for a in sys.argv[1:] if not a.startswith("-")),
                os.path.join(HERE, "..", "lightning_debug.kicad_pcb"))
    board = pcbnew.LoadBoard(path)
    ensure_in2_gnd(board)
    zones = {l: gnd_zone(board, l) for l in (pcbnew.B_Cu, pcbnew.In2_Cu)}
    modes = {l: z.GetIslandRemovalMode() for l, z in zones.items()}
    for z in zones.values():
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())

    grid = fr.Grid(board)
    _, vb = fr.obstacle_maps(board, grid, "", 0.15)   # every item blocks a new via
    # the via must sit inside the island with its own pour clearance around it
    inset = TOMM(zones[pcbnew.B_Cu].GetLocalClearance()) + fr.VIA_D / 2 + 0.1

    todo = {l: islands(z, l) for l, z in zones.items()}
    print("islands without a GND connection:", {board.GetLayerName(l): len(v) for l, v in todo.items()})

    def masks(polys):
        out = []
        for p in polys:
            q = pcbnew.SHAPE_POLY_SET(p)
            q.Deflate(MM(inset), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, MM(0.01))
            out.append(grid.raster([q]) if q.OutlineCount() else None)
        return out

    m = {l: masks(v) for l, v in todo.items()}
    done = {l: [False] * len(v) for l, v in todo.items()}
    added = 0
    gnd = board.FindNet("/GND")
    # first pass: spots that serve an In2 and a B.Cu island at once, then single islands
    for both in (True, False):
        for la, lb in ((pcbnew.In2_Cu, pcbnew.B_Cu), (pcbnew.B_Cu, pcbnew.In2_Cu)):
            for ia, ma in enumerate(m[la]):
                if done[la][ia] or ma is None:
                    continue
                ok = ma & ~vb
                hit_b = None
                if both:
                    for ib, mb in enumerate(m[lb]):
                        if not done[lb][ib] and mb is not None and (ok & mb).any():
                            ok, hit_b = ok & mb, ib
                            break
                    if hit_b is None:
                        continue
                js, is_ = np.nonzero(ok)
                if not len(js):
                    continue
                # most interior free cell: the one farthest from blocked cells (approx: median)
                k = len(js) // 2
                x, y = (float(c) for c in grid.xy(int(is_[k]), int(js[k])))
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
                v.SetWidth(MM(fr.VIA_D))
                v.SetDrill(MM(fr.VIA_DRILL))
                v.SetNet(gnd)
                board.Add(v)
                added += 1
                r = int((fr.VIA_D + fr.CLEAR + 0.3) / fr.RES)
                vb[max(0, js[k] - r):js[k] + r + 1, max(0, is_[k] - r):is_[k] + r + 1] = True
                done[la][ia] = True
                if hit_b is not None:
                    done[lb][hit_b] = True
    left = {board.GetLayerName(l): done[l].count(False) for l in done}
    print(f"added {added} GND vias; islands left without a via (will be removed): {left}")

    for l, z in zones.items():
        z.SetIslandRemovalMode(modes[l])
    filler.Fill(board.Zones())
    board.Save(path)


if __name__ == "__main__":
    main()
