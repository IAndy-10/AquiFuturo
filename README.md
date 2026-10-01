# AquiFuturo

Augmented reality experience that sonifies tree morphology — translating a Coast Live Oak's canopy and root structure into spatial sound through physical modeling and neural audio synthesis.

**[Project page](https://www.italorojas-portfolio.cl/projects/aquifuturo)**

MAT M.S. thesis project — UC Santa Barbara, 2026.

---

## Concept

Visitors approach a Coast Live Oak, point their phone near the trunk, and tap to place a virtual underground root system in AR. A five-track soundscape responds to how the user moves and where they touch, revealing the tree's hidden morphology through sound.

The root system is displayed alone — no above-ground tree model. Interaction is physical: orientation, tilt, distance, and touch drive the mix in real time.

---

## Sonification

### Canopy — Modal synthesis

The branch skeleton (267 nodes) is treated as a mass-spring network with per-class stiffness multipliers, stratifying the spectrum across five structural classes — from trunk base (20–120 Hz) to terminal tips (1,500–8,000 Hz). 96 natural frequencies are extracted via eigenvalue decomposition and rendered into audio.

### Roots — Neural audio synthesis (RAVE)

8 morphological features per node are mapped into a 16-dimensional latent space via PCA. A RAVE decoder trained on water sounds generates audio from smooth TSP tour trajectories through that space, producing one clip per spatial root zone.

### Mixing layer

Five looping stereo tracks play phase-locked via `PlayScheduled()`. Four are modulated by phone pose — attention drives a logarithmic low-pass filter sweep, azimuth controls stereo pan, tilt shifts layer balance, and distance scales gain. The fifth track (`track_river`) is a static field-recording bed. Tapping on root zone colliders triggers the RAVE-generated interaction clips.

---

## Tech stack

| Layer | Technology |
|---|---|
| Platform | iOS — Unity 6 LTS, AR Foundation 6, ARKit |
| Audio engine | Unity AudioSource + AudioLowPassFilter (no 3D spatialisation) |
| Skeleton extraction | Python 3.11, Blender 5.2 LTS |
| Modal synthesis | Python — mass-spring eigenvalue decomposition |
| Neural synthesis | RAVE (16-dim latent), PCA manifold alignment |
| Asset validation | Python CLI (`validate_assets.py`) |

---

## Repository layout

```
aquifuturo-ar/
├── SPEC.md                  # technical specification
├── CLAUDE.md                # Claude Code working agreement
├── CHANGELOG.md
├── tools/                   # Python CLI tools
│   ├── graph_builder.py     # Blender-native skeleton → root_graph.json
│   ├── split_roots.py       # skeleton → 4 spatial zone skeletons
│   ├── tree_to_wav.py       # modal synthesis from branch_graph.json
│   ├── branch_synth.py      # per-class modal synthesis
│   ├── pca_rave.py          # TSP tour → PCA latent → WAV (RAVE pipeline)
│   ├── audio_manifest.json  # track + interaction clip registry
│   ├── validate_assets.py   # CI asset validator
│   └── requirements.txt
├── data/
│   ├── processed/
│   │   ├── skeleton/        # root_graph.json, branch_graph.json, zone graphs
│   │   └── audio/           # 5 looping tracks + 4 RAVE zone clips (48 kHz stereo)
│   └── raw/
├── assets_src/              # source meshes and audio (Git LFS)
└── unity/
    └── Assets/
        ├── Art/Models/      # root system FBX models
        ├── Audio/           # tracks + interaction clips
        ├── Prefabs/
        └── Scripts/         # C# — Core, Placement, Graph, Audio, Interaction, UI
```

---

## License

See thesis document for terms.
