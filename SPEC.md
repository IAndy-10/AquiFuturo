
# AquiFuturo — AR Root System Prototype (MVP)
### Master Build Specification · v1.1

**Author:** Italo
**Context:** MAT M.S. thesis (AquiFuturo), UC Santa Barbara
**Date:** August 2026
**Status:** Authoritative build guide. Supersedes the original short spec.

---

## 0. How to use this document

This document is the single source of truth for the prototype. It is written to be consumed by three different executors, and each section is tagged accordingly:

| Tag | Executor | What it does |
|---|---|---|
| `[CC]` | **Claude Code** (desktop) | Creates repo, folders, C# scripts, Python asset tools, configs, docs. Never touches `.unity` scene files or binary assets. |
| `[BL]` | **Blender MCP session** | Point cloud cleanup, retopology, root mesh generation, skeleton extraction, GLB export. |
| `[UN]` | **Unity MCP session** | Scene assembly, prefab creation, component wiring, build settings, XR config. |
| `[ME]` | **You, manually** | Photogrammetry capture, audio production, Xcode signing, TestFlight, field testing. |

**Rule of separation:** Claude Code writes *code and data contracts*. MCP sessions assemble *scenes and assets against those contracts*. If a step requires both, the contract is written first (by `[CC]`), then satisfied (by `[BL]`/`[UN]`).

Read §2 (Conventions) and §5 (Data Contracts) before starting any executor session. Those two sections are what keep the three workstreams from diverging.

---

## 1. Project overview

### 1.1 What this is

An iOS Augmented Reality application that reveals the underground root system of a real tree, accompanied by a multi-layer soundscape that responds to how the user moves the phone and where they touch the roots. The user stands at a real tree, places a virtual twin, sees roots that would normally be invisible, and shapes the mix through orientation, distance and touch.

This is a **research prototype** built for evaluation by ~20 participants using their own iPhones and headphones, outdoors. It is not a production application.

### 1.2 Relationship to the AquiFuturo thesis

The thesis system centres on an unsupervised cross-domain manifold alignment: root skeleton graph topology is mapped onto a RAVE latent space without paired training data, and traversals of the root graph (k-NN / Delaunay neighbourhoods, TSP/VRP-derived paths) become traversals of the latent space, producing sound.

**This MVP performs no runtime neural inference.** One of the four audio tracks — the "root voice" — is produced *offline* by the thesis pipeline:

```
root skeleton graph  →  graph traversal (TSP tour)  →  latent trajectory
                                                            ↓
                                                   RAVE decode (offline, desktop)
                                                            ↓
                                                    root_rave.wav  →  Unity
```

The remaining tracks are conventionally designed or recorded. The AR app is the *interaction and mixing layer* over that stem. Real-time on-device inference is deferred (§3.3) but the architecture must not preclude it.


### 1.3 Design intent

Contemplative, not game-like. The user is listening to a tree, not playing one. No score, no timers, no win state. The interaction vocabulary is: look, walk, tilt, touch and hear.

---

## 2. Conventions `[CC]` `[BL]` `[UN]`

These are non-negotiable and apply across every executor. Violations here are the most common source of silent breakage.

### 2.1 Units and coordinate system

- **Unit:** 1 Blender/Unity unit = 1 metre. No exceptions, no scaling at import.
- **Blender:** Z-up, Y-forward (native). Export via glTF 2.0 with `+Y up` conversion enabled so Unity receives Y-up.
- **Unity:** Y-up, left-handed. After glTF import the tree must appear upright with no rotation correction on the root transform. If a `-90°` X rotation is needed on import, the export was wrong — fix the export, not the Unity transform.
- **Origin:** The tree model's origin is at the **base of the trunk, at ground level**. Trunk and branches occupy `y > 0`. Roots occupy `y < 0`. This is the ground plane the AR placement raycast will land on.
- **Scale reference:** Real target tree height is recorded during capture (§6.1) and the model is scaled to match in Blender, not in Unity.

### 2.2 Naming

- Files and folders: `PascalCase` for Unity assets, `snake_case` for Python and data files.
- GLB: single `tree_full.glb` with named children `Trunk`, `Branches`, `Roots`.
- Audio tracks: `track_<name>.wav` (`track_root_rave.wav`, `track_soil.wav`, `track_canopy.wav`, `track_drone.wav`).
- Interaction one-shots: `hit_<nodeclass>_<nn>.wav`.
- Unity layers: `RootMesh` (dedicated layer, used for raycast filtering — do **not** raycast against Default).
- Unity tags: `TreeRoot`, `RootNode`.

### 2.3 Versioning

Semantic versioning on the app: `0.MINOR.PATCH` until field test. Build number increments on every TestFlight upload. Asset versions are tracked by the `schema_version` field in `root_graph.json` (§5.1) — Unity refuses to load a graph whose version it does not recognise.

### 2.4 Target software versions

| Tool | Version | Note |
|---|---|---|
| Unity | 6 LTS (6000.0.x) | Fallback: 2022.3 LTS if AR Foundation 6 causes friction |
| AR Foundation | 6.x | Must match Unity major |
| ARKit XR Plugin | matching AR Foundation | |
| Blender | 4.x | |
| Xcode | latest supporting the target iOS | iOS 16.0 minimum deployment |
| Python | 3.11 | For asset tooling and RAVE rendering |

**No third-party audio middleware.** The audio layer uses stock Unity `AudioSource` + `AudioLowPassFilter` + `AudioMixer` only. This is a deliberate v1.1 decision (§9.6).

Lock these versions on day one and record them in `README.md`. Prevent version drift between the Unity MCP session and your local editor.

---

## 3. Scope

### 3.1 In scope (MVP)

- AR plane detection and manual tree placement with rotation and scale adjustment
- Anchored virtual tree with underground root mesh
- **Four-track flat audio mix**, sample-synced, looping continuously
- Device-pose-driven modulation: low-pass filter, stereo pan, layer balance, distance gain (§9.3)
- Touch interaction on roots triggering one-shot samples and particles
- Session telemetry logging for evaluation (§12)
- Fully offline, local execution

### 3.2 Out of scope (MVP)

Networking · multiplayer · cloud sync · **runtime AI inference** · **3D/HRTF spatialised audio** · GPS localisation · image/marker recognition · persistent cross-session world anchors · user accounts · Vision Pro / Quest builds.

### 3.3 Deferred, but architecturally reserved

These are *not built* but the code must not make them impossible. Each gets a clearly marked seam:

| Deferred feature | Reserved seam |
|---|---|
| Runtime RAVE inference | `ITrackSource` interface — clip-backed implementation now, streaming implementation later |
| 3D spatialised emitters | `root_graph.json` carries an `emitters` array, unused in MVP but populated |
| Multi-playhead VRP traversal | `root_graph.json` carries precomputed tours (§5.1) |
| Root growth animation | Graph nodes carry `depth_order` for progressive reveal |
| LiDAR occlusion | `AROcclusionManager` present but auto-disabled on non-LiDAR devices |
| Multiple trees | `TreeInstance` is a prefab; `GameManager` holds a list, not a singleton |

---

## 4. System architecture

```
┌─────────────── OFFLINE (desktop) ───────────────┐
│                                                  │
│  Photos ──► PostShot ──► Gaussian Splat ──► Blender │
│                                            │     │
│                                   ┌────────┴───┐ │
│                              tree mesh    root mesh
│                                   │            │ │
│                                   │-->  skeletonization
│                                          (Python, iter 03)
│                                               │ │
│                                         root_graph.json
│                                               │ │
│                                         TSP traversal ──► latent trajectory
│                                               │ │
│                                         RAVE decode (offline)
│                                               │ │
│                                        track_root_rave.wav
│                                               + │
│                                        3 designed tracks  [ME]
│                                               + │
│                                        interaction one-shots
│                                    ▼            ▼ │
│                              tree_full.glb  Audio/│
└──────────────────────┬───────────────────────────┘
                       │  (committed to repo, LFS)
┌──────────────────────▼───── RUNTIME (iOS) ───────┐
│                                                   │
│  ARSession ──► plane detect ──► TreePlacement     │
│                                      │            │
│                                 TreeInstance      │
│                                 ├─ meshes         │
│                                 ├─ RootGraph (parsed JSON, touch lookup only)
│                                 └─ RootInteraction (raycast → nearest node)
│                                       ├─ InteractionAudioPool
│                                       └─ ParticleSpawner
│                                                   │
│  PoseAnalyzer  ──► azimuth, alignment, tilt, distance
│        │                                          │
│        ▼                                          │
│  TrackMixer (4 × AudioSource, spatialBlend = 0)   │
│        ├─ per-track AudioLowPassFilter            │
│        ├─ per-track panStereo                     │
│        └─ per-track volume                        │
│                        │                          │
│                   AudioMixer (master) ──► output  │
│                                                   │
│  SessionLogger ──► CSV                            │
└───────────────────────────────────────────────────┘
```

**Key architectural point (v1.1):** the audio is *not* positioned in 3D space. It is a stereo mix. What makes it feel connected to the tree is that every modulation parameter is computed from the AR camera's pose **relative to the placed tree**. Placement still matters; the tree is the reference frame for the mix even though no sound is emitted from it.

---

## 5. Data contracts `[CC]`

Claude Code writes these schemas and the loaders/validators **first**, before any Unity or Blender work.

### 5.1 `root_graph.json`

Produced by the Blender/Python skeletonization pipeline (§6.4). Consumed by Unity for **touch-to-node resolution** and carried as a complete record of the thesis pipeline state.

```json
{
  "schema_version": "1.1",
  "tree_id": "sbcast_oak_01",
  "generated_utc": "2026-08-10T18:22:00Z",
  "source_mesh": "tree_full.glb",
  "units": "meters",
  "coordinate_space": "unity_y_up",
  "bounds": { "min": [-2.4, -1.8, -2.1], "max": [2.2, 0.0, 2.3] },
  "nodes": [
    {
      "id": 0,
      "position": [0.0, 0.0, 0.0],
      "radius": 0.18,
      "depth_order": 0,
      "branch_order": 0,
      "is_terminal": false,
      "class": "trunk_base"
    }
  ],
  "edges": [
    { "source": 0, "target": 1, "length": 0.34 }
  ],
  "emitters": [],
  "tours": [
    {
      "name": "tsp_primary",
      "method": "tsp_2opt",
      "node_sequence": [0, 3, 7, 12, 19],
      "total_length": 14.2,
      "rendered_stem": "track_root_rave.wav"
    }
  ]
}
```

Field notes:
- `position` is **already in Unity space** (Y-up, metres, origin at trunk base). Conversion happens in the Python exporter, not at runtime.
- `class` ∈ `{trunk_base, primary, lateral, fine, terminal}` — selects which interaction one-shot fires on touch.
- `emitters` is **empty in the MVP** (reserved for a future 3D-audio build). The validator warns but does not fail on an empty array.
- `tours[].rendered_stem` records which audio file was produced from which traversal. This is the provenance link between the graph and the sound, and it is the single most important field for the thesis write-up.

### 5.2 `audio_manifest.json`

```json
{
  "schema_version": "1.1",
  "loop_length_seconds": 120.0,
  "tracks": [
    {
      "id": "root_rave",
      "file": "track_root_rave.wav",
      "role": "root_voice",
      "base_gain_db": -4.0,
      "tilt_bias": -1.0,
      "provenance": "rave_decode:tsp_primary"
    },
    {
      "id": "soil",
      "file": "track_soil.wav",
      "role": "texture",
      "base_gain_db": -8.0,
      "tilt_bias": -0.5,
      "provenance": "field_recording"
    },
    {
      "id": "canopy",
      "file": "track_canopy.wav",
      "role": "texture",
      "base_gain_db": -10.0,
      "tilt_bias": 1.0,
      "provenance": "field_recording"
    },
    {
      "id": "drone",
      "file": "track_drone.wav",
      "role": "bed",
      "base_gain_db": -12.0,
      "tilt_bias": 0.0,
      "provenance": "designed"
    }
  ],
  "interaction": [
    { "file": "hit_lateral_01.wav", "node_class": "lateral", "pitch_var_semitones": 2.0 }
  ]
}
```

`tilt_bias` ∈ [−1, 1] places each track on the vertical axis: −1 = fully underground, +1 = fully canopy, 0 = always present. See §9.3.

**All four tracks must be exactly `loop_length_seconds` long.** The validator enforces this to the sample.

### 5.3 GLB requirements

- Single file `tree_full.glb` with top-level children named exactly `Trunk`, `Branches`, `Roots`.
- Triangles only. No n-gons.
- Budget: ≤ 60k tris total (§13).
- Materials: one per child, unlit or simple lit, no textures required for MVP (vertex colour acceptable).
- No animations, cameras, or lights in the GLB.
- `Roots` must be manifold with no zero-area faces (mesh collider requirement).

### 5.4 Validator `[CC]`

`tools/validate_assets.py` — checks GLB structure; node/edge referential integrity in `root_graph.json`; that every manifest file exists in `Assets/Audio/`; that all node positions fall inside `bounds`; that all four tracks are 48 kHz and **identical in sample length**; that every `node.class` present in the graph has at least one matching interaction sample. Run in CI (§14.4) and before every Unity import.

---

## 6. Asset pipeline

### 6.1 Capture `[ME]`

- I collected 96 pictures of the tree making a continuous shots to cover the core of the tree. I followed a radiuse around the tree aproximately about 5 m. I used an Iphone 11.

### 6.2 PostShot `[ME]`

Using PostShot I create a Gaussian splatting scenario, that was exported as 'tree-model.psht' file.

### 6.3 Blender: mesh preparation `[BL]`

See Appendix B for the full MCP session brief. Outcome:
- `Trunk` and `Branches`: retopologised from the point cloud, decimated to budget, scaled to real measurements, origin at trunk base.
- `Roots`: generated (roots are underground and cannot be photogrammetred). MVP approach: mirror-and-perturb the branch structure downward, or a space-colonisation script. Roots must be plausible, not accurate.

### 6.4 Skeletonization `[CC]` + `[BL]`

Your existing skeletonization pipeline (iteration 03) is adapted as a CLI:

```bash
python tools/skeletonize.py \
  --mesh assets_src/roots.obj \
  --out data/root_graph.json \
  --knn 6 --tour tsp_2opt \
  --coordinate-space unity_y_up
```

Responsibilities: mesh → point sample → skeleton → graph (k-NN and/or Delaunay) → prune → node classification → TSP tour → JSON emit conforming to §5.1.

Note that in v1.1 the graph has **two consumers**: the offline latent traversal (which produces `track_root_rave.wav`) and the runtime touch lookup (which selects one-shots by node class). Emitter selection is no longer needed.

### 6.5 Audio production `[ME]`

This is now conventional multitrack production, with one generated element.

**Track 1 — `track_root_rave.wav` (the root voice).**
Take the TSP tour from `root_graph.json`, map it to a latent trajectory, decode offline with RAVE at the full `loop_length_seconds`. A **closed** TSP tour returns to its starting node, which means the latent trajectory returns to its starting point, which means the audio loops seamlessly with no crossfade. This is a genuinely elegant property and worth a paragraph in the thesis — use a closed tour for this reason.

**Tracks 2–4 — `soil`, `canopy`, `drone`.**
Designed or recorded conventionally in your DAW. Mix them *against* the RAVE track, not independently — the RAVE stem is the lead voice and the others are context.

**Production requirements:**
- All four tracks: exactly the same length, 48 kHz, 24-bit WAV, **stereo**.
- Bounce from the same DAW session start so they are phase-coherent when summed.
- Seamless loop: verify by looping in the DAW for 5 minutes with no audible seam.
- Loop length: 90–180 s. Shorter loops become obvious within a 10-minute session.
- **Leave headroom for filtering.** The runtime LPF closes to 800 Hz; if a track's identity lives entirely above 2 kHz it will simply vanish rather than transform. Give each track meaningful low-mid content.
- Normalise the summed mix to −16 LUFS integrated with ≥ 6 dB true-peak headroom. Outdoor headphone listening will lose quiet material, but do not compress the life out of it.

**Interaction one-shots:** 3–5 variants per node class, 0.3–3 s, 48 kHz, **mono** (they are pooled and pitch-shifted; mono keeps the pool cheap). Short decodes from latent points near nodes of that class are a natural source, but hand-designed samples are acceptable.

### 6.6 Export `[BL]`

glTF 2.0 binary (`.glb`), `+Y up`, apply modifiers, selected objects only, no cameras/lights, compression off.

Deliverables land in `unity/Assets/Art/Models/` and `unity/Assets/Audio/` via Git LFS.

---

## 7. Application state machine `[CC]`

`GameManager` owns an explicit state machine. Every state has a defined entry condition, exit condition, and UI.

| State | Entry | UI | Exit |
|---|---|---|---|
| `Booting` | app launch | logo | AR session ready |
| `Scanning` | session ready | "Move your phone slowly to scan the ground" + plane visualisation | ≥1 plane ≥ 1 m² detected **OR** 20 s timeout → `PlacingFallback` |
| `Placing` | planes found | "Tap at the base of the trunk" + reticle | user taps valid plane point |
| `PlacingFallback` | scan timeout | "Point at the tree base and tap" + reticle at fixed 2 m forward ray | user taps |
| `Adjusting` | tree instantiated | rotate (one-finger drag) / scale (pinch) / "Confirm" button | confirm pressed |
| `Experiencing` | placement confirmed | no HUD except a small "Reset" affordance | user presses Reset → `Placing`, or app backgrounded |
| `Ended` | session end button held 2 s | thank-you + log flush | — |

Audio behaviour across states: the four tracks begin playing (sample-synced) on entry to `Adjusting`, at reduced gain and with the LPF closed, so the mix "arrives" as the user confirms placement. They never stop until `Ended`. Transitions are logged (§12).

The fallback path exists because **outdoor plane detection on soil, grass and leaf litter is unreliable in bright sun** — this is the single most likely cause of a failed field session and the original spec had no mitigation for it.

---

## 8. Placement and anchoring `[CC]` `[UN]`

### 8.1 Placement

1. `ARRaycastManager` raycast from screen tap against `PlaneWithinPolygon`.
2. On hit: instantiate `TreeInstance` prefab at hit pose, yaw-aligned to camera.
3. **Attach an `ARAnchor`** to the instantiated object (`ARAnchorManager.AttachAnchor` on the hit plane). Do not simply set a world transform — an un-anchored object drifts as the user walks a full orbit.
4. Fallback path: place at `camera.position + camera.forward * 2.0m`, projected to `y = camera.y - 1.4m` (assumed eye height), then let the user adjust with a two-finger vertical drag.

### 8.2 Adjustment

- One-finger horizontal drag → yaw rotation.
- Pinch → uniform scale, clamped to `[0.5, 2.0]` of authored scale.
- Two-finger vertical drag → distance along camera forward (fallback path only).
- Confirm → freeze transform, disable manipulators, hide plane visualisation, transition to `Experiencing`.

### 8.3 Drift handling

- Log `ARSession` tracking state every second.
- If tracking is lost > 3 s: close the LPF fully and drop the mix to −24 dB over 1 s, show "Move back toward the tree". Restore on recovery. Because the audio is 2D it will not appear to come from the wrong place — but the *modulation* becomes meaningless, so muting the response is still correct.
- Expose "Reset placement" at all times.

### 8.4 Occlusion and the underground read

- Add `AROcclusionManager`; enable environment depth **only if** the device reports support (LiDAR). Most participants' phones will not have it.
- The roots sit below the real ground and AR will not occlude them — they will appear to float over the grass. Rather than fight this, **make it intentional:** a shader on the `Roots` material fading opacity from 1.0 at the deepest node to ~0.25 near `y = 0`, plus a subtle dark radial "excavation" quad at `y = 0.01`. This reads as *looking into* the ground.
- **This carries more weight in v1.1.** With flat stereo audio there is no HRTF elevation cue, so the perception that roots are *below* the user rests on the visuals and on the tilt-driven filtering (§9.3, axis 3). Validate this specifically in the pilot sessions; if participants report the roots reading as floating, strengthen the fade shader and the tilt mapping before the main study rather than adding spatialisation back.

---

## 9. Audio system `[CC]` `[UN]`

### 9.1 Model

Four continuously looping stereo tracks, played as **2D sources** (`spatialBlend = 0`), summed to a master mixer group. There are no positional audio sources in the scene. Expression comes entirely from per-track modulation of filter, pan and gain, driven by the phone's pose relative to the placed tree.

One GameObject per track under `Bootstrap/TrackMixer/`:

```
TrackMixer
├── Track_RootRave   [AudioSource (2D), AudioLowPassFilter]
├── Track_Soil       [AudioSource (2D), AudioLowPassFilter]
├── Track_Canopy     [AudioSource (2D), AudioLowPassFilter]
└── Track_Drone      [AudioSource (2D), AudioLowPassFilter]
```

All four route to AudioMixer group `Master`. Per-track control is done on the components (`volume`, `panStereo`, `cutoffFrequency`), not through exposed mixer parameters — simpler, no snapshot management, and avoids the mixer's lack of a native pan effect.

### 9.2 Sample-synchronised start `[CC]`

The tracks must stay phase-locked for the whole session, or the mix relationships you designed in the DAW will not survive. Do not call `Play()` four times in a loop.

```csharp
double startTime = AudioSettings.dspTime + 0.2;
foreach (var t in tracks) t.Source.PlayScheduled(startTime);
```

Set `loop = true` on all four. Unity's looping AudioSources do not drift relative to each other once scheduled from a common `dspTime`. Verify with a 10-minute soak test (§17 M5): if the mix smears audibly by the end, re-schedule all four on a common loop boundary.

### 9.3 Pose axes and modulation mapping

`PoseAnalyzer` computes four scalars per frame from the AR camera pose and the placed tree transform. All are smoothed with `SmoothDamp` before use.

| Axis | Computation | Range | Smooth time |
|---|---|---|---|
| `azimuth` | signed angle in XZ from camera forward to (treeBase − cameraPos), positive = tree is to the right | −180°…180° | 0.20 s |
| `alignment` | `dot(cameraForward, normalize(rootCentroid − cameraPos))` | −1…1 | 0.35 s |
| `tilt` | `cameraForward.y` (−1 = looking straight down, +1 = straight up) | −1…1 | 0.30 s |
| `distance` | horizontal distance from camera to tree base | 0…∞ m | 0.50 s |

**Mapping 1 — Attention → low-pass cutoff (all tracks).**

```
attention = saturate(inverseLerp(0.2, 0.85, alignment))
cutoff    = 800 * pow(20000/800, attention)      // logarithmic in Hz
```

Cutoff interpolation **must be logarithmic in frequency**. Linear interpolation of Hz sounds like nothing happens for the first 80% of the range — this is the most common way this effect gets implemented badly. `lowpassResonanceQ = 1.0`; do not add resonance, it draws attention to the filter itself.

| `attention` | cutoff |
|---|---|
| 0.0 (looking away) | 800 Hz |
| 0.5 | ~4 kHz |
| 1.0 (looking at the tree) | 20 kHz |

**Mapping 2 — Azimuth → stereo pan (all tracks).**

```
pan = sin(azimuth)      // azimuth in radians, positive = tree to the right
```

Tree directly ahead or directly behind → centre. Tree at 90° right → hard right. The sine form handles the front/back ambiguity gracefully, because when the tree is behind you `attention` has already closed the filter and the mix has receded.

Apply a per-track pan width multiplier so the layers do not all swing together: `root_rave` × 1.0, `soil` × 0.7, `canopy` × 0.85, `drone` × 0.25 (the bed stays near centre and anchors the image).

**Mapping 3 — Tilt → vertical layer balance.** This is the axis that carries the "underground" perception in v1.1.

```
trackGain_dB = base_gain_db + 6 * (tilt_bias * -tilt)
```

Looking down (`tilt` = −1) lifts tracks with negative `tilt_bias` (root_rave, soil) by up to +6 dB and attenuates the canopy by the same. Looking up inverts it. `drone` (`tilt_bias` = 0) is unaffected. Clamp the total per-track gain to [−24, 0] dB.

**Mapping 4 — Distance → master gain and a second filter stage.**

| Distance | Master gain | Additional cutoff ceiling |
|---|---|---|
| ≤ 1.5 m | 0 dB | none |
| 4 m | −5 dB | 8 kHz |
| ≥ 8 m | −14 dB | 3 kHz |

Implemented as a multiplicative ceiling on the Mapping-1 cutoff, so walking away dulls the mix even when the user is looking directly at the tree. This rewards approaching the tree, which is the behaviour you want during a field session.

### 9.4 Interaction layer

Independent of the four tracks and unaffected by Mappings 1–4. Pooled one-shot `AudioSource`s (pool size 12), 2D, panned to match the touch point's azimuth relative to the camera so touches feel located even without spatialisation. Random pitch within `pitch_var_semitones`. Free overlap, max 6 concurrent, steal oldest.

### 9.5 Unity audio settings `[UN]`

- DSP buffer: "Best latency" (256 samples) → interaction latency budget (§13).
- Sample rate: 48 kHz.
- Max real voices: 24. Virtual: 64.
- Spatialiser plugin: **None**.
- iOS audio session category: `AVAudioSessionCategoryPlayback`, so audio survives the ringer switch. **Test this** — a participant with the silent switch on hearing nothing is a wasted session.
- Import settings: four tracks → Streaming, Compressed in Memory not required, **Force to Mono OFF**, Preload OFF, Load in Background ON. Interaction one-shots → Decompress on Load, Preload ON.

### 9.6 Why no spatialiser (design rationale)

Recorded here as an ADR summary so the decision is not relitigated mid-build. 3D/HRTF spatialisation was specified in v1.0 and removed in v1.1 because: it added a third-party plugin and an iOS build risk on a compressed schedule; it required mono stems, which conflicts with producing the piece in a DAW as a stereo mix; and per-emitter processing multiplied CPU cost. The cost is the loss of an elevation cue for the underground read, which is mitigated visually (§8.4) and through the tilt mapping (§9.3, Mapping 3). State this tradeoff explicitly in the thesis limitations section.

---

## 10. Interaction `[CC]`

1. On `TouchPhase.Began`, raycast from screen point against layer `RootMesh` only, max distance 10 m.
2. On hit, find the nearest graph node to the hit point using a prebuilt spatial hash (built once at load, cell size 0.25 m). Do not linear-scan the node list per touch.
3. Fire:
   - One-shot matching `node.class`, random variant, random pitch, panned by touch azimuth (§9.4).
   - Particle burst at the hit point, normal-aligned.
   - Log the event (§12).
4. Debounce: ignore a second hit on the same node within 120 ms.
5. Touch does not modify the four-track mix in the MVP. (Reserved: touched nodes could bias a runtime traversal in a future build.)

---

## 11. Particles `[UN]`

One `ParticleSystem` prefab, pooled (8 instances).

- 12–20 particles per burst, world simulation space
- Lifetime 0.6–1.2 s, size 0.01–0.03 m
- Upward drift 0.15 m/s, slight turbulence
- Additive material, warm off-white, alpha fade over lifetime
- No collision, no physics, no sub-emitters

Restraint is the design goal. Sparks should read as something surfacing from the soil, not as a game effect.

---

## 12. Evaluation instrumentation `[CC]`

The original spec had measurable success criteria but no measurement. Since this feeds a thesis chapter, add a `SessionLogger`.

Writes CSV to `Application.persistentDataPath/sessions/<session_id>.csv`, flushed every 5 s and on pause:

```
timestamp_ms, event, payload
0,      session_start,   {"device":"iPhone14,2","ios":"18.2","build":"0.4.1"}
4210,   state_change,    {"from":"Scanning","to":"Placing"}
9840,   placement_done,  {"attempts":2,"elapsed_ms":9840,"fallback":false}
12030,  pose,            {"az":34.2,"align":0.81,"tilt":-0.43,"dist":2.1}   // 2 Hz
15220,  root_touch,      {"node_id":37,"class":"lateral","dist_m":0.9}
...
```

The `pose` event at 2 Hz is the most valuable record you will collect: it lets you reconstruct, per participant, how much of the four-axis modulation space they actually explored. Plot tilt-vs-azimuth coverage per participant in the thesis — that is direct evidence about whether the mapping was discoverable.

Also logged: tracking loss, FPS every 10 s, reset presses, total duration.

**Human subjects:** confirm UCSB IRB status before running the 20-participant study. Even for an exempt-category study, "we log interaction telemetry" needs to appear on the consent form. Build a one-page consent + debrief questionnaire (Appendix D) early — approval lead time is a schedule risk, not a formality.

No PII. No audio or video recording. No network transmission — logs exported via share sheet or pulled over USB.

---

## 13. Performance budgets

| Metric | Target | Hard limit |
|---|---|---|
| Frame rate | 60 FPS | ≥ 45 FPS sustained |
| Cold start to camera | < 5 s | 10 s |
| Placement to first audio | < 1 s | 2 s |
| Touch → sound onset | < 60 ms | 100 ms |
| Total triangles | 60k | 100k |
| Concurrent audio voices | 10 | 24 |
| Memory | < 350 MB | 600 MB |
| Battery | ≥ 25 min continuous | 15 min |

Four streamed stereo tracks plus four low-pass filters is a small audio load — well under 3% CPU on an A14. The v1.1 audio simplification buys back roughly the headroom that HRTF processing would have consumed; spend it on frame rate stability rather than on adding tracks.

Measure with Unity Profiler over USB and Xcode Instruments on the oldest device you expect a participant to bring. Set the floor at iPhone 12 / A14 and state it in the recruitment blurb. AR passthrough is thermally significant; expect throttling after ~15 min outdoors in sun, so design sessions for ≤ 10 minutes.

---

## 14. Repository `[CC]`

### 14.1 Structure

```
aquifuturo-ar/
├── README.md
├── CLAUDE.md                    # Claude Code session brief (Appendix A)
├── SPEC.md                      # this document
├── CHANGELOG.md
├── .gitignore                   # Unity + Python + macOS
├── .gitattributes               # Git LFS rules
├── docs/
│   ├── blender_session.md       # Appendix B
│   ├── unity_session.md         # Appendix C
│   ├── field_protocol.md        # Appendix D
│   └── decisions/               # ADRs, one file per significant choice
├── tools/
│   ├── skeletonize.py
│   ├── validate_assets.py
│   ├── render_latent_audio.py   # RAVE decode driver (offline)
│   └── requirements.txt
├── data/
│   ├── root_graph.json
│   └── audio_manifest.json
├── assets_src/                  # LFS: raw capture, .blend, .ply, DAW session — not shipped
└── unity/
    └── Assets/
        ├── Art/{Models,Materials,Particles}/
        ├── Audio/{Tracks,Interaction}/
        ├── Data/                # StreamingAssets copies of data/*.json
        ├── Prefabs/
        ├── Scenes/
        ├── Scripts/
        │   ├── Core/            # GameManager, AppState, SessionLogger
        │   ├── Placement/       # TreePlacement, PlacementReticle, TreeAdjuster
        │   ├── Graph/           # RootGraph, RootGraphLoader, SpatialHash
        │   ├── Audio/           # TrackMixer, PoseAnalyzer, TrackChannel,
        │   │                    # InteractionAudioPool, ITrackSource
        │   ├── Interaction/     # RootInteraction, ParticleSpawner
        │   └── UI/              # HudController
        ├── Settings/            # ScriptableObject configs
        └── XR/
```

### 14.2 Git LFS `[CC]`

`.gitattributes`:
```
*.glb   filter=lfs diff=lfs merge=lfs -text
*.wav   filter=lfs diff=lfs merge=lfs -text
*.blend filter=lfs diff=lfs merge=lfs -text
*.ply   filter=lfs diff=lfs merge=lfs -text
*.fbx   filter=lfs diff=lfs merge=lfs -text
*.png   filter=lfs diff=lfs merge=lfs -text
```
Run `git lfs install` before the first asset commit. Four 120-second 24-bit stereo WAVs are ~70 MB — plain Git will handle that badly and the point clouds worse. Committing them without LFS is unrecoverable without a history rewrite.

Also enable Unity's **Force Text** serialisation and **Visible Meta Files** so scene diffs are legible.

### 14.3 Branching

`main` (always buildable) ← `dev` ← `feat/<short-name>`. Tag each field-test build `v0.x.y-field`. Keep it this simple; you are the only committer.

### 14.4 CI

GitHub Actions: on push, run `python tools/validate_assets.py` and `ruff` on `tools/`. Do not attempt Unity Cloud Build for the MVP — licence and signing complexity is not worth it at this scale.

---

## 15. Configuration objects `[CC]`

Claude Code cannot wire Inspector fields. Therefore **all tunable values live in ScriptableObjects**, created once in the Unity MCP session and referenced by a single bootstrapper.

- `AudioSettingsConfig` — cutoff min/max, smooth times per axis, pan width per track, tilt gain range, distance curve, master gain curve, pool size
- `PlacementSettingsConfig` — scan timeout, scale clamps, fallback distance, drift thresholds
- `InteractionSettingsConfig` — debounce ms, max voices, raycast distance, spatial hash cell size
- `DebugSettingsConfig` — logging verbosity, on-screen readout of the four pose axes, gizmos for graph nodes

The on-screen pose readout in `DebugSettingsConfig` is not optional for you — you cannot tune four simultaneous mappings by ear in the field without seeing the raw values. Build it in M3.

**No magic numbers in code.** Field tuning must not require a recompile.

---

## 16. Build and distribution `[ME]`

1. Unity → Build Settings → iOS. Development build off for field builds, on for profiling builds.
2. Player Settings: camera usage description ("Used to display the tree's root system in your environment"), microphone off, minimum iOS 16.0, ARM64, Metal.
3. Xcode: signing team, bundle ID `edu.ucsb.mat.aquifuturo`.
4. **TestFlight, not ad-hoc.** External TestFlight testing requires Apple beta app review, which can take **1–3 days for the first submission**. Submit a placeholder build at Milestone M1 so review is cleared before you need it. This is the highest-variance item on the schedule and it is entirely front-loadable.
5. Participants install TestFlight and the build ahead of the session; do not spend field time on installation.

---

## 17. Milestones and acceptance criteria

Roughly a 5-week plan with a hard scope-cut ladder.

| ID | Milestone | Owner | Acceptance |
|---|---|---|---|
| **M0** | Repo + contracts | `[CC]` | Repo created, LFS configured, schemas + validator written, `CLAUDE.md` and MCP briefs in `docs/`, validator passes on synthetic fixtures |
| **M1** | Placeholder end-to-end | `[CC]`+`[UN]` | Placeholder cylinder "tree" placeable in AR on device, anchored, four placeholder tracks playing sample-synced with working LPF and pan. **Nothing real, everything connected.** Placeholder TestFlight build submitted (§16.4) |
| **M2** | Real assets | `[BL]`+`[ME]` | `tree_full.glb` under budget, correct scale and orientation, `root_graph.json` validating, imports with no transform correction |
| **M3** | Audio complete | `[ME]`+`[CC]`+`[UN]` | Four final tracks bounced and validated; all four pose mappings implemented; debug readout on screen; mix tuned on headphones outdoors, not at a desk |
| **M4** | Interaction + polish | `[CC]`+`[UN]` | Raycast→node resolution correct, particles, root fade shader, HUD, reset flow, tracking-loss handling |
| **M5** | Instrumentation + hardening | `[CC]` | SessionLogger writing valid CSV including 2 Hz pose samples; performance targets met on floor device; 20-min soak with no crash, drift, or audible loop desync |
| **M6** | Field readiness | `[ME]` | IRB confirmed, consent + questionnaire printed, TestFlight build live, 3 pilot sessions with non-expert users, protocol revised |

**Scope-cut ladder** — if time compresses, drop in this order: distance→cutoff stage (Mapping 4) → per-track pan widths (all tracks pan together) → root fade shader → particle polish → reduce from 4 tracks to 3 (drop `drone`) → multi-variant interaction samples. Do **not** cut: anchoring, the fallback placement path, the tilt mapping, the logger, or the pilot sessions.

The tilt mapping is on the do-not-cut list because after removing spatialisation it is the only *audio* cue that the roots are below you.

---

## 18. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Outdoor plane detection fails | **High** | High | Fallback placement path (§7, §8.1) — build at M1, not later |
| TestFlight review delay | Medium | High | Submit placeholder build at M1 |
| ARKit drift over a full orbit | High | Medium | ARAnchor + drift detection + mix duck + reset affordance (§8.3) |
| Roots read as floating, not underground | **High** | High (perceptual claim) | Fade shader + excavation quad + tilt mapping; validate in pilot. Higher likelihood in v1.1 than v1.0 — no HRTF elevation cue |
| Four mappings are not discoverable by participants | Medium | Medium | Pilot sessions; if unnoticed, increase mapping depth rather than adding explanation to the HUD |
| Tracks drift out of sync over a long session | Low | Medium | `PlayScheduled` from common dspTime; 10-min soak test at M5 |
| Participants' phones too old / no headphones | Medium | Medium | State device floor in recruitment; bring 2 spare wired headphones + 1 loaner phone |
| Wind / traffic masks quiet material | High | Medium | Loudness normalisation, over-ear loaners, sheltered site, morning sessions |
| Point cloud too noisy for a usable mesh | Medium | Medium | MVP tolerates a stylised trunk; roots are synthetic anyway |
| IRB not in place | Medium | **Blocking** | Confirm in week 1 |

---

## 19. Open decisions

Resolve before M2 and record each as an ADR in `docs/decisions/`:

1. **Which tree?** A specific, accessible, named tree. Everything downstream depends on it.
2. **Root generation method** — mirrored branch structure vs. space colonisation vs. hand-modelled.
3. **Loop length** — 90 s vs. 120 s vs. 180 s. Longer is less repetitive but a larger RAVE render and a larger binary.
4. **Closed vs. open TSP tour** for the RAVE render. Recommend closed, for seamless looping (§6.5).
5. **Session length** for participants — recommend 8–10 minutes given thermal limits.
6. **Does the app ship a second tree?** Default: no.

*(Resolved in v1.1: spatialiser — none, see §9.6.)*

---

# Appendix A — Claude Code session brief `[CC]`

Save as `CLAUDE.md` at the repo root.

```markdown
# AquiFuturo AR — Claude Code working agreement

## Project
Unity 6 LTS + AR Foundation 6 iOS AR prototype. Read SPEC.md before any task.
Conventions in SPEC.md §2 and data contracts in §5 are binding.

## Audio model (read this before touching anything in Scripts/Audio)
Four looping STEREO tracks played as 2D AudioSources (spatialBlend = 0).
No 3D audio. No spatialiser plugin. No positional emitters.
Expression comes from per-track modulation of AudioLowPassFilter.cutoffFrequency,
AudioSource.panStereo and AudioSource.volume, driven by four pose axes
computed relative to the placed tree (SPEC.md §9.3).
All four tracks start via PlayScheduled() from a single shared dspTime.

## What you own
- All C# under unity/Assets/Scripts/
- All Python under tools/
- ScriptableObject class definitions (not the .asset instances)
- .gitignore, .gitattributes, README, CHANGELOG, docs/, GitHub Actions
- Editor scripts under Assets/Editor/ for validation and import checks

## What you must NOT do
- Do not edit .unity scene files or .prefab files. Scene assembly happens in the
  Unity MCP session. If a task needs scene changes, write the code plus a short
  "Unity wiring required" note listing exactly what to wire.
- Do not create or modify binary assets (.glb, .wav, .blend, .png).
- Do not add third-party packages without asking. Especially not audio middleware.
- Do not reintroduce 3D spatialisation. It was removed deliberately (SPEC.md §9.6).
- Do not commit to main. Work on feat/* branches.

## Code standards
- C#: namespace AquiFuturo.<Area>. One public type per file. XML doc on public members.
- No magic numbers — every tunable lives in a ScriptableObject config (SPEC.md §15).
- No allocations in Update(). Cache component references in Awake().
- Filter cutoff interpolation is LOGARITHMIC in Hz (SPEC.md §9.3). Never linear.
- Guard all AR Foundation subsystem access with null/support checks.
- A single Bootstrap component finds or creates its dependencies at runtime so
  Inspector wiring stays minimal.
- Python: type hints, argparse CLIs, no notebook-style scripts.

## Definition of done
1. Compiles with no warnings.
2. Any new tunable is in a config ScriptableObject.
3. tools/validate_assets.py still passes.
4. One-line entry added to CHANGELOG.md.
5. Unity wiring requirements, if any, listed explicitly.

## Order of work
Follow SPEC.md §17. Do not start M3 audio tuning before M1 places a placeholder
object in AR on a real device with four placeholder tracks audibly responding to
phone movement.
```

---

# Appendix B — Blender MCP session brief `[BL]`

Paste at the start of the Blender MCP session. Keep the session narrow: one asset, one outcome.

```markdown
# Blender MCP session — AquiFuturo tree asset

## Objective
Produce unity/Assets/Art/Models/tree_full.glb containing exactly three named
children: Trunk, Branches, Roots. Plus assets_src/roots.obj for skeletonization.

## Hard constraints (SPEC.md §2, §5.3)
- Scene unit scale 1.0, unit system Metric, 1 unit = 1 metre.
- Object origin at the base of the trunk, at ground level: world (0,0,0).
- Trunk and Branches occupy Z > 0 (Blender). Roots occupy Z < 0.
- Triangles only. Total <= 60,000 tris.
- One material per object. No textures required. No animations, cameras, lights.
- Roots must be manifold with no zero-area faces (Unity mesh collider requirement).

## Working rules
1. Work on ONE object at a time. After each operation report vertex/tri count,
   bounding box, and world origin. Do not batch five operations and report at
   the end — I need to catch drift early.
2. Never delete or replace an object without telling me first.
3. Never apply a modifier to the original — duplicate, apply on the copy, keep
   the original in a collection named SRC (excluded from export).
4. Do not re-import the point cloud if a mesh already exists; ask.
5. Save incrementally: tree_v01.blend, tree_v02.blend. Never overwrite.

## Steps
1. Import point cloud from assets_src/pointclouds/<file>.ply.
2. Report bounds. I will give you the real trunk height; scale uniformly to match.
3. Retopologise / remesh trunk and branches. Decimate to budget. Report counts.
4. Set origin to trunk base, then move the object so the origin is at world (0,0,0).
5. Generate root structure below Z=0 (method TBD — SPEC §19.2). Roots extend
   roughly 1.5x canopy radius laterally and 1.5–2.5 m deep.
6. Name objects exactly: Trunk, Branches, Roots.
7. Export Roots alone as assets_src/roots.obj (for skeletonization).
8. Export all three as GLB:
   - Format: glTF Binary (.glb)
   - Include: Selected Objects only
   - Transform: +Y Up   <-- critical, do not skip
   - Geometry: Apply Modifiers ON, UVs optional, Normals ON
   - Compression: OFF
   - Animation: OFF
   Output: unity/Assets/Art/Models/tree_full.glb

## Acceptance check before ending the session
- [ ] Three objects, correctly named
- [ ] Total tris <= 60k (report the number)
- [ ] Origin verified at world (0,0,0), trunk base
- [ ] Roots bounding box max Z ~ 0, min Z ~ -2
- [ ] GLB exported with +Y Up
- [ ] roots.obj exported
- [ ] .blend saved with an incremented version number
```

---

# Appendix C — Unity MCP session brief `[UN]`

Run **after** Claude Code has committed the scripts for the milestone. Split across at least three sessions rather than one long one — long Unity MCP sessions drift badly.

```markdown
# Unity MCP session — AquiFuturo AR

## Preconditions
- Scripts for the current milestone exist and compile.
- Read SPEC.md §7–§11 and §15 for the components involved.

## Working rules
1. NEVER create a new scene. Work in Assets/Scenes/Main.unity only.
2. After every GameObject creation or component add, report the resulting
   hierarchy path and its components. I verify before you continue.
3. Do not modify any C# file. If something needs a code change, stop and tell me;
   it goes to Claude Code.
4. Do not install packages beyond SPEC.md §2.4 without asking.
   In particular: DO NOT install any audio spatialiser plugin.
5. Save the scene after each completed sub-step.
6. If a serialised reference cannot be resolved, leave it null and report it.
   Do not invent a substitute object.

## Session C1 — Scene skeleton
Target hierarchy:

Main.unity
├── AR Session
├── XR Origin
│   └── Camera Offset
│       └── Main Camera        [ARCameraManager, ARCameraBackground,
│                                AROcclusionManager (auto-disable if unsupported),
│                                AudioListener]
├── AR Managers               [ARPlaneManager, ARRaycastManager, ARAnchorManager]
├── Bootstrap                 [GameManager, SessionLogger, HudController,
│                               PoseAnalyzer]
│   └── TrackMixer            [TrackMixer]
│       ├── Track_RootRave    [AudioSource, AudioLowPassFilter]
│       ├── Track_Soil        [AudioSource, AudioLowPassFilter]
│       ├── Track_Canopy      [AudioSource, AudioLowPassFilter]
│       └── Track_Drone       [AudioSource, AudioLowPassFilter]
├── InteractionAudioPool      [InteractionAudioPool]
├── Placement                 [TreePlacement, PlacementReticle, TreeAdjuster]
└── UI Canvas (Screen Space - Overlay)
    ├── ScanPrompt
    ├── PlacePrompt
    ├── ConfirmButton
    ├── ResetButton
    └── DebugReadout          (four pose axes, toggled by DebugSettings)

Also:
- Create layer `RootMesh` (index 8) and tags `TreeRoot`, `RootNode`.
- Create ScriptableObject instances in Assets/Settings/: AudioSettings.asset,
  PlacementSettings.asset, InteractionSettings.asset, DebugSettings.asset.
  Populate from SPEC.md §9.3, §10, §13.
- Wire config references on Bootstrap components.
- Project Settings: Force Text serialisation, Visible Meta Files.
- Player Settings: iOS, ARM64, Metal, min iOS 16.0, camera usage description.

## Session C2 — Tree prefab and audio
- Create prefab Assets/Prefabs/TreeInstance.prefab from tree_full.glb:
  - Roots child -> layer RootMesh, add MeshCollider (convex OFF), tag TreeRoot
  - Trunk / Branches -> no collider
- Verify import: NO rotation correction on the prefab root transform. If the
  model is lying on its side, STOP — the GLB export was wrong (SPEC §2.1).
- Audio Project Settings: 48 kHz, Best latency, 24 real / 64 virtual voices,
  Spatializer Plugin = None.
- For each of the four Track_* objects:
  - AudioSource: assign clip, loop ON, playOnAwake OFF, spatialBlend 0,
    output = Master mixer group, priority 0
  - AudioLowPassFilter: cutoff 800, resonance Q 1.0
  - Import settings on the clip: Streaming, Force to Mono OFF, Preload OFF,
    Load in Background ON
- Interaction clips: Decompress on Load, Preload ON, mono.
- Assign the four track references and their manifest ids on TrackMixer.

## Session C3 — Interaction and polish
- Create Assets/Prefabs/RootSpark.prefab per SPEC.md §11.
- Wire RootInteraction raycast layer mask to RootMesh only.
- Create the root fade material/shader per SPEC.md §8.4 and the excavation quad.
- Configure InteractionAudioPool size and assign the one-shot clips by class.
- Build Settings: add Main.unity, switch platform to iOS, build to Xcode project.

## Acceptance check per session
- [ ] Scene saved and hierarchy matches the target
- [ ] No null serialised references except those explicitly reported
- [ ] Project compiles, no console errors on Play
- [ ] In Play mode, all four tracks audible and starting together
- [ ] git status shows only expected files changed
```

---

# Appendix D — Field protocol `[ME]`

**Before the day:** IRB confirmation; consent forms printed; TestFlight build live and installed by participants in advance; site chosen (sheltered, low traffic noise, morning light); 2 spare wired headphones; 1 loaner iPhone; power bank; tape measure; printed one-page instructions.

**Per session (~20 min total):**
1. Consent form, verbal summary, questions. (3 min)
2. Headphone fit, volume calibration against a reference tone. (2 min)
3. Hand over the phone and read the standard prompt verbatim: *"Point the camera at the tree, tap where the trunk meets the ground, and then explore however you like. Take as long as you want."* No further coaching unless the participant is stuck for > 60 s. **Do not mention that sound responds to movement** — whether they discover it is a result. (1 min)
4. Free exploration, 8–10 min. Observer takes timestamped notes; do not intervene.
5. Semi-structured interview, 5 min.

**Questionnaire targets** (map onto §20):
- Did the roots seem to be *under* the ground, or floating above it?
- Did you notice the sound changing? What did you think caused it?
- Did you notice anything change when you looked down versus up?
- Did moving closer or further away change anything?
- Did touching feel like it did something?
- What did the tree sound like it was doing?

Log which participants used the fallback placement path — that number is a result, not just a bug metric. Same for how many discovered the tilt mapping unprompted.

---

## 20. Success criteria

The prototype succeeds if a first-time user can, without assistance:

| Criterion | Measurement |
|---|---|
| Place the tree in under one minute | `placement_done.elapsed_ms` < 60,000 |
| Clearly perceive the root system as underground | Questionnaire item 1, ≥ 70% report "under" |
| Notice that sound responds to their movement | Questionnaire item 2, unprompted mention |
| Discover at least one specific mapping | Questionnaire items 3–4; ≥ 50% correctly identify orientation, tilt, or distance |
| Trigger sounds and particles by touch | ≥ 5 `root_touch` events logged |
| Complete the experience unassisted | Observer note, no intervention |
| Explore the modulation space | `pose` log shows ≥ 120° azimuth range and ≥ 0.8 tilt range |

Target: ≥ 16 of 20 participants meet the first six.

---

*End of specification. Amendments go in `docs/decisions/` as ADRs; do not edit this document in place once M1 starts.*
