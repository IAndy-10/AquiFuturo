# AquiFuturo AR

iOS Augmented Reality prototype for an MAT M.S. thesis (UC Santa Barbara, 2026).

The app places a virtual underground root system in AR and reveals it alongside a five-track soundscape that responds to how the user moves and where they touch. One audio track — the *root voice* — is produced offline by an unsupervised cross-domain manifold alignment: root skeleton graph traversals (TSP tour) become trajectories through a RAVE latent space, decoded into audio. Interaction zone clips are also RAVE-generated, one per spatial root zone. The remaining tracks are conventionally designed. The app is the interaction and mixing layer over those stems.

The root system is displayed alone (no above-ground tree model). Placement is manual: the user points the phone near the real tree trunk and taps to fix the root system at that position.

Target audience: ~20 participants, outdoors, using their own iPhones and headphones.

---

## Repository layout

```
aquifuturo-ar/
├── SPEC.md                  # single source of truth — read this first
├── CLAUDE.md                # Claude Code working agreement
├── CHANGELOG.md
├── STATUS.md
├── tools/
│   ├── graph_builder.py     # Blender-native skeleton → root_graph.json
│   ├── split_roots.py       # skeleton → 4 spatial zone skeletons
│   ├── tree_to_wav.py       # modal synthesis from branch_graph.json
│   ├── branch_synth.py      # per-class modal synthesis
│   ├── pca_rave.py          # TSP tour → PCA latent → WAV (RAVE pipeline)
│   ├── audio_manifest.json  # track + interaction clip registry
│   ├── validate_assets.py   # CI asset validator (SPEC §5)
│   └── requirements.txt
├── data/
│   ├── processed/
│   │   ├── skeleton/        # root_graph.json, branch_graph.json, zone graphs g1–g4
│   │   └── audio/           # 5 looping tracks + 4 rave zone clips (48 kHz stereo)
│   └── raw/                 # raw audio stems before resampling
├── assets_src/
│   ├── zones/               # per-zone skeleton JSONs (split_roots.py output)
│   └── audio/               # source audio files (Git LFS)
└── unity/
    └── Assets/
        ├── Art/Models/      # AquiFuturo_RootA.fbx, AquiFuturo_RootB.fbx, AquiFuturo_Trunk.fbx
        ├── Audio/
        │   ├── Tracks/      # 5 × looping WAV (48 kHz stereo, 120 s)
        │   └── Interaction/ # 4 × RAVE zone clips
        ├── Prefabs/         # AquiFuturo_Tree_Terra.prefab
        └── Scripts/
            ├── Core/        # GameManager, AppState, SessionLogger
            ├── Placement/   # TreePlacement, TreeAdjuster
            ├── Graph/       # RootGraph, RootGraphLoader, SpatialHash
            ├── Audio/       # TrackMixer, PoseAnalyzer, TrackChannel
            ├── Interaction/ # ZoneInteraction, ZoneTrigger, ParticleSpawner
            └── UI/          # HudController
```

---

## Software versions (lock these)

| Tool | Version |
|---|---|
| Unity | 6 LTS (6000.0.x) |
| AR Foundation | 6.x |
| ARKit XR Plugin | matching AR Foundation |
| Blender | 4.x |
| Xcode | latest — iOS 16.0 minimum deployment |
| Python | 3.11 |

No third-party audio middleware. Audio uses stock Unity `AudioSource` + `AudioLowPassFilter` + `AudioMixer` only (SPEC §9.6).

---

## Python tools setup

```bash
pip install -r tools/requirements.txt
```

### Skeleton extraction — `tools/skeletonize.py`

Reads a PLY/GLB/OBJ mesh, extracts a curve skeleton via geodesic shell slicing or point-cloud k-NN (auto-selected by mesh connectivity), classifies nodes with Strahler stream order, computes a closed TSP 2-opt tour, converts to Unity Y-up coordinates, and writes `root_graph.json` (schema v1.1, SPEC §5.1).

**Roots mesh** (540 disconnected tube components → point-cloud k-NN mode):
```bash
python tools/skeletonize.py \
  --mesh assets_src/skel_roots_main.ply \
  --out  data/root_graph.json \
  --tour tsp_2opt \
  --coordinate-space unity_y_up \
  --root-at-top \
  --no-decimate \
  --min-nodes 80 \
  --center-at-root
```

**Branches mesh** (connected → geodesic shell mode):
```bash
python tools/skeletonize.py \
  --mesh assets_src/skel_branches.ply \
  --out  data/branch_graph.json \
  --tour tsp_2opt \
  --coordinate-space unity_y_up \
  --no-decimate \
  --center-at-root
```

Add `--viz` to either command to open an interactive Polyscope overlay (mesh surface + skeleton nodes coloured by class + TSP tour in magenta).

**Node classes** (Strahler-derived): `trunk_base` · `primary` · `lateral` · `fine` · `terminal`

### Asset validation — `tools/validate_assets.py`

```bash
python tools/validate_assets.py
```

Checks `root_graph.json` schema, node/edge integrity, audio sample-rate parity (48 kHz stereo, identical lengths), and GLB child-name contract. Must pass before merging to `dev`.

---

## Git workflow

```
main  ←  dev  ←  feat/<short-name>
```

- `main` is always a buildable Xcode project. Never commit directly.
- Tag each field-test build: `v0.MINOR.PATCH-field`.
- Binary assets (`.ply`, `.glb`, `.wav`, `.blend`, `.png`) are tracked by Git LFS — run `git lfs install` before the first asset commit.

---

## Milestones

| ID | Status | Description |
|---|---|---|
| M0 | ✅ done | Repo + contracts, validator, CLAUDE.md, all C# scripts imported by Unity |
| M1 | ✅ done | Root system visible in AR on device; five tracks sample-synced with working LPF and pan |
| M2 | ✅ done | Real root FBX models in Unity; `root_graph.json` + zone graphs produced; modal synthesis + RAVE pipeline complete |
| M3 | ✅ done | Five final tracks (48 kHz, 120 s, stereo); RAVE zone clips; all pose mappings; zone interaction audio working |
| M4 | 🔄 in progress | Polish + UI: particle visual feedback, root fade shader, HUD, reset — `feat/polish-and-ui` |
| M5 | ⬜ | Instrumentation + hardening: SessionLogger CSV, 20-min soak |
| M6 | ⬜ | Field readiness: IRB, TestFlight live, 3 pilot sessions |

### What's done on `dev`

| Area | State |
|---|---|
| Repo scaffold, `.gitignore`, `.gitattributes`, Git LFS | ✅ |
| `validate_assets.py` — schema, node/edge integrity, audio parity | ✅ |
| `tools/graph_builder.py` + `split_roots.py` — skeleton extraction, 4-zone split | ✅ |
| `tools/tree_to_wav.py` + `branch_synth.py` — modal synthesis pipeline | ✅ |
| `tools/pca_rave.py` — TSP tour → PCA latent → RAVE zone WAVs | ✅ |
| `data/processed/skeleton/` — root_graph.json + branch_graph.json + zone graphs g1–g4 | ✅ |
| `tools/audio_manifest.json` — 5-track + 4-zone interaction registry | ✅ |
| C# scripts: Core / Audio / Placement / Graph / Interaction / UI | ✅ |
| 4 ScriptableObject config classes (no magic numbers) | ✅ |
| Unity scene assembled (AquiFuturo_Tree_Terra prefab, zones, TrackMixer) | ✅ |
| Root FBX models imported (`AquiFuturo_RootA`, `RootB`, `Trunk`) | ✅ |
| 5 looping tracks — 48 kHz stereo, 120 s, phase-locked via `PlayScheduled()` | ✅ |
| 4 RAVE interaction zone clips (`rave_zone1–4.wav`) | ✅ |
| Zone-based tap interaction (4 × Box Collider + `ZoneTrigger` + `ZoneInteraction`) | ✅ |
| Pose-driven modulation confirmed: LPF, pan, tilt, distance | ✅ |
| TestFlight build submitted | ❌ pending |

See SPEC.md §17 for full acceptance criteria per milestone.

---

## Key conventions

- **Coordinate system:** 1 unit = 1 metre. Tree origin at trunk base, ground level. `y > 0` = trunk/branches, `y < 0` = roots.
- **Audio:** Five looping stereo tracks, 2D (`spatialBlend = 0`), sample-synced via `PlayScheduled()`. Modulation via LPF cutoff (logarithmic Hz), stereo pan, and volume — driven by pose axes relative to the placed tree (SPEC §9.3). `track_river` is a static bed (no modulation). No 3D spatialisation. Interaction taps on zone Box Colliders trigger RAVE zone clips (`rave_zone1–4.wav`).
- **No magic numbers:** every tunable lives in a ScriptableObject config.
- **No `GameObject.Find`:** all wiring is through the Inspector or Bootstrap component.

Full conventions in SPEC.md §2 and CLAUDE.md.
