# UrbanFlow AI — Proactive Traffic Management Prototype

A digital-twin prototype demonstrating **system-optimal, predictive traffic
routing** for Bangalore, built around the Silk Board Junction ↔ Marathahalli
Bridge corridor — one of the city's most congested stretches.

> Built for MSME Hackathon 2.0. This repository contains the working
> prototype behind the UrbanFlow AI pitch deck.

---

## The problem

Bangalore's traffic management is **reactive**: signals and navigation apps
respond to congestion after it happens. Worse, apps like Google Maps
independently route every driver toward the "best" route — causing everyone
to converge on the same road, which then congests, while alternate routes
sit underused.

## The idea

Instead of reactive, individually-optimized routing, coordinate traffic
**proactively**: predict congestion before it peaks, and distribute vehicles
across multiple available routes to minimize total system delay — not just
each driver's own trip.

---

## What's in this repository

| Component | Status | Description |
|---|---|---|
| Digital twin | ✅ Working | Real Bangalore road network (OSMnx/OpenStreetMap), exported to SUMO |
| Route verification | ✅ Working | 2 genuinely distinct routes identified: ORR (11.02km) and Sarjapur Road (13.57km), 5.7% edge overlap |
| Congestion simulation | ✅ Working | Real SUMO simulation of baseline (shortest-path) congestion at the Silk Board bottleneck |
| Real capacity measurement | ✅ Working | Silk Board bottleneck capacity measured directly from network data: 1,900 vehicles/hour |
| ML congestion prediction | ✅ Working | Regression model trained on real Bangalore traffic data (Kaggle: "Bangalore's Traffic Pulse"), R²=0.97, leakage-audited |
| Explainable AI layer | ✅ Working | Plain-English explanations of model predictions using feature importance |
| System-optimal comparison | ✅ Working (analytical) | BPR volume-delay function applied to real measured capacity — see Methodology below |
| Visualization | ✅ Working | Before/after traffic management animation, comparison charts, wide-area scaling map |

---

## Key results

Using real network geometry and a real measured bottleneck capacity:

| Metric | Baseline (all traffic → ORR) | System-Optimal (54% ORR / 46% Sarjapur) |
|---|---|---|
| Avg delay per driver | 6.9 min | 0.3 min |
| Avg travel time | 18.9 min | 12.6–14.8 min |
| Total system time | 840 vehicle-hours | 604 vehicle-hours |

**Result: 28.1% reduction in total system travel time**, and a 96% reduction
in per-driver delay, achieved purely by redistributing traffic across two
existing roads — no new infrastructure required.

---

## Repository structure

```
razorpay/
├── build_network.py              # Pulls & exports the road network (OSMnx → SUMO)
├── generate_demand.py            # Synthetic peak-hour demand, calibrated to real capacity
├── run_baseline.py               # Baseline (shortest-path) SUMO simulation
├── train_congestion_model.py     # ML model training on real Bangalore data
├── analytical_comparison.py      # BPR-based system-optimal comparison
├── explain_congestion.py         # Explainable AI layer for model predictions
├── wide_area_map.py              # Wider-area vision/scaling map
├── data/
│   └── Banglore_traffic_Dataset.csv   # Real Bangalore traffic data (Kaggle)
├── output/
│   ├── bangalore_corridor.net.xml     # Exported SUMO network
│   ├── network_routes.png             # Route visualization
│   ├── route_summary.txt              # Verified route geometry & node IDs
│   ├── bangalore_congestion_model.joblib  # Trained ML model
│   ├── congestion_model_report.txt        # Model performance report
│   ├── congestion_model_leakage_audit.txt # Leakage audit results
│   ├── FINAL_RESULT_SUMMARY.txt           # Final comparison numbers & methodology
│   └── wide_area_vision_map.png           # Scaling visualization
└── README.md
```

---

## How to run

**Requirements**: Python 3.10+, SUMO 1.27+, OSMnx 2.x

```bash
pip install osmnx sumolib pandas scikit-learn joblib matplotlib
```

```bash
# 1. Build the network
python build_network.py

# 2. Generate calibrated demand
python generate_demand.py

# 3. Run baseline simulation
python run_baseline.py

# 4. Train the congestion model
python train_congestion_model.py

# 5. Run the analytical comparison
python analytical_comparison.py

# 6. Get an explained prediction
python explain_congestion.py
```

---

## Methodology & honest scope notes

This section is here deliberately — a good engineering project states its
assumptions and limitations plainly.

- **Baseline congestion** is a real, completed SUMO microsimulation of this
  corridor under calibrated peak-hour demand.
- **The Silk Board bottleneck capacity (1,900 veh/hr)** is directly measured
  from the real network — it corresponds to a genuine single-lane merge
  point identified during network analysis.
- **The system-optimal comparison** is computed analytically using the BPR
  (Bureau of Public Roads) volume-delay function — the standard
  transportation-engineering formula for estimating travel time from
  volume and capacity — rather than a live dual-route SUMO simulation.
  This was a deliberate choice after encountering a routing-configuration
  issue where per-vehicle trip files did not reliably preserve distinct
  route assignments in SUMO's internal router. The analytical model uses
  the same real, verified inputs (measured capacity, real route distances)
  and is a standard, citable methodology — not simulated microbehavior,
  but not fabricated either.
- **Sarjapur Road's capacity (3,800 veh/hr)** is a standard 2-lane urban
  arterial capacity assumption, clearly distinguished from the *measured*
  ORR/Silk Board figure.
- **The ML congestion model** is trained on real historical data for Silk
  Board Junction, Marathahalli Bridge, and Sarjapur Road specifically
  (1,447 real records). The source dataset does not contain entries for
  ORR by name, so ORR's congestion behavior in this prototype relies on
  the simulation/capacity model rather than this specific trained model.

## Roadmap (not built in this prototype)

Consistent with the original pitch's phased roadmap: live camera/sensor
integration, whole-city network optimization (beyond this 2-route corridor),
ambulance priority routing, EV-specific routing, and closed-loop real-time
rerouting (via SUMO's TraCI or an equivalent live control interface) are
explicitly future-phase work, not part of this MVP.

## Data sources

- Road network: OpenStreetMap, via OSMnx
- Real traffic data: ["Bangalore's Traffic Pulse"](https://www.kaggle.com/datasets/preethamgouda/banglore-city-traffic-dataset) (Kaggle), also cited in peer-reviewed traffic-prediction research (Scientific Reports, Nov 2025)