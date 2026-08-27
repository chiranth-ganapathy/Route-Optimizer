import os
import sys
import numpy as np
import subprocess
from pathlib import Path

# -- Configuration ---------------------------------------------------------
PROJECT_DIR = Path(r"d:\razorpay")
OUTPUT_DIR = PROJECT_DIR / "output"
NET_FILE = OUTPUT_DIR / "bangalore_corridor.net.xml"
ROU_FILE = OUTPUT_DIR / "trips.rou.xml"

# Selected SUMO edges for origin and destination based on network analysis
# 1167293938 (highway.trunk) -> 1316838535 (highway.primary)
ORIG_EDGE = "1167293938"
DEST_EDGE = "1316838535"

# Demand parameters
TOTAL_VEHICLES = 4000
DURATION_SECONDS = 3600

# -- Main -------------------------------------------------------------------

def generate_trips():
    print("=" * 70)
    print("STEP 1: Generating synthetic demand")
    print("=" * 70)
    print(f"  Origin Edge:      {ORIG_EDGE}")
    print(f"  Destination Edge: {DEST_EDGE}")
    print(f"  Total vehicles:   {TOTAL_VEHICLES}")
    print(f"  Time window:      {DURATION_SECONDS} seconds (1 hour peak)")
    
    # Generate departure times using a normal distribution to simulate peak hour buildup
    np.random.seed(42)  # For reproducibility
    mu = DURATION_SECONDS / 2
    sigma = DURATION_SECONDS / 4
    
    # Generate random numbers and clip them to the 0-DURATION_SECONDS range
    depart_times = np.random.normal(mu, sigma, TOTAL_VEHICLES)
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
    print(f"    Total trips generated: {len(depart_times)}")
    print()

def smoke_test():
    print("=" * 70)
    print("STEP 2: Smoke-testing the simulation")
    print("=" * 70)
    print("  Running SUMO to verify vehicles move without errors...")
    
    cmd = [
        "sumo",
        "-n", str(NET_FILE),
        "-r", str(ROU_FILE),
        "--no-step-log",
        "--ignore-route-errors", "false"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"  [FAIL] SUMO simulation failed (exit code {result.returncode})")
        print(f"  Error output:\n{result.stderr[:1000]}")
    else:
        print("  [OK] SUMO smoke test passed.")
        
        # Analyze output for routing errors
        warnings = [l for l in result.stderr.splitlines() if "Warning" in l]
        if warnings:
            print(f"    SUMO warnings: {len(warnings)}")
            for w in warnings[:5]:
                print(f"      {w}")
        else:
            print("    No warnings reported.")
            
    print()

if __name__ == "__main__":
    generate_trips()
    smoke_test()
