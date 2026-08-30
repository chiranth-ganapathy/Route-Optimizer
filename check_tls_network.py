"""
Check TLS junctions in new network and run smoke test.
"""
import sys
import math
import numpy as np
import subprocess
import xml.etree.ElementTree as ET
import sumolib
from pathlib import Path

OUTPUT_DIR = Path(r"d:\razorpay\output")
OLD_NET = OUTPUT_DIR / "bangalore_corridor.net.xml"
NEW_NET = OUTPUT_DIR / "bangalore_corridor_tls.net.xml"
ROU_FILE = OUTPUT_DIR / "trips.rou.xml"
TRIPINFO_FILE = OUTPUT_DIR / "tripinfo_tls.xml"

ORIG_EDGE = "1167293938"
DEST_EDGE = "1316838535"
DURATION_SECONDS = 3600

def get_route_path(net):
    orig = net.getEdge(ORIG_EDGE)
    dest = net.getEdge(DEST_EDGE)
    path, _ = net.getShortestPath(orig, dest)
    return path

def analyze_junctions(net, path_edges, label):
    signalized, priority, other = 0, 0, 0
    nodes = set()
    for e in path_edges:
        nodes.add(e.getToNode())
    for n in nodes:
        t = n.getType()
        if "traffic_light" in t:
            signalized += 1
        elif "priority" in t or "right_before_left" in t:
            priority += 1
        else:
            other += 1
    print(f"\n  Junction Analysis [{label}] ({len(nodes)} junctions):")
    print(f"    Signalized (Traffic Lights): {signalized}")
    print(f"    Priority / Uncontrolled:     {priority}")
    print(f"    Other:                       {other}")
    return signalized, priority, other

def generate_trips(demand, orig_edge, dest_edge):
    np.random.seed(42)
    mu = DURATION_SECONDS / 2
    sigma = DURATION_SECONDS / 6
    depart_times = np.random.normal(mu, sigma, int(demand))
    depart_times = np.clip(depart_times, 0, DURATION_SECONDS - 1)
    depart_times = np.sort(depart_times)
    with open(ROU_FILE, 'w') as f:
        f.write('<routes>\n')
        f.write('    <vType id="car" vClass="passenger" maxSpeed="20.0" accel="2.6" decel="4.5" length="4.5" minGap="2.5" />\n')
        for i, t in enumerate(depart_times):
            f.write(f'    <trip id="veh_{i}" type="car" depart="{t:.1f}" from="{orig_edge}" to="{dest_edge}" />\n')
        f.write('</routes>\n')

def run_and_parse(net_file, tripinfo_file, demand):
    generate_trips(demand, ORIG_EDGE, DEST_EDGE)
    cmd = [
        "sumo", "-n", str(net_file), "-r", str(ROU_FILE),
        "--tripinfo-output", str(tripinfo_file),
        "--no-step-log", "--ignore-route-errors", "false"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    warnings = [l for l in result.stderr.splitlines() if "Warning" in l]
    teleports = len([l for l in result.stderr.splitlines() if "Teleporting" in l])

    durations, lengths = [], []
    if tripinfo_file.exists():
        tree = ET.parse(tripinfo_file)
        for ti in tree.getroot().findall('tripinfo'):
            durations.append(float(ti.get('duration')))
            lengths.append(float(ti.get('routeLength')))

    completed = len(durations)
    if completed > 0:
        avg_dur = sum(durations) / completed
        avg_len = sum(lengths) / completed
        avg_speed_kmh = (avg_len / avg_dur) * 3.6
    else:
        avg_dur, avg_speed_kmh = 0, 0

    return completed, avg_dur, avg_speed_kmh, len(warnings), teleports

def main():
    print("=" * 65)
    print("CHECKING OLD NETWORK JUNCTIONS (bangalore_corridor.net.xml)")
    print("=" * 65)
    old_net = sumolib.net.readNet(str(OLD_NET))
    old_path = get_route_path(old_net)
    print(f"  Path: {len(old_path)} edges")
    analyze_junctions(old_net, old_path, "OLD")

    print("\n" + "=" * 65)
    print("CHECKING NEW NETWORK JUNCTIONS (bangalore_corridor_tls.net.xml)")
    print("=" * 65)
    new_net = sumolib.net.readNet(str(NEW_NET))
    # Find new edge IDs near the same coords as ORIG/DEST
    import math as _m
    def nearest_edge(net, lon, lat):
        x, y = net.convertLonLat2XY(lon, lat)
        best, bdist = None, 1e9
        for e in net.getEdges():
            sh = e.getShape()
            mx, my = sh[len(sh)//2]
            d = _m.hypot(mx-x, my-y)
            if d < bdist:
                best, bdist = e, d
        return best

    new_orig = nearest_edge(new_net, 77.622657, 12.917213)
    new_dest = nearest_edge(new_net, 77.700943, 12.956748)
    print(f"  New origin edge: {new_orig.getID()} (type: {new_orig.getType()})")
    print(f"  New dest edge:   {new_dest.getID()} (type: {new_dest.getType()})")
    new_path, _ = new_net.getShortestPath(new_orig, new_dest)
    if not new_path:
        print("  ERROR: No path found in new network!")
        return
    print(f"  Path: {len(new_path)} edges")
    sig, prio, oth = analyze_junctions(new_net, new_path, "NEW with TLS")

    print("\n" + "=" * 65)
    print("SMOKE TEST: 7830 vehicles vs NEW TLS network")
    print("=" * 65)
    # We need to regenerate trips using the new origin/dest edges if they changed
    new_orig_id = new_orig.getID()
    new_dest_id = new_dest.getID()
    print(f"  Using: from={new_orig_id} to={new_dest_id}")

    # Patch generate_trips for new edge IDs
    np.random.seed(42)
    depart_times = np.random.normal(DURATION_SECONDS/2, DURATION_SECONDS/6, 7830)
    depart_times = np.clip(depart_times, 0, DURATION_SECONDS - 1)
    depart_times = np.sort(depart_times)
    with open(ROU_FILE, 'w') as f:
        f.write('<routes>\n')
        f.write('    <vType id="car" vClass="passenger" maxSpeed="20.0" accel="2.6" decel="4.5" length="4.5" minGap="2.5" />\n')
        for i, t in enumerate(depart_times):
            f.write(f'    <trip id="veh_{i}" type="car" depart="{t:.1f}" from="{new_orig_id}" to="{new_dest_id}" />\n')
        f.write('</routes>\n')

    cmd = [
        "sumo", "-n", str(NEW_NET), "-r", str(ROU_FILE),
        "--tripinfo-output", str(TRIPINFO_FILE),
        "--no-step-log", "--ignore-route-errors", "false"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    warnings_all = result.stderr.splitlines()
    warnings = [l for l in warnings_all if "Warning" in l]
    teleports = len([l for l in warnings_all if "Teleporting" in l])

    durations, lengths = [], []
    if TRIPINFO_FILE.exists():
        tree = ET.parse(TRIPINFO_FILE)
        for ti in tree.getroot().findall('tripinfo'):
            durations.append(float(ti.get('duration')))
            lengths.append(float(ti.get('routeLength')))

    completed = len(durations)
    if completed > 0:
        avg_dur = sum(durations) / completed
        avg_len = sum(lengths) / completed
        avg_speed_kmh = (avg_len / avg_dur) * 3.6
        print(f"  Completed: {completed}/7830 trips")
        print(f"  Avg Travel Time: {avg_dur:.1f} s ({avg_dur/60:.1f} min)")
        print(f"  Avg Speed: {avg_speed_kmh:.1f} km/h")
        print(f"  Teleports: {teleports}  |  Total warnings: {len(warnings)}")
        if avg_speed_kmh < 30:
            print("  [OK] VISIBLE CONGESTION CONFIRMED (speed < 30 km/h)")
        elif avg_speed_kmh < 50:
            print("  [~] PARTIAL CONGESTION (speed 30-50 km/h)")
        else:
            print("  [!] Speed still near free-flow")

if __name__ == "__main__":
    main()
