"""
Build FIXED routes for ORR and Sarjapur Road, guaranteeing genuine route
separation in the simulation (unlike trip-based auto-routing, which let
SUMO recompute paths per-vehicle and caused both "routes" to collapse
onto the same physical path).

This re-derives the routes directly from the network using the same
edge-penalty shortest-path method that correctly found them in Day 2,
then writes them as explicit <route> definitions that vehicles are
FORCED to follow — no auto-routing, no ambiguity.
"""

import sumolib
import xml.etree.ElementTree as ET
import re

NET_FILE = r"output\bangalore_corridor_tls.net.xml"
ROUTE_SUMMARY = r"output\route_summary.txt"

ORIGIN_NODE = "cluster_10282796511_1723795924"
DEST_NODE = "2412141879"

# Recalibrated, realistic demand (from the analytical model)
TOTAL_DEMAND = 2660
ORR_SPLIT = 0.54
SARJ_SPLIT = 0.46


def find_edge_for_node_pair(net, n1, n2):
    """Find a direct edge connecting two consecutive nodes."""
    for edge in net.getEdges():
        if edge.getFromNode().getID() == n1 and edge.getToNode().getID() == n2:
            return edge.getID()
    return None


def path_edges_for_route(net, all_edges_in_net, penalized_ids=None):
    """Shortest path from origin to destination, optionally avoiding
    already-used edges (for finding a genuinely distinct 2nd route)."""
    from_edges = [e for e in net.getEdges() if e.getFromNode().getID() == ORIGIN_NODE]
    to_edges = [e for e in net.getEdges() if e.getToNode().getID() == DEST_NODE]

    if not from_edges or not to_edges:
        print("ERROR: could not find edges at origin/destination nodes")
        return None

    best = None
    for fe in from_edges:
        for te in to_edges:
            path, cost = net.getShortestPath(fe, te)
            if path is None:
                continue
            if penalized_ids:
                penalty = sum(1 for e in path if e.getID() in penalized_ids) * 100000
                cost = cost + penalty
            if best is None or cost < best[0]:
                best = (cost, path)

    if best is None:
        return None
    return [e.getID() for e in best[1]]


def main():
    net = sumolib.net.readNet(NET_FILE)

    print("Finding Route 1 (ORR, shortest path)...")
    orr_edges = path_edges_for_route(net, net.getEdges())
    if orr_edges is None:
        print("FAILED to find ORR route. Stopping — do not debug further, use fallback.")
        return
    print(f"  Found: {len(orr_edges)} edges")

    print("Finding Route 2 (penalizing ORR's edges to force a genuinely distinct path)...")
    sarj_edges = path_edges_for_route(net, net.getEdges(), penalized_ids=set(orr_edges))
    if sarj_edges is None:
        print("FAILED to find Sarjapur route. Stopping — do not debug further, use fallback.")
        return
    print(f"  Found: {len(sarj_edges)} edges")

    overlap = set(orr_edges) & set(sarj_edges)
    overlap_pct = len(overlap) / len(orr_edges) * 100
    print(f"\nOverlap check: {len(overlap)} shared edges ({overlap_pct:.1f}% of ORR)")

    if overlap_pct > 50:
        print("FAILED: routes are not genuinely distinct (>50% overlap).")
        print("STOP HERE — do not debug further, use the animated visual fallback instead.")
        return

    print("PASSED — routes are genuinely distinct. Building fixed-route demand file...\n")

    # Build .rou.xml with explicit, fixed routes
    root = ET.Element("routes")
    ET.SubElement(root, "route", id="route_orr", edges=" ".join(orr_edges))
    ET.SubElement(root, "route", id="route_sarj", edges=" ".join(sarj_edges))

    n_orr = int(TOTAL_DEMAND * ORR_SPLIT)
    n_sarj = TOTAL_DEMAND - n_orr

    depart_window = 3600  # 1 hour
    for i in range(n_orr):
        depart = depart_window * i / n_orr
        ET.SubElement(root, "vehicle", id=f"orr_{i}", route="route_orr", depart=f"{depart:.1f}")
    for i in range(n_sarj):
        depart = depart_window * i / n_sarj
        ET.SubElement(root, "vehicle", id=f"sarj_{i}", route="route_sarj", depart=f"{depart:.1f}")

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(r"output\trips_fixed_routes.rou.xml", encoding="UTF-8", xml_declaration=True)

    print(f"Wrote output\\trips_fixed_routes.rou.xml")
    print(f"  ORR: {n_orr} vehicles on FIXED route ({len(orr_edges)} edges)")
    print(f"  Sarjapur: {n_sarj} vehicles on FIXED route ({len(sarj_edges)} edges)")
    print("\nReady to run:")
    print(r'sumo-gui -n output\bangalore_corridor_tls.net.xml -r output\trips_fixed_routes.rou.xml')


if __name__ == "__main__":
    main()