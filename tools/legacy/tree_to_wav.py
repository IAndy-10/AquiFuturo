#!/usr/bin/env python3
"""
tree_to_wav.py — AquiFuturo physical modelling synthesis
branch_graph.json (mass-spring tree) -> modal synthesis -> looping WAV

Method: Modal analysis of the mass-spring system.
  - Nodes = masses  (m ∝ radius²)
  - Edges = springs (k ∝ stiffness_scale / length²)
  - Solve generalised eigenvalue problem K·φ = ω²·M·φ
  - Synthesise audio by summing modal contributions at listening nodes
  - Optionally drive with a TSP tour strike train

AUDIBILITY FIX (v2)
-------------------
The old `tour_sweep` excitation used a slow Gaussian *envelope* directly as the
force signal. A Gaussian of width σ ≈ 0.2–1.3 s carries essentially no energy
above ~1 Hz, so every resonator was driven far below resonance and returned its
quasi-static deflection F/ω² — a sub-sonic DC wander, not a tone. Peak
normalisation then set the level from that inaudible excursion, leaving the
real modal content 60–110 dB down. Only the impulse path (broadband by nature)
produced audible ringing.

v2 changes:
  * `strike_tour` (new default): each tour node is struck with a short
    broadband click whose width auto-scales to the top of the frequency window,
    so energy actually lands on the modes
  * `--mode-tilt` replaces the hard-wired 1/ω displacement tilt (default 0 =
    velocity-like/flat, so high modes are no longer 100× quieter than low ones)
  * `--listen-sum abs` avoids phase cancellation when summing mode shapes over
    many listening nodes
  * `--highpass` removes the DC/sub-sonic term before normalisation
  * `--normalize rms` levels by loudness rather than by peak

Usage:
    # Strike tour along the TSP path, listening at terminals:
    python3 tools/tree_to_wav.py --graph data/processed/branch_graph.json \\
        --out physical-modelling/tree_strikes.wav

    # Single pluck at trunk base:
    python3 tools/tree_to_wav.py --graph data/processed/branch_graph.json \\
        --out physical-modelling/tree_impulse.wav --excitation impulse

    # Bright, lightly damped, all nodes:
    python3 tools/tree_to_wav.py --graph data/processed/branch_graph.json \\
        --out physical-modelling/tree_bright.wav \\
        --stiffness-scale 4.0 --damping 0.005 --n-modes 128 --freq-max 8000 \\
        --listen-class all

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
    """Build stiffness K and mass M matrices from the graph."""
    nodes = graph["nodes"]
    edges = graph["edges"]
    N = len(nodes)

    id_to_idx: dict[int, int] = {n["id"]: i for i, n in enumerate(nodes)}

    K = np.zeros((N, N), dtype=np.float64)
    M = np.zeros(N, dtype=np.float64)

    for n in nodes:
        i = id_to_idx[n["id"]]
        r = max(n["radius"], 1e-4)        # clamp tiny radii
        M[i] = mass_scale * r * r         # mass ∝ cross-section area

    for e in edges:
        i = id_to_idx[e["source"]]
        j = id_to_idx[e["target"]]
        length = max(e["length"], 1e-6)
        k = stiffness_scale / (length * length)   # stiffer for shorter segments
        K[i, i] += k
        K[j, j] += k
        K[i, j] -= k
        K[j, i] -= k

    log.info(f"Built K ({N}×{N}), M range [{M.min():.4e}, {M.max():.4e}]")
    return K, M, id_to_idx


# ---------------------------------------------------------------- modal analysis

def modal_analysis(
    K: np.ndarray,
    M: np.ndarray,
    n_modes: int,
    freq_min: float,
    freq_max: float,
    sr: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Solve generalised eigenvalue problem K·φ = ω²·M·φ."""
    N = K.shape[0]
    n_modes = min(n_modes, N - 1)

    M_reg = np.maximum(M, 1e-10)
    M_sqrt_inv = 1.0 / np.sqrt(M_reg)
    K_sym = M_sqrt_inv[:, None] * K * M_sqrt_inv[None, :]
    K_sym = 0.5 * (K_sym + K_sym.T)

    log.info(f"Solving eigenvalue problem (N={N}, requesting {n_modes} modes)…")
    eigenvalues, eigenvectors = scipy.linalg.eigh(
        K_sym,
        subset_by_index=[0, n_modes],
        driver="evr",
    )

    omega_sq = np.maximum(eigenvalues, 0.0)
    omega = np.sqrt(omega_sq)                    # rad/s
    freqs = omega / (2.0 * np.pi)                # Hz

    modes = M_sqrt_inv[:, None] * eigenvectors

    nyquist = sr / 2.0
    freq_max_clip = min(freq_max, nyquist * 0.95)
    mask = (freqs >= freq_min) & (freqs <= freq_max_clip)

    freqs = freqs[mask]
    modes = modes[:, mask]

    if len(freqs):
        log.info(
            f"Modal analysis: {mask.sum()} modes in [{freq_min:.1f}, {freq_max_clip:.1f}] Hz "
            f"(range: {freqs.min():.2f}–{freqs.max():.2f} Hz)"
        )
    return freqs, modes


# ---------------------------------------------------------------- DSP helpers

def highpass(x: np.ndarray, sr: int, fc: float, order: int = 2) -> np.ndarray:
    """Zero-phase Butterworth high-pass — removes the quasi-static DC term."""
    if fc <= 0.0 or fc >= sr / 2.0 or len(x) < 3 * (order + 1) * 2:
        return x
    sos = scipy.signal.butter(order, fc / (sr / 2.0), btype="high", output="sos")
    return scipy.signal.sosfiltfilt(sos, x)


def soft_clip(x: np.ndarray, ceiling: float = 0.98) -> np.ndarray:
    return ceiling * np.tanh(x / max(ceiling, 1e-9))


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def band_energy_fraction(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    n = min(len(x), 1 << 20)
    seg = x[:n] * np.hanning(n)
    P = np.abs(np.fft.rfft(seg)) ** 2
    f = np.fft.rfftfreq(n, 1.0 / sr)
    m = (f >= lo) & (f < hi)
    return float(P[m].sum() / (P.sum() + 1e-30))


# ---------------------------------------------------------------- excitation

def build_excitation_impulse(
    N: int,
    id_to_idx: dict[int, int],
    nodes: list[dict],
) -> np.ndarray:
    """Single impulse at the trunk_base node (or node 0 as fallback)."""
    f = np.zeros(N)
    trunk = next((n for n in nodes if n["class"] == "trunk_base"), nodes[0])
    f[id_to_idx[trunk["id"]]] = 1.0
    log.info(f"Excitation: impulse at node {trunk['id']} (class={trunk['class']})")
    return f


def build_excitation_noise(N: int, rng: np.random.Generator) -> np.ndarray:
    """Random force vector: white noise injection across all nodes."""
    f = rng.standard_normal(N)
    log.info("Excitation: white noise across all nodes")
    return f


def build_strike_events(
    tour: list[int],
    id_to_idx: dict[int, int],
    sr: int,
    duration: float,
    min_strike_rate: float,
    jitter: float,
    amp_spread: float,
    rng: np.random.Generator,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Strike train along the tour: (node_indices, sample_times, amplitudes).

    The tour is repeated as many times as needed to reach `min_strike_rate`
    strikes per second, so sparse tours do not read as silence.
    """
    seq = [nid for nid in tour if nid in id_to_idx]
    if not seq:
        raise ValueError("Tour contains no nodes present in the graph.")

    n_samples = int(sr * duration)
    repeats = max(1, math.ceil(duration * min_strike_rate / len(seq)))
    seq_rep = seq * repeats
    n_ev = len(seq_rep)

    interval = n_samples / n_ev
    times = (np.arange(n_ev) + 0.5) * interval
    if jitter > 0.0:
        times = times + rng.uniform(-jitter, jitter, n_ev) * interval
    times = np.clip(times, 0, n_samples - 1).astype(np.int64)

    amps = np.exp(rng.normal(0.0, amp_spread, n_ev)) if amp_spread > 0 else np.ones(n_ev)
    idx = np.array([id_to_idx[nid] for nid in seq_rep], dtype=np.int64)

    log.info(f"Excitation: strike_tour — {len(seq)} nodes × {repeats} passes "
             f"= {n_ev} strikes ({n_ev / duration:.2f} /s)")
    return idx, times, amps


# ---------------------------------------------------------------- synthesis

def _listen_shape(modes: np.ndarray, listen_idx: list[int], how: str) -> np.ndarray:
    """Modal participation at the listening nodes.

    'signed' is the textbook sum, but mode shapes alternate sign across a large
    node set, so summing many nodes cancels most of the amplitude ('fine'
    measured a coherence of 0.26). 'abs' models spatially incoherent pickup.
    """
    sub = modes[listen_idx, :]
    return np.abs(sub).sum(axis=0) if how == "abs" else sub.sum(axis=0)


def _mode_kernel(
    wd: float, zeta_w: float, sr: int, n_samples: int, max_len: int = 262_144
) -> np.ndarray | None:
    decay_time = 6.0 / (zeta_w + 1e-6)
    kernel_len = int(min(decay_time * sr, n_samples, max_len))
    if kernel_len < 2 or wd < 1e-3:
        return None
    t_k = np.arange(kernel_len) / sr
    return np.sin(wd * t_k) * np.exp(-zeta_w * t_k)


def synthesise_modal(
    freqs: np.ndarray,
    modes: np.ndarray,
    excitation_force: np.ndarray,
    listen_indices: list[int],
    damping: float,
    sr: int,
    duration: float,
    mode_tilt: float = 0.0,
    listen_sum: str = "abs",
) -> np.ndarray:
    """Impulse/noise excitation → modal synthesis → time-domain audio.

    For each mode k:
        - modal force:       f_k = φ_k · F
        - modal response:    q_k(t) = f_k · ω_k^-tilt · sin(ω_k·t) · e^(-ζ·ω_k·t)
        - physical output:   y(t) = Σ_k  L_k · q_k(t)
    """
    n_samples = int(sr * duration)
    t = np.arange(n_samples) / sr

    listen_shape = _listen_shape(modes, listen_indices, listen_sum)
    modal_force = modes.T @ excitation_force

    omega = 2.0 * np.pi * freqs
    omega_d = omega * np.sqrt(np.maximum(1.0 - damping ** 2, 1e-6))

    audio = np.zeros(n_samples, dtype=np.float64)
    for k in range(len(freqs)):
        w, wd = omega[k], omega_d[k]
        if wd < 1e-3:
            continue
        amplitude = listen_shape[k] * modal_force[k] / (w ** mode_tilt if mode_tilt else 1.0)
        audio += amplitude * np.sin(wd * t) * np.exp(-damping * w * t)

    return audio


def synthesise_modal_strikes(
    freqs: np.ndarray,
    modes: np.ndarray,
    ev_idx: np.ndarray,
    ev_t: np.ndarray,
    ev_amp: np.ndarray,
    listen_indices: list[int],
    damping: float,
    sr: int,
    duration: float,
    burst_ms: float,
    mode_tilt: float = 0.0,
    listen_sum: str = "abs",
) -> np.ndarray:
    """Broadband strike train along the tour → modal ringing.

    Replaces the old envelope-as-force `synthesise_modal_tour`. Each strike is
    a short click, so its spectrum reaches the modal frequencies instead of
    stopping ~3 decades below them.
    """
    n_samples = int(sr * duration)
    Phi_ev = modes[ev_idx, :] * ev_amp[:, None]
    lis = _listen_shape(modes, listen_indices, listen_sum)

    # A click of width T low-passes at ~1/T; too wide and it attenuates the very
    # band we want to excite. bl < 3 samples ⇒ use a bare unit impulse.
    bl = max(1, int(round(burst_ms * 1e-3 * sr)))
    if bl < 3:
        burst = np.ones(1)
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
        h = scipy.signal.fftconvolve(h, burst)[: len(h) + len(burst)]
        train = np.zeros(n_samples, dtype=np.float64)
        np.add.at(train, ev_t, Phi_ev[:, k])
        resp = scipy.signal.oaconvolve(train, h, mode="full")[:n_samples]
        audio += (lis[k] / (omega[k] ** mode_tilt if mode_tilt else 1.0)) * resp

    return audio


# ---------------------------------------------------------------- looping

def loop_to_duration(audio: np.ndarray, sr: int, duration: float) -> np.ndarray:
    """Tile + crossfade to target duration, then trim."""
    n_target = int(sr * duration)
    if len(audio) == 0:
        return np.zeros(n_target)

    fade_secs = min(0.5, len(audio) / sr / 4.0)
    fade_len = int(fade_secs * sr)

    rms_window = max(1, len(audio) // 64)
    energy = np.convolve(audio ** 2, np.ones(rms_window) / rms_window, mode="same")
    threshold = energy.max() * 1e-4
    nonzero = np.where(energy > threshold)[0]
    loop_end = nonzero[-1] + rms_window if len(nonzero) else len(audio)
    loop_end = min(loop_end, len(audio))
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


# ---------------------------------------------------------------- listening nodes

def resolve_listen_indices(
    nodes: list[dict],
    id_to_idx: dict[int, int],
    listen_class: str,
) -> list[int]:
    """Return matrix row indices for the requested listen class."""
    class_filter = {
        "terminal": {"terminal"},
        "primary":  {"primary", "trunk_base"},
        "all":      {"terminal", "fine", "lateral", "primary", "trunk_base"},
        "fine":     {"fine", "terminal"},
    }
    allowed = class_filter.get(listen_class, {"terminal"})
    indices = [id_to_idx[n["id"]] for n in nodes if n["class"] in allowed]
    if not indices:
        log.warning(f"No nodes found for listen_class={listen_class}, using all")
        indices = list(range(len(nodes)))
    log.info(f"Listening at {len(indices)} nodes (class filter: {listen_class})")
    return indices


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Mass-spring modal synthesis from branch_graph.json → WAV",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--graph", required=True, type=Path, help="branch_graph.json")
    ap.add_argument("--out", default="physical-modelling/tree.wav", type=Path)
    ap.add_argument("--duration", type=float, default=120.0, help="output seconds")
    ap.add_argument("--sr", type=int, default=48000, help="sample rate")

    # Physical model
    ap.add_argument("--stiffness-scale", type=float, default=1.0,
                    help="multiplies all spring constants (raise → higher pitch)")
    ap.add_argument("--mass-scale", type=float, default=1.0,
                    help="multiplies all node masses (raise → lower pitch)")
    ap.add_argument("--damping", type=float, default=0.01,
                    help="modal damping ratio ζ (0=undamped, 0.1=heavily damped)")

    # Modal parameters
    ap.add_argument("--n-modes", type=int, default=64,
                    help="number of eigenmodes to retain")
    ap.add_argument("--freq-min", type=float, default=20.0,
                    help="lower frequency cutoff (Hz)")
    ap.add_argument("--freq-max", type=float, default=4000.0,
                    help="upper frequency cutoff (Hz)")
    ap.add_argument("--mode-tilt", type=float, default=0.0,
                    help="modal amplitude ∝ ω^-tilt. 0 = flat (velocity-like); "
                         "1 = physical displacement (old behaviour, buries high modes)")
    ap.add_argument("--listen-sum", choices=["abs", "signed"], default="abs",
                    help="abs = incoherent pickup (no phase cancellation across many "
                         "listening nodes); signed = old behaviour")

    # Excitation
    ap.add_argument("--excitation", choices=["strike_tour", "impulse", "noise"],
                    default="strike_tour",
                    help="strike_tour=broadband click at each tour node, "
                         "impulse=single pluck at trunk_base, noise=stochastic")
    ap.add_argument("--burst-ms", type=float, default=-1.0,
                    help="strike click width in ms; negative = auto "
                         "(a quarter period at --freq-max)")
    ap.add_argument("--min-strike-rate", type=float, default=1.5,
                    help="minimum strikes/second; the tour repeats to reach it")
    ap.add_argument("--strike-jitter", type=float, default=0.3,
                    help="timing jitter as a fraction of the inter-strike interval")
    ap.add_argument("--strike-amp-spread", type=float, default=0.35,
                    help="log-normal σ of per-strike amplitude variation")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed")

    # Listening
    ap.add_argument("--listen-class",
                    choices=["terminal", "primary", "fine", "all"],
                    default="terminal",
                    help="node class to record output from")

    # Output
    ap.add_argument("--highpass", type=float, default=0.7,
                    help="high-pass cutoff as a fraction of --freq-min (0 disables); "
                         "removes the sub-sonic quasi-static term before normalising")
    ap.add_argument("--normalize", choices=["peak", "rms"], default="peak",
                    help="peak = normalise by peak; rms = normalise by RMS then "
                         "soft-limit (much louder perceptually)")
    ap.add_argument("--gain", type=float, default=0.891,
                    help="output target level (0–1); peak in peak mode, RMS in rms mode")

    args = ap.parse_args()

    # ---- load
    graph = load_graph(args.graph)
    nodes = graph["nodes"]
    edges = graph["edges"]
    log.info(f"Graph: {len(nodes)} nodes, {len(edges)} edges")

    # ---- matrices
    K, M, id_to_idx = build_matrices(graph, args.stiffness_scale, args.mass_scale)

    # ---- modal analysis
    freqs, modes = modal_analysis(K, M, args.n_modes, args.freq_min, args.freq_max, args.sr)
    if len(freqs) == 0:
        log.error("No modes found in the requested frequency window. "
                  "Try adjusting --freq-min/max or --stiffness-scale.")
        sys.exit(1)

    # ---- listening nodes
    listen_idx = resolve_listen_indices(nodes, id_to_idx, args.listen_class)

    # ---- excitation + synthesis
    rng = np.random.default_rng(args.seed)
    N = len(nodes)

    if args.excitation == "strike_tour":
        tours = graph.get("tours", [])
        if not tours:
            log.error("No tours found in graph. Use --excitation impulse or noise.")
            sys.exit(1)
        tour_seq = tours[0]["node_sequence"]
        log.info(f"Tour: '{tours[0]['name']}' ({len(tour_seq)} nodes)")

        burst_ms = args.burst_ms
        if burst_ms < 0:
            burst_ms = 250.0 / max(min(args.freq_max, args.sr / 2 * 0.95), 1.0)
            log.info(f"Auto burst width {burst_ms:.3f} ms")

        ev_idx, ev_t, ev_amp = build_strike_events(
            tour_seq, id_to_idx, args.sr, args.duration,
            args.min_strike_rate, args.strike_jitter, args.strike_amp_spread, rng,
        )
        audio = synthesise_modal_strikes(
            freqs, modes, ev_idx, ev_t, ev_amp, listen_idx, args.damping,
            args.sr, args.duration, burst_ms, args.mode_tilt, args.listen_sum,
        )

    else:
        if args.excitation == "impulse":
            F_static = build_excitation_impulse(N, id_to_idx, nodes)
        else:
            F_static = build_excitation_noise(N, rng)
        raw = synthesise_modal(freqs, modes, F_static, listen_idx, args.damping,
                               args.sr, args.duration, args.mode_tilt, args.listen_sum)
        audio = loop_to_duration(raw, args.sr, args.duration)

    # ---- remove the quasi-static / DC term before normalising
    fc = args.highpass * args.freq_min
    if fc > 0:
        audio = highpass(audio, args.sr, max(fc, 12.0))

    in_band = band_energy_fraction(audio, args.sr, args.freq_min,
                                   min(args.freq_max, args.sr / 2 * 0.95))
    sub = band_energy_fraction(audio, args.sr, 0.0, 20.0)
    log.info(f"In-band energy {100 * in_band:.2f} %   sub-20 Hz {100 * sub:.4f} %")
    if in_band < 0.5:
        log.warning("Less than half the energy is inside the requested window — "
                    "output will be hard to hear.")

    # ---- normalise
    if args.normalize == "rms":
        ref = rms(audio)
        if ref < 1e-12:
            log.error("Output is silent — check frequency window and stiffness scale.")
            sys.exit(1)
        out = soft_clip(audio / ref * args.gain)
    else:
        ref = np.abs(audio).max()
        if ref < 1e-12:
            log.error("Output is silent — check frequency window and stiffness scale.")
            sys.exit(1)
        out = audio / ref * args.gain
    out = out.astype(np.float32)

    # ---- write
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(args.out), out, args.sr, subtype="PCM_24")
    log.info(f"Wrote {args.out}  ({len(out)/args.sr:.1f}s, {args.sr} Hz, "
             f"{len(freqs)} modes, peak={np.abs(out).max():.3f} "
             f"({20*np.log10(np.abs(out).max()+1e-12):.1f} dBFS), "
             f"rms={rms(out):.4f} ({20*np.log10(rms(out)+1e-12):.1f} dBFS))")


if __name__ == "__main__":
    main()