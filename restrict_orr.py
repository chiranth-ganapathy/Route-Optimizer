"""
restrict_orr.py
---------------
Applies a capacity constraint at Silk Board Junction on the ORR route
as a proxy for real-world congestion behavior, since OSM data for this
corridor lacks traffic signal timing at 74/76 junctions.

The restriction simulates the documented merge bottleneck at Silk Board
where multiple approach lanes converge before the flyover.

Approach: Use a SUMO edge-type additional file to reduce speed + effective
capacity on the identified bottleneck edges. This is cleaner than XML
surgery on net.xml (which would require re-running netconvert). Instead
we use --additional-files with <edge> overrides.
"""
import subprocess
import xml.etree.ElementTree as ET
import numpy as np
from pathlib import Path
import sumolib
import math

OUTPUT_DIR = Path(r"d:\razorpay\output")
NET_FILE = OUTPUT_DIR / "bangalore_corridor_tls.net.xml"
ROU_FILE = OUTPUT_DIR / "trips.rou.xml"
ADD_FILE = OUTPUT_DIR / "silk_board_restriction.add.xml"
TRIPINFO_FILE = OUTPUT_DIR / "tripinfo_restricted.xml"

ORIG_EDGE = "610101763"
DEST_EDGE = "1279028557"
DURATION_SECONDS = 3600
DEMAND = 7830

# These are the ORR approach + merge edges at Silk Board Junction
# identified from the network:
#   160331539#2  -- the 1-lane merge segment (128m) right after the junction
#   1384907601   -- the 302m service road leading out (2 lanes, already 8.3 m/s)
# We will also add a short speed cap on the approaches (edges 00-04).
SILK_BOARD_BOTTLENECK_EDGES = [
    "160331539#2",    # 1-lane merge (natural bottleneck), keep lanes=1
    "1384907601",     # ORR exit ramp / service road, already 30 km/h
    "1421955576",     # Continuing service road segment
]

# Speed to apply on bottleneck edges (m/s). 
# 5.56 m/s = 20 km/h = heavy congestion proxy
BOTTLENECK_SPEED = 5.56  # m/s


def write_additional_file(speed_mps):
    """Write a SUMO .add.xml that overrides max speed on bottleneck edges."""
    root = ET.Element("additional")
    for eid in SILK_BOARD_BOTTLENECK_EDGES:
        ET.SubElement(root, "edge", id=eid, speed=f"{speed_mps:.2f}")
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    tree.write(str(ADD_FILE), xml_declaration=True, encoding="UTF-8")
    print(f"  Wrote restriction file: {ADD_FILE}")
    print(f"  Edges restricted: {SILK_BOARD_BOTTLENECK_EDGES}")
    print(f"  Speed cap: {speed_mps:.2f} m/s ({speed_mps*3.6:.1f} km/h)")


def generate_trips():
    np.random.seed(42)
    mu = DURATION_SECONDS / 2
    sigma = DURATION_SECONDS / 6
    depart_times = np.sort(np.clip(np.random.normal(mu, sigma, DEMAND), 0, DURATION_SECONDS - 1))
    with open(ROU_FILE, 'w') as f:
        f.write('<routes>\n')
        f.write('    <vType id="car" vClass="passenger" maxSpeed="20.0" accel="2.6" decel="4.5" length="4.5" minGap="2.5" />\n')
        for i, t in enumerate(depart_times):
            f.write(f'    <trip id="veh_{i}" type="car" depart="{t:.1f}" from="{ORIG_EDGE}" to="{DEST_EDGE}" />\n')
        f.write('</routes>\n')


def run_smoke_test(use_additional=True):
    cmd = [
        "sumo",
        "-n", str(NET_FILE),
        "-r", str(ROU_FILE),
        "--tripinfo-output", str(TRIPINFO_FILE),
        "--no-step-log",
        "--ignore-route-errors", "false",
    ]
    if use_additional:
        cmd += ["--additional-files", str(ADD_FILE)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stderr.splitlines()
    warnings = [l for l in lines if "Warning" in l]
    teleports = len([l for l in lines if "Teleporting" in l])

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
        avg_kmh = (avg_len / avg_dur) * 3.6
        return completed, avg_dur, avg_kmh, len(warnings), teleports
    return 0, 0, 0, len(warnings), teleports


def main():
    print("=" * 65)
    print("STEP 1: Baseline (no restriction) — reference point")
    print("=" * 65)
    generate_trips()
    comp, avg_dur, avg_kmh, warns, tele = run_smoke_test(use_additional=False)
    print(f"  Demand: {DEMAND} veh | Completed: {comp}")
    print(f"  Avg Travel Time: {avg_dur:.1f} s ({avg_dur/60:.1f} min)")
    print(f"  Avg Speed: {avg_kmh:.1f} km/h | Teleports: {tele}")

    print("\n" + "=" * 65)
    print("STEP 2: Applying Silk Board capacity restriction")
    print("=" * 65)
    print("""
  Rationale:
  Since OSM data lacks traffic signal timing at 74/76 junctions on this
  corridor, a capacity constraint is applied at Silk Board Junction --
  Bangalore's most documented real-world bottleneck -- as a proxy for
  real congestion behavior. The restriction reduces max speed at the
  known merge point (160331539#2 and downstream service road edges)
  to simulate the merge friction and reduced throughput that characterizes
  peak-hour conditions at this junction.
""")

    # Try progressively tighter restrictions until congestion appears
    test_speeds = [
        ("20 km/h", 5.56),
        ("15 km/h", 4.17),
        ("10 km/h", 2.78),
    ]

    for label, speed in test_speeds:
        print(f"\n  --- Testing speed cap: {label} ---")
        write_additional_file(speed)
        comp, avg_dur, avg_kmh, warns, tele = run_smoke_test(use_additional=True)
        print(f"  Demand: {DEMAND} veh | Completed: {comp}")
        print(f"  Avg Travel Time: {avg_dur:.1f} s ({avg_dur/60:.1f} min)")
        print(f"  Avg Speed: {avg_kmh:.1f} km/h | Warnings: {warns} | Teleports: {tele}")

        if avg_kmh < 30 and tele == 0:
            print(f"\n  [OK] Visible congestion achieved at {label} bottleneck cap!")
            print(f"  Final config: speed={speed} m/s on edges {SILK_BOARD_BOTTLENECK_EDGES}")
            break
        elif avg_kmh < 40:
            print(f"  [~] Partial congestion at {label} -- tightening further...")
        else:
            print(f"  [!] Speed still near free-flow at {label}")

    print("\n" + "=" * 65)
    print("DONE")
    print("=" * 65)
    print(f"  Modified network uses: {NET_FILE.name}")
    print(f"  Restriction additional file: {ADD_FILE.name}")
    print(f"  Demand file: {ROU_FILE.name}")


if __name__ == "__main__":
    main()
