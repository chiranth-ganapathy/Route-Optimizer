import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

OUTPUT_DIR = Path(r"d:\razorpay\output")
NET_FILE = OUTPUT_DIR / "bangalore_corridor_restricted.net.xml"
ROU_FILE = OUTPUT_DIR / "trips.rou.xml"
TRIPINFO_FILE = OUTPUT_DIR / "tripinfo_restricted.xml"

ORIG_EDGE = "610101763"
DEST_EDGE = "1279028557"
DEMAND = 7830
DURATION_SECONDS = 3600

def generate_trips():
    np.random.seed(42)
    mu = DURATION_SECONDS / 2
    sigma = DURATION_SECONDS / 6
    depart_times = np.random.normal(mu, sigma, int(DEMAND))
    depart_times = np.clip(depart_times, 0, DURATION_SECONDS - 1)
    depart_times = np.sort(depart_times)
    with open(ROU_FILE, 'w') as f:
        f.write('<routes>\n')
        f.write('    <vType id="car" vClass="passenger" maxSpeed="20.0" accel="2.6" decel="4.5" length="4.5" minGap="2.5" />\n')
        for i, t in enumerate(depart_times):
            f.write(f'    <trip id="veh_{i}" type="car" depart="{t:.1f}" from="{ORIG_EDGE}" to="{DEST_EDGE}" />\n')
        f.write('</routes>\n')

def run_smoke_test():
    cmd = [
        "sumo", "-n", str(NET_FILE), "-r", str(ROU_FILE),
        "--tripinfo-output", str(TRIPINFO_FILE),
        "--no-step-log", "--ignore-route-errors", "false"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stderr.splitlines()
    warnings = len([l for l in lines if "Warning" in l])
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
        print(f"Completed: {completed}/{DEMAND} trips")
        print(f"Avg Travel Time: {avg_dur:.1f} s ({avg_dur/60:.1f} min)")
        print(f"Avg Speed: {avg_kmh:.1f} km/h")
        print(f"Teleports: {teleports} | Total warnings: {warnings}")
        if avg_kmh < 30:
            print("[OK] VISIBLE CONGESTION CONFIRMED (speed < 30 km/h)")
        else:
            print("[!] Speed still near free-flow")
    else:
        print("No trips completed.")

if __name__ == "__main__":
    generate_trips()
    run_smoke_test()
