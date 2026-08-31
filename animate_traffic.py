import ast
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from pathlib import Path
import osmnx as ox

OUTPUT_DIR = Path(r'd:\razorpay\output')
CACHE_DIR = Path(r'd:\razorpay\cache')
ox.settings.cache_folder = str(CACHE_DIR)
ox.settings.use_cache = True

print("Loading route summary...")
with open(OUTPUT_DIR / "route_summary.txt", "r") as f:
    lines = f.readlines()

paths = []
for line in lines:
    if "OSM node sequence:" in line:
        path_str = line.split("OSM node sequence:")[1].strip()
        paths.append(ast.literal_eval(path_str))

path1 = paths[0]
path2 = paths[1]

print("Loading text from summary...")
with open(OUTPUT_DIR / "FINAL_RESULT_SUMMARY.txt", "r") as f:
    summary_lines = f.readlines()
base_text = summary_lines[0].strip()
opt_text = summary_lines[1].strip()

print("Loading graph...")
BBOX = (77.60, 12.900, 77.72, 12.970)
G = ox.graph_from_bbox(bbox=BBOX, network_type="drive", simplify=True, retain_all=False, truncate_by_edge=True)

def interpolate_path(path_nodes, num_points=300):
    coords = np.array([(G.nodes[n]['x'], G.nodes[n]['y']) for n in path_nodes if n in G.nodes])
    if len(coords) == 0:
        return np.zeros((num_points, 2))
    
    # Calculate cumulative distances
    dists = np.zeros(len(coords))
    for i in range(1, len(coords)):
        dists[i] = dists[i-1] + np.linalg.norm(coords[i] - coords[i-1])
        
    total_dist = dists[-1]
    if total_dist == 0:
        return np.repeat(coords[0:1], num_points, axis=0)
        
    # Interpolate evenly spaced points
    target_dists = np.linspace(0, total_dist, num_points)
    
    x = np.interp(target_dists, dists, coords[:, 0])
    y = np.interp(target_dists, dists, coords[:, 1])
    
    return np.column_stack((x, y))

NUM_FRAMES = 150
p1_interp = interpolate_path(path1, num_points=1000)
p2_interp = interpolate_path(path2, num_points=1000)

print("Creating animation...")
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
fig.patch.set_facecolor('#111111')

# Draw background network paths
for ax in (ax1, ax2):
    ax.set_facecolor('#111111')
    ax.plot(p1_interp[:, 0], p1_interp[:, 1], color='#444444', lw=4, zorder=1)
    ax.plot(p2_interp[:, 0], p2_interp[:, 1], color='#444444', lw=4, zorder=1)
    ax.axis('off')

ax1.set_title(base_text, color='white', pad=20, fontsize=14)
ax2.set_title(opt_text, color='white', pad=20, fontsize=14)

# Create scatter plots for vehicles
scat1 = ax1.scatter([], [], c='red', s=40, zorder=3)
scat2_orr = ax2.scatter([], [], c='#00ff00', s=40, zorder=3)
scat2_sar = ax2.scatter([], [], c='#00ff00', s=40, zorder=3)

# Vehicle states
N_VEHICLES = 60
base_positions = np.random.uniform(-0.3, 0.0, N_VEHICLES)

N_ORR = int(N_VEHICLES * 0.54)
N_SAR = N_VEHICLES - N_ORR
opt_orr_pos = np.random.uniform(-0.3, 0.0, N_ORR)
opt_sar_pos = np.random.uniform(-0.3, 0.0, N_SAR)

def update(frame):
    # Base configuration: all on ORR, move slow/bunch at beginning (0 to 0.3)
    progress = frame / NUM_FRAMES
    
    # 1. Baseline: traffic jam in the first 30% of the route
    curr_base_pos = base_positions + progress * 0.8
    # Non-linear speed to simulate jam:
    # If they are between 0 and 0.3, they move very slowly
    for i in range(len(curr_base_pos)):
        if 0.0 < curr_base_pos[i] < 0.35:
            curr_base_pos[i] = 0.0 + (curr_base_pos[i] * 0.3) # compress into jam
        elif curr_base_pos[i] >= 0.35:
            curr_base_pos[i] = 0.35 + (curr_base_pos[i] - 0.35) * 1.5 # speed up after jam
            
    # Clip and get coords
    curr_base_pos = np.clip(curr_base_pos, 0, 0.99)
    base_idx = (curr_base_pos * 999).astype(int)
    scat1.set_offsets(p1_interp[base_idx])
    
    # Change color to red if stuck in jam (position < 0.3)
    colors = np.array(['red' if p < 0.3 else 'orange' for p in curr_base_pos])
    scat1.set_color(colors)
    
    # 2. Optimal: smooth flow on both routes
    curr_opt_orr = np.clip(opt_orr_pos + progress * 1.2, 0, 0.99)
    curr_opt_sar = np.clip(opt_sar_pos + progress * 1.2, 0, 0.99)
    
    idx_orr = (curr_opt_orr * 999).astype(int)
    idx_sar = (curr_opt_sar * 999).astype(int)
    
    scat2_orr.set_offsets(p1_interp[idx_orr])
    scat2_sar.set_offsets(p2_interp[idx_sar])
    
    return scat1, scat2_orr, scat2_sar

plt.tight_layout()
ani = animation.FuncAnimation(fig, update, frames=NUM_FRAMES, interval=50, blit=True)

out_path_gif = OUTPUT_DIR / 'traffic_management_demo.gif'
out_path_mp4 = OUTPUT_DIR / 'traffic_management_demo.mp4'

print("Saving animation...")
try:
    writer = animation.FFMpegWriter(fps=20, bitrate=2000)
    ani.save(out_path_mp4, writer=writer)
    print(f"Saved MP4 to {out_path_mp4}")
except Exception as e:
    print(f"FFMpeg failed ({e}), falling back to Pillow GIF writer...")
    ani.save(out_path_gif, writer='pillow', fps=20)
    print(f"Saved GIF to {out_path_gif}")

