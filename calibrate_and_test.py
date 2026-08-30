import os
import sys
import math
import numpy as np
import subprocess
import xml.etree.ElementTree as ET
import sumolib
from pathlib import Path

# -- Configuration ---------------------------------------------------------
PROJECT_DIR = Path(r"d:\razorpay")
OUTPUT_DIR = PROJECT_DIR / "output"
NET_FILE = OUTPUT_DIR / "bangalore_corridor.net.xml"
ROU_FILE = OUTPUT_DIR / "trips.rou.xml"
TRIPINFO_FILE = OUTPUT_DIR / "tripinfo.xml"

ORIG_EDGE = "1167293938"
DEST_EDGE = "1316838535"
DURATION_SECONDS = 3600

# We need the ORR path to find the bottleneck. We'll use sumolib to find the shortest path 
# between ORIG_EDGE and DEST_EDGE (which naturally falls on ORR based on earlier tests).

def get_route_capacity(net, path_edges):
    # Capacity is bottleneck capacity. Minimum lanes on the main arterial stretches.
    # Exclude very short edges (< 30m) which might be just intersection internals
    valid_edges = [e for e in path_edges if e.getLength() > 30]
    if not valid_edges:
        valid_edges = path_edges # fallback
        
    min_lanes = min([e.getLaneNumber() for e in valid_edges])
    
    # Check max speed as well, though typical lane capacity is ~1800-1900
    # Let's assume 1900 per lane
    return min_lanes * 1900, min_lanes

def analyze_junctions(net, path_edges):
    signalized = 0
    priority = 0
    other = 0
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
    return signalized, priority, other

def generate_trips(demand):
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
            f.write(f'    <trip id="veh_{i}" type="car" depart="{t:.1f}" from="{ORIG_EDGE}" to="{DEST_EDGE}" />\n')
        f.write('</routes>\n')

def run_simulation():
    cmd = [
        "sumo",
        "-n", str(NET_FILE),
        "-r", str(ROU_FILE),
        "--tripinfo-output", str(TRIPINFO_FILE),
        "--no-step-log",
        "--ignore-route-errors", "false"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result

def parse_tripinfo():
    if not TRIPINFO_FILE.exists():
        return 0, 0, 0
    tree = ET.parse(TRIPINFO_FILE)
    root = tree.getroot()
    durations = []
    route_lengths = []
    
    for tripinfo in root.findall('tripinfo'):
        durations.append(float(tripinfo.get('duration')))
        route_lengths.append(float(tripinfo.get('routeLength')))
        
    completed = len(durations)
    if completed > 0:
        avg_duration = sum(durations) / completed
        avg_length = sum(route_lengths) / completed
        avg_speed = avg_length / avg_duration
        return completed, avg_duration, avg_speed
    return 0, 0, 0

def main():
    net = sumolib.net.readNet(str(NET_FILE))
    
    orig = net.getEdge(ORIG_EDGE)
    dest = net.getEdge(DEST_EDGE)
    
    # 1. Find the path (ORR is the shortest path between these two edges)
    orr_path, _ = net.getShortestPath(orig, dest)
    
    if not orr_path:
        print("ERROR: No path found between origin and destination!")
        return
        
    print(f"Path found with {len(orr_path)} edges.")
    
    # 2. Extract ACTUAL capacity
    orr_cap, orr_min_lanes = get_route_capacity(net, orr_path)
    
    print("=" * 60)
    print("CAPACITY CALCULATION")
    print("=" * 60)
    print(f"Assumed ORR lanes: 3  -> Assumed Capacity: 5400 PCU/hr")
    print(f"ACTUAL ORR bottleneck lanes: {orr_min_lanes} -> ACTUAL Capacity: {orr_cap} PCU/hr")
    
    # Analyze junctions
    sig, prio, oth = analyze_junctions(net, orr_path)
    print(f"\nJunction Analysis along ORR:")
    print(f"  Signalized (Traffic Lights): {sig}")
    print(f"  Priority / Uncontrolled:     {prio}")
    print(f"  Other:                       {oth}")
    
    print("\nStarting Simulation Loop to find congestion...")
    multipliers = [1.5, 2.0, 2.5, 3.0, 4.0]
    
    for mult in multipliers:
        demand = int(orr_cap * mult)
        print(f"\n--- Testing Multiplier {mult}x (Demand: {demand} veh/hr) ---")
        generate_trips(demand)
        
        run_simulation()
        
        completed, avg_dur, avg_speed = parse_tripinfo()
        speed_kmh = avg_speed * 3.6 if avg_speed > 0 else 0
        
        print(f"Completed: {completed}/{demand} | Avg Speed: {speed_kmh:.1f} km/h")
        
        if speed_kmh > 0 and speed_kmh < 30.0:
            print(f"--> [SUCCESS] Visible congestion achieved at {mult}x!")
            break
            
if __name__ == "__main__":
    main()
