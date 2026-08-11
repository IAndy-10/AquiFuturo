#!/usr/bin/env python3
"""
render_rave.py — AquiFuturo offline audio render
root_graph.json (TSP tour) -> latent trajectory -> RAVE decode -> looping WAV

Usage:
    python3 render_rave.py --graph root_graph.json --model bird.ts \
        --out track_root_rave.wav --duration 150 --z-scale 1.6

    # If you have reference audio, calibrate the latent frame to the model's
    # actual usage (strongly recommended):
    python3 render_rave.py --graph root_graph.json --model bird.ts \
        --ref-audio refs/*.wav --out track_root_rave.wav

Deps: pip install torch numpy scipy soundfile
"""

import argparse, glob, json, sys
import numpy as np
import torch
from scipy.interpolate import CubicSpline
import soundfile as sf

torch.set_grad_enabled(False)


# ---------------------------------------------------------------- model probing

def load_model(path):
    model = torch.jit.load(path, map_location="cpu")
    model.eval()
    return model


def probe_model(model):
    """Discover sample rate, latent dim, and compression ratio (samples/frame)."""
    sr = None
    for attr in ("sr", "sample_rate", "sampling_rate"):
        if hasattr(model, attr):
            v = getattr(model, attr)
            sr = int(v.item() if torch.is_tensor(v) else v)
            break
    if sr is None:
        sr = 44100
        print("[probe] no sr attribute found, assuming 44100")

    # Encode noise to find latent dim; measure hop from decode (encode pads)
    x = torch.randn(1, 1, sr) * 0.1
    z = model.encode(x)
    latent_dim = z.shape[1]
    probe_frames = 32
    audio = model.decode(torch.zeros(1, latent_dim, probe_frames))
    hop = audio.shape[-1] // probe_frames
    print(f"[probe] sr={sr}  latent_dim={latent_dim}  hop={hop} samples/frame "
          f"({sr/hop:.1f} latent fps)")
    return sr, latent_dim, hop


def latent_stats_from_refs(model, sr, latent_dim, ref_paths):
    """Encode reference audio; return per-dim (mean, std) of the latent usage."""
    zs = []
    for p in ref_paths:
        audio, in_sr = sf.read(p, always_2d=True)
        audio = audio.mean(axis=1)  # mono
        if in_sr != sr:
            # cheap linear resample; fine for statistics
            n_out = int(len(audio) * sr / in_sr)
            audio = np.interp(np.linspace(0, len(audio) - 1, n_out),
                              np.arange(len(audio)), audio)
        x = torch.from_numpy(audio.astype(np.float32))[None, None, :]
        z = model.encode(x)[0].numpy()          # (D, T)
        zs.append(z)
        print(f"[refs] {p}: {z.shape[1]} frames")
    Z = np.concatenate(zs, axis=1)              # (D, total_T)
    return Z.mean(axis=1), Z.std(axis=1)


# ---------------------------------------------------------------- graph -> trajectory

def node_features(graph, tour):
    """Per-node feature matrix along the tour, standardized to zero-mean/unit-std.

    Feature order = latent dim priority. RAVE v2 .ts exports order latent dims
    by informativeness, so the most meaningful root features go to dims 0..k.
    """
    nodes = {n["id"]: n for n in graph["nodes"]}
    class_rank = {"trunk_base": 0, "primary": 1, "lateral": 2,
                  "fine": 3, "terminal": 4}
    F = np.array([
        [
            nodes[i]["position"][1],            # depth underground (Y)
            nodes[i]["radius"],                 # thickness
            nodes[i]["branch_order"],           # hierarchy level
            nodes[i]["depth_order"],            # hops from trunk
            class_rank.get(nodes[i]["class"], 2),
            nodes[i]["position"][0],            # lateral spread X
            nodes[i]["position"][2],            # lateral spread Z
            float(nodes[i]["is_terminal"]),
        ]
        for i in tour
    ])
    return (F - F.mean(0)) / (F.std(0) + 1e-8)


def build_trajectory(Zanchors, n_frames):
    """Closed periodic spline through per-node anchors, sampled at n_frames."""
    closed = np.vstack([Zanchors, Zanchors[:1]])
    t = np.linspace(0.0, 1.0, len(closed))
    cs = CubicSpline(t, closed, bc_type="periodic")
    return cs(np.linspace(0.0, 1.0, n_frames, endpoint=False))  # (T, k)


def features_to_latent(traj_feats, latent_dim, z_scale, mean=None, std=None):
    """(T, k) standardized features -> (T, D) latent trajectory."""
    T, k = traj_feats.shape
    Z = np.zeros((T, latent_dim), dtype=np.float32)
    Z[:, :min(k, latent_dim)] = traj_feats[:, :latent_dim]
    if mean is not None:
        # calibrate to the model's actual latent usage: mean ± z_scale*std
        Z = mean[None, :] + Z * (std[None, :] * z_scale * 0.5)
    else:
        Z *= z_scale
    return Z


# ---------------------------------------------------------------- decode

def decode_chunked(model, Z, chunk_frames=512, overlap=8):
    """Decode (T, D) latent trajectory in overlapping chunks, crossfaded."""
    T, D = Z.shape
    out, prev_tail, hop_len = [], None, None
    starts = list(range(0, T, chunk_frames))
    for si, s in enumerate(starts):
        e = min(s + chunk_frames + overlap, T)
        z = torch.from_numpy(Z[s:e].T[None]).float()      # (1, D, t)
        audio = model.decode(z)[0, 0].numpy()
        if hop_len is None:
            hop_len = round(len(audio) / (e - s))
        if prev_tail is not None:
            fade = np.linspace(0, 1, len(prev_tail))
            audio[: len(prev_tail)] = (prev_tail * (1 - fade)
                                       + audio[: len(prev_tail)] * fade)
        keep = (min(s + chunk_frames, T) - s) * hop_len
        out.append(audio[:keep])
        prev_tail = audio[keep: keep + overlap * hop_len] \
            if e < T else None
        print(f"[decode] chunk {si+1}/{len(starts)}", end="\r")
    print()
    return np.concatenate(out)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", default="track_root_rave.wav")
    ap.add_argument("--duration", type=float, default=150.0,
                    help="target seconds (120-180 per SPEC)")
    ap.add_argument("--tour", default=None,
                    help="tour name in graph['tours']; default = first")
    ap.add_argument("--z-scale", type=float, default=1.6,
                    help="latent excursion; raise for wilder, lower for tamer")
    ap.add_argument("--ref-audio", nargs="*", default=None,
                    help="wav files to calibrate latent stats (recommended)")
    args = ap.parse_args()

    graph = json.load(open(args.graph))
    tours = graph["tours"]
    tour = next((t for t in tours if t["name"] == args.tour), tours[0])
    seq = tour["node_sequence"]
    print(f"[graph] tour '{tour['name']}' ({tour['method']}), {len(seq)} nodes")

    model = load_model(args.model)
    sr, latent_dim, hop = probe_model(model)

    mean = std = None
    if args.ref_audio:
        paths = [p for pat in args.ref_audio for p in glob.glob(pat)]
        if paths:
            mean, std = latent_stats_from_refs(model, sr, latent_dim, paths)
            print(f"[refs] calibrated latent frame from {len(paths)} file(s)")

    n_frames = int(round(args.duration * sr / hop))
    feats = node_features(graph, seq)
    traj = build_trajectory(feats, n_frames)
    Z = features_to_latent(traj, latent_dim, args.z_scale, mean, std)
    print(f"[traj] {n_frames} latent frames -> ~{n_frames*hop/sr:.1f}s of audio")

    audio = decode_chunked(model, Z)
    peak = np.abs(audio).max()
    if peak > 0:
        audio = audio / peak * 0.891  # -1 dBFS
    sf.write(args.out, audio.astype(np.float32), sr)
    print(f"[done] wrote {args.out}  ({len(audio)/sr:.1f}s, sr={sr}, "
          f"loops seamlessly)")


if __name__ == "__main__":
    main()
