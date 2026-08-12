# AquiFuturo AR

iOS Augmented Reality prototype for an MAT M.S. thesis (UC Santa Barbara, 2026).

The app places a virtual twin of a real tree in AR and reveals its underground root system alongside a four-track soundscape that responds to how the user moves and where they touch the roots. One audio track — the *root voice* — is produced offline by an unsupervised cross-domain manifold alignment: root skeleton graph traversals (TSP tour) become trajectories through a RAVE latent space, decoded into audio. The remaining tracks are conventionally designed. The app is the interaction and mixing layer over those stems.

Target audience: ~20 participants, outdoors, using their own iPhones and headphones.

---

## Repository layout

```
aquifuturo-ar/
├── SPEC.md                  # single source of truth — read this first
├── CLAUDE.md                # Claude Code working agreement
├── CHANGELOG.md
├── tools/
│   ├── skeletonize.py       # mesh → root_graph.json (SPEC §6.4)
│   ├── validate_assets.py   # CI asset validator (SPEC §5)
│   └── requirements.txt
├── data/
│   ├── root_graph.json      # extracted root skeleton (schema v1.1)
│   └── branch_graph.json    # extracted branch skeleton (schema v1.1)
├── assets_src/              # Git LFS: .ply, .blend, raw capture — not shipped
├── docs/
│   ├── blender_session.md
│   ├── unity_session.md
│   ├── field_protocol.md
│   └── decisions/           # ADRs
└── unity/
    └── Assets/Scripts/
        ├── Core/            # GameManager, AppState, SessionLogger
        ├── Placement/       # TreePlacement, TreeAdjuster
        ├── Graph/           # RootGraph, RootGraphLoader, SpatialHash
        ├── Audio/           # TrackMixer, PoseAnalyzer, TrackChannel
        ├── Interaction/     # RootInteraction, ParticleSpawner
        └── UI/              # HudController
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
| M0 | ✅ done | Repo + contracts, validator, CLAUDE.md, all 19 C# scripts imported by Unity |
| M1 | 🔄 in progress | Placeholder AR end-to-end on device, four tracks sample-synced — **blocked on Unity MCP scene assembly (Session C1)** |
| M2 | ✅ done | Real tree assets — `root_graph.json` + `branch_graph.json` produced ✅; roots FBX imported ✅ (branches used for geometry/audio extraction only, no Unity model needed) |
| M3 | ⬜ | Audio complete: four final tracks, all pose mappings, outdoor mix tuning |
| M4 | ⬜ | Interaction + polish: raycast, particles, root fade, HUD, reset |
| M5 | ⬜ | Instrumentation + hardening: SessionLogger CSV, 20-min soak |
| M6 | ⬜ | Field readiness: IRB, TestFlight live, 3 pilot sessions |

### What's done on `main`

| Area | State |
|---|---|
| Repo scaffold, `.gitignore`, `.gitattributes`, Git LFS | ✅ |
| `validate_assets.py` — all checks, PASS with 2 TODOs | ✅ |
| `tools/skeletonize.py` — mesh → `root_graph.json` (SPEC §6.4) | ✅ |
| `tools/graph_builder.py` — Blender-native skeleton extraction | ✅ |
| `data/root_graph.json` + `data/branch_graph.json` | ✅ |
| 19 C# scripts across Core / Audio / Placement / Graph / Interaction / UI | ✅ |
| 4 ScriptableObject config classes (no magic numbers) | ✅ |
| Unity project open, packages installed, scripts imported (.meta files present) | ✅ |
| Unity scene assembled (Session C1) | ❌ pending |
| `data/audio_manifest.json` | ❌ pending |
| Roots FBX (`AquiFuturo_RootA`) imported into Unity | ✅ |
| Audio tracks (4 × WAV, 48 kHz stereo, identical length) | ❌ pending |
| `tools/render_latent_audio.py` — RAVE offline decode driver | ❌ pending |
| TestFlight placeholder build submitted | ❌ pending |

See SPEC.md §17 for full acceptance criteria per milestone.

---

## Key conventions

- **Coordinate system:** 1 unit = 1 metre. Tree origin at trunk base, ground level. `y > 0` = trunk/branches, `y < 0` = roots.
- **Audio:** Four looping stereo tracks, 2D (`spatialBlend = 0`), sample-synced via `PlayScheduled()`. Modulation via LPF cutoff (logarithmic Hz), stereo pan, and volume — driven by pose axes relative to the placed tree (SPEC §9.3). No 3D spatialisation.
- **No magic numbers:** every tunable lives in a ScriptableObject config.
- **No `GameObject.Find`:** all wiring is through the Inspector or Bootstrap component.

Full conventions in SPEC.md §2 and CLAUDE.md.
