# AquiFuturo AR — Project Status

**Date:** 2026-08-05
**Branch:** `main` (clean)
**Spec version:** v1.1

---

## Milestone summary

| ID | Milestone | Status | Blocker |
|---|---|---|---|
| M0 | Repo + contracts | done | — |
| M1 | Placeholder AR end-to-end on device | blocked | Unity MCP scene assembly (Session C1) not done; no audio tracks yet |
| M2 | Real tree assets | partial | `tree_full.glb` pending Blender session |
| M3 | Audio complete | not started | depends on M1 + M2 |
| M4 | Interaction + polish | not started | depends on M3 |
| M5 | Instrumentation + hardening | not started | depends on M4 |
| M6 | Field readiness | not started | depends on M5 + IRB |

---

## M0 — Repo + contracts (done)

| Item | State |
|---|---|
| Repo scaffold, `.gitignore`, `.gitattributes`, Git LFS | done |
| `SPEC.md` v1.1, `CLAUDE.md`, `CHANGELOG.md` | done |
| `docs/blender_session.md`, `docs/unity_session.md`, `docs/field_protocol.md` | done |
| `docs/decisions/` directory | done (empty — no ADRs written yet) |
| `tools/validate_assets.py` — schema, node/edge integrity, audio parity checks | done |
| `tools/skeletonize.py` — mesh-to-root_graph.json CLI (SPEC §6.4) | done |
| `tools/graph_builder.py` — Blender-native skeleton extraction (stdlib + numpy) | done |
| `tools/requirements.txt` | done |
| `data/root_graph.json` — 545 nodes, 543 edges, schema v1.1, Unity Y-up | done |
| `data/branch_graph.json` — 267 nodes, 266 edges, schema v1.1, Unity Y-up | done |
| 20 C# scripts across Core / Audio / Placement / Graph / Interaction / UI | done |
| 4 ScriptableObject config classes (`AudioSettingsConfig`, `PlacementSettingsConfig`, `InteractionSettingsConfig`, `DebugSettingsConfig`) | done |
| Unity project open, packages installed, scripts imported (.meta files present) | done |

---

## M1 — Placeholder end-to-end (blocked)

Acceptance: placeholder cylinder placeable in AR on device, anchored, four placeholder tracks playing sample-synced with working LPF and pan. TestFlight placeholder submitted.

| Item | State | Owner |
|---|---|---|
| Unity scene assembled (`Bootstrap`, `ARSession`, `TrackMixer` hierarchy, reticle) | **pending** | Unity MCP Session C1 |
| `TreeInstance` prefab wired (`GameManager`, `TreePlacement`, `TrackMixer`, `RootGraphLoader`) | **pending** | Unity MCP Session C1 |
| AR plane detection + tap-to-place + `ARAnchor` attach | **pending** | Unity MCP Session C1 |
| Four placeholder AudioClips imported and playing via `PlayScheduled()` | **pending** | Unity MCP Session C1 |
| LPF + pan responding to phone orientation (pose axes live) | **pending** | Unity MCP Session C1 |
| `data/audio_manifest.json` authored | **pending** | [CC] |
| TestFlight placeholder build submitted (Apple review cleared early) | **pending** | [ME] |

**Critical path note:** TestFlight first-submission review takes 1–3 days (SPEC §16.4). Submit a placeholder build as soon as M1 scene is assembled — do not wait for real assets.

---

## M2 — Real tree assets (partial)

| Item | State | Owner |
|---|---|---|
| `data/root_graph.json` (schema v1.1, Unity Y-up, TSP tour) | done | [CC]+[BL] |
| `data/branch_graph.json` (schema v1.1, Unity Y-up, TSP tour) | done | [CC]+[BL] |
| `unity/Assets/Art/Models/tree_full.glb` (`Trunk`, `Branches`, `Roots` children, ≤60k tris) | **pending** | Blender MCP session |
| GLB validated: correct Y-up orientation, no transform correction needed in Unity | **pending** | [BL]+[UN] |
| `unity/Assets/Audio/` — 4 tracks × 48 kHz stereo WAV, identical sample length | **pending** | [ME] |
| `tools/render_latent_audio.py` — RAVE offline decode driver | **pending** | [CC] |
| `track_root_rave.wav` decoded from TSP tour latent trajectory | **pending** | [ME] |

---

## M3 — Audio complete (not started)

Depends on: M1 (scene running on device), M2 (final tracks + GLB).

| Item | State |
|---|---|
| Four final tracks bounced, validated by `validate_assets.py` | pending |
| All four pose mappings implemented (attention→LPF, azimuth→pan, tilt→layer balance, distance→gain+cutoff ceiling) | pending |
| LPF interpolation confirmed logarithmic in Hz (SPEC §9.3) | pending |
| Per-track pan width multipliers applied (1.0 / 0.7 / 0.85 / 0.25) | pending |
| Debug pose readout on screen (`DebugSettingsConfig`) | pending |
| Tracking-loss muting (`ARSessionState` → `TrackMixer` −24 dB + LPF closed) | pending |
| Mix tuned on headphones outdoors | pending |

---

## M4 — Interaction + polish (not started)

Depends on: M3.

| Item | State |
|---|---|
| Touch raycast against `RootMesh` layer → nearest node via `SpatialHash` | pending |
| Interaction one-shot samples (3–5 variants per node class, 48 kHz mono) | pending |
| `InteractionAudioPool` (12 sources, max 6 concurrent, steal oldest) | pending |
| Particle burst at hit point, normal-aligned (`ParticleSpawner`) | pending |
| Root fade shader (opacity 1.0 at deepest node → 0.25 near y=0) | pending |
| HUD — scan prompt, reticle, confirm button, reset affordance | pending |
| Tracking-loss UI ("Move back toward the tree") | pending |
| `PlacingFallback` state (20 s scan timeout → fixed 2 m forward ray) | pending |
| Full state machine validated (`Booting`→`Scanning`→`Placing`→`Adjusting`→`Experiencing`→`Ended`) | pending |

---

## M5 — Instrumentation + hardening (not started)

Depends on: M4.

| Item | State |
|---|---|
| `SessionLogger` writing valid CSV (`session_start`, `state_change`, `placement_done`, 2 Hz `pose`, `root_touch`, FPS, tracking loss) | pending |
| CSV flush every 5 s and on pause | pending |
| IOException caught and logged to `Debug.LogError` (SPEC §12 / silent-failure rule) | pending |
| 20-minute soak test — no crash, no drift, no audible loop desync | pending |
| Performance targets met on floor device (iPhone 12 / A14): ≥45 FPS, <350 MB, ≥25 min battery | pending |

---

## M6 — Field readiness (not started)

Depends on: M5.

| Item | State |
|---|---|
| UCSB IRB confirmation (exempt category or full review) | pending |
| Consent form + debrief questionnaire (Appendix D) | pending |
| TestFlight live build with real assets | pending |
| 3 pilot sessions with non-expert users | pending |
| Protocol revised from pilot feedback | pending |

---

## Outstanding gaps (any milestone)

| Gap | SPEC ref | Priority |
|---|---|---|
| `data/audio_manifest.json` missing — validate_assets.py will warn | §5.2 | high — needed for M1 |
| `tools/render_latent_audio.py` not written — RAVE offline decode | §6.5 | high — needed for M2 audio |
| No ADRs written in `docs/decisions/` — spatialiser removal is the first one due | §9.6 | medium |
| `PlacementReticle` script not found in Scripts/ — may be a Unity-side prefab concern | §8.1 | medium — clarify before M1 scene assembly |
| `unity/Assets/Data/` (StreamingAssets copies of data/*.json) — needs Unity MCP wiring | §14.1 | medium — needed for `RootGraphLoader` at runtime |

---

## CI status

- `ruff check tools/` — not verified this session (run before any merge to dev)
- `python tools/validate_assets.py` — passes with 2 TODOs (audio tracks and GLB absent; validator warns, does not fail on missing optional assets)
- GitHub Actions workflow — present; runs validate_assets.py and ruff on push

---

## Key pending decisions

- **Loop length** — must be set before audio production begins. SPEC §5.2 suggests 90–180 s; target 120 s unless RAVE decode time is prohibitive.
- **Pilot device floor** — stated as iPhone 12 / A14 in SPEC §13. Confirm with participant recruitment criteria.
- **IRB timeline** — approval lead time is the highest-variance schedule risk. Start this process now (SPEC §12).
