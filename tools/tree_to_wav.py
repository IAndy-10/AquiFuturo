#!/usr/bin/env python3
"""
tree_to_wav.py — AquiFuturo physical modelling synthesis
branch_graph.json (mass-spring tree) -> modal synthesis -> looping WAV

Method: Modal analysis of the mass-spring system.
  - Nodes = masses  (m ∝ radius²)
  - Edges = springs (k ∝ stiffness_scale / length²)
  - Solve generalised eigenvalue problem K·φ = ω²·M·φ
  - Synthesise audio by summing modal contributions at listening nodes
  - Optionally drive with TSP tour sweep (echoing pca_rave.py approach)

Usage:
    # Quick impulse at trunk base, listen at terminals:
    python3 tools/tree_to_wav.py --graph data/branch_graph.json \\
        --out physical-modelling/tree_impulse.wav

    # Tour sweep, wider frequency window, more damping:
    python3 tools/tree_to_wav.py --graph data/branch_graph.json \\
        --out physical-modelling/tree_sweep.wav \\
        --excitation tour_sweep --damping 0.05 --freq-min 40 --freq-max 3000

    # Bright, lightly damped, all terminals:
    python3 tools/tree_to_wav.py --graph data/branch_graph.json \\
        --out physical-modelling/tree_bright.wav \\
        --stiffness-scale 4.0 --damping 0.005 --n-modes 128 --freq-max 8000

Deps: pip install numpy scipy soundfile
"""

import argparse
import json
import logging
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
    """Build stiffness K and mass M matrices from the graph.

    Returns:
        K          (N, N) stiffness matrix (weighted Laplacian)
        M          (N,)   mass vector (diagonal of mass matrix)
        id_to_idx  mapping from node id to matrix index
    """
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
    """Solve generalised eigenvalue problem K·φ = ω²·M·φ.

    Returns:
        freqs   (n_kept,)    resonant frequencies in Hz
        modes   (N, n_kept)  mode shape matrix, mass-normalised
    """
    N = K.shape[0]
    n_modes = min(n_modes, N - 1)

    # Regularise M to avoid division by zero
    M_reg = np.maximum(M, 1e-10)

    # Scale to M⁻½ · K · M⁻½ form for standard eigenvalue solve
    M_sqrt_inv = 1.0 / np.sqrt(M_reg)           # (N,)
    K_sym = M_sqrt_inv[:, None] * K * M_sqrt_inv[None, :]

    # Symmetrise to kill floating-point asymmetry
    K_sym = 0.5 * (K_sym + K_sym.T)

    log.info(f"Solving eigenvalue problem (N={N}, requesting {n_modes} modes)…")
    # scipy.linalg.eigh returns eigenvalues in ascending order
    # 'subset_by_index' picks the n_modes+1 smallest (lowest freq first)
    # driver must be 'evr' or 'evx' to support subsets
    eigenvalues, eigenvectors = scipy.linalg.eigh(
        K_sym,
        subset_by_index=[0, n_modes],
        driver="evr",
    )

    # ω² = eigenvalue (may be slightly negative due to float error at zero mode)
    omega_sq = np.maximum(eigenvalues, 0.0)
    omega = np.sqrt(omega_sq)                    # rad/s
    freqs = omega / (2.0 * np.pi)               # Hz

    # Back-transform eigenvectors: φ = M⁻½ · v
    modes = M_sqrt_inv[:, None] * eigenvectors  # (N, n_modes+1)

    # Filter to audible window (skip DC / rigid-body mode at ≈0 Hz)
    nyquist = sr / 2.0
    freq_max_clip = min(freq_max, nyquist * 0.95)
    mask = (freqs >= freq_min) & (freqs <= freq_max_clip)

    freqs = freqs[mask]
    modes = modes[:, mask]

    log.info(
        f"Modal analysis: {mask.sum()} modes in [{freq_min:.1f}, {freq_max_clip:.1f}] Hz "
        f"(range: {freqs.min():.2f}–{freqs.max():.2f} Hz)"
    )
    return freqs, modes


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


def build_tour_excitation_envelope(
    tour: list[int],
    id_to_idx: dict[int, int],
    N: int,
    n_frames: int,
) -> np.ndarray:
    """Time-varying force: sweep through tour nodes, each receiving a Gaussian bump.

    Returns F (N, n_frames) — force at each node over time.
    Each tour node gets a bump centred at its position in the sweep.
    """
    log.info(f"Excitation: tour_sweep over {len(tour)} nodes → {n_frames} frames")
    F = np.zeros((N, n_frames), dtype=np.float32)
    n_nodes = len(tour)
    bump_width = n_frames / n_nodes / 3.0          # σ in frames

    for k, node_id in enumerate(tour):
        if node_id not in id_to_idx:
            continue
        idx = id_to_idx[node_id]
        centre = (k + 0.5) / n_nodes * n_frames
        t = np.arange(n_frames)
        bump = np.exp(-0.5 * ((t - centre) / bump_width) ** 2)
        F[idx] += bump

    return F


# ---------------------------------------------------------------- synthesis

def synthesise_modal(
    freqs: np.ndarray,
    modes: np.ndarray,
    excitation_force: np.ndarray,
    listen_indices: list[int],
    damping: float,
    sr: int,
    duration: float,
) -> np.ndarray:
    """Impulse/noise excitation → modal synthesis → time-domain audio.

    For each mode k:
        - modal force:       f_k = φ_k · F   (dot product over nodes)
        - modal response:    q_k(t) = (f_k / ω_k) · sin(ω_k·t) · e^(-ζ·ω_k·t)
        - physical output:   y(t) = Σ_k  (Σ_listen φ_k[listen]) · q_k(t)

    Works for both static force vector and per-node stochastic (noise) vector.
    """
    n_samples = int(sr * duration)
    t = np.arange(n_samples) / sr

    # Modal participation at listening nodes
    listen_shape = modes[listen_indices, :].sum(axis=0)    # (n_modes,)

    # Modal forcing
    modal_force = modes.T @ excitation_force               # (n_modes,)

    omega = 2.0 * np.pi * freqs                           # (n_modes,)
    omega_d = omega * np.sqrt(np.maximum(1.0 - damping**2, 1e-6))  # damped freq

    audio = np.zeros(n_samples, dtype=np.float64)
    n_modes = len(freqs)

    for k in range(n_modes):
        w = omega[k]
        wd = omega_d[k]
        if wd < 1e-3:
            continue
        amplitude = listen_shape[k] * modal_force[k] / (w + 1e-12)
        decay = np.exp(-damping * w * t)
        audio += amplitude * np.sin(wd * t) * decay

    return audio


def synthesise_modal_tour(
    freqs: np.ndarray,
    modes: np.ndarray,
    F: np.ndarray,
    listen_indices: list[int],
    damping: float,
    sr: int,
    duration: float,
) -> np.ndarray:
    """Tour-sweep excitation → modal synthesis.

    F is (N, n_frames_coarse), resampled to audio rate via cubic spline.
    We compute the convolution response per mode using the modal force trajectory.
    """
    n_samples = int(sr * duration)
    t_audio = np.arange(n_samples) / sr

    # Upsample force matrix from coarse frames to audio samples
    n_coarse = F.shape[1]
    t_coarse = np.linspace(0.0, duration, n_coarse)

    # Project force onto modes: modal_force_t[k, :] = Σ_i φ_k[i] · F[i, t]
    MF_coarse = modes.T @ F                         # (n_modes, n_coarse)

    listen_shape = modes[listen_indices, :].sum(axis=0)    # (n_modes,)
    omega = 2.0 * np.pi * freqs
    omega_d = omega * np.sqrt(np.maximum(1.0 - damping**2, 1e-6))

    audio = np.zeros(n_samples, dtype=np.float64)
    n_modes = len(freqs)

    for k in range(n_modes):
        wd = omega_d[k]
        zeta_w = damping * omega[k]
        if wd < 1e-3:
            continue

        # Upsample modal force to audio rate
        mf_audio = np.interp(t_audio, t_coarse, MF_coarse[k])

        # Convolve with damped sinusoid impulse response
        # h(t) = (1/ω_d) · sin(ω_d·t) · e^(-ζω·t)
        # Use short kernel (keep it causally correct via overlap-add)
        decay_time = 6.0 / (zeta_w + 1e-6)        # time to -60 dB
        kernel_len = min(int(decay_time * sr), n_samples // 4, 65536)
        if kernel_len < 2:
            continue
        t_k = np.arange(kernel_len) / sr
        h = (1.0 / wd) * np.sin(wd * t_k) * np.exp(-zeta_w * t_k)

        response = scipy.signal.fftconvolve(mf_audio, h, mode="full")[:n_samples]
        audio += listen_shape[k] * response

    return audio


# ---------------------------------------------------------------- looping

def loop_to_duration(audio: np.ndarray, sr: int, duration: float) -> np.ndarray:
    """Tile + crossfade to target duration, then trim."""
    n_target = int(sr * duration)
    if len(audio) == 0:
        return np.zeros(n_target)

    # Crossfade window for looping
    fade_secs = min(0.5, len(audio) / sr / 4.0)
    fade_len = int(fade_secs * sr)

    # Trim silence at tail to find natural loop point
    rms_window = max(1, len(audio) // 64)
    energy = np.convolve(audio**2, np.ones(rms_window) / rms_window, mode="same")
    threshold = energy.max() * 1e-4
    nonzero = np.where(energy > threshold)[0]
    loop_end = nonzero[-1] + rms_window if len(nonzero) else len(audio)
    loop_end = min(loop_end, len(audio))
    loop = audio[:loop_end]

    if len(loop) < fade_len * 2:
        # Too short to crossfade — just tile
        tiled = np.tile(loop, (n_target // len(loop)) + 2)
        return tiled[:n_target]

    # Crossfade: blend tail into head
    fade_out = np.linspace(1.0, 0.0, fade_len)
    fade_in = np.linspace(0.0, 1.0, fade_len)
    loop[-fade_len:] = loop[-fade_len:] * fade_out + loop[:fade_len] * fade_in
    loop_body = loop[fade_len:]                   # skip blended head on repeat

    # Tile
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

    # Excitation
    ap.add_argument("--excitation", choices=["impulse", "noise", "tour_sweep"],
                    default="impulse",
                    help="excitation type: impulse=single pluck at trunk_base, "
                         "noise=stochastic, tour_sweep=sequential excitation along tour")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed (for noise)")

    # Listening
    ap.add_argument("--listen-class",
                    choices=["terminal", "primary", "fine", "all"],
                    default="terminal",
                    help="node class to record output from")

    # Output
    ap.add_argument("--gain", type=float, default=0.891,
                    help="output peak level (0–1), default = -1 dBFS")

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

    if args.excitation == "impulse":
        F_static = build_excitation_impulse(N, id_to_idx, nodes)
        raw = synthesise_modal(freqs, modes, F_static, listen_idx,
                               args.damping, args.sr, args.duration)

    elif args.excitation == "noise":
        F_static = build_excitation_noise(N, rng)
        raw = synthesise_modal(freqs, modes, F_static, listen_idx,
                               args.damping, args.sr, args.duration)

    elif args.excitation == "tour_sweep":
        tours = graph.get("tours", [])
        if not tours:
            log.error("No tours found in graph. Use --excitation impulse or noise.")
            sys.exit(1)
        tour_seq = tours[0]["node_sequence"]
        log.info(f"Tour: '{tours[0]['name']}' ({len(tour_seq)} nodes)")

        # Coarse time grid: one frame per tour node
        n_coarse = len(tour_seq) * 4      # 4 frames per node for smoother envelope
        F_tour = build_tour_excitation_envelope(tour_seq, id_to_idx, N, n_coarse)
        raw = synthesise_modal_tour(freqs, modes, F_tour, listen_idx,
                                    args.damping, args.sr, args.duration)

    # ---- loop to duration
    audio = loop_to_duration(raw, args.sr, args.duration)

    # ---- normalise
    peak = np.abs(audio).max()
    if peak < 1e-10:
        log.error("Output is silent — check frequency window and stiffness scale.")
        sys.exit(1)
    audio = (audio / peak * args.gain).astype(np.float32)

    # ---- write
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(args.out), audio, args.sr, subtype="PCM_24")
    log.info(f"Wrote {args.out}  ({len(audio)/args.sr:.1f}s, {args.sr} Hz, "
             f"{len(freqs)} modes, peak→{args.gain:.3f})")


if __name__ == "__main__":
    main()
