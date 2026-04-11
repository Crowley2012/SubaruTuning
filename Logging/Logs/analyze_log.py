import csv
import statistics
from collections import defaultdict
import glob
import os
import math
import re
import json

# read all CSVs in the Logs folder for date 20260405
folder = os.path.dirname(__file__)
pattern = os.path.join(folder, 'romraiderlog_20260405_*.csv')
files = sorted(glob.glob(pattern))
if not files:
    raise SystemExit('No 20260405 log files found')

cols = None
rows = []
for path in files:
    with open(path, newline='') as f:
        reader = csv.reader(f)
        file_cols = next(reader)
        if cols is None:
            cols = file_cols
        elif cols != file_cols:
            # simple safety: require same headers across files
            raise SystemExit(f'Header mismatch in {path}')
        for r in reader:
            if not r:
                continue
            rows.append(r)

# map header to index
h = {c: i for i, c in enumerate(cols)}
needed = ["A/F Correction #1 (%)", "A/F Learning #1 (%)", "Ethanol Content (%)", "Engine Load*  (g/rev)", "Engine Speed (rpm)", "Throttle Sensor Voltage (V)"]
for n in needed:
    if n not in h:
        raise SystemExit(f"Missing column: {n}")

corrs = []
lears = []
ets = []
loads = []
rpms = []
by_eth = defaultdict(list)

for r in rows:
    try:
        corr = float(r[h["A/F Correction #1 (%)"]])
        learn = float(r[h["A/F Learning #1 (%)"]])
        eth = float(r[h["Ethanol Content (%)"]])
        load = float(r[h["Engine Load*  (g/rev)"]])
        rpm = float(r[h["Engine Speed (rpm)"]])
    except Exception as e:
        continue
    corrs.append(corr)
    lears.append(learn)
    nets = corr + learn
    ets.append(eth)
    loads.append(load)
    rpms.append(rpm)
    by_eth[round(eth,1)].append((corr, learn, nets))

# Filter by throttle stability: exclude throttle==0 and unstable (delta to neighbors > threshold)
thr_idx = h["Throttle Sensor Voltage (V)"]
throttle_vals = []
for r in rows:
    try:
        throttle_vals.append(float(r[thr_idx]))
    except:
        throttle_vals.append(0.0)

stable_mask = [False]*len(rows)
th_delta = 0.02
for i, v in enumerate(throttle_vals):
    if abs(v) < 1e-9:
        # throttle reported 0 -> skip (likely tip-in or closed throttle)
        continue
    prev_v = throttle_vals[i-1] if i>0 else v
    next_v = throttle_vals[i+1] if i<len(throttle_vals)-1 else v
    if abs(v-prev_v) <= th_delta and abs(v-next_v) <= th_delta:
        stable_mask[i] = True

# build filtered lists
fcorrs = []
flears = []
fnets = []
fby_eth = defaultdict(list)
for i, r in enumerate(rows):
    if not stable_mask[i]:
        continue
    try:
        c = float(r[h["A/F Correction #1 (%)"]])
        L = float(r[h["A/F Learning #1 (%)"]])
        e = float(r[h["Ethanol Content (%)"]])
    except:
        continue
    fcorrs.append(c)
    flears.append(L)
    fnets.append(c+L)
    fby_eth[round(e,1)].append(c+L)


def stats(arr):
    return {
        'count': len(arr),
        'mean': statistics.mean(arr) if arr else 0,
        'stdev': statistics.stdev(arr) if len(arr)>1 else 0,
        'min': min(arr) if arr else 0,
        'max': max(arr) if arr else 0,
    }

print('Rows parsed:', len(rows))
print('\nOverall A/F Correction #1 (%) stats:')
print(stats(corrs))
print('\nOverall A/F Learning #1 (%) stats:')
print(stats(lears))
net_vals = [c+l for c,l in zip(corrs, lears)]
print('\nOverall NET correction (correction + learning) stats:')
print(stats(net_vals))

print('\nEthanol content unique values and per-value net means:')
for eth_val in sorted(by_eth.keys()):
    lst = by_eth[eth_val]
    nets = [t[2] for t in lst]
    print(f"{eth_val}% -> count {len(nets)}, mean net {statistics.mean(nets):.3f}, stdev {statistics.stdev(nets) if len(nets)>1 else 0:.3f}")

# compute net mean for the dominant ethanol value
if by_eth:
    # pick ethanol value with max count
    eth_dom = max(by_eth.keys(), key=lambda k: len(by_eth[k]))
    nets_dom = [t[2] for t in by_eth[eth_dom]]
    print(f"\nDominant ethanol {eth_dom}% samples: {len(nets_dom)}, mean net {statistics.mean(nets_dom):.3f}%")
    print('Recommended multiplier to table entries at that ethanol: 1 + mean_net/100')
    print(f"Multiplier = {1+statistics.mean(nets_dom)/100:.6f}")

print('\n--- Now filtered to stable throttle samples (throttle !=0 and neighbor delta <= 0.02V) ---')
print('Filtered sample count:', len(fnets))
if fnets:
    print('Filtered A/F Correction mean:', statistics.mean(fcorrs))
    print('Filtered A/F Learning mean:', statistics.mean(flears))
    print('Filtered NET mean:', statistics.mean(fnets))
    # dominant ethanol in filtered
    eth_dom_f = max(fby_eth.keys(), key=lambda k: len(fby_eth[k]))
    print(f'Dominant ethanol in filtered: {eth_dom_f}%, samples: {len(fby_eth[eth_dom_f])}, mean net {statistics.mean(fby_eth[eth_dom_f]):.3f}%')
    print('Filtered multiplier =', 1+statistics.mean(fby_eth[eth_dom_f])/100)
else:
    print('No filtered samples')

# --- Per-manifold-pressure (MAP) row multipliers ---
# Read the Selection3D table to determine number of MAP rows. We'll assume each row in the Selection3D
# corresponds to a MAP row in the ethanol compensation table. If that's not correct, tell me which axis
# maps to MAP and I will adapt.
selection_path = os.path.join(folder, 'Ethanol Content Global Compenstation.txt')
num_rows = None
if os.path.exists(selection_path):
    with open(selection_path, 'r', newline='') as sf:
        text = sf.read()
    m = re.search(r"\[Selection3D\]\s*(.+)$", text, re.DOTALL)
    if m:
        block = m.group(1).strip()
        lines = [l for l in block.splitlines() if l.strip()]
        num_rows = len(lines)
        print(f"Detected {num_rows} rows in Selection3D table")
    else:
        print('Could not find [Selection3D] block in selection file')
else:
    print('Selection3D file not found at', selection_path)

if num_rows and fnets:
    # Prefer fixed MAP breakpoints if available. Use the known breakpoints provided by the user as defaults
    # Manifold Pressure (psi absolute) - 18 rows
    map_breaks = [
        5.029988606770833,6.964599609375,8.899210611979166,10.833821614583334,12.7684326171875,14.703043619791666,16.637654622395832,18.572265625,20.506876627604168,22.441487630208332,24.3760986328125,26.310709635416668,28.245320638020832,30.179931640625,32.114542643229164,34.049153645833336,35.9837646484375,39.852986653645836
    ]
    # Ethanol Content (%) X axis (21 cols) - provided but not required for this pass
    ethanol_breaks = [
        0.0,8.000305180437934,10.000762951094835,14.999618524452583,20.0,25.000381475547417,30.000762951094835,34.99961852445258,40.0,45.000381475547414,50.000762951094835,54.99961852445258,60.0,65.00038147554741,70.00076295109483,74.99961852445259,80.0,85.00038147554741,90.00076295109483,94.99961852445259,100.0
    ]

    # collect MAP values for filtered samples
    map_idx = h.get('Manifold Absolute Pressure (psi)') or h.get('Manifold Absolute Pressure (psi relative sea level)') or h.get('Manifold Absolute Pressure (psi relative sea level)') or h.get('Manifold Absolute Pressure (psi)')
    if map_idx is None:
        print('MAP column not found in log headers; skipping per-MAP bin multipliers')
    else:
        map_vals = []
        map_nets = []
        map_eths = []
        for i, r in enumerate(rows):
            if not stable_mask[i]:
                continue
            try:
                mv = float(r[map_idx])
                e = round(float(r[h['Ethanol Content (%)']]),1)
                c = float(r[h['A/F Correction #1 (%)']])
                L = float(r[h['A/F Learning #1 (%)']])
            except:
                continue
            # only include samples of the dominant filtered ethanol
            if e != eth_dom_f:
                continue
            map_vals.append(mv)
            map_nets.append(c+L)
            map_eths.append(e)

        if not map_vals:
            print('No filtered samples for dominant ethanol to compute MAP bins')
        else:
            # create bins based on fixed map_breaks: boundaries are midpoints between breakpoints
            breaks = map_breaks
            edges = []
            for i in range(len(breaks)-1):
                edges.append((breaks[i] + breaks[i+1]) / 2.0)
            # establish bin ranges: first bin is (-inf, edge0], middle bins (edge_{i-1}, edge_i], last (edge_{-1}, +inf)
            bin_ranges_fixed = []
            if edges:
                bin_ranges_fixed.append((float('-inf'), edges[0]))
                for i in range(1, len(edges)):
                    bin_ranges_fixed.append((edges[i-1], edges[i]))
                bin_ranges_fixed.append((edges[-1], float('inf')))
            else:
                bin_ranges_fixed = [(float('-inf'), float('inf'))]

            # ensure number of bins equals num_rows
            if len(bin_ranges_fixed) != num_rows:
                print(f'Warning: computed {len(bin_ranges_fixed)} MAP bins but Selection3D has {num_rows} rows; proceeding with min count')

            # assign samples to bins
            assigned = [[] for _ in range(num_rows)]
            for mv, net in zip(map_vals, map_nets):
                assigned_idx = None
                for bi, (lo, hi) in enumerate(bin_ranges_fixed):
                    if mv <= hi and mv > lo:
                        assigned_idx = bi
                        break
                if assigned_idx is None:
                    # fallback: nearest breakpoint
                    diffs = [abs(mv - b) for b in breaks]
                    assigned_idx = diffs.index(min(diffs))
                if assigned_idx < len(assigned):
                    assigned[assigned_idx].append(net)

            multipliers = []
            for r_i in range(num_rows):
                nets = assigned[r_i]
                if not nets:
                    multipliers.append((r_i, None, None, 0, bin_ranges_fixed[r_i] if r_i < len(bin_ranges_fixed) else (None,None)))
                else:
                    mean_net = statistics.mean(nets)
                    mult = 1 + mean_net/100
                    multipliers.append((r_i, mean_net, mult, len(nets), bin_ranges_fixed[r_i] if r_i < len(bin_ranges_fixed) else (None,None)))

            print('\nPer-MAP-row suggested multipliers using fixed MAP breakpoints:')
            for r_i, mean_net, mult, cnt, br in multipliers:
                if mean_net is None:
                    print(f'row {r_i}: MAP range {br[0]}-{br[1]} psi, samples 0 -> leave unchanged or interpolate')
                else:
                    print(f'row {r_i}: MAP range {br[0]:.2f}-{br[1]:.2f} psi, samples {cnt}, mean net {mean_net:.3f}%, multiplier {mult:.6f}')

            # Apply multipliers to Selection3D values and write a new file
            sel_in_path = selection_path
            sel_out_path = os.path.join(folder, 'Ethanol Content Global Compenstation.updated.txt')
            with open(sel_in_path, 'r', newline='') as sf:
                txt = sf.read()
            m = re.search(r"(\[Selection3D\]\s*)(.+)$", txt, re.DOTALL)
            if not m:
                print('Could not find Selection3D block to apply changes')
            else:
                header = m.group(1)
                block = m.group(2).strip()
                lines = [l for l in block.splitlines() if l.strip()]
                # Determine which ethanol columns have filtered data (from fby_eth built earlier)
                obs_eth_values = sorted(fby_eth.keys())
                if obs_eth_values:
                    eth_min = min(obs_eth_values)
                    eth_max = max(obs_eth_values)
                else:
                    eth_min = None; eth_max = None
                # Enforce user constraint: only update columns between 60% and 68%
                if eth_min is not None:
                    eth_min = max(eth_min, 60.0)
                    eth_max = min(eth_max, 68.0)
                apply_col_idx = set()
                for ci, eth_bp in enumerate(ethanol_breaks):
                    if eth_min is None:
                        continue
                    # include breakpoint if it lies within the observed & allowed ethanol window
                    if eth_bp >= eth_min - 0.01 and eth_bp <= eth_max + 0.01:
                        apply_col_idx.add(ci)
                print('Observed ethanol range (after intersecting with 60-68%):', eth_min, eth_max)
                print('Will apply column multipliers to ethanol columns indices:', sorted(list(apply_col_idx)))
                new_lines = []
                for i, line in enumerate(lines):
                    parts = line.strip().split()
                    nums = []
                    for p in parts:
                        try:
                            nums.append(float(p))
                        except:
                            nums.append(p)
                    # apply multiplier for row i if present
                    mult = None
                    if i < len(multipliers):
                        mult = multipliers[i][2]
                    if mult is None:
                        new_parts = [str(x) for x in parts]
                    else:
                        new_parts = []
                        for col_i, v in enumerate(nums):
                            if isinstance(v, float):
                                # only apply multiplier if this ethanol column has data
                                if col_i in apply_col_idx:
                                    new_v = v * mult
                                else:
                                    new_v = v
                                new_parts.append(f"{new_v:.6f}")
                            else:
                                new_parts.append(str(v))
                    new_lines.append('\t'.join(new_parts))
                new_block = header + '\n' + '\n'.join(new_lines) + '\n'
                # build new file text: replace old block
                new_txt = re.sub(r"(\[Selection3D\]\s*)(.+)$", new_block, txt, flags=re.DOTALL)
                with open(sel_out_path, 'w', newline='') as of:
                    of.write(new_txt)
                print('\nWrote updated Selection3D to', sel_out_path)

            print('\nNotes:')
            print('- Bins are created by sorting filtered MAP values for the dominant ethanol (61.5%) and splitting into', num_rows, 'equal-sized slices.\n- If your table rows correspond to fixed MAP breakpoints (not quantiles), provide those breakpoints and I will recompute exact bin->row mapping.')

# also show corrections at higher load (engine load > 1.5 g/rev) as a representative
# (computed below by iterating rows)

# If the above failed (complex), compute simply by iterating again
high_list = []
for r in rows:
    try:
        ld = float(r[h['Engine Load*  (g/rev)']])
        if ld>1.5:
            c = float(r[h['A/F Correction #1 (%)']]); L = float(r[h['A/F Learning #1 (%)']])
            high_list.append(c+L)
    except:
        pass
if high_list:
    print('\nHigh-load (g/rev>1.5) mean net correction: ', statistics.mean(high_list))
else:
    print('\nNo samples with Engine Load >1.5 g/rev')
