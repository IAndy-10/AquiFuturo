#!/usr/bin/env python3
"""
branch_synth.py — AquiFuturo per-branch-class physical modelling
branch_graph.json → per-class modal synthesis → mixed WAV

Each node class is treated as an independent resonant layer with its own
stiffness and frequency window. Frequency range increases from trunk outward:

    trunk_base   20 – 120  Hz  (stiffness × 1)
    primary      50 – 380  Hz  (stiffness × 25)
    lateral     160 – 1500 Hz  (stiffness × 500)
    fine        500 – 4000 Hz  (stiffness × 5 000)
    terminal   1500 – 8000 Hz  (stiffness × 20 000)

EXCITATION (v2 — see docs/physical-modelling-documentation.md)
--------------------------------------------------------------
The v1 `tour_sweep` excitation used a slow Gaussian *envelope* directly as the
force signal.  A Gaussian of width σ ≈ 0.2–1.3 s has essentially no spectral
energy above ~1 Hz, so it drove every resonator far below resonance: the
response was the quasi-static deflection F/ω², i.e. a sub-sonic DC wander with
no ringing at all.  Measured on branch_mix_v3_parts/fine.wav, 99.9999 % of the
energy sat below 20 Hz and the intended 500–4000 Hz band was ~110 dB down.
Only trunk_base sounded, because with a single node it fell back to the
impulse path, which *is* broadband.

v2 replaces that with a **strike train**: as the TSP tour passes each node it
receives a short broadband click (raised-cosine, ~2 ms) which actually excites
the modes.  Additionally:
  * the physical 1/ω displacement tilt is now selectable (--mode-tilt);
    the default 0 gives a velocity-like, spectrally flat output
  * listening mode-shape summation uses |φ| by default (--listen-sum abs)
    so the 163 fine nodes no longer phase-cancel each other (measured
    coherence was 0.26 for `fine` with signed summation)
  * a DC/sub-sonic high-pass is applied per class before normalisation
  * per-class WAVs are RMS-normalised (not peak) so all five sit at a
    comparable, audible loudness

Usage:
    python3 tools/branch_synth.py \\
        --graph data/processed/branch_graph.json \\
        --out   physical-modelling/branch_mix.wav --save-parts

    # Reproduce the v1 (broken) behaviour for comparison:
    python3 tools/branch_synth.py --graph ... --out ... \\
        --excitation tour_sweep --mode-tilt 1.0 --listen-sum signed \\
        --highpass 0 --part-normalize peak

Deps: pip install numpy scipy soundfile
"""

import argparse
import json
import logging
import math
import sys
from pathlib import Path

import numpy as np
import scipy.linalg
import scipy.signal
import soundfile as sf

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSION = "1.1"

CLASS_ORDER = ["trunk_base", "primary", "lateral", "fine", "terminal"]

# Per-class stiffness multiplier applied on top of --stiffness-base.
# f ∝ √(stiffness_scale / mass_scale), scale=1 → ~21–66 Hz on this graph.
CLASS_STIFFNESS: dict[str, float] = {
    "trunk_base": 1.0,        # √1   =  1.0× → ~21–98  Hz
    "primary":    25.0,       # √25  =  5.0× → ~106–377 Hz
    "lateral":    500.0,      # √500 = 22.4× → ~475–1493 Hz
    "fine":       5_000.0,    # √5k  = 70.7× → ~1500–3977 Hz
    "terminal":   20_000.0,   # √20k =141.4× → ~3000–7954 Hz
}

CLASS_FREQ: dict[str, tuple[float, float]] = {
    "trunk_base": (20.0,    120.0),
    "primary":    (50.0,    380.0),
    "lateral":    (160.0,  1_500.0),
    "fine":       (500.0,  4_000.0),
    "terminal":  (1_500.0, 8_000.0),
}

# Linear gain per class in the final mix (applied after per-class RMS levelling).
CLASS_GAIN: dict[str, float] = {
    "trunk_base": 1.00,
    "primary":    0.80,
    "lateral":    0.60,
    "fine":       0.35,
    "terminal":   0.25,
}


# ---------------------------------------------------------------- graph loading

def load_graph(path: Path) -> dict:
    data = json.loads(path.read_text())
    if data.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported schema_version '{data.get('schema_version')}'. "
            f"Expected '{SUPPORTED_SCHEMA_VERSION}'."
        )
    return data


# ---------------------------------------------------------------- matrix construction

def build_matrices(
    graph: dict,
    stiffness_scale: float,
    mass_scale: float,
) -> tuple[np.ndarray, np.ndarray, dict[int, int]]:
    """Stiffness matrix K (weighted Laplacian) and mass vector M."""
    nodes = graph["nodes"]
    edges = graph["edges"]
    N = len(nodes)
    id_to_idx: dict[int, int] = {n["id"]: i for i, n in enumerate(nodes)}

    K = np.zeros((N, N), dtype=np.float64)
    M = np.zeros(N, dtype=np.float64)

    for n in nodes:
        i = id_to_idx[n["id"]]
        r = max(n["radius"], 1e-4)
        M[i] = mass_scale * r * r          # m ∝ cross-section area

    for e in edges:
        i = id_to_idx[e["source"]]
        j = id_to_idx[e["target"]]
        length = max(e["length"], 1e-6)
        k = stiffness_scale / (length * length)   # k ∝ stiffness / length²
        K[i, i] += k
        K[j, j] += k
        K[i, j] -= k
        K[j, i] -= k

    return K, M, id_to_idx


# ---------------------------------------------------------------- modal analysis

def modal_analysis(
    K: np.ndarray,
    M: np.ndarray,
    n_modes: int,
    freq_min: float,
    freq_max: float,
    sr: int,
    class_label: str = "",
) -> tuple[np.ndarray, np.ndarray]:
    """Solve K·φ = ω²·M·φ, return modes inside [freq_min, freq_max]."""
    N = K.shape[0]
    n_request = min(n_modes, N - 1)

    M_reg = np.maximum(M, 1e-10)
    M_si = 1.0 / np.sqrt(M_reg)
    K_sym = M_si[:, None] * K * M_si[None, :]
    K_sym = 0.5 * (K_sym + K_sym.T)

    eigenvalues, eigenvectors = scipy.linalg.eigh(
        K_sym,
        subset_by_index=[0, n_request],
        driver="evr",
    )

    omega_sq = np.maximum(eigenvalues, 0.0)
    omega = np.sqrt(omega_sq)
    freqs = omega / (2.0 * np.pi)

    modes = M_si[:, None] * eigenvectors

    nyquist = sr / 2.0
    freq_max_clip = min(freq_max, nyquist * 0.95)
    mask = (freqs >= freq_min) & (freqs <= freq_max_clip)
    freqs = freqs[mask]
    modes = modes[:, mask]

    tag = f"[{class_label}] " if class_label else ""
    log.info(f"{tag}{mask.sum()} modes in [{freq_min:.0f}, {freq_max_clip:.0f}] Hz"
             + (f" ({freqs.min():.1f}–{freqs.max():.1f} Hz)" if len(freqs) else " — none found"))
    return freqs, modes


# ---------------------------------------------------------------- DSP helpers

def highpass(x: np.ndarray, sr: int, fc: float, order: int = 2) -> np.ndarray:
    """Zero-phase Butterworth high-pass. Removes the quasi-static DC term."""
    if fc <= 0.0 or fc >= sr / 2.0 or len(x) < 3 * (order + 1) * 2:
        return x
    sos = scipy.signal.butter(order, fc / (sr / 2.0), btype="high", output="sos")
    return scipy.signal.sosfiltfilt(sos, x)


def soft_clip(x: np.ndarray, ceiling: float = 0.98) -> np.ndarray:
    """tanh limiter — keeps transient peaks in range without audible clipping."""
    return ceiling * np.tanh(x / max(ceiling, 1e-9))


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def band_energy_fraction(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    """Fraction of total energy inside [lo, hi] Hz — used for the audibility report."""
    n = min(len(x), 1 << 20)
    seg = x[:n] * np.hanning(n)
    P = np.abs(np.fft.rfft(seg)) ** 2
    f = np.fft.rfftfreq(n, 1.0 / sr)
    m = (f >= lo) & (f < hi)
    return float(P[m].sum() / (P.sum() + 1e-30))


def a_weight(x: np.ndarray, sr: int) -> np.ndarray:
    """IEC 61672 A-weighting — used only for the loudness report."""
    f1, f2, f3, f4 = 20.598997, 107.65265, 737.86223, 12194.217
    A1000 = 1.9997
    nums = [(2 * np.pi * f4) ** 2 * 10 ** (A1000 / 20.0), 0, 0, 0, 0]
    dens = np.polymul(
        np.polymul([1, 4 * np.pi * f4, (2 * np.pi * f4) ** 2],
                   [1, 4 * np.pi * f1, (2 * np.pi * f1) ** 2]),
        np.polymul([1, 2 * np.pi * f3], [1, 2 * np.pi * f2]),
    )
    b, a = scipy.signal.bilinear(nums, dens, sr)
    return scipy.signal.lfilter(b, a, x)


# ---------------------------------------------------------------- excitation

def class_tour_sequence(graph: dict, class_name: str) -> list[int]:
    """Node ids of `class_name` in TSP-tour order (falls back to depth order)."""
    class_nodes = [n for n in graph["nodes"] if n["class"] == class_name]
    class_ids = {n["id"] for n in class_nodes}
    tours = graph.get("tours", [])
    if tours:
        seq = [nid for nid in tours[0]["node_sequence"] if nid in class_ids]
        if seq:
            return seq
    return [n["id"] for n in sorted(class_nodes, key=lambda n: n["depth_order"])]


def build_strike_events(
    graph: dict,
    class_name: str,
    id_to_idx: dict[int, int],
    sr: int,
    duration: float,
    min_strike_rate: float,
    jitter: float,
    amp_spread: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Strike train along the class tour.

    Returns (node_indices, sample_times, amplitudes), one entry per strike.

    The tour is repeated as many times as needed to reach `min_strike_rate`
    strikes/second — without this, sparse classes (terminal has 17 nodes) get
    one 40 ms ring every 7 s and read as silence.
    """
    seq = class_tour_sequence(graph, class_name)
    n_samples = int(sr * duration)

    repeats = max(1, math.ceil(duration * min_strike_rate / max(len(seq), 1)))
    seq_rep = seq * repeats
    n_ev = len(seq_rep)

    interval = n_samples / n_ev
    times = (np.arange(n_ev) + 0.5) * interval
    if jitter > 0.0:
        times = times + rng.uniform(-jitter, jitter, n_ev) * interval
    times = np.clip(times, 0, n_samples - 1).astype(np.int64)

    amps = np.exp(rng.normal(0.0, amp_spread, n_ev)) if amp_spread > 0 else np.ones(n_ev)

    idx = np.array([id_to_idx[nid] for nid in seq_rep], dtype=np.int64)

    log.info(f"[{class_name}] strike train: {len(seq)} tour nodes × {repeats} passes "
             f"= {n_ev} strikes ({n_ev / duration:.2f} /s)")
    return idx, times, amps


def impulse_for_class(
    graph: dict,
    class_name: str,
    id_to_idx: dict[int, int],
    N: int,
) -> np.ndarray:
    """Unit impulse at the node of class_name with the smallest depth_order."""
    class_nodes = [n for n in graph["nodes"] if n["class"] == class_name]
    rep = min(class_nodes, key=lambda n: n["depth_order"])
    f = np.zeros(N)
    f[id_to_idx[rep["id"]]] = 1.0
    log.info(f"[{class_name}] impulse at node {rep['id']} (depth_order={rep['depth_order']})")
    return f


def tour_for_class(
    graph: dict,
    class_name: str,
    id_to_idx: dict[int, int],
    N: int,
    n_frames: int,
) -> np.ndarray | None:
    """LEGACY v1 envelope-as-force excitation. Kept only for A/B comparison."""
    seq = class_tour_sequence(graph, class_name)
    if len(seq) < 2:
        return None
    F = np.zeros((N, n_frames), dtype=np.float32)
    bump_width = n_frames / len(seq) / 3.0
    t = np.arange(n_frames)
    for k, node_id in enumerate(seq):
        if node_id not in id_to_idx:
            continue
        centre = (k + 0.5) / len(seq) * n_frames
        F[id_to_idx[node_id]] += np.exp(-0.5 * ((t - centre) / bump_width) ** 2)
    return F


# ---------------------------------------------------------------- synthesis

def _listen_shape(modes: np.ndarray, listen_idx: list[int], how: str) -> np.ndarray:
    """Modal participation at the listening nodes.

    'signed' is the textbook sum, but mode shapes alternate sign across a large
    node set, so summing 163 fine nodes cancels ~75 % of the amplitude.
    'abs' models incoherent (spatially distributed) pickup and preserves level.
    """
    sub = modes[listen_idx, :]
    return np.abs(sub).sum(axis=0) if how == "abs" else sub.sum(axis=0)


def _mode_kernel(
    wd: float, zeta_w: float, sr: int, n_samples: int, max_len: int = 262_144
) -> np.ndarray | None:
    decay_time = 6.0 / (zeta_w + 1e-6)          # ~-52 dB
    kernel_len = int(min(decay_time * sr, n_samples, max_len))
    if kernel_len < 2 or wd < 1e-3:
        return None
    t_k = np.arange(kernel_len) / sr
    return np.sin(wd * t_k) * np.exp(-zeta_w * t_k)


def synthesise_strikes(
    freqs: np.ndarray,
    modes: np.ndarray,
    ev_idx: np.ndarray,
    ev_t: np.ndarray,
    ev_amp: np.ndarray,
    listen_idx: list[int],
    damping: float,
    sr: int,
    duration: float,
    burst_ms: float,
    mode_tilt: float,
    listen_sum: str,
) -> np.ndarray:
    """Broadband strike train → modal ringing.

    Each strike is a short raised-cosine click (broadband up to ~1/burst_ms),
    so it deposits energy AT the modal frequencies instead of below them.
    """
    n_samples = int(sr * duration)
    Phi_ev = modes[ev_idx, :] * ev_amp[:, None]          # (n_ev, n_modes)
    lis = _listen_shape(modes, listen_idx, listen_sum)   # (n_modes,)

    # A click of width T is a low-pass with cutoff ~1/T: too wide and it
    # attenuates the very band we are trying to excite (a 2 ms click removes
    # ~20 dB at 3 kHz, which is why `terminal` stayed quiet).  burst_ms < 0
    # picks a quarter period of the top of the class window automatically.
    bl = max(1, int(round(burst_ms * 1e-3 * sr)))
    if bl < 3:
        burst = np.ones(1)                     # unit impulse: fully broadband
    else:
        burst = np.hanning(bl)
        burst /= burst.sum()

    omega = 2.0 * np.pi * freqs
    omega_d = omega * np.sqrt(np.maximum(1.0 - damping ** 2, 1e-6))

    audio = np.zeros(n_samples, dtype=np.float64)
    for k in range(len(freqs)):
        h = _mode_kernel(omega_d[k], damping * omega[k], sr, n_samples)
        if h is None:
            continue
        # fold the click shape into the modal impulse response — one convolution
        h = scipy.signal.fftconvolve(h, burst)[: len(h) + bl]
        train = np.zeros(n_samples, dtype=np.float64)
        np.add.at(train, ev_t, Phi_ev[:, k])
        resp = scipy.signal.oaconvolve(train, h, mode="full")[:n_samples]
        audio += (lis[k] / (omega[k] ** mode_tilt if mode_tilt else 1.0)) * resp

    return audio


def synthesise_impulse(
    freqs: np.ndarray,
    modes: np.ndarray,
    F_static: np.ndarray,
    listen_idx: list[int],
    damping: float,
    sr: int,
    duration: float,
    mode_tilt: float,
    listen_sum: str,
) -> np.ndarray:
    """Analytical response to a static force vector (single pluck at t=0)."""
    n_samples = int(sr * duration)
    t = np.arange(n_samples) / sr

    lis = _listen_shape(modes, listen_idx, listen_sum)
    modal_force = modes.T @ F_static
    omega = 2.0 * np.pi * freqs
    omega_d = omega * np.sqrt(np.maximum(1.0 - damping ** 2, 1e-6))

    audio = np.zeros(n_samples, dtype=np.float64)
    for k in range(len(freqs)):
        w, wd = omega[k], omega_d[k]
        if wd < 1e-3:
            continue
        amplitude = lis[k] * modal_force[k] / (w ** mode_tilt if mode_tilt else 1.0)
        audio += amplitude * np.sin(wd * t) * np.exp(-damping * w * t)

    return audio


def synthesise_tour_legacy(
    freqs: np.ndarray,
    modes: np.ndarray,
    F: np.ndarray,
    listen_idx: list[int],
    damping: float,
    sr: int,
    duration: float,
    mode_tilt: float,
    listen_sum: str,
) -> np.ndarray:
    """v1 envelope-as-force response. Retained for A/B only — see module docstring."""
    n_samples = int(sr * duration)
    t_audio = np.arange(n_samples) / sr
    t_coarse = np.linspace(0.0, duration, F.shape[1])

    MF_coarse = modes.T @ F
    lis = _listen_shape(modes, listen_idx, listen_sum)
    omega = 2.0 * np.pi * freqs
    omega_d = omega * np.sqrt(np.maximum(1.0 - damping ** 2, 1e-6))

    audio = np.zeros(n_samples, dtype=np.float64)
    for k in range(len(freqs)):
        h = _mode_kernel(omega_d[k], damping * omega[k], sr, n_samples, max_len=65_536)
        if h is None:
            continue
        mf_audio = np.interp(t_audio, t_coarse, MF_coarse[k])
        resp = scipy.signal.oaconvolve(mf_audio, h, mode="full")[:n_samples]
        audio += (lis[k] / (omega[k] ** mode_tilt if mode_tilt else 1.0)) * resp

    return audio


# ---------------------------------------------------------------- looping

def loop_to_duration(audio: np.ndarray, sr: int, duration: float) -> np.ndarray:
    """Crossfade-loop to target duration."""
    n_target = int(sr * duration)
    if len(audio) == 0:
        return np.zeros(n_target)

    fade_secs = min(0.5, len(audio) / sr / 4.0)
    fade_len = int(fade_secs * sr)

    rms_window = max(1, len(audio) // 64)
    energy = np.convolve(audio ** 2, np.ones(rms_window) / rms_window, mode="same")
    threshold = energy.max() * 1e-4
    nonzero = np.where(energy > threshold)[0]
    loop_end = min(nonzero[-1] + rms_window if len(nonzero) else len(audio), len(audio))
    loop = audio[:loop_end].copy()          # copy: the crossfade below mutates it

    if len(loop) < fade_len * 2:
        tiled = np.tile(loop, (n_target // max(len(loop), 1)) + 2)
        return tiled[:n_target]

    fade_out = np.linspace(1.0, 0.0, fade_len)
    fade_in = np.linspace(0.0, 1.0, fade_len)
    loop[-fade_len:] = loop[-fade_len:] * fade_out + loop[:fade_len] * fade_in
    loop_body = loop[fade_len:]

    out = np.empty(0)
    while len(out) < n_target:
        out = np.concatenate([out, loop_body])
    return out[:n_target]


# ---------------------------------------------------------------- per-class pipeline

def synth_class(
    class_name: str,
    graph: dict,
    stiffness_scale: float,
    mass_scale: float,
    freq_min: float,
    freq_max: float,
    damping: float,
    n_modes: int,
    excitation: str,
    sr: int,
    duration: float,
    *,
    mode_tilt: float,
    listen_sum: str,
    burst_ms: float,
    min_strike_rate: float,
    jitter: float,
    amp_spread: float,
    highpass_ratio: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Full pipeline for one class. Returns high-passed audio at natural level."""
    nodes = graph["nodes"]
    K, M, id_to_idx = build_matrices(graph, stiffness_scale, mass_scale)
    N = len(nodes)

    freqs, modes = modal_analysis(K, M, n_modes, freq_min, freq_max, sr, class_name)
    if len(freqs) == 0:
        log.warning(f"[{class_name}] no modes found — silent layer")
        return np.zeros(int(sr * duration))

    listen_idx = [id_to_idx[n["id"]] for n in nodes if n["class"] == class_name]
    if not listen_idx:
        log.warning(f"[{class_name}] no nodes — silent layer")
        return np.zeros(int(sr * duration))

    log.info(f"[{class_name}] stiffness={stiffness_scale:.0f}  "
             f"listen={len(listen_idx)} nodes  damping={damping}  tilt={mode_tilt}")

    if excitation == "strike_tour":
        if burst_ms < 0:                        # auto: ¼ period at top of band
            burst_ms = 250.0 / max(freq_max, 1.0)
            log.info(f"[{class_name}] auto burst width {burst_ms:.3f} ms")
        ev_idx, ev_t, ev_amp = build_strike_events(
            graph, class_name, id_to_idx, sr, duration,
            min_strike_rate, jitter, amp_spread, rng,
        )
        raw = synthesise_strikes(freqs, modes, ev_idx, ev_t, ev_amp, listen_idx,
                                 damping, sr, duration, burst_ms, mode_tilt, listen_sum)
        raw = raw[:int(sr * duration)]

    elif excitation == "tour_sweep":                       # legacy
        n_coarse = max(len(listen_idx) * 4, 64)
        F_tour = tour_for_class(graph, class_name, id_to_idx, N, n_coarse)
        if F_tour is not None:
            raw = synthesise_tour_legacy(freqs, modes, F_tour, listen_idx,
                                         damping, sr, duration, mode_tilt, listen_sum)
        else:
            log.info(f"[{class_name}] tour too short, falling back to impulse")
            raw = synthesise_impulse(freqs, modes,
                                     impulse_for_class(graph, class_name, id_to_idx, N),
                                     listen_idx, damping, sr, duration, mode_tilt, listen_sum)
        raw = loop_to_duration(raw, sr, duration)

    else:                                                   # impulse
        raw = synthesise_impulse(freqs, modes,
                                 impulse_for_class(graph, class_name, id_to_idx, N),
                                 listen_idx, damping, sr, duration, mode_tilt, listen_sum)
        raw = loop_to_duration(raw, sr, duration)

    # Kill the quasi-static / DC term that otherwise owns all the headroom.
    fc = highpass_ratio * freq_min
    if fc > 0:
        raw = highpass(raw, sr, max(fc, 12.0))

    frac = band_energy_fraction(raw, sr, freq_min, min(freq_max, sr / 2 * 0.95))
    sub = band_energy_fraction(raw, sr, 0.0, 20.0)
    log.info(f"[{class_name}] in-band energy {100 * frac:.2f} %   sub-20 Hz {100 * sub:.4f} %")
    if frac < 0.5:
        log.warning(f"[{class_name}] less than half the energy is inside the class "
                    f"window — this layer will be hard to hear.")

    return raw


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Per-branch-class modal synthesis — frequency rises from trunk to tips",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--graph", required=True, type=Path)
    ap.add_argument("--out", default="physical-modelling/branch_mix.wav", type=Path)
    ap.add_argument("--duration", type=float, default=120.0)
    ap.add_argument("--sr", type=int, default=48000)
    ap.add_argument("--seed", type=int, default=42)

    ap.add_argument("--stiffness-base", type=float, default=1.0,
                    help="global multiplier applied to all per-class stiffness values")
    ap.add_argument("--mass-scale", type=float, default=1.0,
                    help="global mass multiplier (raise → lower pitch across all classes)")
    ap.add_argument("--damping", type=float, default=0.008,
                    help="modal damping ratio ζ, same for all classes")
    ap.add_argument("--n-modes", type=int, default=96,
                    help="max eigenmodes requested per class")

    ap.add_argument("--excitation",
                    choices=["strike_tour", "impulse", "tour_sweep"],
                    default="strike_tour",
                    help="strike_tour: broadband click at each tour node (v2 default); "
                         "impulse: single pluck at shallowest node, looped; "
                         "tour_sweep: LEGACY v1 envelope-as-force (near-inaudible)")
    ap.add_argument("--burst-ms", type=float, default=-1.0,
                    help="strike click width in ms — smaller = brighter/more broadband. "
                         "Negative = auto (a quarter period at the top of each class "
                         "window), which is what keeps the high classes in band.")
    ap.add_argument("--min-strike-rate", type=float, default=1.5,
                    help="minimum strikes per second per class; the tour is repeated "
                         "to reach it (sparse classes would otherwise read as silence)")
    ap.add_argument("--strike-jitter", type=float, default=0.3,
                    help="timing jitter as a fraction of the inter-strike interval")
    ap.add_argument("--strike-amp-spread", type=float, default=0.35,
                    help="log-normal σ of per-strike amplitude variation (0 = uniform)")

    ap.add_argument("--mode-tilt", type=float, default=0.0,
                    help="modal amplitude ∝ ω^-tilt. 0 = flat (velocity-like, bright); "
                         "1 = physical displacement (v1 behaviour, buries high classes); "
                         "-1 = acceleration (very bright)")
    ap.add_argument("--listen-sum", choices=["abs", "signed"], default="abs",
                    help="how mode shapes are summed over listening nodes. "
                         "abs = incoherent pickup (no phase cancellation); "
                         "signed = v1 behaviour (cancels ~75 %% for the fine class)")
    ap.add_argument("--highpass", type=float, default=0.7,
                    help="per-class high-pass cutoff as a fraction of the class freq_min "
                         "(0 disables). Removes the sub-sonic quasi-static term.")

    ap.add_argument("--gains", default=None,
                    help="comma-separated linear gains for "
                         "trunk_base,primary,lateral,fine,terminal")
    ap.add_argument("--save-parts", action="store_true",
                    help="save per-class WAVs alongside the mix (in <out_stem>_parts/)")
    ap.add_argument("--part-normalize", choices=["rms", "peak"], default="rms",
                    help="per-class WAV levelling. rms = equal loudness across classes "
                         "(recommended); peak = v1 behaviour")
    ap.add_argument("--part-rms-dbfs", type=float, default=-18.0,
                    help="target RMS for per-class WAVs when --part-normalize rms")
    ap.add_argument("--gain-out", type=float, default=0.891,
                    help="mix output target level (peak or RMS depending on --normalize)")
    ap.add_argument("--normalize", choices=["peak", "rms"], default="peak",
                    help="mix normalisation: peak, or rms + soft limiting (louder)")

    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    graph = load_graph(args.graph)
    log.info(f"Graph: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")

    gains = dict(CLASS_GAIN)
    if args.gains:
        parts = args.gains.split(",")
        if len(parts) != 5:
            ap.error("--gains must have exactly 5 comma-separated values")
        for cls, val in zip(CLASS_ORDER, parts):
            gains[cls] = float(val)

    log.info("=== Per-class frequency bands ===")
    for cls in CLASS_ORDER:
        s = CLASS_STIFFNESS[cls] * args.stiffness_base
        flo, fhi = CLASS_FREQ[cls]
        log.info(f"  {cls:12} stiffness={s:>9.1f}  window=[{flo:.0f}, {fhi:.0f}] Hz  "
                 f"gain={gains[cls]:.2f}")

    mix = np.zeros(int(args.sr * args.duration), dtype=np.float64)
    parts_dir = args.out.parent / (args.out.stem + "_parts")
    report: list[tuple[str, float, float, float]] = []

    for cls in CLASS_ORDER:
        stiffness = CLASS_STIFFNESS[cls] * args.stiffness_base
        freq_min, freq_max = CLASS_FREQ[cls]

        audio = synth_class(
            class_name=cls,
            graph=graph,
            stiffness_scale=stiffness,
            mass_scale=args.mass_scale,
            freq_min=freq_min,
            freq_max=freq_max,
            damping=args.damping,
            n_modes=args.n_modes,
            excitation=args.excitation,
            sr=args.sr,
            duration=args.duration,
            mode_tilt=args.mode_tilt,
            listen_sum=args.listen_sum,
            burst_ms=args.burst_ms,
            min_strike_rate=args.min_strike_rate,
            jitter=args.strike_jitter,
            amp_spread=args.strike_amp_spread,
            highpass_ratio=args.highpass,
            rng=rng,
        )

        # RMS-normalise each class to unit level before mixing, so CLASS_GAIN
        # is a meaningful perceptual balance rather than an accident of 1/ω.
        r = rms(audio)
        if r > 1e-12:
            audio = audio / r
        mix += audio * gains[cls]

        aw = rms(a_weight(audio * gains[cls], args.sr))
        report.append((cls, r, 20 * np.log10(aw + 1e-12),
                       band_energy_fraction(audio, args.sr, freq_min,
                                            min(freq_max, args.sr / 2 * 0.95))))
        log.info(f"[{cls}] raw rms={r:.4e}  mix gain={gains[cls]:.2f}")

        if args.save_parts:
            parts_dir.mkdir(parents=True, exist_ok=True)
            part_path = parts_dir / f"{cls}.wav"
            if args.part_normalize == "rms":
                target = 10 ** (args.part_rms_dbfs / 20.0)
                part_out = soft_clip(audio * target / max(rms(audio), 1e-12))
            else:
                peak = np.abs(audio).max()
                part_out = audio / peak * args.gain_out if peak > 1e-12 else audio
            part_out = part_out.astype(np.float32)
            sf.write(str(part_path), part_out, args.sr, subtype="PCM_24")
            log.info(f"[{cls}] saved {part_path}  "
                     f"peak={np.abs(part_out).max():.3f} rms={rms(part_out):.4f}")

    # ---- mix normalisation
    if args.normalize == "rms":
        ref = rms(mix)
        mix_out = soft_clip(mix / max(ref, 1e-12) * args.gain_out)
        mode_label = "rms"
    else:
        ref = np.abs(mix).max()
        mix_out = np.clip(mix / max(ref, 1e-12) * args.gain_out, -1.0, 1.0)
        mode_label = "peak"
    if ref < 1e-12:
        log.error("Mix is silent — check graph and stiffness settings.")
        sys.exit(1)
    mix_out = mix_out.astype(np.float32)

    log.info("=== Per-class audibility report ===")
    log.info(f"  {'class':12} {'raw rms':>10} {'A-wtd dBFS':>11} {'in-band':>9}")
    for cls, r, awdb, frac in report:
        log.info(f"  {cls:12} {r:10.3e} {awdb:11.1f} {100 * frac:8.2f}%")

    log.info(f"Mix normalised by {mode_label}: peak={np.abs(mix_out).max():.4f} "
             f"({20 * np.log10(np.abs(mix_out).max() + 1e-12):.1f} dBFS)  "
             f"rms={rms(mix_out):.4f} ({20 * np.log10(rms(mix_out) + 1e-12):.1f} dBFS)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(args.out), mix_out, args.sr, subtype="PCM_24")
    log.info(f"Wrote {args.out}  ({args.duration:.0f}s, {args.sr} Hz)")


if __name__ == "__main__":
    main()