"""
Analytical traffic assignment comparison using the BPR (Bureau of Public
Roads) volume-delay function — standard transportation engineering method.

t(v) = t0 * (1 + alpha * (v/c)^beta)
  t0 = free-flow travel time
  v  = volume (vehicles/hour) on the route
  c  = route capacity (vehicles/hour), taken as the bottleneck
       (minimum-lane-count edge) along the route
  alpha=0.15, beta=4  -- standard BPR defaults

This uses REAL data already produced by this project:
  - Actual routed edge sequences from trips_optimal.rou.xml
  - Actual lane counts and speeds from the SUMO network file
No simulation micro-behavior (teleports, deadlocks, routing bugs) is
involved — this sidesteps the SUMO routing issues encountered earlier
by computing travel time directly from network geometry and demand.
"""

import xml.etree.ElementTree as ET
import sumolib

NET_FILE = r"output\bangalore_corridor_tls.net.xml"  # unrestricted network - real geometry
TRIPS_FILE = r"output\trips_optimal.rou.xml"
TOTAL_DEMAND = 7830  # vehicles over the peak hour, from Day 3 calibration

PCU_PER_LANE_PER_HOUR = 1900  # standard urban arterial capacity benchmark
ALPHA, BETA = 0.15, 4  # standard BPR parameters


def get_route_edges(trips_file, prefix):
    tree = ET.parse(trips_file)
    root = tree.getroot()
    for v in root.findall("vehicle"):
        if v.get("id", "").startswith(prefix):
            route = v.find("route")
            if route is not None:
                return route.get("edges").split()
    return None


def analyze_route(net, all_edges, exclusive_edges):
    """
    Free-flow time uses the FULL route (all_edges).
    Bottleneck capacity is found only among EXCLUSIVE edges (not shared
    with the other route) — shared-approach congestion affects both
    scenarios equally and isn't what a routing decision can change, so
    it's excluded from the capacity comparison that drives the split.
    """
    total_length_m = 0.0
    total_freeflow_s = 0.0
    for eid in all_edges:
        try:
            edge = net.getEdge(eid)
        except KeyError:
            continue
        total_length_m += edge.getLength()
        total_freeflow_s += edge.getLength() / edge.getSpeed() if edge.getSpeed() > 0 else 0

    min_capacity = None
    bottleneck_edge = None
    MIN_EDGE_LENGTH_FOR_BOTTLENECK = 30

    search_edges = exclusive_edges if exclusive_edges else all_edges
    for eid in search_edges:
        try:
            edge = net.getEdge(eid)
        except KeyError:
            continue
        if edge.getLength() < MIN_EDGE_LENGTH_FOR_BOTTLENECK:
            continue
        cap = edge.getLaneNumber() * PCU_PER_LANE_PER_HOUR
        if min_capacity is None or cap < min_capacity:
            min_capacity = cap
            bottleneck_edge = eid

    if min_capacity is None:
        for eid in search_edges:
            try:
                edge = net.getEdge(eid)
            except KeyError:
                continue
            cap = edge.getLaneNumber() * PCU_PER_LANE_PER_HOUR
            if min_capacity is None or cap < min_capacity:
                min_capacity = cap
                bottleneck_edge = eid

    return {
        "length_km": total_length_m / 1000,
        "freeflow_s": total_freeflow_s,
        "capacity_veh_hr": min_capacity,
        "bottleneck_edge": bottleneck_edge,
    }


def bpr_time(t0, v, c):
    if c <= 0:
        return float("inf")
    return t0 * (1 + ALPHA * (v / c) ** BETA)


def total_system_time(v1, t0_1, c1, v2, t0_2, c2):
    """Total vehicle-hours for a given split."""
    t1 = bpr_time(t0_1, v1, c1)
    t2 = bpr_time(t0_2, v2, c2)
    return (v1 * t1 + v2 * t2) / 3600, t1, t2


def find_system_optimal_split(t0_1, c1, t0_2, c2, demand, steps=2000):
    """Grid search for the split minimizing total system travel time."""
    best = None
    for i in range(steps + 1):
        v1 = demand * i / steps
        v2 = demand - v1
        total_hrs, t1, t2 = total_system_time(v1, t0_1, c1, v2, t0_2, c2)
        if best is None or total_hrs < best[0]:
            best = (total_hrs, v1, v2, t1, t2)
    return best


def main():
    net = sumolib.net.readNet(NET_FILE)

    orr_edges = get_route_edges(TRIPS_FILE, "orr_")
    sarj_edges = get_route_edges(TRIPS_FILE, "sarj_")

    if orr_edges is None or sarj_edges is None:
        print("ERROR: could not find orr_/sarj_ prefixed routes in", TRIPS_FILE)
        return

    shared = set(orr_edges) & set(sarj_edges)
    orr_exclusive = [e for e in orr_edges if e not in shared]
    sarj_exclusive = [e for e in sarj_edges if e not in shared]

    print(f"Shared edges (both routes, excluded from bottleneck search): {len(shared)}")
    print(f"ORR-exclusive edges: {len(orr_exclusive)}  |  Sarjapur-exclusive edges: {len(sarj_exclusive)}")
    print()

    orr = analyze_route(net, orr_edges, orr_exclusive)
    sarj = analyze_route(net, sarj_edges, sarj_exclusive)

    print("=" * 70)
    print("REAL NETWORK DATA (from actual routed edges + net file)")
    print("=" * 70)
    print(f"ORR      : {orr['length_km']:.2f} km, free-flow {orr['freeflow_s']:.0f}s, "
          f"bottleneck capacity {orr['capacity_veh_hr']:.0f} veh/hr "
          f"(edge {orr['bottleneck_edge']})")
    print(f"Sarjapur : {sarj['length_km']:.2f} km, free-flow {sarj['freeflow_s']:.0f}s, "
          f"bottleneck capacity {sarj['capacity_veh_hr']:.0f} veh/hr "
          f"(edge {sarj['bottleneck_edge']})")
    print()

    # --- Baseline: everyone takes ORR (it's shorter) ---
    baseline_hrs, baseline_t, _ = total_system_time(
        TOTAL_DEMAND, orr["freeflow_s"], orr["capacity_veh_hr"], 0, sarj["freeflow_s"], sarj["capacity_veh_hr"]
    )
    baseline_avg_tl = baseline_t - orr["freeflow_s"]

    print("=" * 70)
    print("BASELINE — all demand on ORR (shortest-path / Google Maps style)")
    print("=" * 70)
    print(f"Volume on ORR        : {TOTAL_DEMAND} veh/hr")
    print(f"Travel time per veh  : {baseline_t:.1f}s ({baseline_t/60:.1f} min)")
    print(f"TimeLoss per vehicle : {baseline_avg_tl:.1f}s")
    print(f"Total system time    : {baseline_hrs:.1f} vehicle-hours")
    print()

    # --- System-optimal: find the split minimizing total time ---
    opt_hrs, v1, v2, t1, t2 = find_system_optimal_split(
        orr["freeflow_s"], orr["capacity_veh_hr"],
        sarj["freeflow_s"], sarj["capacity_veh_hr"],
        TOTAL_DEMAND
    )
    opt_avg_tl_orr = t1 - orr["freeflow_s"]
    opt_avg_tl_sarj = t2 - sarj["freeflow_s"]
    opt_avg_tl = (v1 * opt_avg_tl_orr + v2 * opt_avg_tl_sarj) / TOTAL_DEMAND

    print("=" * 70)
    print("SYSTEM-OPTIMAL — demand split to minimize total system time")
    print("=" * 70)
    print(f"ORR volume      : {v1:.0f} veh/hr ({v1/TOTAL_DEMAND*100:.1f}%) -> {t1:.1f}s/veh")
    print(f"Sarjapur volume : {v2:.0f} veh/hr ({v2/TOTAL_DEMAND*100:.1f}%) -> {t2:.1f}s/veh")
    print(f"Avg timeLoss/veh: {opt_avg_tl:.1f}s")
    print(f"Total system time: {opt_hrs:.1f} vehicle-hours")
    print()

    improvement = (baseline_hrs - opt_hrs) / baseline_hrs * 100
    print("=" * 70)
    print(f"RESULT: {improvement:.1f}% reduction in total system travel time")
    print(f"Baseline: {baseline_hrs:.1f} vehicle-hours -> Optimal: {opt_hrs:.1f} vehicle-hours")
    print("=" * 70)

    with open("output/final_analytical_comparison.txt", "w", encoding="utf-8") as f:
        f.write(f"ORR: {orr['length_km']:.2f}km, freeflow={orr['freeflow_s']:.0f}s, capacity={orr['capacity_veh_hr']:.0f}veh/hr\n")
        f.write(f"Sarjapur: {sarj['length_km']:.2f}km, freeflow={sarj['freeflow_s']:.0f}s, capacity={sarj['capacity_veh_hr']:.0f}veh/hr\n\n")
        f.write(f"BASELINE: 100% ORR, {baseline_t:.1f}s/veh, {baseline_hrs:.1f} vehicle-hours total\n")
        f.write(f"OPTIMAL: {v1:.0f} ORR / {v2:.0f} Sarjapur, {opt_hrs:.1f} vehicle-hours total\n\n")
        f.write(f"IMPROVEMENT: {improvement:.1f}% reduction in total system travel time\n")

    print("\nSaved to output/final_analytical_comparison.txt")


if __name__ == "__main__":
    main()