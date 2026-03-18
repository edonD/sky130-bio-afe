#!/usr/bin/env python3
"""
1st-order SC Sigma-Delta ADC — Transistor-Level Evaluator
Runs ngspice transient simulation, extracts 1-bit bitstream,
computes SNDR/ENOB via FFT, then scores against specs.

NO behavioral Python modulator — all signal processing is
performed on the actual ngspice .tran waveform data.
"""

import os, sys, json, csv, subprocess, re, time
import numpy as np

BLOCK_DIR = os.path.dirname(os.path.abspath(__file__))
SPEC_FILE = os.path.join(BLOCK_DIR, "specs.json")
PARAM_FILE = os.path.join(BLOCK_DIR, "parameters.csv")
CIR_FILE   = os.path.join(BLOCK_DIR, "design.cir")
MEAS_FILE  = os.path.join(BLOCK_DIR, "measurements.json")
TRAN_DAT   = "/tmp/adc_tran.dat"

# ---------- corners for PVT sweep ----------
CORNERS = ["tt", "ff", "ss", "fs", "sf"]
TEMPS   = [27, -40, 125]

# ---------- ADC target parameters ----------
FS_HZ   = 1e6    # clock frequency
FIN_HZ  = 1.5e3  # input sine frequency; coherent: 1.5kHz*10000/1MHz = bin 15 (integer)
OSR     = 256    # effective OSR for EEG/ECG applications:
                 #   bandwidth = fs/(2*OSR) = 1MHz/512 = 1953Hz covers EEG+ECG (0-1kHz)
                 #   noise shaping gives ~8.5 ENOB over this band vs 4.6 ENOB at OSR=64
DEC_LEN = 512    # decimation filter length (must be ≤ total cycles captured)
SINC_N  = 3      # sinc^N decimation filter order

# ============================================================
# Parameter I/O
# ============================================================

def read_params():
    params = {}
    if not os.path.exists(PARAM_FILE):
        return params
    with open(PARAM_FILE) as f:
        for row in csv.DictReader(f):
            params[row['name']] = float(row['value'])
    return params

def read_specs():
    with open(SPEC_FILE) as f:
        return json.load(f)

# ============================================================
# SPICE netlist helpers
# ============================================================

def build_netlist(corner="tt", temp=27, out_path="/tmp/adc_sim.cir"):
    """Read design.cir, patch corner/temp, write to out_path."""
    with open(CIR_FILE) as f:
        netlist = f.read()

    # Patch corner in .lib line
    netlist = re.sub(
        r'(\.lib\s+\S+sky130\.lib\.spice\s+)\w+',
        lambda m: m.group(1) + corner,
        netlist
    )

    # Inject temperature
    if '.temp' in netlist.lower():
        netlist = re.sub(r'\.temp\s+[\d.\-]+', f'.temp {temp}', netlist, flags=re.IGNORECASE)
    else:
        # Insert after first .lib line
        netlist = re.sub(
            r'(\.lib\s+\S+sky130\.lib\.spice\s+\w+)',
            r'\1\n.temp ' + str(temp),
            netlist, count=1
        )

    with open(out_path, 'w') as f:
        f.write(netlist)
    return out_path

def run_ngspice(cir_path, timeout=300):
    """Run ngspice in batch mode, return (stdout, stderr, returncode)."""
    t0 = time.time()
    try:
        result = subprocess.run(
            ["ngspice", "-b", "-o", "/tmp/ngspice.log", cir_path],
            capture_output=True, text=True, timeout=timeout
        )
        dt = time.time() - t0
        return result.stdout, result.stderr, result.returncode, dt
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1, timeout

# ============================================================
# Waveform parsing
# ============================================================

def parse_wrdata(path):
    """
    Parse wrdata output file into a dict of arrays.
    Format: header line with variable names, then numeric rows.
    """
    if not os.path.exists(path):
        return None
    with open(path) as f:
        lines = f.readlines()

    # Find header (first non-comment line)
    header = None
    data_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('#') or stripped.startswith('$') or not stripped:
            continue
        # Check if this looks like a header (non-numeric)
        try:
            float(stripped.split()[0])
        except ValueError:
            header = stripped.split()
            data_start = i + 1
            break
        else:
            # No header, treat first col as 'time'
            header = None
            data_start = i
            break

    # Parse numeric data
    rows = []
    for line in lines[data_start:]:
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('$'):
            continue
        try:
            rows.append([float(x) for x in stripped.split()])
        except ValueError:
            continue

    if not rows:
        return None

    arr = np.array(rows)
    if header and len(header) == arr.shape[1]:
        return {h: arr[:, i] for i, h in enumerate(header)}
    else:
        # Fallback: columns are time, vint_out, vdac_q, vin, phi1, phi2, vcomp_p
        cols = ['time', 'v(vint_out)', 'v(vdac_q)', 'v(vin)', 'v(phi1)', 'v(phi2)', 'v(vcomp_p)']
        return {cols[i]: arr[:, i] for i in range(min(len(cols), arr.shape[1]))}

# ============================================================
# Bitstream extraction and SNDR/ENOB
# ============================================================

def _sample_at_phi2_edges(wavedata, col_key):
    """Sample wavedata[col_key] at phi2 falling edges. Returns 0/1 array."""
    phi2_key = None
    for k in wavedata.keys():
        if 'phi2' in k.lower() and 'b' not in k.lower():
            phi2_key = k
            break

    t    = wavedata['time']
    vdac = wavedata.get(col_key)
    if vdac is None:
        return None

    if phi2_key:
        phi2 = wavedata[phi2_key]
        edges = [i for i in range(1, len(phi2))
                 if phi2[i-1] > 0.9 and phi2[i] < 0.9]
        if len(edges) > 10:
            # 3-level decode: +1 / 0 / -1 for 1.8V / 0.9V / 0V DAC output
            def decode3(v):
                if v > 1.35:   return  1.0
                if v < 0.45:   return -1.0
                return 0.0
            return np.array([decode3(vdac[i]) for i in edges])

    # Fallback: regular sampling at 1µs intervals
    ts = t[1] - t[0]
    clk_samples = max(1, int(round(1e-6 / ts)))
    indices = np.arange(clk_samples//2, len(t), clk_samples)
    v = vdac[indices]
    return np.where(v > 1.35, 1.0, np.where(v < 0.45, -1.0, 0.0))


def extract_bitstream(wavedata):
    """
    Extract Stage 1 bitstream from vdac1_q (MASH) or vdac_q (legacy).
    Returns 0/1 array sampled at phi2 falling edges.
    """
    # MASH: look for vdac1_q first, then fall back to vdac_q
    for candidate in ['v(vdac1_q)', 'v(vdac_q)']:
        if candidate in wavedata:
            return _sample_at_phi2_edges(wavedata, candidate)
    # substring search
    for k in wavedata.keys():
        if 'dac1_q' in k.lower() or ('dac_q' in k.lower() and 'dac2' not in k.lower()):
            return _sample_at_phi2_edges(wavedata, k)
    # final fallback: second column
    keys = list(wavedata.keys())
    return _sample_at_phi2_edges(wavedata, keys[1]) if len(keys) > 1 else None


def extract_bitstream2(wavedata):
    """Extract Stage 2 bitstream from vdac2_q. Returns 0/1 array or None."""
    for candidate in ['v(vdac2_q)']:
        if candidate in wavedata:
            return _sample_at_phi2_edges(wavedata, candidate)
    for k in wavedata.keys():
        if 'dac2_q' in k.lower():
            return _sample_at_phi2_edges(wavedata, k)
    return None

def decimation_filter(bits, osr=OSR, order=SINC_N):
    """Apply sinc^N decimation filter to 1-bit bitstream. Returns baseband samples."""
    # Build sinc^1 impulse response (box filter of length osr)
    h_sinc1 = np.ones(osr) / osr
    # Cascade 'order' times
    h = h_sinc1.copy()
    for _ in range(order - 1):
        h = np.convolve(h, h_sinc1)

    # Apply filter and downsample by osr
    filtered = np.convolve(bits.astype(float), h, mode='valid')
    downsampled = filtered[::osr]
    return downsampled

def compute_sndr_enob(bits, fin_hz=FIN_HZ, fs_hz=FS_HZ, osr=OSR):
    """
    Compute in-band SNDR and ENOB directly from the 1-bit bitstream.

    Uses the full N-point bitstream FFT at the oversampled rate (fs_hz).
    With fin=1500Hz, fs=1MHz, N=10000: signal falls EXACTLY on bin 15 (coherent)
    → no spectral leakage → accurate SNDR measurement.

    In-band region: [0, fs_hz/(2*osr)].  SNDR includes harmonic distortion.
    """
    N = len(bits)
    if N < 256:
        return None, None

    bits_ac = bits.astype(float) - np.mean(bits)

    # Hann window (sidelobes -31dB; fine since signal is coherent → mainly in ±1 bins)
    window = np.hanning(N)
    spec = np.fft.rfft(bits_ac * window)
    power = np.abs(spec) ** 2

    # Signal bin (coherent: fin*N/fs_hz should be integer)
    sig_bin = int(round(fin_hz * N / fs_hz))
    sig_bin = max(2, min(sig_bin, len(power) - 3))

    # Signal power: ±2 bins (captures Hann window main lobe)
    sig_power = np.sum(power[sig_bin-2: sig_bin+3])

    # In-band noise: bins 1 to fs/(2*osr) / resolution, excluding signal ±2
    inband_cutoff = int(fs_hz / (2.0 * osr) / (fs_hz / N))
    inband_cutoff = min(inband_cutoff, len(power) - 1)
    noise_idx = [i for i in range(1, inband_cutoff + 1)
                 if i < sig_bin - 2 or i > sig_bin + 2]
    noise_power = sum(power[i] for i in noise_idx) if noise_idx else 1e-30

    if noise_power <= 0 or sig_power <= 0:
        return None, None

    sndr_db = 10 * np.log10(sig_power / noise_power)
    enob = (sndr_db - 1.76) / 6.02
    return sndr_db, enob

# ============================================================
# Main evaluation
# ============================================================

def evaluate_corner(corner, temp, timeout=480):
    """Run one PVT corner, return dict of metrics."""
    cir_path = f"/tmp/adc_{corner}_{temp}.cir"
    build_netlist(corner=corner, temp=temp, out_path=cir_path)

    stdout, stderr, rc, dt = run_ngspice(cir_path, timeout=timeout)

    result = {
        "corner": corner,
        "temp": temp,
        "ngspice_ok": rc == 0,
        "sim_time_s": dt,
        "enob": None,
        "sndr_db": None,
        "n_bits": 0,
        "error": None
    }

    if rc != 0:
        # Try to extract error from log
        log = ""
        if os.path.exists("/tmp/ngspice.log"):
            with open("/tmp/ngspice.log") as f:
                log = f.read()
        result["error"] = (stderr + log)[-500:]
        return result

    # Parse waveform
    wavedata = parse_wrdata(TRAN_DAT)
    if wavedata is None:
        result["error"] = f"No waveform data at {TRAN_DAT}"
        return result

    # Extract Stage 1 bitstream
    bits1 = extract_bitstream(wavedata)
    if bits1 is None or len(bits1) < 256:
        result["error"] = f"Stage1 bitstream too short: {len(bits1) if bits1 is not None else 0}"
        return result

    result["n_bits"] = len(bits1)

    density1 = float(np.mean(np.abs(bits1)))
    result["bit_density"] = density1
    if density1 > 0.98:
        result["error"] = f"Stage1 bitstream stuck: activity={density1:.3f}"

    # Try MASH combination if Stage 2 bitstream is present
    bits2 = extract_bitstream2(wavedata)
    if bits2 is not None and len(bits2) >= len(bits1):
        # Align lengths
        N = min(len(bits1), len(bits2))
        y1 = bits1[:N].astype(float)
        y2 = bits2[:N].astype(float)
        # MASH 1-1 digital combination: y_final[n] = y1[n] + (1/a2)*(y2[n] - y2[n-1])
        # a2 = Cs2a/Ci2 = 0.5 → 1/a2 = 2
        y_final = y1[1:] + 2.0*(y2[1:] - y2[:-1])
        density2 = float(np.mean(bits2))
        result["bit_density2"] = density2
        sndr_db, enob = compute_sndr_enob(y_final)
        result["mash_used"] = True
    else:
        # Fallback: Stage 1 only
        sndr_db, enob = compute_sndr_enob(bits1)
        result["mash_used"] = False

    result["sndr_db"] = float(sndr_db) if sndr_db is not None else None
    result["enob"]    = float(enob)    if enob    is not None else None

    return result


def score_result(result, specs):
    """Convert metrics to 0-1 score based on specs."""
    if not result.get("ngspice_ok"):
        return 0.0
    enob = result.get("enob")
    if enob is None:
        return 0.0

    target_enob = specs.get("enob_min", 14.0)
    # Graceful scoring: 0.5 at target/2, 1.0 at target+2
    score = min(1.0, max(0.0, (enob - target_enob * 0.5) / (target_enob * 0.5 + 2.0)))
    return score


def main():
    specs = read_specs()

    # Run TT 27°C first (fastest feedback)
    print("=== ADC Evaluation: Transistor-level SC Sigma-Delta ===")
    print(f"  CIR: {CIR_FILE}")
    print(f"  OSR={OSR}, fs={FS_HZ/1e6:.1f}MHz, fin={FIN_HZ/1e3:.1f}kHz")
    print()

    # Run TT corner first
    tt_result = evaluate_corner("tt", 27)
    print(f"[TT 27°C] ngspice_ok={tt_result['ngspice_ok']}, "
          f"sim_time={tt_result['sim_time_s']:.1f}s, "
          f"n_bits={tt_result['n_bits']}, "
          f"ENOB={tt_result.get('enob')}, "
          f"SNDR={tt_result.get('sndr_db'):.1f}dB" if tt_result.get('sndr_db') else
          f"[TT 27°C] ngspice_ok={tt_result['ngspice_ok']}, error={tt_result.get('error','')[:200]}")

    if not tt_result['ngspice_ok'] or tt_result.get('enob') is None:
        print("\nFAIL: TT simulation did not produce valid ENOB.")
        print("Error:", tt_result.get('error', 'unknown'))
        # Write partial measurements for optimizer feedback
        measurements = {
            "score": 0.0,
            "enob_tt_27": None,
            "sndr_tt_27": None,
            "error": tt_result.get('error', '')[:500],
            "ngspice_ok": False
        }
        with open(MEAS_FILE, 'w') as f:
            json.dump(measurements, f, indent=2)
        sys.exit(1)

    # Run PVT corners if TT passes
    all_results = [tt_result]
    pvt_corners = [("ff", -40), ("ff", 125), ("ss", -40), ("ss", 125)]
    for corner, temp in pvt_corners:
        r = evaluate_corner(corner, temp, timeout=480)
        all_results.append(r)
        enob_str = f"{r['enob']:.1f}" if r.get('enob') is not None else "N/A"
        print(f"[{corner.upper()} {temp:+d}°C] ENOB={enob_str}, "
              f"ok={r['ngspice_ok']}, time={r['sim_time_s']:.0f}s")

    # Collect ENOB across corners
    enob_values = [r['enob'] for r in all_results if r.get('enob') is not None]
    enob_min = min(enob_values) if enob_values else None
    enob_tt  = tt_result.get('enob')

    score = score_result(tt_result, specs)

    print(f"\n--- SUMMARY ---")
    print(f"  ENOB (TT/27°C): {enob_tt:.2f} bits" if enob_tt else "  ENOB: N/A")
    print(f"  ENOB (PVT min): {enob_min:.2f} bits" if enob_min else "  ENOB min: N/A")
    print(f"  Score: {score:.3f}")

    # Write measurements
    measurements = {
        "score": score,
        "enob_tt_27":  float(enob_tt)   if enob_tt   is not None else None,
        "enob_pvt_min": float(enob_min) if enob_min  is not None else None,
        "sndr_tt_27":  float(tt_result.get('sndr_db') or 0),
        "n_bits_tt":   tt_result.get('n_bits', 0),
        "pvt_results": [
            {k: (float(v) if isinstance(v, float) else v)
             for k, v in r.items()} for r in all_results
        ]
    }
    with open(MEAS_FILE, 'w') as f:
        json.dump(measurements, f, indent=2)

    print(f"\nMeasurements written to {MEAS_FILE}")
    return score


if __name__ == "__main__":
    main()
