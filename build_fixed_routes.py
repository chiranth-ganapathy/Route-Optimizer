import sumolib
import xml.etree.ElementTree as ET

NET_FILE = r"output\bangalore_corridor.net.xml"
ORIGIN_NODE = "cluster_10282796511_1723795924"
DEST_NODE = "2412141879"
TOTAL_DEMAND = 2660
ORR_SPLIT = 0.54
SARJ_SPLIT = 0.46

def path_edges_for_route(net, penalized_ids=None):
    try:
        origin_node = net.getNode(ORIGIN_NODE)
    except KeyError:
        print(f"ERROR: origin node '{ORIGIN_NODE}' not found.")
        for n in net.getNodes():
            if "10282796511" in n.getID() or "1723795924" in n.getID():
                print(" ", n.getID())
        return None
    try:
        dest_node = net.getNode(DEST_NODE)
    except KeyError:
        print(f"ERROR: destination node '{DEST_NODE}' not found.")
        return None

    from_edges = origin_node.getOutgoing()
    to_edges = dest_node.getIncoming()
    print(f"  Origin has {len(from_edges)} outgoing edges")
    print(f"  Destination has {len(to_edges)} incoming edges")

    if not from_edges or not to_edges:
        print("ERROR: no connected edges in expected direction")
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
        print("ERROR: no path found")
        return None
    return [e.getID() for e in best[1]]

net = sumolib.net.readNet(NET_FILE)

print("Finding Route 1 (ORR)...")
orr_edges = path_edges_for_route(net)
if orr_edges is None:
    print("FAILED. Using fallback.")
else:
    print(f"  Found: {len(orr_edges)} edges")
    print("Finding Route 2 (Sarjapur, penalized)...")
    sarj_edges = path_edges_for_route(net, penalized_ids=set(orr_edges))
    if sarj_edges is None:
        print("FAILED. Using fallback.")
    else:
        print(f"  Found: {len(sarj_edges)} edges")
        overlap = set(orr_edges) & set(sarj_edges)
        overlap_pct = len(overlap) / len(orr_edges) * 100
        print(f"Overlap: {overlap_pct:.1f}%")
        if overlap_pct > 50:
            print("FAILED: too much overlap. Using fallback.")
        else:
            print("PASSED")
            root = ET.Element("routes")
            ET.SubElement(root, "route", id="route_orr", edges=" ".join(orr_edges))
            ET.SubElement(root, "route", id="route_sarj", edges=" ".join(sarj_edges))
            n_orr = int(TOTAL_DEMAND * ORR_SPLIT)
            n_sarj = TOTAL_DEMAND - n_orr
            for i in range(n_orr):
                depart = 3600 * i / n_orr
                ET.SubElement(root, "vehicle", id=f"orr_{i}", route="route_orr", depart=f"{depart:.1f}")
            for i in range(n_sarj):
                depart = 3600 * i / n_sarj
                ET.SubElement(root, "vehicle", id=f"sarj_{i}", route="route_sarj", depart=f"{depart:.1f}")
            tree = ET.ElementTree(root)
            ET.indent(tree, space="  ")
            tree.write(r"output\trips_fixed_routes.rou.xml", encoding="UTF-8", xml_declaration=True)
            print("Wrote output\\trips_fixed_routes.rou.xml")
            print(f"ORR: {n_orr} vehicles, Sarjapur: {n_sarj} vehicles")
            print(r'Run: sumo-gui -n output\bangalore_corridor.net.xml -r output\trips_fixed_routes.rou.xml')
