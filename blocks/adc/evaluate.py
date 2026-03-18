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
FIN_HZ  = 1.5e3  # input sine frequency; 1.5kHz avoids sinc³ droop (-4.4dB at 5kHz)
OSR     = 64     # oversampling ratio (must match design.cir Ts)
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

def extract_bitstream(wavedata):
    """
    Sample vdac_q at phi2 falling edges to get 1-bit bitstream.
    Returns array of 0/1 values.
    """
    # Try to find the right column names
    time_key = 'time'
    dac_key  = None
    phi2_key = None

    for k in wavedata.keys():
        kl = k.lower()
        if 'dac_q' in kl or 'vdac_q' in kl:
            dac_key = k
        if 'phi2' in kl and 'b' not in kl:
            phi2_key = k

    if dac_key is None:
        # Fallback: second column after time
        keys = list(wavedata.keys())
        if len(keys) > 1:
            dac_key = keys[1]

    t     = wavedata[time_key]
    vdac  = wavedata.get(dac_key, None)

    if vdac is None:
        return None

    if phi2_key:
        phi2 = wavedata[phi2_key]
        # Find phi2 falling edges (threshold crossing 0.9V going down)
        edges = []
        for i in range(1, len(phi2)):
            if phi2[i-1] > 0.9 and phi2[i] < 0.9:
                edges.append(i)
        if len(edges) > 10:
            bits = []
            for idx in edges:
                bits.append(1 if vdac[idx] > 0.9 else 0)
            return np.array(bits)

    # Fallback: sample at regular intervals (every 1us = 1e-6)
    ts = t[1] - t[0]
    clk_samples = max(1, int(round(1e-6 / ts)))
    indices = np.arange(clk_samples//2, len(t), clk_samples)
    bits = (vdac[indices] > 0.9).astype(int)
    return bits

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

def compute_sndr_enob(samples, fin_hz=FIN_HZ, fs_output=None):
    """
    Compute SNDR and ENOB from decimated output samples.
    fs_output = FS_HZ / OSR (after decimation)
    """
    if fs_output is None:
        fs_output = FS_HZ / OSR

    N = len(samples)
    if N < 16:
        return None, None

    # Remove DC bias before FFT to prevent Hann window DC leakage into adjacent bins.
    # (SDM output has mean ≈ Vin/VDD ≈ 0.5; this DC would dominate the "noise" estimate
    # since Hann window leaks DC into bin±1, giving false SNDR ≈ -15 dB.)
    samples = samples - np.mean(samples)

    # Hann window to reduce spectral leakage
    window = np.hanning(N)
    spec = np.fft.rfft(samples * window)
    power = np.abs(spec) ** 2

    freqs = np.fft.rfftfreq(N, d=1.0/fs_output)

    # Find signal bin
    sig_bin = int(round(fin_hz / fs_output * N))
    sig_bin = max(1, min(sig_bin, len(power)-2))

    # Signal power: sum over ±2 bins around fundamental
    sig_power = np.sum(power[max(0, sig_bin-2): sig_bin+3])

    # Noise power: everything except signal and DC
    noise_idx = list(range(1, max(1, sig_bin-2))) + list(range(sig_bin+3, len(power)))
    noise_power = np.sum(power[noise_idx]) if noise_idx else 1e-30

    if noise_power <= 0 or sig_power <= 0:
        return None, None

    sndr_db = 10 * np.log10(sig_power / noise_power)
    enob = (sndr_db - 1.76) / 6.02

    return sndr_db, enob

# ============================================================
# Main evaluation
# ============================================================

def evaluate_corner(corner, temp):
    """Run one PVT corner, return dict of metrics."""
    cir_path = f"/tmp/adc_{corner}_{temp}.cir"
    build_netlist(corner=corner, temp=temp, out_path=cir_path)

    stdout, stderr, rc, dt = run_ngspice(cir_path, timeout=300)

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

    # Extract bitstream
    bits = extract_bitstream(wavedata)
    if bits is None or len(bits) < 100:
        result["error"] = f"Bitstream too short: {len(bits) if bits is not None else 0} bits"
        return result

    result["n_bits"] = len(bits)

    # Check bitstream is not stuck (density between 5% and 95%)
    density = np.mean(bits)
    result["bit_density"] = float(density)
    if density < 0.05 or density > 0.95:
        result["error"] = f"Bitstream stuck: density={density:.3f}"
        # Still compute ENOB anyway for diagnostics

    # Decimate and compute SNDR
    samples = decimation_filter(bits, osr=OSR, order=SINC_N)
    if len(samples) < 16:
        result["error"] = f"Too few decimated samples: {len(samples)}"
        return result

    sndr_db, enob = compute_sndr_enob(samples)
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
        r = evaluate_corner(corner, temp)
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
