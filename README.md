# AquiFuturo

[![Validate assets](https://github.com/IAndy-10/AquiFuturo/actions/workflows/validate.yml/badge.svg)](https://github.com/IAndy-10/AquiFuturo/actions/workflows/validate.yml)

Augmented reality experience that sonifies tree morphology — translating a Coast Live Oak's canopy and root structure into spatial sound through physical modeling and neural audio synthesis.

**[Project page](https://www.italorojas-portfolio.cl/projects/aquifuturo)** · MAT M.S. thesis project — UC Santa Barbara, 2026.

[![AquiFuturo demo](https://img.youtube.com/vi/JtSMAYQnHuI/maxresdefault.jpg)](https://www.youtube.com/watch?v=JtSMAYQnHuI)

---

## Concept

Visitors approach a Coast Live Oak, point their phone near the trunk, and tap to place a virtual underground root system in AR. A five-track soundscape responds to how the user moves and where they touch, revealing the tree's hidden morphology through sound.

The root system is displayed alone — no above-ground tree model. Interaction is physical: orientation, tilt, distance, and touch drive the mix in real time.

---

## Pipeline

```
 Capture                Geometry                      Graph                         Sound                          App
 ───────                ────────                      ─────                         ─────                          ───
 96 iPhone photos  ──►  PostShot Gaussian splat  ──►  Blender: trunk + branches
 (5 m orbit)            ──► Blender mesh prep          retopologised, roots
                                                       generated
                                                          │
                                                          ▼
                                                     skeleton JSON
                                                     (skel_*_skeleton.json)
                                                          │
                                       ┌──────────────────┴──────────────────┐
                                       ▼                                     ▼
                                 branch skeleton                       root skeleton
                                       │                                     │
                                       │                          split_roots.py → 4 zones (G1–G4)
                                       ▼                                     ▼
                              graph_builder.py                      graph_builder.py
                              branch_graph.json                     root_graph.json + zone graphs
                              (nodes, classes, TSP tour)            (nodes, classes, TSP tour)
                                       │                                     │
                                       ▼                                     ▼
                              branch_synth.py                        pca_rave.py
                              modal synthesis per class              PCA features → RAVE latent
                              → track_canopy.wav                     → track_voice.wav, rave_zone1–4.wav
                                       │                                     │
                                       └──────────────────┬──────────────────┘
                                                          ▼
                                              validate_assets.py (CI)
                                                          │
                                                          ▼
                                         Unity 6 + AR Foundation + ARKit (iOS)
                                         5 phase-locked tracks, pose-driven mix,
                                         tap-triggered zone clips
```

Field recordings (`track_river`, `track_birds1`, `track_birds2`) join the mix directly.

---

## Sonification

### Canopy — Modal synthesis

The branch skeleton (267 nodes) is treated as a mass-spring network with per-class stiffness multipliers, stratifying the spectrum across five structural classes — from trunk base (20–120 Hz) to terminal tips (1,500–8,000 Hz). Mode shapes come from the generalised eigenvalue problem `K·φ = ω²·M·φ` (96 modes), and a strike train following the TSP tour excites them. The five class layers are RMS-normalised, then mixed into the final stereo stem.

### Roots — Neural audio synthesis (RAVE)

8 morphological features per node are mapped into a 16-dimensional latent space via PCA. A RAVE decoder trained on water sounds generates audio from smooth TSP tour trajectories through that space. A closed tour returns to its starting latent point, so the decoded track loops seamlessly with no crossfade. One clip is rendered per spatial root zone.

### Mixing layer

Five looping stereo tracks (48 kHz, 120 s, identical sample length) play phase-locked via `PlayScheduled()`. Four are modulated by phone pose — attention drives a logarithmic low-pass filter sweep, azimuth controls stereo pan, tilt shifts layer balance, and distance scales gain. The fifth track (`track_river`) is a static field-recording bed. Tapping on one of the four root zones triggers its RAVE-generated clip.

There is deliberately no 3D spatialiser: the mix is driven by pose, not by positional emitters (SPEC.md §9.6).

---

## Tech stack

| Layer | Technology |
|---|---|
| Platform | iOS — Unity 6 LTS, AR Foundation 6, ARKit |
| Audio engine | Unity AudioSource + AudioLowPassFilter (2D, no spatialiser) |
| Capture | iPhone photos → PostShot (Gaussian splatting) |
| Geometry | Blender 5.2 LTS |
| Modal synthesis | Python — NumPy/SciPy mass-spring eigenvalue decomposition |
| Neural synthesis | RAVE (16-dim latent, TorchScript), PCA manifold alignment |
| Asset validation | Python CLI (`validate_assets.py`), GitHub Actions |

---

## Python tools

Python 3.11. Install the dependencies once:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r tools/requirements.txt
pip install torch          # only for pca_rave.py
```

Audio and models are in Git LFS. Run `git lfs install && git lfs pull` after cloning.

| Tool | What it does |
|---|---|
| `tools/split_roots.py` | Splits the root skeleton into 4 spatial zones (G1–G4) by depth and radial spread |
| `tools/graph_builder.py` | Skeleton JSON → `root_graph.json` / `branch_graph.json` (schema 1.1): node classes, bounds, TSP tour. Stdlib + NumPy only, so it also runs inside Blender |
| `tools/branch_synth.py` | `branch_graph.json` → per-class modal synthesis → WAV |
| `tools/pca_rave.py` | Graph TSP tour → PCA latent trajectory → RAVE decode → looping WAV |
| `tools/validate_assets.py` | Checks the assets against the data contracts (see below) |
| `tools/legacy/` | Earlier single-pass modal synthesis and graph simplification, kept for reference |

Example run, from the repo root:

```bash
# Root skeleton → 4 zones → one graph per zone
python tools/split_roots.py --input data/raw/skeletons/skel_roots_skeleton.json --outdir data/raw/skeletons/
python tools/graph_builder.py --input data/raw/skeletons/skel_roots_g1.json \
    --out data/processed/skeleton/root_graph_g1.json --root-at-top --tour tsp_2opt

# Branch graph → canopy modal synthesis (120 s, 48 kHz)
python tools/branch_synth.py --graph data/processed/skeleton/branch_graph.json --out track_canopy_raw.wav

# Root graph → RAVE decode (needs a RAVE TorchScript model, not in the repo)
python tools/pca_rave.py --graph data/processed/skeleton/root_graph.json --model path/to/model.ts --out track_voice_raw.wav
```

Each tool has `--help` for the full set of options.

---

## Validation

`tools/validate_assets.py` checks the assets the Unity app depends on, against the data contracts in SPEC.md §5:

1. `root_graph.json` and `branch_graph.json`: schema version, node/edge referential integrity, node classes, positions inside the declared bounds.
2. `audio_manifest.json`: schema version and all five track IDs.
3. Every track and interaction clip exists. All five tracks are 48 kHz stereo and **identical in sample length** — the phase-locked start depends on it. Files still stored as Git LFS pointers are reported.
4. The three FBX models required by SPEC §5.3 exist.

```bash
pip install soundfile
python tools/validate_assets.py      # exit 0 = pass, 1 = failure, 2 = usage error
```

The [Validate assets workflow](.github/workflows/validate.yml) runs it, together with `ruff check tools/`, on every push and pull request. The LFS audio is cached in CI, so it is only downloaded again when it changes.

---

## Repository layout

```
AquiFuturo/
├── SPEC.md                    # technical specification (data contracts, audio model, milestones)
├── CLAUDE.md                  # Claude Code working agreement
├── CHANGELOG.md
├── .github/workflows/         # CI: ruff + asset validation
├── tools/                     # Python CLI tools (see above) + audio_manifest.json
├── data/
│   ├── raw/
│   │   ├── skeletons/         # Blender-exported skeletons (roots, branches, 4 root zones)
│   │   └── audio/             # unprocessed recordings and RAVE renders (LFS)
│   └── processed/
│       ├── skeleton/          # root_graph.json, branch_graph.json, zone graphs
│       └── audio/             # 5 looping tracks + 4 RAVE zone clips (LFS)
├── AquiFuturo-app/            # Unity 6 project
│   └── Assets/
│       ├── Art/Models/        # AquiFuturo_RootA/RootB/Trunk.fbx (LFS)
│       ├── Audio/             # Tracks/ and Interaction/ (LFS)
│       ├── StreamingAssets/   # root_graph.json loaded at runtime
│       └── Scripts/           # C# — Core, Placement, Graph, Audio, Interaction, UI
└── xcode_build/               # Unity-generated iOS project (tracked stubs only)
```

---

## License

See thesis document for terms.
