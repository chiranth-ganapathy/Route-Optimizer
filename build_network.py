"""
Day 2 network setup for the Bangalore Silk Board -> Marathahalli corridor.

This script:
1. Pulls a drivable OSM road graph with OSMnx using graph_from_bbox.
2. Finds exactly two plausible alternate routes:
   - Route 1: shortest path, expected to follow ORR.
   - Route 2: edge-penalty search, expected to follow Sarjapur Road.
3. Verifies overlap and route-length realism.
4. Plots both routes.
5. Trims the export graph to a 500 m buffer around the two routes.
6. Exports a SUMO .net.xml with netconvert.
7. Writes a reusable route summary.

No traffic demand, routing assignment, or simulation is generated here.
"""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import networkx as nx
import osmnx as ox
from shapely.geometry import LineString


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "output"
CACHE_DIR = PROJECT_DIR / "cache"

# Endpoint coordinates as (latitude, longitude).
SILK_BOARD = (12.9170, 77.6227)
MARATHAHALLI = (12.9563, 77.7009)

# Bounding box as (west, south, east, north). This deliberately includes ORR
# and the Sarjapur/Bellandur/Yemalur corridor without pulling excessive city area.
BBOX = (77.60, 12.900, 77.72, 12.970)

BUFFER_METERS = 500
TARGET_MAX_SHARED_EDGES = 40.0
MAX_REALISTIC_LENGTH_RATIO = 1.50
SECOND_ROUTE_PENALTIES = (2, 3, 5, 8, 13, 21, 34, 50, 80, 120, 200)

ROUTE_KEYWORDS = {
    "ORR": (
        "outer ring road",
        "orr",
        "outer ring",
        "dr. vishnuvardhan road",
    ),
    "Sarjapur Road": (
        "sarjapur",
        "sarjapura",
        "bellandur",
        "bellanduru",
        "haralur",
        "harlur",
        "iblur",
        "ambalipura",
        "kaikondrahalli",
        "kempapura",
        "yemalur",
        "yamalur",
    ),
}


def edge_bundle(G: nx.MultiDiGraph, u: int, v: int) -> list[dict[str, Any]]:
    return list(G.get_edge_data(u, v, default={}).values())


def best_edge(G: nx.MultiDiGraph, u: int, v: int) -> dict[str, Any]:
    edges = edge_bundle(G, u, v)
    if not edges:
        raise KeyError(f"No edge data found for {u} -> {v}")
    return min(edges, key=lambda data: data.get("length", float("inf")))


def edge_name(edge: dict[str, Any]) -> str:
    name = edge.get("name", "")
    if isinstance(name, list):
        return " / ".join(str(part) for part in name)
    return str(name) if name else ""


def ordered_unique(values: list[Any]) -> list[Any]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def route_edges(path: list[int]) -> set[tuple[int, int]]:
    return set(zip(path[:-1], path[1:]))


def route_length_km(G: nx.MultiDiGraph, path: list[int]) -> float:
    total_meters = sum(
        best_edge(G, u, v).get("length", 0.0)
        for u, v in zip(path[:-1], path[1:])
    )
    return total_meters / 1000.0


def route_profile(G: nx.MultiDiGraph, path: list[int]) -> dict[str, Any]:
    scores: Counter[str] = Counter()
    road_names = []

    for u, v in zip(path[:-1], path[1:]):
        name = edge_name(best_edge(G, u, v))
        if name:
            road_names.append(name)
        name_lower = name.lower()
        for label, keywords in ROUTE_KEYWORDS.items():
            if any(keyword in name_lower for keyword in keywords):
                scores[label] += 1

    label = scores.most_common(1)[0][0] if scores else "Unclassified"
    return {
        "label": label,
        "scores": dict(scores),
        "road_names": ordered_unique(road_names),
        "length_km": route_length_km(G, path),
        "node_count": len(path),
    }


def shared_edge_pct(path_a: list[int], path_b: list[int]) -> float:
    edges_a = route_edges(path_a)
    edges_b = route_edges(path_b)
    denominator = min(len(edges_a), len(edges_b))
    if denominator == 0:
        return 0.0
    return 100.0 * len(edges_a & edges_b) / denominator


def set_penalty_weights(G: nx.MultiDiGraph, first_path: list[int], penalty: float) -> None:
    first_edges = route_edges(first_path)
    for u, v, _key, data in G.edges(keys=True, data=True):
        base = data.get("length", 1.0)
        data["penalty_weight"] = base * penalty if (u, v) in first_edges else base


def choose_second_route(
    G: nx.MultiDiGraph,
    origin: int,
    destination: int,
    first_path: list[int],
) -> tuple[list[int], dict[str, Any]]:
    candidates = []
    shortest_length = route_length_km(G, first_path)

    for penalty in SECOND_ROUTE_PENALTIES:
        set_penalty_weights(G, first_path, penalty)
        try:
            path = ox.shortest_path(G, origin, destination, weight="penalty_weight")
        except nx.NetworkXNoPath:
            continue

        if not path or path == first_path:
            continue

        profile = route_profile(G, path)
        overlap = shared_edge_pct(first_path, path)
        ratio = profile["length_km"] / shortest_length
        candidates.append(
            {
                "path": path,
                "penalty": penalty,
                "profile": profile,
                "overlap_pct": overlap,
                "length_ratio": ratio,
                "is_realistic": ratio <= MAX_REALISTIC_LENGTH_RATIO,
                "is_low_overlap": overlap <= TARGET_MAX_SHARED_EDGES,
                "sarjapur_score": profile["scores"].get("Sarjapur Road", 0),
            }
        )

    if not candidates:
        raise RuntimeError("Could not find a second route with the edge-penalty search.")

    realistic = [candidate for candidate in candidates if candidate["is_realistic"]]
    pool = realistic if realistic else candidates
    low_overlap = [candidate for candidate in pool if candidate["is_low_overlap"]]
    if low_overlap:
        pool = low_overlap

    # Prefer the known plausible corridor pairing when it satisfies the checks;
    # otherwise fall back to the best overlap/length tradeoff.
    chosen = sorted(
        pool,
        key=lambda candidate: (
            -candidate["sarjapur_score"],
            candidate["overlap_pct"],
            candidate["length_ratio"],
        ),
    )[0]
    return chosen["path"], chosen


def route_line(G: nx.MultiDiGraph, path: list[int]) -> LineString:
    return LineString([(G.nodes[node]["x"], G.nodes[node]["y"]) for node in path])


def trim_graph_to_routes(
    G_unsimplified: nx.MultiDiGraph,
    G_routing: nx.MultiDiGraph,
    routes: list[list[int]],
) -> nx.MultiDiGraph:
    route_lines = [route_line(G_routing, path) for path in routes]
    gdf = gpd.GeoDataFrame(geometry=route_lines, crs="EPSG:4326")
    gdf_metric = gdf.to_crs(gdf.estimate_utm_crs())
    buffer_metric = gdf_metric.geometry.buffer(BUFFER_METERS)
    buffer_wgs84 = buffer_metric.to_crs("EPSG:4326").union_all()
    return ox.truncate.truncate_graph_polygon(
        G_unsimplified,
        buffer_wgs84,
        truncate_by_edge=True,
    )


def parse_sumo_junction_ids(net_path: Path, osm_node_ids: list[int]) -> dict[int, str | None]:
    wanted = {str(node_id): node_id for node_id in osm_node_ids}
    ranks: dict[int, int] = {node_id: 99 for node_id in osm_node_ids}
    result: dict[int, str | None] = {node_id: None for node_id in osm_node_ids}

    for _event, elem in ET.iterparse(net_path, events=("end",)):
        if elem.tag == "junction":
            junction_id = elem.attrib.get("id", "")
            for osm_text, osm_node_id in wanted.items():
                if junction_id == osm_text:
                    rank = 0
                elif junction_id.startswith(f"cluster_") and osm_text in junction_id:
                    rank = 1
                elif not junction_id.startswith(":") and osm_text in junction_id:
                    rank = 2
                elif osm_text in junction_id:
                    rank = 3
                else:
                    continue

                if rank < ranks[osm_node_id]:
                    result[osm_node_id] = junction_id
                    ranks[osm_node_id] = rank
        elem.clear()

    return result


def print_route_block(route: dict[str, Any]) -> None:
    print(f"  Route {route['index']}: {route['label']}")
    print(f"    Distance: {route['length_km']:.2f} km")
    print(f"    Nodes: {route['node_count']}")
    print(f"    Start OSM node: {route['start_node']}")
    print(f"    End OSM node: {route['end_node']}")
    print(f"    Start SUMO node: {route['start_sumo_node']}")
    print(f"    End SUMO node: {route['end_sumo_node']}")
    print(f"    Key roads: {', '.join(route['road_names'][:14])}")
    if len(route["road_names"]) > 14:
        print(f"               ... and {len(route['road_names']) - 14} more")


def write_summary(
    summary_path: Path,
    routes: list[dict[str, Any]],
    origin: int,
    destination: int,
    origin_data: dict[str, Any],
    destination_data: dict[str, Any],
    overlap_pct: float,
    length_ratio: float,
    osm_path: Path,
    net_path: Path,
    plot_path: Path,
) -> None:
    summary = {
        "corridor": "Silk Board Junction -> Marathahalli Bridge",
        "origin": {
            "name": "Silk Board Junction",
            "osm_node": origin,
            "sumo_node": routes[0]["start_sumo_node"],
            "lat": origin_data["y"],
            "lon": origin_data["x"],
        },
        "destination": {
            "name": "Marathahalli Bridge",
            "osm_node": destination,
            "sumo_node": routes[0]["end_sumo_node"],
            "lat": destination_data["y"],
            "lon": destination_data["x"],
        },
        "route_count": 2,
        "shared_edges_pct": round(overlap_pct, 2),
        "length_ratio_longer_to_shorter": round(length_ratio, 3),
        "routes": routes,
        "files": {
            "osm_xml": str(osm_path),
            "sumo_net": str(net_path),
            "route_plot": str(plot_path),
        },
    }

    text_lines = [
        "=" * 72,
        "BANGALORE CORRIDOR: SILK BOARD JUNCTION -> MARATHAHALLI BRIDGE",
        "Day 2 network setup summary",
        "=" * 72,
        "",
        "ENDPOINTS",
        "-" * 40,
        (
            f"Origin: Silk Board Junction | OSM node {origin} | "
            f"SUMO node {routes[0]['start_sumo_node']} | "
            f"({origin_data['y']:.6f}, {origin_data['x']:.6f})"
        ),
        (
            f"Destination: Marathahalli Bridge | OSM node {destination} | "
            f"SUMO node {routes[0]['end_sumo_node']} | "
            f"({destination_data['y']:.6f}, {destination_data['x']:.6f})"
        ),
        "",
        "ROUTE PAIR CHECKS",
        "-" * 40,
        "Routes exported: exactly 2",
        f"Shared directed edges: {overlap_pct:.1f}%",
        f"Longer/shorter distance ratio: {length_ratio:.2f}x",
        (
            "Realism check: PASS"
            if length_ratio <= MAX_REALISTIC_LENGTH_RATIO
            else "Realism check: WARNING - longer route exceeds 1.5x"
        ),
        "",
        "IDENTIFIED ROUTES",
        "-" * 40,
    ]

    for route in routes:
        text_lines.extend(
            [
                "",
                f"Route {route['index']}: {route['label']}",
                f"  Distance: {route['length_km']:.2f} km",
                f"  OSM start node: {route['start_node']}",
                f"  OSM end node: {route['end_node']}",
                f"  SUMO start node: {route['start_sumo_node']}",
                f"  SUMO end node: {route['end_sumo_node']}",
                f"  OSM node sequence: {route['node_sequence']}",
                f"  SUMO node sequence: {route['sumo_node_sequence']}",
                f"  Road names: {', '.join(route['road_names'])}",
            ]
        )

    text_lines.extend(
        [
            "",
            "FILES",
            "-" * 40,
            f"Trimmed OSM XML: {osm_path}",
            f"SUMO net.xml: {net_path}",
            f"Route plot: {plot_path}",
            "",
            "MACHINE-READABLE JSON",
            "-" * 40,
            json.dumps(summary, indent=2),
            "",
        ]
    )

    summary_path.write_text("\n".join(text_lines), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    ox.settings.cache_folder = str(CACHE_DIR)
    ox.settings.use_cache = True

    print("=" * 72)
    print("STEP 1: Pull road network with OSMnx graph_from_bbox")
    print("=" * 72)
    print(f"Bounding box (W, S, E, N): {BBOX}")
    print(f"Origin: Silk Board Junction {SILK_BOARD}")
    print(f"Destination: Marathahalli Bridge {MARATHAHALLI}")

    G = ox.graph_from_bbox(
        bbox=BBOX,
        network_type="drive",
        simplify=True,
        retain_all=False,
        truncate_by_edge=True,
    )
    G_unsimplified = ox.graph_from_bbox(
        bbox=BBOX,
        network_type="drive",
        simplify=False,
        retain_all=False,
        truncate_by_edge=True,
    )
    print(f"Simplified routing graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print(f"Unsimplified export graph: {G_unsimplified.number_of_nodes()} nodes, {G_unsimplified.number_of_edges()} edges")

    print("\n" + "=" * 72)
    print("STEP 2: Locate origin and destination nodes")
    print("=" * 72)
    origin = ox.nearest_nodes(G, X=SILK_BOARD[1], Y=SILK_BOARD[0])
    destination = ox.nearest_nodes(G, X=MARATHAHALLI[1], Y=MARATHAHALLI[0])
    origin_data = G.nodes[origin]
    destination_data = G.nodes[destination]
    print(f"Origin OSM node: {origin} ({origin_data['y']:.6f}, {origin_data['x']:.6f})")
    print(f"Destination OSM node: {destination} ({destination_data['y']:.6f}, {destination_data['x']:.6f})")

    print("\n" + "=" * 72)
    print("STEP 3: Find exactly two realistic alternate routes")
    print("=" * 72)
    first_path = ox.shortest_path(G, origin, destination, weight="length")
    if not first_path:
        raise RuntimeError("No shortest path found between the selected endpoint nodes.")

    second_path, second_choice = choose_second_route(G, origin, destination, first_path)
    route_paths = [first_path, second_path]

    first_profile = route_profile(G, first_path)
    second_profile = route_profile(G, second_path)
    overlap_pct = shared_edge_pct(first_path, second_path)
    lengths = [first_profile["length_km"], second_profile["length_km"]]
    length_ratio = max(lengths) / min(lengths)

    print("Route 1 penalty: none (shortest path)")
    print(f"Route 2 selected from edge penalty {second_choice['penalty']}")
    print(f"Shared directed edges: {overlap_pct:.1f}%")
    print(f"Length ratio: {length_ratio:.2f}x")
    if overlap_pct > TARGET_MAX_SHARED_EDGES:
        print("Overlap note: low-overlap target was relaxed to keep the route realistic.")
    if length_ratio > MAX_REALISTIC_LENGTH_RATIO:
        print("WARNING: selected second route exceeds the requested 1.5x realism threshold.")

    print("\n" + "=" * 72)
    print("STEP 4: Plot both routes")
    print("=" * 72)
    colors = [mcolors.TABLEAU_COLORS["tab:red"], mcolors.TABLEAU_COLORS["tab:blue"]]
    fig, ax = ox.plot_graph_routes(
        G,
        route_paths,
        route_colors=colors,
        route_linewidths=[4, 4],
        node_size=0,
        bgcolor="white",
        edge_color="#d0d0d0",
        edge_linewidth=0.5,
        figsize=(14, 10),
        show=False,
        close=False,
    )
    ax.scatter([origin_data["x"]], [origin_data["y"]], c="black", s=130, zorder=10, marker="*", label="Origin")
    ax.scatter([destination_data["x"]], [destination_data["y"]], c="green", s=130, zorder=10, marker="*", label="Destination")

    from matplotlib.lines import Line2D

    legend_elements = [
        Line2D([0], [0], marker="*", color="w", markerfacecolor="black", markersize=12, label="Silk Board Junction"),
        Line2D([0], [0], marker="*", color="w", markerfacecolor="green", markersize=12, label="Marathahalli Bridge"),
        Line2D([0], [0], color=colors[0], linewidth=4, label=f"Route 1: {first_profile['label']} ({first_profile['length_km']:.1f} km)"),
        Line2D([0], [0], color=colors[1], linewidth=4, label=f"Route 2: {second_profile['label']} ({second_profile['length_km']:.1f} km)"),
    ]
    ax.legend(handles=legend_elements, loc="upper left", fontsize=9, framealpha=0.95)
    ax.set_title("Silk Board Junction to Marathahalli Bridge: two selected routes", fontsize=14)

    plot_path = OUTPUT_DIR / "network_routes.png"
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved route plot: {plot_path}")

    print("\n" + "=" * 72)
    print("STEP 5: Trim network and export SUMO net.xml")
    print("=" * 72)
    G_trim = trim_graph_to_routes(G_unsimplified, G, route_paths)
    print(f"Trimmed graph: {G_trim.number_of_nodes()} nodes, {G_trim.number_of_edges()} edges")

    osm_path = OUTPUT_DIR / "bangalore_corridor.osm"
    net_path = OUTPUT_DIR / "bangalore_corridor.net.xml"
    ox.save_graph_xml(G_trim, filepath=osm_path)
    print(f"Saved trimmed OSM XML: {osm_path} ({osm_path.stat().st_size / (1024 * 1024):.1f} MB)")

    netconvert_cmd = [
        "netconvert",
        "--osm-files",
        str(osm_path),
        "-o",
        str(net_path),
        "--geometry.remove",
        "--ramps.guess",
        "--junctions.join",
        "--tls.guess-signals",
        "--tls.discard-simple",
        "--tls.join",
    ]
    result = subprocess.run(netconvert_cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print("netconvert failed with rich options; retrying minimal conversion.")
        print(result.stderr[-1000:])
        result = subprocess.run(
            ["netconvert", "--osm-files", str(osm_path), "-o", str(net_path), "--geometry.remove"],
            capture_output=True,
            text=True,
            check=False,
        )

    if result.returncode != 0:
        print(result.stderr)
        sys.exit(result.returncode)

    warnings = [line for line in result.stderr.splitlines() if "Warning" in line]
    print(f"Saved SUMO net.xml: {net_path} ({net_path.stat().st_size / (1024 * 1024):.1f} MB)")
    if warnings:
        print(f"netconvert warnings: {len(warnings)}")

    print("\n" + "=" * 72)
    print("STEP 6: Save route summary")
    print("=" * 72)
    route_node_ids = ordered_unique([node for path in route_paths for node in path])
    sumo_lookup = parse_sumo_junction_ids(net_path, route_node_ids)

    routes = []
    for index, (path, profile) in enumerate(((first_path, first_profile), (second_path, second_profile)), start=1):
        sumo_node_sequence = [sumo_lookup.get(node) or str(node) for node in path]
        route = {
            "index": index,
            "label": profile["label"],
            "length_km": round(profile["length_km"], 3),
            "node_count": profile["node_count"],
            "scores": profile["scores"],
            "road_names": profile["road_names"],
            "start_node": path[0],
            "end_node": path[-1],
            "start_sumo_node": sumo_node_sequence[0],
            "end_sumo_node": sumo_node_sequence[-1],
            "node_sequence": path,
            "sumo_node_sequence": sumo_node_sequence,
        }
        routes.append(route)
        print_route_block(route)

    summary_path = OUTPUT_DIR / "route_summary.txt"
    write_summary(
        summary_path=summary_path,
        routes=routes,
        origin=origin,
        destination=destination,
        origin_data=origin_data,
        destination_data=destination_data,
        overlap_pct=overlap_pct,
        length_ratio=length_ratio,
        osm_path=osm_path,
        net_path=net_path,
        plot_path=plot_path,
    )
    print(f"Saved summary: {summary_path}")

    print("\n" + "=" * 72)
    print("DONE: Day 2 network setup complete")
    print("=" * 72)
    print(f"Routes: exactly {len(routes)}")
    print(f"Distances: {routes[0]['length_km']:.2f} km, {routes[1]['length_km']:.2f} km")
    print(f"Shared directed edges: {overlap_pct:.1f}%")
    print(f"SUMO net: {net_path}")


if __name__ == "__main__":
    main()
