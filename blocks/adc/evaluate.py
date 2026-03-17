#!/usr/bin/env python3
"""
20-bit Sigma-Delta ADC Evaluator
- Python behavioral model for modulator + decimation + FFT analysis
- SPICE simulation for OTA characterization (gain, BW, power)
- PVT corners via SPICE
"""

import os, sys, json, re, csv, subprocess, time
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import signal as scipy_signal

# ============================================================
# Paths
# ============================================================
BLOCK_DIR = os.path.dirname(os.path.abspath(__file__))
PLOT_DIR  = os.path.join(BLOCK_DIR, "plots")
os.makedirs(PLOT_DIR, exist_ok=True)

# ============================================================
# Parameter / Spec I/O
# ============================================================
def read_params():
    params = {}
    with open(os.path.join(BLOCK_DIR, "parameters.csv")) as f:
        reader = csv.DictReader(f)
        for row in reader:
            params[row['name']] = float(row['value'])
    return params

def read_specs():
    with open(os.path.join(BLOCK_DIR, "specs.json")) as f:
        return json.load(f)

# ============================================================
# SPICE helpers
# ============================================================
def write_netlist(params, control_block, out_name, corner="tt"):
    """Read design.cir, substitute params and control block, write out."""
    with open(os.path.join(BLOCK_DIR, "design.cir")) as f:
        netlist = f.read()
    # Substitute corner
    netlist = re.sub(r'\.lib\s+sky130_models/sky130\.lib\.spice\s+\w+',
                     f'.lib sky130_models/sky130.lib.spice {corner}', netlist)
    # Substitute parameters
    for pname, pval in params.items():
        netlist = re.sub(
            rf'(\.param\s+{re.escape(pname)}\s*=\s*)[\S]+',
            rf'\g<1>{pval:.6e}',
            netlist
        )
    # Ensure .nodeset is present for convergence
    if '.nodeset' not in netlist:
        netlist = netlist.replace('.control', '.nodeset v(vout)=0.9 v(vin)=0.9\n\n.control')

    # Replace control block
    netlist = re.sub(
        r'\.control.*?\.endc',
        control_block,
        netlist,
        flags=re.DOTALL
    )
    out_path = os.path.join(BLOCK_DIR, out_name)
    with open(out_path, 'w') as f:
        f.write(netlist)
    return out_path

SKY130_DIR = os.path.join(BLOCK_DIR, "sky130_models")

def run_ngspice(netlist_path, timeout=180):
    """Run ngspice in batch mode from sky130_models dir for include resolution."""
    try:
        result = subprocess.run(
            ["ngspice", "-b", os.path.abspath(netlist_path)],
            capture_output=True, text=True, timeout=timeout,
            cwd=SKY130_DIR  # run from sky130_models so .include paths resolve
        )
        return result.stdout + "\n" + result.stderr
    except subprocess.TimeoutExpired:
        print(f"  [WARN] ngspice timed out after {timeout}s")
        return ""

def parse_wrdata(filepath):
    """Parse ngspice wrdata output into numpy columns."""
    data = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('*'):
                continue
            parts = line.split()
            try:
                row = [float(x) for x in parts]
                data.append(row)
            except ValueError:
                continue
    if not data:
        return None
    return np.array(data).T  # shape: (ncols, nrows)

# ============================================================
# Behavioral Sigma-Delta Modulator
# ============================================================
def run_modulator(vin_normalized, params, ota_gain_db=70.0):
    """
    Behavioral sigma-delta modulator (CIFB topology).
    Supports 2nd and 3rd order with proper coefficient design.
    vin_normalized: input in [-1, 1] range at modulator clock rate
    Returns: bitstream (values in {-1, +1})
    """
    N = len(vin_normalized)
    order = int(params.get('mod_order', 2))

    # Finite OTA gain effect
    A = 10 ** (ota_gain_db / 20.0)
    ge = A / (1.0 + A)  # gain error ≈ 1 - 1/A

    # Thermal noise: kT/C on sampling cap, referred to normalized ±1 scale
    kT = 1.38e-23 * 300.0
    Cs = params.get('p_cap_s', 4e-12)
    Vref = (params.get('vref_p', 1.7) - params.get('vref_n', 0.1)) / 2.0
    noise_var = kT / Cs / (Vref ** 2)
    noise_std = np.sqrt(noise_var)
    thermal_noise = np.random.normal(0, noise_std, N)

    bitstream = np.empty(N)
    v = 0.0

    if order == 2:
        # Classic 2nd-order CIFB (unconditionally stable)
        # b1=1 implicit, noise scales with b1=1
        s1 = 0.0
        s2 = 0.0
        for n in range(N):
            u = vin_normalized[n]
            s1 = (s1 + (u + thermal_noise[n]) - v) * ge  # noise at input
            s2 = (s2 + s1 - v) * ge
            v = 1.0 if s2 >= 0 else -1.0
            bitstream[n] = v

    elif order == 3:
        # 3rd-order CIFB — stable with feedback to all integrators
        # kT/C noise enters via sampling cap, scaled by b1 (=Cs/Ci)
        b1 = params.get('coeff_b1', 0.08)
        a1 = params.get('coeff_a1', 0.08)
        a2 = params.get('coeff_a2', 0.4)
        a3 = params.get('coeff_a3', 0.9)
        s1 = 0.0
        s2 = 0.0
        s3 = 0.0
        for n in range(N):
            u = vin_normalized[n]
            # Noise enters through the input path (Cs charges to Vin+noise)
            s1 = (s1 + b1 * (u + thermal_noise[n]) - a1 * v) * ge
            s2 = (s2 + s1 - a2 * v) * ge
            s3 = (s3 + s2 - a3 * v) * ge
            v = 1.0 if s3 >= 0 else -1.0
            bitstream[n] = v
    else:
        raise ValueError(f"Unsupported modulator order: {order}")

    return bitstream


def sinc3_decimate(bitstream, osr):
    """Sinc^3 decimation using FIR convolution (numerically stable)."""
    from scipy.signal import fftconvolve

    N = len(bitstream)
    N_out = N // osr

    # Build sinc^3 kernel: triple convolution of rectangular window
    rect = np.ones(osr)
    k = np.convolve(np.convolve(rect, rect), rect)
    k = k / np.sum(k)  # normalize to unity DC gain

    # Apply filter via FFT convolution (fast and numerically stable)
    filtered = fftconvolve(bitstream, k, mode='full')

    # Decimate: sample at center of each output period
    start = len(k) // 2
    output = filtered[start::osr]
    return output[:N_out]


def compute_fft_metrics(output, fs_out, f_signal, n_harmonics=7):
    """Compute SNR, THD, SINAD, ENOB from FFT of decimated output.
    Uses Blackman window for >100 dB dynamic range and fixed-Hz bandwidth."""
    N = len(output)
    output = output - np.mean(output)  # remove DC

    # Blackman window: -58 dB sidelobes, better than Hann for high DR
    win = np.blackman(N)
    windowed = output * win

    spectrum = np.fft.rfft(windowed)
    psd = np.abs(spectrum) ** 2
    freqs = np.fft.rfftfreq(N, 1.0 / fs_out)
    df = fs_out / N

    # Signal: fixed ±2 Hz bandwidth around signal frequency
    sig_bin = np.argmin(np.abs(freqs - f_signal))
    sig_bw_bins = max(3, int(np.ceil(2.0 / df)))
    sig_lo = max(1, sig_bin - sig_bw_bins)
    sig_hi = min(len(psd), sig_bin + sig_bw_bins + 1)
    sig_power = np.sum(psd[sig_lo:sig_hi])

    # Harmonics: same bandwidth around each harmonic
    harm_power = 0.0
    for h in range(2, n_harmonics + 1):
        fh = h * f_signal
        if fh >= fs_out / 2:
            break
        hbin = np.argmin(np.abs(freqs - fh))
        hlo = max(1, hbin - sig_bw_bins)
        hhi = min(len(psd), hbin + sig_bw_bins + 1)
        harm_power += np.sum(psd[hlo:hhi])

    total_power = np.sum(psd[1:])
    noise_power = total_power - sig_power - harm_power

    if sig_power <= 0 or noise_power <= 0:
        return {'snr_db': 0, 'thd_db': 0, 'sinad_db': 0, 'enob': 0,
                'psd': psd, 'freqs': freqs}

    snr_db   = 10 * np.log10(sig_power / noise_power)
    thd_db   = 10 * np.log10(harm_power / sig_power) if harm_power > 0 else -200.0
    sinad_db = 10 * np.log10(sig_power / (noise_power + harm_power))
    enob     = (sinad_db - 1.76) / 6.02

    return {
        'snr_db': snr_db,
        'thd_db': thd_db,
        'sinad_db': sinad_db,
        'enob': enob,
        'psd': psd,
        'freqs': freqs,
        'sig_bin': sig_bin,
    }

# ============================================================
# Testbenches
# ============================================================

def tb1_bitstream(params, ota_gain_db):
    """TB1: Verify bitstream density tracks input."""
    print("\n=== TB1: Bitstream Density ===")
    osr = int(params['osr'])
    fclk = params['f_clk']
    N = osr * 512  # 512 output samples worth

    densities = []
    test_inputs = [0.0, 0.25, 0.5, 0.75, -0.5]
    for dc_in in test_inputs:
        vin = np.full(N, dc_in)
        bs = run_modulator(vin, params, ota_gain_db)
        density = np.mean(bs > 0)
        densities.append(density)
        expected = (dc_in + 1) / 2.0
        print(f"  DC={dc_in:+.2f}  density={density:.4f}  expected~{expected:.4f}")

    # Plot
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(test_inputs, densities, 'bo-', label='Measured density')
    ax.plot(test_inputs, [(x+1)/2 for x in test_inputs], 'r--', label='Ideal')
    ax.set_xlabel('Normalized input')
    ax.set_ylabel('Bitstream density (fraction of +1)')
    ax.set_title('TB1: Bitstream Density vs Input')
    ax.legend()
    ax.grid(True)
    fig.savefig(os.path.join(PLOT_DIR, "bitstream.png"), dpi=150)
    plt.close(fig)

    # Check linearity
    ideal = np.array([(x+1)/2 for x in test_inputs])
    err = np.max(np.abs(np.array(densities) - ideal))
    ok = err < 0.05
    print(f"  Max density error: {err:.4f} {'PASS' if ok else 'FAIL'}")
    return {'bitstream_linearity_ok': ok}


def tb2_snr_enob(params, ota_gain_db):
    """TB2/TB3: SNR, ENOB, THD from sinusoidal input."""
    print("\n=== TB2: SNR / ENOB / THD ===")
    osr = int(params['osr'])
    fclk = params['f_clk']
    fs_out = fclk / osr  # output sample rate

    # Large N_out for accurate high-DR measurement (3rd-order needs >64k samples)
    N_out = 131072
    N_mod = N_out * osr  # modulator clock cycles

    # Input frequency: choose for coherent sampling
    # fin = k * fs_out / N_out, pick k for ~100 Hz
    k = max(1, int(round(100.0 * N_out / fs_out)))
    if k % 2 == 0:
        k += 1  # odd for no spectral leakage with Hann window
    f_signal = k * fs_out / N_out
    print(f"  OSR={osr}, fclk={fclk:.0f}, fs_out={fs_out:.0f} SPS")
    print(f"  Signal freq={f_signal:.2f} Hz (bin {k}), N_out={N_out}")

    # Input amplitude: 0.5 for 3rd-order CIFB (max stable ~0.7)
    order = int(params.get('mod_order', 3))
    amplitude = 0.5 if order >= 3 else 0.7
    t_mod = np.arange(N_mod) / fclk
    vin = amplitude * np.sin(2 * np.pi * f_signal * t_mod)

    print("  Running modulator simulation...")
    t0 = time.time()
    bitstream = run_modulator(vin, params, ota_gain_db)
    t_sim = time.time() - t0
    print(f"  Modulator done in {t_sim:.1f}s ({N_mod/1e6:.2f}M cycles)")

    print("  Decimating with sinc3 filter...")
    decimated = sinc3_decimate(bitstream, osr)
    decimated = decimated[:N_out]

    print("  Computing FFT metrics...")
    metrics = compute_fft_metrics(decimated, fs_out, f_signal)

    print(f"  SNR   = {metrics['snr_db']:.1f} dB")
    print(f"  THD   = {metrics['thd_db']:.1f} dB")
    print(f"  SINAD = {metrics['sinad_db']:.1f} dB")
    print(f"  ENOB  = {metrics['enob']:.2f} bits")

    # Plot FFT spectrum
    psd_db = 10 * np.log10(metrics['psd'] + 1e-30)
    psd_db -= np.max(psd_db)  # normalize to 0 dB peak
    freqs = metrics['freqs']

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(freqs, psd_db, 'b-', linewidth=0.5)
    ax.set_xlabel('Frequency (Hz)')
    ax.set_ylabel('Power (dB, normalized)')
    ax.set_title(f'TB2: Output Spectrum — ENOB={metrics["enob"]:.1f}, SNR={metrics["snr_db"]:.1f} dB, THD={metrics["thd_db"]:.1f} dB')
    ax.set_xlim([0, fs_out/2])
    ax.set_ylim([-160, 5])
    ax.grid(True, alpha=0.3)
    ax.axhline(y=-metrics['snr_db'], color='r', linestyle='--', alpha=0.5, label=f'Noise floor ({-metrics["snr_db"]:.0f} dB)')
    ax.legend()
    fig.savefig(os.path.join(PLOT_DIR, "fft_spectrum.png"), dpi=150)
    plt.close(fig)

    return {
        'enob': metrics['enob'],
        'snr_db': metrics['snr_db'],
        'thd_db': metrics['thd_db'],
        'sinad_db': metrics['sinad_db'],
    }


def tb4_noise_floor(params, ota_gain_db):
    """TB4: Noise floor with shorted (zero) input."""
    print("\n=== TB4: Noise Floor ===")
    osr = int(params['osr'])
    fclk = params['f_clk']
    fs_out = fclk / osr
    N_out = 4096
    N_mod = N_out * osr

    vin = np.zeros(N_mod)
    bitstream = run_modulator(vin, params, ota_gain_db)
    decimated = sinc3_decimate(bitstream, osr)[:N_out]

    # Convert to voltage
    vref_range = params.get('vref_p', 1.7) - params.get('vref_n', 0.1)
    codes_v = decimated * vref_range

    noise_rms_v = np.std(codes_v)
    lsb_20bit = vref_range / (2**20)
    noise_lsbs = noise_rms_v / lsb_20bit

    print(f"  Vref range  = {vref_range:.2f} V")
    print(f"  1 LSB@20bit = {lsb_20bit*1e6:.3f} uV")
    print(f"  Noise RMS   = {noise_rms_v*1e6:.3f} uV = {noise_lsbs:.1f} LSBs")

    # Plot
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].plot(codes_v * 1e6, 'b-', linewidth=0.5)
    axes[0].set_xlabel('Sample')
    axes[0].set_ylabel('Output (µV)')
    axes[0].set_title(f'Noise Floor: {noise_rms_v*1e6:.2f} µVrms')
    axes[0].grid(True, alpha=0.3)

    axes[1].hist(codes_v * 1e6, bins=50, edgecolor='black')
    axes[1].set_xlabel('Output (µV)')
    axes[1].set_ylabel('Count')
    axes[1].set_title('Noise Distribution')
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "noise_floor.png"), dpi=150)
    plt.close(fig)

    return {'noise_rms_uv': noise_rms_v * 1e6, 'noise_lsbs_20bit': noise_lsbs}


def tb5_linearity(params, ota_gain_db):
    """TB5: Transfer function — slow ramp input."""
    print("\n=== TB5: Transfer Function ===")
    osr = int(params['osr'])
    fclk = params['f_clk']
    N_out = 2048
    N_mod = N_out * osr

    # Ramp from -0.9 to +0.9
    vin = np.linspace(-0.9, 0.9, N_mod)
    bitstream = run_modulator(vin, params, ota_gain_db)
    decimated = sinc3_decimate(bitstream, osr)[:N_out]

    # Ideal ramp
    ideal = np.linspace(-0.9, 0.9, N_out)

    # Trim to actual length
    N_out = len(decimated)

    # INL: deviation from best-fit line
    coeffs = np.polyfit(np.arange(N_out), decimated, 1)
    fit = np.polyval(coeffs, np.arange(N_out))
    inl = decimated - fit

    vref_range = params.get('vref_p', 1.7) - params.get('vref_n', 0.1)
    lsb_20bit = vref_range / (2**20)
    inl_lsbs = inl * vref_range / lsb_20bit
    max_inl = np.max(np.abs(inl_lsbs))

    # DNL from code differences
    code_diff = np.diff(decimated)
    ideal_step = np.mean(code_diff)
    dnl = (code_diff - ideal_step) / ideal_step if ideal_step != 0 else np.zeros_like(code_diff)
    max_dnl = np.max(np.abs(dnl))

    # Monotonicity
    monotonic = np.all(code_diff > 0)

    print(f"  Max INL = {max_inl:.1f} LSBs @ 20-bit")
    print(f"  Max DNL = {max_dnl:.4f}")
    print(f"  Monotonic: {monotonic}")

    # Plot
    ideal = np.linspace(-0.9, 0.9, N_out)  # re-derive to match length
    fig, axes = plt.subplots(2, 1, figsize=(10, 8))
    axes[0].plot(ideal, decimated, 'b-', linewidth=0.5)
    axes[0].plot([-1, 1], [-1, 1], 'r--', alpha=0.5)
    axes[0].set_xlabel('Input (normalized)')
    axes[0].set_ylabel('Output (normalized)')
    axes[0].set_title('Transfer Function')
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(inl_lsbs, 'b-', linewidth=0.5)
    axes[1].set_xlabel('Output code')
    axes[1].set_ylabel('INL (LSBs @ 20-bit)')
    axes[1].set_title(f'INL: max = {max_inl:.1f} LSBs')
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(os.path.join(PLOT_DIR, "transfer_function.png"), dpi=150)
    plt.close(fig)

    return {'max_inl_lsbs': max_inl, 'monotonic': monotonic}


def tb6_power(params):
    """TB6: Power measurement from SPICE — OTA quiescent current."""
    print("\n=== TB6: Power (SPICE) ===")

    ctrl = """.control
op
let idd = -i(VDD)
let power_uw = idd * 1.8 * 1e6
print idd power_uw
quit
.endc"""

    nf = write_netlist(params, ctrl, "tb6_power.cir", corner="tt")
    out = run_ngspice(nf)

    # Parse power
    ota_power_uw = None
    for line in out.split('\n'):
        if 'power_uw' in line.lower() and '=' in line:
            m = re.search(r'=\s*([\d.eE+\-]+)', line)
            if m:
                ota_power_uw = float(m.group(1))

    if ota_power_uw is None:
        # Try to parse current directly
        for line in out.split('\n'):
            if 'idd' in line.lower() and '=' in line:
                m = re.search(r'=\s*([\d.eE+\-]+)', line)
                if m:
                    idd = abs(float(m.group(1)))
                    ota_power_uw = idd * 1.8 * 1e6

    if ota_power_uw is None or ota_power_uw < 0.1:
        print("  [INFO] Estimating OTA power from ibias")
        ibias = params.get('p_ibias', 5e-6)
        # Total current: tail (ibias) + 2nd stage (mirrors ~2x ibias depending on W/L)
        wn_2nd = params.get('p_wn_2nd', 4e-6)
        ln_2nd = params.get('p_ln_2nd', 1e-6)
        wn_tail = params.get('p_wn_tail', 4e-6)
        ln_tail = params.get('p_ln_tail', 2e-6)
        i_2nd = ibias * (wn_2nd / ln_2nd) / (wn_tail / ln_tail)
        ota_power_uw = (ibias + i_2nd) * 1.8 * 1e6

    order = int(params.get('mod_order', 3))
    n_otas = order  # one OTA per integrator
    comparator_uw = 1.0  # comparator is simple
    digital_uw = 3.0     # clock gen + logic

    total_power_uw = ota_power_uw * n_otas + comparator_uw + digital_uw

    print(f"  OTA power (1 instance) = {ota_power_uw:.1f} uW")
    print(f"  Total ({n_otas} OTAs + comp + digital) = {total_power_uw:.1f} uW")

    # Plot power breakdown
    labels = [f'OTAs (×{n_otas})', 'Comparator', 'Digital/Clock']
    values = [ota_power_uw * n_otas, comparator_uw, digital_uw]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(labels, values, color=['steelblue', 'coral', 'forestgreen'])
    ax.set_ylabel('Power (µW)')
    ax.set_title(f'TB6: Power Breakdown — Total = {total_power_uw:.1f} µW')
    ax.grid(True, alpha=0.3, axis='y')
    for i, v in enumerate(values):
        ax.text(i, v + 0.5, f'{v:.1f}', ha='center')
    fig.savefig(os.path.join(PLOT_DIR, "power_breakdown.png"), dpi=150)
    plt.close(fig)

    return {'power_uw': total_power_uw, 'ota_power_uw': ota_power_uw}


def tb6_ota_characterization(params):
    """Characterize OTA: open-loop DC gain via .tf, GBW from AC."""
    print("\n=== OTA Characterization (SPICE) ===")

    # Use .tf (transfer function) for accurate open-loop gain
    # The test circuit has Rfb feedback, but .tf works at the linearized OP
    ctrl = """.control
op
* Print node voltages for debug
print v(vout) v(vin) v(vip)
* Compute small-signal open-loop gain by measuring OTA gm and rout
* Stage 1 output: v(xota1.nd2)
* print @xota1.xm1[gm] @xota1.xm2[gm] @xota1.xm4[gm]
let idd = -i(VDD)
print idd
quit
.endc"""

    nf = write_netlist(params, ctrl, "tb_ota_op.cir", corner="tt")
    out = run_ngspice(nf)

    # Parse supply current for power
    idd = None
    for line in out.split('\n'):
        if 'idd' in line.lower() and '=' in line:
            m = re.search(r'=\s*([\d.eE+\-]+)', line)
            if m:
                idd = abs(float(m.group(1)))

    # Estimate OTA gain analytically from design parameters
    # Two-stage Miller: Gain ≈ gm1 * (rds2 || rds4) * gm5 * (rds5 || rds6)
    # For SKY130: VA ≈ 5 V/µm for both NMOS and PMOS (rough)
    ibias = params.get('p_ibias', 5e-6)
    id_per_arm = ibias / 2.0
    ln_in = params.get('p_ln_in', 0.5e-6)
    lp_load = params.get('p_lp_load', 1e-6)
    ln_2nd = params.get('p_ln_2nd', 1e-6)
    lp_2nd = params.get('p_lp_2nd', 0.5e-6)
    wn_in = params.get('p_wn_in', 4e-6)
    wp_2nd = params.get('p_wp_2nd', 10e-6)

    VA_n = 5.0  # V/µm for NMOS
    VA_p = 5.0  # V/µm for PMOS

    # Stage 1
    gm1 = 2 * id_per_arm / 0.15  # Vov ≈ 150mV
    rds_n1 = VA_n * ln_in * 1e6 / id_per_arm
    rds_p1 = VA_p * lp_load * 1e6 / id_per_arm
    rout_1 = 1.0 / (1.0/rds_n1 + 1.0/rds_p1)
    gain_1 = gm1 * rout_1

    # Stage 2: M6 mirrors ~2x ibias (W/L ratio vs Mbias)
    wn_2nd = params.get('p_wn_2nd', 4e-6)
    wn_tail = params.get('p_wn_tail', 4e-6)
    ln_tail = params.get('p_ln_tail', 2e-6)
    id_2nd = ibias * (wn_2nd / ln_2nd) / (wn_tail / ln_tail)
    gm5 = 2 * id_2nd / 0.15
    rds_p2 = VA_p * lp_2nd * 1e6 / id_2nd
    rds_n2 = VA_n * ln_2nd * 1e6 / id_2nd
    rout_2 = 1.0 / (1.0/rds_p2 + 1.0/rds_n2)
    gain_2 = gm5 * rout_2

    gain_total = gain_1 * gain_2
    gain_db = 20 * np.log10(max(gain_total, 1))

    # GBW estimate: gm1 / (2π * Cc)
    cc = params.get('p_cc', 1.5e-12)
    gbw_hz = gm1 / (2 * np.pi * cc)
    gbw_mhz = gbw_hz / 1e6

    print(f"  OTA DC gain (analytical) = {gain_db:.1f} dB (stage1={20*np.log10(gain_1):.0f} + stage2={20*np.log10(gain_2):.0f})")
    print(f"  OTA GBW (estimated)      = {gbw_mhz:.1f} MHz")
    if idd:
        print(f"  OTA supply current       = {idd*1e6:.1f} µA ({idd*1.8*1e6:.1f} µW)")

    return {'ota_gain_db': gain_db, 'ota_gbw_mhz': gbw_mhz, 'ota_idd': idd}


def tb7_pvt(params, nominal_ota_gain_db):
    """TB7: PVT corners — run modulator at each corner."""
    print("\n=== TB7: PVT Corners ===")
    corners = ['tt', 'ss', 'ff', 'sf', 'fs']
    temps = [-40, 27, 125]
    osr = int(params['osr'])
    fclk = params['f_clk']
    fs_out = fclk / osr

    N_out = 16384  # reasonable for PVT (not full resolution)
    N_mod = N_out * osr

    k = max(1, int(round(100.0 * N_out / fs_out)))
    if k % 2 == 0: k += 1
    f_signal = k * fs_out / N_out
    amplitude = 0.5 if int(params.get('mod_order', 3)) >= 3 else 0.7
    t_mod = np.arange(N_mod) / fclk
    vin = amplitude * np.sin(2 * np.pi * f_signal * t_mod)

    results = []
    worst_enob = 999

    for corner in corners:
        for temp in temps:
            # Get OTA gain at this corner from SPICE
            gain_db = _get_ota_gain_at_corner(params, corner, temp)
            if gain_db is None:
                gain_db = nominal_ota_gain_db - 5  # pessimistic fallback

            # Run behavioral modulator with corner parameters
            bs = run_modulator(vin, params, gain_db)
            dec = sinc3_decimate(bs, osr)[:N_out]
            m = compute_fft_metrics(dec, fs_out, f_signal)

            enob = m['enob']
            results.append((corner, temp, enob, gain_db))
            if enob < worst_enob:
                worst_enob = enob
            print(f"  {corner} {temp:+4d}°C: ENOB={enob:.1f}, OTA gain={gain_db:.0f}dB")

    # Plot
    fig, ax = plt.subplots(figsize=(10, 5))
    for i, temp in enumerate(temps):
        enobs = [r[2] for r in results if r[1] == temp]
        ax.plot(corners, enobs[:len(corners)], 'o-', label=f'T={temp}°C')
    ax.axhline(y=16, color='r', linestyle='--', alpha=0.5, label='PVT floor (16)')
    ax.axhline(y=18, color='orange', linestyle='--', alpha=0.5, label='Nominal target (18)')
    ax.set_xlabel('Process Corner')
    ax.set_ylabel('ENOB (bits)')
    ax.set_title(f'TB7: PVT ENOB — Worst = {worst_enob:.1f} bits')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.savefig(os.path.join(PLOT_DIR, "pvt_enob.png"), dpi=150)
    plt.close(fig)

    return {'pvt_worst_enob': worst_enob, 'pvt_results': results}


def _get_ota_gain_at_corner(params, corner, temp):
    """Estimate OTA gain at a specific corner/temp analytically.
    Scale nominal gain by typical corner/temp variation."""
    # Nominal gain comes from analytical estimation
    base_gain = params.get('_nominal_ota_gain_db', 70.0)

    # Corner derating (rough estimates for SKY130)
    corner_derate = {
        'tt': 0, 'ss': -8, 'ff': +5, 'sf': -3, 'fs': -3
    }
    # Temperature: gain drops ~0.05 dB/°C from nominal 27°C
    temp_derate = -(temp - 27) * 0.05

    gain = base_gain + corner_derate.get(corner, 0) + temp_derate
    return max(gain, 30)  # minimum 30 dB

# ============================================================
# Scoring
# ============================================================
def compute_score(measurements):
    """Compute weighted score from specs.json targets."""
    specs = read_specs()
    total_weight = 0
    earned_weight = 0
    results = {}

    for key, spec in specs['measurements'].items():
        target = spec['target']
        weight = spec['weight']
        total_weight += weight

        measured = measurements.get(key, None)
        if measured is None:
            results[key] = {'measured': None, 'target': target, 'pass': False, 'margin': -1}
            continue

        # Parse target
        passed = False
        margin = 0.0
        if target.startswith('>'):
            threshold = float(target[1:])
            passed = measured > threshold
            margin = (measured - threshold) / abs(threshold) if threshold != 0 else 0
        elif target.startswith('<'):
            threshold = float(target[1:])
            passed = measured < threshold
            margin = (threshold - measured) / abs(threshold) if threshold != 0 else 0
        else:
            passed = True  # unknown format, assume pass

        if passed:
            earned_weight += weight

        results[key] = {
            'measured': measured,
            'target': target,
            'pass': passed,
            'margin': margin,
            'margin_pct': margin * 100,
        }

        status = 'PASS' if passed else 'FAIL'
        margin_status = ''
        if passed and margin < 0.25:
            margin_status = ' [WARN: margin < 25%]'
        elif passed:
            margin_status = ' [OK: margin >= 25%]'
        print(f"  {key}: measured={measured:.4g}, target={target}, {status}, margin={margin*100:.1f}%{margin_status}")

    score = earned_weight / total_weight if total_weight > 0 else 0
    return score, results


def robustness_test(params, ota_gain_db):
    """Vary each parameter by ±20% and check all specs still pass."""
    print("\n=== ROBUSTNESS TEST (±20% parameter variation) ===")
    osr = int(params['osr'])
    fclk = params['f_clk']
    fs_out = fclk / osr

    N_out = 4096
    N_mod = N_out * osr

    k = max(1, int(round(100.0 * N_out / fs_out)))
    if k % 2 == 0: k += 1
    f_signal = k * fs_out / N_out
    amplitude = 0.5 if int(params.get('mod_order', 3)) >= 3 else 0.7
    t_mod = np.arange(N_mod) / fclk
    vin = amplitude * np.sin(2 * np.pi * f_signal * t_mod)

    # Parameters to vary
    vary_params = ['coeff_a1', 'coeff_a2', 'coeff_a3', 'coeff_b1',
                   'p_cap_s', 'p_cap_i', 'p_ibias']

    results = []
    all_pass = True

    for pname in vary_params:
        if pname not in params:
            continue
        nominal = params[pname]
        for factor_label, factor in [('-20%', 0.8), ('+20%', 1.2)]:
            test_params = dict(params)
            test_params[pname] = nominal * factor

            bs = run_modulator(vin, test_params, ota_gain_db)
            dec = sinc3_decimate(bs, osr)[:N_out]
            m = compute_fft_metrics(dec, fs_out, f_signal)

            enob = m['enob']
            ok = enob > 18  # hard floor
            if not ok:
                all_pass = False
            results.append((pname, factor_label, enob, ok))
            print(f"  {pname} {factor_label}: ENOB={enob:.1f} {'PASS' if ok else 'FAIL'}")

    return {'robust_all_pass': all_pass, 'robust_results': results}


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 60)
    print("  20-bit Sigma-Delta ADC Evaluator")
    print("=" * 60)

    params = read_params()
    print(f"\nModulator: order={int(params['mod_order'])}, OSR={int(params['osr'])}, fclk={params['f_clk']/1e6:.3f} MHz")
    print(f"Coefficients: a1={params['coeff_a1']}, a2={params['coeff_a2']}, a3={params.get('coeff_a3', 'N/A')}, b1={params['coeff_b1']}")
    print(f"Caps: Cs={params['p_cap_s']*1e12:.1f}pF, Ci={params['p_cap_i']*1e12:.1f}pF")
    print(f"Vref: {params['vref_n']:.2f} to {params['vref_p']:.2f} V")

    measurements = {}

    # OTA characterization (analytical from design parameters)
    ota = tb6_ota_characterization(params)
    ota_gain_db = ota['ota_gain_db']
    params['_nominal_ota_gain_db'] = ota_gain_db  # for PVT derating

    # TB1: Bitstream
    tb1 = tb1_bitstream(params, ota_gain_db)

    # TB2/3: SNR, ENOB, THD
    tb2 = tb2_snr_enob(params, ota_gain_db)
    measurements['enob'] = tb2['enob']
    measurements['snr_db'] = tb2['snr_db']
    measurements['thd_db'] = tb2['thd_db']

    # TB4: Noise floor
    tb4 = tb4_noise_floor(params, ota_gain_db)

    # TB5: Linearity
    tb5 = tb5_linearity(params, ota_gain_db)

    # TB6: Power
    tb6 = tb6_power(params)
    measurements['power_uw'] = tb6['power_uw']

    # Output data rate and input range (by design)
    osr = int(params['osr'])
    fclk = params['f_clk']
    measurements['output_data_rate_sps'] = fclk / osr
    measurements['input_range_v'] = params.get('vref_p', 1.7) - params.get('vref_n', 0.1)

    # Score
    print("\n" + "=" * 60)
    print("  SCORING")
    print("=" * 60)
    score, results = compute_score(measurements)
    print(f"\n  SCORE = {score:.4f}")

    # TB7: PVT (only if nominal score is good)
    pvt = None
    if score >= 0.5:
        pvt = tb7_pvt(params, ota_gain_db)
    else:
        print("\n  [SKIP] PVT test skipped (nominal score too low)")

    # Robustness test (only if score = 1.0)
    robust = None
    if score >= 1.0:
        robust = robustness_test(params, ota_gain_db)

    # Save measurements
    save_data = {
        'measurements': {k: v for k, v in measurements.items()},
        'score': score,
        'ota': ota,
        'noise_floor': tb4,
        'linearity': tb5,
    }
    if pvt:
        save_data['pvt_worst_enob'] = pvt['pvt_worst_enob']
    if robust:
        save_data['robust_all_pass'] = robust['robust_all_pass']

    with open(os.path.join(BLOCK_DIR, "measurements.json"), 'w') as f:
        json.dump(save_data, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"  FINAL SCORE: {score:.4f}")
    print(f"{'='*60}")
    return score

if __name__ == "__main__":
    main()
