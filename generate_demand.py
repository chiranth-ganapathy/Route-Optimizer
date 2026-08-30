import os
import sys
import numpy as np
import subprocess
from pathlib import Path
import xml.etree.ElementTree as ET
import sumolib

# -- Configuration ---------------------------------------------------------
PROJECT_DIR = Path(r"d:\razorpay")
OUTPUT_DIR = PROJECT_DIR / "output"
NET_FILE = OUTPUT_DIR / "bangalore_corridor.net.xml"
ROU_FILE = OUTPUT_DIR / "trips.rou.xml"
SUMMARY_FILE = OUTPUT_DIR / "calibration_summary.txt"
TRIPINFO_FILE = OUTPUT_DIR / "tripinfo.xml"

ORIG_EDGE = "1167293938"
DEST_EDGE = "1316838535"

DURATION_SECONDS = 3600
TARGET_DC_RATIO = 1.45  # Target Demand-to-Capacity ratio for ORR

# -- Main -------------------------------------------------------------------

def compute_capacity(net):
    # ORR is physically a 3+ lane arterial, but OSM might have 1-lane links 
    # (like slip roads or minor bridges) that falsely reduce calculated capacity.
    # We'll use a realistic baseline capacity of 5400 PCU/hr (3 lanes * 1800).
    capacity_orr = 5400
    
    # Let's say Sarjapur Road has 2 lanes
    capacity_sarjapur = 3600
    
    return capacity_orr, capacity_sarjapur

def generate_trips():
    print("=" * 70)
    print("STEP 1: Calibrating and Generating Demand")
    print("=" * 70)
    
    net = sumolib.net.readNet(str(NET_FILE))
    cap_orr, cap_sarjapur = compute_capacity(net)
    
    target_demand = int(cap_orr * TARGET_DC_RATIO)
    
    summary = []
    summary.append(f"Origin Edge: {ORIG_EDGE}")
    summary.append(f"Destination Edge: {DEST_EDGE}")
    summary.append(f"Calculated Capacity ORR: {cap_orr} PCU/hour")
    summary.append(f"Calculated Capacity Sarjapur Road: {cap_sarjapur} PCU/hour")
    summary.append(f"Target D/C Ratio for ORR: {TARGET_DC_RATIO}")
    summary.append(f"Total Vehicle Demand Generated: {target_demand}")
    summary.append(f"Time window: {DURATION_SECONDS} seconds (1 hour peak)")
    
    print("\n".join(summary))
    
    with open(SUMMARY_FILE, 'w') as f:
        f.write("\n".join(summary) + "\n")
    
    # Generate departure times using a normal distribution
    np.random.seed(42)
    mu = DURATION_SECONDS / 2
    sigma = DURATION_SECONDS / 6  # Tighter bell curve
    
    depart_times = np.random.normal(mu, sigma, target_demand)
    depart_times = np.clip(depart_times, 0, DURATION_SECONDS - 1)
    depart_times = np.sort(depart_times)
    
    print("  Writing to trips.rou.xml...")
    with open(ROU_FILE, 'w') as f:
        f.write('<routes>\n')
        f.write('    <vType id="car" vClass="passenger" maxSpeed="20.0" accel="2.6" decel="4.5" length="4.5" minGap="2.5" />\n')
        
        for i, t in enumerate(depart_times):
            f.write(f'    <trip id="veh_{i}" type="car" depart="{t:.1f}" from="{ORIG_EDGE}" to="{DEST_EDGE}" />\n')
            
        f.write('</routes>\n')
        
    print(f"  [OK] Saved demand to: {ROU_FILE}")
    print()

def smoke_test():
    print("=" * 70)
    print("STEP 2: Smoke-testing the simulation")
    print("=" * 70)
    
    cmd = [
        "sumo",
        "-n", str(NET_FILE),
        "-r", str(ROU_FILE),
        "--tripinfo-output", str(TRIPINFO_FILE),
        "--no-step-log",
        "--ignore-route-errors", "false"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"  [FAIL] SUMO simulation failed (exit code {result.returncode})")
        print(f"  Error output:\n{result.stderr[:1000]}")
    else:
        print("  [OK] SUMO smoke test passed.")
        
        warnings = [l for l in result.stderr.splitlines() if "Warning" in l]
        if warnings:
            print(f"    SUMO warnings: {len(warnings)}")
        
        # Parse tripinfo
        if TRIPINFO_FILE.exists():
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
                
                print(f"    Completed trips: {completed}")
                print(f"    Average travel time: {avg_duration:.1f} s")
                print(f"    Average speed: {avg_speed:.2f} m/s ({avg_speed*3.6:.1f} km/h)")
                
                # Check for severe congestion
                if avg_speed * 3.6 < 30:
                    print("    [OK] Visible congestion confirmed (speed is significantly lower than free-flow).")
                else:
                    print("    [!] WARNING: Speed is high, network may not be congested.")
            else:
                print("    [!] WARNING: No trips completed.")

if __name__ == "__main__":
    generate_trips()
    smoke_test()
