#!/usr/bin/env python3
"""Finish an autorouted board: rip up what DRC flags, re-route open connections, stitch GND.

    python3 tools/finish_route.py [board.kicad_pcb] [--rounds N]

Loop (until DRC is clean or nothing changes):
  1. run DRC (kicad-cli, zones refilled)
  2. delete items DRC flags: dangling vias/tracks, items too close to the board edge or to
     other copper (the shorter/cheaper item of each pair), signal tracks on the inner plane
     layers (In1 = GND reference, In2 = +3V3)
  3. route every open connection with a grid A* on F.Cu / B.Cu (0.05 mm grid, design
     clearances + grid margin), vias where both outer layers and the inner layers are free
Once at the start: GND stitching vias on a 4 mm grid wherever they fit, and every via is
resized to its net class diameter/drill (fixes too-thin annular rings).
"""
import heapq
import math
import os
import re
import subprocess
import sys
import tempfile

import numpy as np
import pcbnew
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RES = 0.05                      # grid (mm)
GRID_MARGIN = 0.04              # covers grid discretisation
CLEAR = 0.15                    # copper clearance (net class)
EDGE = 0.4                      # copper to board edge
HOLE_CLEAR = 0.25               # copper to other-net hole
VIA_D, VIA_DRILL = 0.5, 0.3
PLANE_NETS = {"/GND", "/+3V3"}
OUTER = (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In2_Cu)   # routing layers (In2: the +3V3 pour flows around)
INNER = (pcbnew.In1_Cu,)                             # kept free of tracks (GND reference)
KEEP = []                                            # removed board items (see rip-up)
ROUTE = OUTER                                        # layers the A* uses (In1 added as last resort)
MM = pcbnew.FromMM
TOMM = pcbnew.ToMM


def drc(pcb):
    rpt = os.path.join(tempfile.mkdtemp(), "drc.rpt")
    subprocess.run(["kicad-cli", "pcb", "drc", "--refill-zones", "--save-board", "--schematic-parity",
                    "-o", rpt, pcb], capture_output=True)
    items = []
    lines = open(rpt).read().split("\n")
    i = 0
    while i < len(lines):
        m = re.match(r"\[(\w+)\]: (.*)", lines[i])
        if m:
            kind, locs, sev = m.group(1), [], ""
            j = i + 1
            while j < len(lines) and not lines[j].startswith("["):
                lm = re.match(r"\s+@\(([-\d.]+) mm, ([-\d.]+) mm\): (.*)", lines[j])
                if lm:
                    locs.append((float(lm.group(1)), float(lm.group(2)), lm.group(3)))
                elif "; error" in lines[j] or "; warning" in lines[j]:
                    sev = "error" if "error" in lines[j] else "warning"
                j += 1
            items.append((kind, locs, sev))
            i = j
        else:
            i += 1
    return items


def netclass_of(board, net):
    try:
        return board.GetDesignSettings().m_NetSettings.GetEffectiveNetClass(net)
    except Exception:
        return None


def net_width(board, netname):
    w = {"Power": 0.5, "USB_HS": 0.28}
    if re.match(r"^/(VBUS1|VBUS2|\+5V|LS_IN|LTG_PWR)$", netname):
        return w["Power"]
    if re.match(r"^/(USB._D.|._L0.|L0._._M)$", netname):
        return w["USB_HS"]
    return 0.15


class Grid:
    def __init__(self, board):
        e = board.GetBoardEdgesBoundingBox()
        self.x0, self.y0 = TOMM(e.GetX()), TOMM(e.GetY())
        self.x1, self.y1 = TOMM(e.GetRight()), TOMM(e.GetBottom())
        self.nx = int(round((self.x1 - self.x0) / RES)) + 1
        self.ny = int(round((self.y1 - self.y0) / RES)) + 1

    def ij(self, x, y):
        return int(round((x - self.x0) / RES)), int(round((y - self.y0) / RES))

    def xy(self, i, j):
        return self.x0 + i * RES, self.y0 + j * RES

    def raster(self, polysets):
        img = Image.new("1", (self.nx, self.ny), 0)
        d = ImageDraw.Draw(img)
        for ps in polysets:
            for k in range(ps.OutlineCount()):
                ol = ps.COutline(k)
                pts = [((TOMM(p.x) - self.x0) / RES, (TOMM(p.y) - self.y0) / RES) for p in ol.CPoints()]
                if len(pts) >= 3:
                    d.polygon(pts, fill=1, outline=1)
        return np.array(img, dtype=bool)


def item_poly(item, layer, clearance):
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, MM(clearance), MM(0.005), pcbnew.ERROR_OUTSIDE)
    return ps


def hole_poly(pos, drill, clearance):
    ps = pcbnew.SHAPE_POLY_SET()
    r = drill / 2 + clearance
    ol = pcbnew.SHAPE_LINE_CHAIN()
    for k in range(24):
        a = 2 * math.pi * k / 24
        ol.Append(MM(TOMM(pos.x) + r * math.cos(a)), MM(TOMM(pos.y) + r * math.sin(a)))
    ol.SetClosed(True)
    ps.AddOutline(ol)
    return ps


def copper_items(board):
    for fp in board.GetFootprints():
        for p in fp.Pads():
            yield p
    for t in board.GetTracks():
        yield t


def layers_of(item):
    if isinstance(item, pcbnew.PCB_VIA):
        return list(OUTER + INNER)
    if isinstance(item, pcbnew.PAD):
        return [l for l in OUTER + INNER if item.IsOnLayer(l)]
    return [item.GetLayer()]


def obstacle_maps(board, grid, netname, width, exclude=frozenset()):
    """blocked[layer] for track centrelines of `width` on outer layers; via_blocked for vias."""
    tr_inf = width / 2 + CLEAR + GRID_MARGIN
    via_inf = VIA_D / 2 + CLEAR + GRID_MARGIN
    polys = {l: [] for l in ROUTE}
    vpolys = []
    for it in copper_items(board):
        if exclude and it.m_Uuid.AsString() in exclude:
            continue
        same = netname != "" and it.GetNetname() == netname
        if isinstance(it, pcbnew.PAD) and it.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            hp = hole_poly(it.GetPosition(), TOMM(it.GetDrillSize().x), 0)
            for l in ROUTE:
                polys[l].append(hole_poly(it.GetPosition(), TOMM(it.GetDrillSize().x), width / 2 + HOLE_CLEAR + GRID_MARGIN))
            vpolys.append(hole_poly(it.GetPosition(), TOMM(it.GetDrillSize().x), VIA_D / 2 + HOLE_CLEAR + GRID_MARGIN))
            continue
        if same:
            continue
        for l in layers_of(it):
            if l in ROUTE:
                polys[l].append(item_poly(it, l, tr_inf))
            if not (l in INNER + (pcbnew.In2_Cu,) and isinstance(it, pcbnew.PAD) and it.GetAttribute() == pcbnew.PAD_ATTRIB_SMD):
                vpolys.append(item_poly(it, l, via_inf))
        # other-net drilled holes: hole clearance for new vias
        drill = 0
        if isinstance(it, pcbnew.PCB_VIA):
            drill = TOMM(it.GetDrill())
        elif isinstance(it, pcbnew.PAD) and it.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            drill = TOMM(it.GetDrillSize().x)
        if drill:
            vpolys.append(hole_poly(it.GetPosition(), drill, VIA_DRILL / 2 + HOLE_CLEAR + GRID_MARGIN))
    if pcbnew.In1_Cu in ROUTE:
        # In1 fallback: stay 1 mm away from anything on the high-speed USB / L0 nets
        for it in copper_items(board):
            if re.match(r"^/(USB._D.|._L0.|L0._._M)$", it.GetNetname()):
                for l in layers_of(it):
                    if l in (pcbnew.F_Cu, pcbnew.B_Cu):
                        polys[pcbnew.In1_Cu].append(item_poly(it, l, 1.0 + width / 2))
    blocked = {l: grid.raster(polys[l]) for l in ROUTE}
    vb = grid.raster(vpolys)
    # board edge
    em = int(math.ceil((EDGE + width / 2 + GRID_MARGIN) / RES))
    vm = int(math.ceil((EDGE + VIA_D / 2 + GRID_MARGIN) / RES))
    for b, m in [(blocked[l], em) for l in ROUTE] + [(vb, vm)]:
        b[:m, :] = True
        b[-m:, :] = True
        b[:, :m] = True
        b[:, -m:] = True
    return blocked, vb


def cluster_cells(board, grid, items):
    """Cells covered by the copper of `items` on each outer layer."""
    cells = {l: [] for l in ROUTE}
    for it in items:
        for l in layers_of(it):
            if l in ROUTE:
                cells[l].append(item_poly(it, l, -0.02))
    return {l: grid.raster(cells[l]) for l in ROUTE}


def astar(grid, blocked, vb, start, goal, via_cost=30):
    L = ROUTE
    INF = float("inf")
    anyg = np.zeros_like(goal[L[0]])
    for l in L:
        anyg |= goal[l]
    gy, gx = np.nonzero(anyg)
    if len(gx) == 0:
        return None
    gpts = np.stack([gx, gy], 1)
    sub = gpts[:: max(1, len(gpts) // 64)]

    def h(i, j):
        d = np.abs(sub - (i, j))
        dd = d.min(1) + (math.sqrt(2) - 1) * d.max(1).clip(0) * 0
        return float(np.min(np.maximum(d[:, 0], d[:, 1]) + (math.sqrt(2) - 1) * np.minimum(d[:, 0], d[:, 1])))

    openq, came, g = [], {}, {}
    for li, l in enumerate(L):
        ys, xs = np.nonzero(start[l])
        for i, j in zip(xs, ys):
            n = (li, int(i), int(j))
            g[n] = 0
            heapq.heappush(openq, (h(i, j), 0, n))
    dirs = [(1, 0, 1), (-1, 0, 1), (0, 1, 1), (0, -1, 1), (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]
    hcache = {}
    seen = 0
    while openq:
        f, gc, n = heapq.heappop(openq)
        if gc > g.get(n, INF):
            continue
        li, i, j = n
        if goal[L[li]][j, i]:
            path = [n]
            while path[-1] in came:
                path.append(came[path[-1]])
            return path[::-1]
        seen += 1
        if seen > 3_000_000:
            return None
        nbrs = []
        for di, dj, c in dirs:
            a, b = i + di, j + dj
            if 0 <= a < grid.nx and 0 <= b < grid.ny and (not blocked[L[li]][b, a] or goal[L[li]][b, a] or start[L[li]][b, a]):
                nbrs.append(((li, a, b), c))
        if not vb[j, i]:
            for lo in range(len(L)):
                if lo != li:
                    nbrs.append(((lo, i, j), via_cost + {pcbnew.In2_Cu: 10, pcbnew.In1_Cu: 200}.get(L[lo], 0)))
        for m, c in nbrs:
            ng = gc + c
            if ng < g.get(m, INF):
                g[m] = ng
                came[m] = n
                k = (m[1] // 8, m[2] // 8)
                hv = hcache.get(k)
                if hv is None:
                    hv = hcache[k] = h(m[1], m[2])
                heapq.heappush(openq, (ng + hv, ng, m))
    return None


def emit(board, grid, path, net, width, layers):
    """Turn a cell path into tracks + vias."""
    L = layers
    added = 0
    run = [path[0]]

    def flush(run):
        nonlocal added
        if len(run) < 2:
            return
        pts = [run[0]]
        for k in range(1, len(run) - 1):
            a, b, c = run[k - 1], run[k], run[k + 1]
            if (b[1] - a[1], b[2] - a[2]) != (c[1] - b[1], c[2] - b[2]):
                pts.append(b)
        pts.append(run[-1])
        for a, b in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(MM(grid.xy(a[1], a[2])[0]), MM(grid.xy(a[1], a[2])[1])))
            t.SetEnd(pcbnew.VECTOR2I(MM(grid.xy(b[1], b[2])[0]), MM(grid.xy(b[1], b[2])[1])))
            t.SetWidth(MM(width))
            t.SetLayer(L[a[0]])
            t.SetNet(net)
            board.Add(t)
            added += 1

    for n in path[1:]:
        if n[0] != run[-1][0]:
            flush(run)
            v = pcbnew.PCB_VIA(board)
            x, y = grid.xy(n[1], n[2])
            v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
            v.SetWidth(MM(VIA_D))
            v.SetDrill(MM(VIA_DRILL))
            v.SetNet(net)
            board.Add(v)
            run = [n]
        else:
            run.append(n)
    flush(run)
    return added


def find_item(board, x, y, desc):
    """Map a DRC location + description back to a board item."""
    pos = pcbnew.VECTOR2I(MM(x), MM(y))
    m = re.search(r"\[([^\]]*)\]", desc)
    net = m.group(1) if m else None
    best, bd = None, 1e9
    cands = []
    if desc.startswith(("Pad", "PTH pad", "NPTH pad")):
        cands = [p for fp in board.GetFootprints() for p in fp.Pads()]
    elif desc.startswith("Via"):
        cands = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)]
    elif desc.startswith("Track"):
        cands = [t for t in board.GetTracks() if not isinstance(t, pcbnew.PCB_VIA)]
    for c in cands:
        if net and c.GetNetname() != net:
            continue
        if c.HitTest(pos, MM(0.01)):
            d = (c.GetPosition() - pos).EuclideanNorm() if hasattr(c.GetPosition() - pos, "EuclideanNorm") else 0
            if d < bd:
                best, bd = c, d
    return best


def connected_cluster(board, item):
    """All copper of item's net touching item (transitively), on any layer."""
    net = item.GetNetname()
    items = [p for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetname() == net]
    items += [t for t in board.GetTracks() if t.GetNetname() == net]
    shapes = {}

    def poly(it, l):
        k = (id(it), l)
        if k not in shapes:
            shapes[k] = item_poly(it, l, 0.001)
        return shapes[k]

    cl, todo = {id(item): item}, [item]
    while todo:
        a = todo.pop()
        for b in items:
            if id(b) in cl:
                continue
            common = set(layers_of(a)) & set(layers_of(b))
            for l in common:
                pa, pb = poly(a, l), poly(b, l)
                inter = pcbnew.SHAPE_POLY_SET(pa)
                inter.BooleanIntersection(pb)
                if inter.OutlineCount():
                    cl[id(b)] = b
                    todo.append(b)
                    break
    return list(cl.values())


def fix_vias(board):
    n = 0
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            d, dr = TOMM(t.GetWidth(pcbnew.F_Cu)), TOMM(t.GetDrill())
            want = 0.8 if dr > 0.35 else VIA_D
            if d < dr + 0.2 - 1e-6 or d < want - 1e-6:
                t.SetWidth(MM(max(want, dr + 0.2)))
                n += 1
    return n


def stitch(board, grid, pitch=4.0):
    gnd = board.FindNet("/GND")
    _, vb = obstacle_maps(board, grid, "", 0.15)     # "" = every via/pad is an obstacle
    # don't stitch under parts (courtyards) to keep assembly / rework clean
    cy = []
    for fp in board.GetFootprints():
        try:
            fp.BuildCourtyardCaches()
            c = fp.GetCourtyard(pcbnew.F_CrtYd)
            if c.OutlineCount():
                cy.append(c)
        except Exception:
            pass
    cyb = grid.raster(cy)
    n = 0
    y = grid.y0 + 2.0
    while y < grid.y1 - 1.5:
        x = grid.x0 + 2.0
        while x < grid.x1 - 1.5:
            i, j = grid.ij(x, y)
            if not vb[j, i] and not cyb[j, i]:
                v = pcbnew.PCB_VIA(board)
                v.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
                v.SetWidth(MM(VIA_D))
                v.SetDrill(MM(VIA_DRILL))
                v.SetNet(gnd)
                board.Add(v)
                n += 1
            x += pitch
        y += pitch
    return n


def main():
    global ROUTE
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    pcb = os.path.abspath(args[0]) if args else os.path.join(HERE, "..", "lightning_debug.kicad_pcb")
    rounds = 30
    if "--rounds" in sys.argv:
        rounds = int(sys.argv[sys.argv.index("--rounds") + 1])
    os.environ.setdefault("PCB_FILE", pcb)
    from gen_pcb import set_rules

    board = pcbnew.LoadBoard(pcb)
    grid = Grid(board)
    # In1 tracks cut the GND reference plane: rip them up, they get re-routed elsewhere
    # (run this script on a fresh autorouter result: it also rips its own In1 fallback tracks)
    inner = [t for t in board.GetTracks() if t.GetLayer() in INNER and not isinstance(t, pcbnew.PCB_VIA)]
    for t in inner:
        board.Remove(t)
    KEEP.extend(inner)
    print(f"ripped {len(inner)} inner-layer track segments; resized {fix_vias(board)} vias; "
          f"added {stitch(board, grid)} GND stitching vias")
    board.Save(pcb)
    set_rules()

    last = None
    ripped_any = False
    for rnd in range(rounds):
        items = drc(pcb)
        board = pcbnew.LoadBoard(pcb)
        errs = [(k, l) for k, l, s in items if s == "error" and not k.startswith("silk")]
        summary = {}
        for k, _ in errs:
            summary[k] = summary.get(k, 0) + 1
        print(f"round {rnd}: {summary or 'clean'}")
        if not errs or (summary == last and not ripped_any):
            break
        ripped_any = False
        last = summary
        # ---- rip up
        kill = {}
        for k, locs in errs:
            if k in ("via_dangling", "track_dangling", "copper_edge_clearance", "annular_width"):
                for x, y, d in locs:
                    if d.startswith(("Via", "Track")):
                        it = find_item(board, x, y, d)
                        if it:
                            kill[id(it)] = it
            elif k in ("clearance", "hole_clearance", "shorting_items", "tracks_crossing"):
                its = [find_item(board, x, y, d) for x, y, d in locs if d.startswith(("Via", "Track"))]
                its = [i for i in its if i is not None]
                if its:
                    # remove the shorter track / the via
                    its.sort(key=lambda t: 0 if isinstance(t, pcbnew.PCB_VIA) else TOMM(t.GetLength()))
                    kill[id(its[0])] = its[0]
        for it in kill.values():
            board.Remove(it)
        KEEP.extend(kill.values())
        if kill:
            print(f"  ripped {len(kill)} items")
            board.Save(pcb)
            set_rules()
            items = drc(pcb)
            board = pcbnew.LoadBoard(pcb)
            errs = [(k, l) for k, l, s in items if s == "error" and not k.startswith("silk")]
        # ---- re-route open connections
        routed = failed = 0
        for k, locs in errs:
            if k != "unconnected_items" or len(locs) != 2:
                continue
            (xa, ya, da), (xb, yb, db) = locs
            a, b = find_item(board, xa, ya, da), find_item(board, xb, yb, db)
            if da.startswith("Zone") or a is None or b is None:
                continue
            net = a.GetNet()
            name = a.GetNetname()
            ca, cb = connected_cluster(board, a), connected_cluster(board, b)
            if set(map(id, ca)) & set(map(id, cb)):
                continue
            width = net_width(board, name)
            blocked, vb = obstacle_maps(board, grid, name, width)
            start, goal = cluster_cells(board, grid, ca), cluster_cells(board, grid, cb)
            path = astar(grid, blocked, vb, start, goal)
            path_layers = OUTER
            if path is None and name not in PLANE_NETS:
                # last resort: In1 too (expensive, keeps 1 mm from the USB nets)
                ROUTE = OUTER + INNER
                blocked, vb = obstacle_maps(board, grid, name, width)
                start, goal = cluster_cells(board, grid, ca), cluster_cells(board, grid, cb)
                path = astar(grid, blocked, vb, start, goal)
                if path:
                    print(f"  {name}: routed using In1")
                    path_layers = ROUTE
            if path is None and name in PLANE_NETS:
                # plane nets: a via to the plane next to each side is enough
                path = None
            ROUTE = OUTER
            ripped_up = False
            if path is None and rnd < rounds - 2:
                # rip-up: free the blocked endpoint(s) by removing other nets' tracks
                # around them, route this connection, re-route the victims next round
                victims = {}
                for it in (a, b):
                    zone = item_poly(it, pcbnew.F_Cu if it.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu, 0.6)
                    for t in board.GetTracks():
                        if t.GetNetname() == name or t.GetNetname() in PLANE_NETS or t.GetLayer() == pcbnew.In1_Cu:
                            continue
                        if isinstance(t, pcbnew.PCB_VIA) or t.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu):
                            inter = pcbnew.SHAPE_POLY_SET(zone)
                            inter.BooleanIntersection(item_poly(t, pcbnew.F_Cu, 0))
                            if inter.OutlineCount():
                                victims[t.m_Uuid.AsString()] = t
                blocked, vb = obstacle_maps(board, grid, name, width, frozenset(victims))
                path = astar(grid, blocked, vb, start, goal)
                if path:
                    for t in victims.values():
                        board.Remove(t)
                    KEEP.extend(victims.values())   # never let SWIG free removed items
                    print(f"  {name}: routed after ripping {len(victims)} neighbour items")
                    ripped_up = ripped_any = True
            if path:
                emit(board, grid, path, net, width, path_layers)
                routed += 1
                if ripped_up:
                    break       # board items changed under us: fresh DRC + board next round
            else:
                failed += 1
                print(f"  could not route {name}: {da} -> {db}")
        print(f"  routed {routed}, failed {failed}")
        board.Save(pcb)
        set_rules()
    items = drc(pcb)
    left = [(k, l) for k, l, s in items if s == "error" and not k.startswith("silk")]
    print("final:", {k: sum(1 for kk, _ in left if kk == k) for k, _ in left} or "clean")


if __name__ == "__main__":
    main()
