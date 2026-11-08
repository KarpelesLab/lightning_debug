#!/usr/bin/env python3
"""Place reference designators on the silkscreen so they clear pads, other silk and the edge.

    python3 tools/silk.py

For each footprint (big parts first) it tries spots around the courtyard, horizontal then
vertical, and keeps the first that is free. References with no free spot go to F.Fab
(kept in the fab drawing, not printed); the script lists them.
"""
import math
import os
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.abspath(os.path.join(HERE, "..", "lightning_debug.kicad_pcb"))
CLR = 0.2        # silk-to-silk and silk-to-pad clearance (mask expansion included)
EDGE = 0.3
TXT = 0.8        # small text height for passives
TOMM = pcbnew.ToMM


def rect_of(bbox, grow=0.0):
    return (TOMM(bbox.GetX()) - grow, TOMM(bbox.GetY()) - grow,
            TOMM(bbox.GetRight()) + grow, TOMM(bbox.GetBottom()) + grow)


def rects_hit(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def pt_rect_dist(px, py, r):
    dx = max(r[0] - px, 0, px - r[2])
    dy = max(r[1] - py, 0, py - r[3])
    return math.hypot(dx, dy)


def pt_seg_dist(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * vx + (py - ay) * vy) / L))
    return math.hypot(px - ax - t * vx, py - ay - t * vy)


def seg_hits_rect(s, r):
    ax, ay, bx, by, half = s
    # segment crosses rect?  sample-free test: Liang-Barsky clip
    t0, t1 = 0.0, 1.0
    dx, dy = bx - ax, by - ay
    for p, q in ((-dx, ax - r[0]), (dx, r[2] - ax), (-dy, ay - r[1]), (dy, r[3] - ay)):
        if p == 0:
            if q < 0:
                break
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
    else:
        if t0 <= t1:
            return True
    d = min(pt_rect_dist(ax, ay, r), pt_rect_dist(bx, by, r),
            *(pt_seg_dist(cx, cy, ax, ay, bx, by) for cx in (r[0], r[2]) for cy in (r[1], r[3])))
    return d < half


def main():
    board = pcbnew.LoadBoard(PCB)
    e = board.GetBoardEdgesBoundingBox()
    edge = (TOMM(e.GetX()) + EDGE, TOMM(e.GetY()) + EDGE, TOMM(e.GetRight()) - EDGE, TOMM(e.GetBottom()) - EDGE)

    rects, segs = [], []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.IsOnLayer(pcbnew.F_Cu) or p.IsOnLayer(pcbnew.F_Mask) or p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                rects.append(rect_of(p.GetBoundingBox(), CLR))
        for g in fp.GraphicalItems():
            if g.GetLayer() != pcbnew.F_SilkS or not isinstance(g, pcbnew.PCB_SHAPE):
                continue
            w = TOMM(g.GetWidth()) / 2 + CLR
            st = g.GetShape()
            if st == pcbnew.SHAPE_T_SEGMENT:
                a, b = g.GetStart(), g.GetEnd()
                segs.append((TOMM(a.x), TOMM(a.y), TOMM(b.x), TOMM(b.y), w))
            elif st == pcbnew.SHAPE_T_RECTANGLE or st == pcbnew.SHAPE_T_POLY:
                pts = [g.GetStart(), pcbnew.VECTOR2I(g.GetEnd().x, g.GetStart().y), g.GetEnd(),
                       pcbnew.VECTOR2I(g.GetStart().x, g.GetEnd().y)] if st == pcbnew.SHAPE_T_RECTANGLE \
                    else list(g.GetPolyShape().COutline(0).CPoints())
                for i in range(len(pts)):
                    a, b = pts[i], pts[(i + 1) % len(pts)]
                    segs.append((TOMM(a.x), TOMM(a.y), TOMM(b.x), TOMM(b.y), w))
            else:   # circle / arc: bounding ring approximated by its box edges
                r = rect_of(g.GetBoundingBox())
                for (ax, ay, bx, by) in ((r[0], r[1], r[2], r[1]), (r[2], r[1], r[2], r[3]),
                                         (r[2], r[3], r[0], r[3]), (r[0], r[3], r[0], r[1])):
                    segs.append((ax, ay, bx, by, w))
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.F_SilkS:
            rects.append(rect_of(d.GetBoundingBox(), CLR))

    def free(r):
        if r[0] < edge[0] or r[1] < edge[1] or r[2] > edge[2] or r[3] > edge[3]:
            return False
        return not any(rects_hit(r, o) for o in rects) and not any(seg_hits_rect(s, r) for s in segs)

    fps = sorted(board.GetFootprints(), key=lambda f: -TOMM(f.GetBoundingBox(False).GetWidth()) *
                 TOMM(f.GetBoundingBox(False).GetHeight()))
    hidden = []
    for fp in fps:
        t = fp.Reference()
        ref = t.GetText()
        if ref.startswith("H") or not t.IsVisible():
            continue
        if t.GetLayer() == pcbnew.F_Fab:
            t.SetLayer(pcbnew.F_SilkS)
        small = ref[0] in "RCDFY" or ref.startswith(("FB", "JP", "SW"))
        size = TXT if small else 1.0
        t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
        t.SetTextThickness(pcbnew.FromMM(size * 0.15))
        t.SetKeepUpright(True)
        try:
            fp.BuildCourtyardCaches()
            c = fp.GetCourtyard(pcbnew.F_CrtYd).BBox()
            cy = rect_of(c)
        except Exception:
            cy = rect_of(fp.GetBoundingBox(False))
        cx, cyy = (cy[0] + cy[2]) / 2, (cy[1] + cy[3]) / 2
        tw = len(ref) * size * 0.75 + 0.1
        th = size + 0.1
        cands = []
        for gap in (0.05, 0.4, 0.9):
            for horiz in (True, False):
                w, h = (tw, th) if horiz else (th, tw)
                cands += [
                    (cx, cy[1] - gap - h / 2, horiz), (cx, cy[3] + gap + h / 2, horiz),
                    (cy[0] - gap - w / 2, cyy, horiz), (cy[2] + gap + w / 2, cyy, horiz),
                ]
        if not small:   # big parts: inside the body outline is fine (no pads in the middle)
            cands = [(cx, cyy, True), (cx, cyy, False)] + cands
        placed = False
        for (x, y, horiz) in cands:
            w, h = (tw, th) if horiz else (th, tw)
            r = (x - w / 2, y - h / 2, x + w / 2, y + h / 2)
            if free(r):
                t.SetTextAngleDegrees(0 if horiz else 90)   # absolute (board) angle
                t.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
                rects.append((r[0] - CLR, r[1] - CLR, r[2] + CLR, r[3] + CLR))
                placed = True
                break
        if not placed:
            t.SetLayer(pcbnew.F_Fab)
            t.SetPosition(fp.GetPosition())
            hidden.append(ref)
        # value text is never printed
        fp.Value().SetLayer(pcbnew.F_Fab)
    board.Save(PCB)
    sys.path.insert(0, HERE)
    from gen_pcb import set_rules
    set_rules()
    print("refs moved to F.Fab (no room on silk):", ", ".join(sorted(hidden)) or "none")


if __name__ == "__main__":
    main()
