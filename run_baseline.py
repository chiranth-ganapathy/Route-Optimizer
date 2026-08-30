"""
run_baseline.py
---------------
Baseline scenario: all 7,830 vehicles routed via SUMO's default shortest-path,
mimicking Google Maps / current nav app behavior where every driver independently
picks the fastest route. With the Silk Board bottleneck in place, all traffic
converges on ORR, causing congestion at the merge point.

Outputs:
  output/tripinfo_baseline.xml  -- per-vehicle trip statistics
  output/summary_baseline.txt   -- human-readable headline metrics
"""
import subprocess
import xml.etree.ElementTree as ET
import numpy as np
from pathlib import Path

OUTPUT_DIR = Path(r"d:\razorpay\output")
NET_FILE    = OUTPUT_DIR / "bangalore_corridor_restricted.net.xml"
ROU_FILE    = OUTPUT_DIR / "trips_baseline.rou.xml"
TRIPINFO    = OUTPUT_DIR / "tripinfo_baseline.xml"
SUMMARY     = OUTPUT_DIR / "summary_baseline.txt"

ORIG_EDGE   = "610101763"
DEST_EDGE   = "1279028557"
DEMAND      = 7830
DURATION    = 3600          # 1-hour peak window

SIGNIFICANT_DELAY_S = 60    # threshold for "X drivers were meaningfully delayed"


# ── 1. Generate demand ──────────────────────────────────────────────────────
def generate_trips():
    np.random.seed(42)
    departs = np.random.normal(DURATION / 2, DURATION / 6, DEMAND)
    departs = np.sort(np.clip(departs, 0, DURATION - 1))

    with open(ROU_FILE, "w") as f:
        f.write("<routes>\n")
        # maxSpeed matches vehicle capability; edge speed cap at Silk Board
        # is the binding constraint, not the vehicle.
        f.write('    <vType id="car" vClass="passenger" '
                'maxSpeed="20.0" accel="2.6" decel="4.5" '
                'length="4.5" minGap="2.5" />\n')
        for i, t in enumerate(departs):
            f.write(f'    <trip id="veh_{i}" type="car" depart="{t:.1f}" '
                    f'from="{ORIG_EDGE}" to="{DEST_EDGE}" />\n')
        f.write("</routes>\n")

    print(f"Generated {DEMAND} trips -> {ROU_FILE.name}")


# ── 2. Run SUMO ─────────────────────────────────────────────────────────────
def run_sumo():
    cmd = [
        "sumo",
        "-n", str(NET_FILE),
        "-r", str(ROU_FILE),
        "--tripinfo-output", str(TRIPINFO),
        "--no-step-log",
        "--ignore-route-errors", "false",
    ]
    print("Running SUMO baseline simulation...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines  = result.stderr.splitlines()
    teleports = sum(1 for l in lines if "Teleporting" in l)
    warnings  = sum(1 for l in lines if "Warning" in l)
    print(f"  SUMO exit code : {result.returncode}")
    print(f"  Warnings       : {warnings}")
    print(f"  Teleports      : {teleports}")
    return teleports, warnings


# ── 3. Parse tripinfo ────────────────────────────────────────────────────────
def parse_tripinfo():
    tree = ET.parse(TRIPINFO)
    root = tree.getroot()

    durations    = []
    route_lengths = []
    time_losses  = []

    for ti in root.findall("tripinfo"):
        durations.append(float(ti.get("duration")))
        route_lengths.append(float(ti.get("routeLength")))
        time_losses.append(float(ti.get("timeLoss")))

    n = len(durations)
    avg_duration  = sum(durations)   / n
    avg_length    = sum(route_lengths) / n
    avg_speed_kmh = (avg_length / avg_duration) * 3.6

    total_time_loss  = sum(time_losses)
    avg_time_loss    = total_time_loss / n
    delayed_count    = sum(1 for tl in time_losses if tl > SIGNIFICANT_DELAY_S)
    max_time_loss    = max(time_losses)
    median_time_loss = sorted(time_losses)[n // 2]

    return {
        "n":               n,
        "avg_duration_s":  avg_duration,
        "avg_speed_kmh":   avg_speed_kmh,
        "total_time_loss": total_time_loss,
        "avg_time_loss":   avg_time_loss,
        "max_time_loss":   max_time_loss,
        "median_time_loss": median_time_loss,
        "delayed_count":   delayed_count,
    }


# ── 4. Report ────────────────────────────────────────────────────────────────
def report(m, teleports, warnings):
    lines = [
        "=" * 65,
        "BASELINE SCENARIO — Shortest-Path Routing (All Vehicles on ORR)",
        "=" * 65,
        "",
        f"  Vehicles simulated  : {m['n']:,}",
        f"  Completed trips     : {m['n']:,}  (teleports: {teleports})",
        "",
        "── Travel Time ─────────────────────────────────────────────",
        f"  Avg travel time     : {m['avg_duration_s']:.1f} s  "
        f"({m['avg_duration_s']/60:.1f} min)",
        f"  Avg corridor speed  : {m['avg_speed_kmh']:.1f} km/h",
        "",
        "── timeLoss (headline congestion metric) ───────────────────",
        f"  Total system timeLoss  : {m['total_time_loss']:,.0f} s  "
        f"({m['total_time_loss']/3600:.1f} vehicle-hours lost)",
        f"  Avg timeLoss/vehicle   : {m['avg_time_loss']:.1f} s  "
        f"({m['avg_time_loss']/60:.1f} min per driver)",
        f"  Median timeLoss        : {m['median_time_loss']:.1f} s",
        f"  Max timeLoss           : {m['max_time_loss']:.1f} s  "
        f"({m['max_time_loss']/60:.1f} min worst case)",
        f"  Drivers delayed >60 s  : {m['delayed_count']:,} / {m['n']:,}  "
        f"({m['delayed_count']/m['n']*100:.1f}%)",
        "",
        "── For video headline ───────────────────────────────────────",
        f"  \"{m['delayed_count']:,} out of {m['n']:,} drivers experienced "
        f"significant congestion delay (>{SIGNIFICANT_DELAY_S}s) under "
        f"shortest-path routing.\"",
        f"  \"Total system waste: {m['total_time_loss']/3600:.1f} vehicle-hours "
        f"lost to congestion.\"",
        "",
        f"  SUMO warnings: {warnings}",
        "=" * 65,
    ]
    text = "\n".join(lines)
    print("\n" + text)
    SUMMARY.write_text(text)
    print(f"\nSummary saved → {SUMMARY.name}")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    generate_trips()
    teleports, warnings = run_sumo()
    m = parse_tripinfo()
    report(m, teleports, warnings)
