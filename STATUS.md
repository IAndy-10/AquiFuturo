# AquiFuturo AR — Project Status

**Date:** 2026-08-23
**Branch:** `dev`
**Spec version:** v1.1

---

## Milestone summary

| ID | Milestone | Status | Blocker |
|---|---|---|---|
| M0 | Repo + contracts | ✅ done | — |
| M1 | Root system visible in AR on device, audio responding to pose | ✅ done | — |
| M2 | Real assets — FBX models, skeleton graphs, synthesis pipeline | ✅ done | — |
| M3 | Audio complete — 5 tracks, RAVE zones, pose mappings, interaction | ✅ done | — |
| M4 | Polish + UI — particles, fade shader, HUD, reset | 🔄 in progress | `feat/polish-and-ui` |
| M5 | Instrumentation + hardening — SessionLogger CSV, 20-min soak | not started | depends on M4 |
| M6 | Field readiness — IRB, TestFlight live, 3 pilot sessions | not started | depends on M5 + IRB |

---

## M0 — Repo + contracts (done)

| Item | State |
|---|---|
| Repo scaffold, `.gitignore`, `.gitattributes`, Git LFS | done |
| `SPEC.md` v1.1, `CLAUDE.md`, `CHANGELOG.md`, `STATUS.md` | done |
| `tools/validate_assets.py` — schema, node/edge integrity, audio parity checks | done |
| `tools/graph_builder.py` — Blender-native skeleton extraction (stdlib + numpy) | done |
| `tools/requirements.txt` | done |
| `data/processed/skeleton/root_graph.json` — 545 nodes, 543 edges, schema v1.1, Unity Y-up | done |
| `data/processed/skeleton/branch_graph.json` — 267 nodes, 266 edges, schema v1.1, Unity Y-up | done |
| C# scripts across Core / Audio / Placement / Graph / Interaction / UI | done |
| 4 ScriptableObject config classes (`AudioSettingsConfig`, `PlacementSettingsConfig`, `InteractionSettingsConfig`, `DebugSettingsConfig`) | done |
| Unity project open, packages installed, scripts imported (.meta files present) | done |

---

## M1 — Root system in AR, audio responding to pose (done)

| Item | State |
|---|---|
| Unity scene assembled (`Bootstrap`, `ARSession`, `TrackMixer`, zone colliders) | done |
| Root system FBX visible in AR on device | done |
| Root system displayed alone — no above-ground tree model visible | done |
| All 4 ScriptableObject config assets created and wired | done |
| Five looping tracks playing via `PlayScheduled()` from shared `dspTime` | done |
| LPF + pan + tilt + distance modulation responding to phone movement | done |
| `AquiFuturo_Tree_Terra.prefab` wired (TrackMixer, zones, ZoneInteraction) | done |
| `InteractionZone` layer added to TagManager | done |
| TestFlight build submitted | **pending** |

---

## M2 — Real assets (done)

Decision: no full-tree GLB. Only root FBX models are used at runtime. Branches FBX is for pipeline extraction only.

| Item | State |
|---|---|
| `data/processed/skeleton/root_graph.json` (schema v1.1, 545 nodes, Unity Y-up) | done |
| `data/processed/skeleton/branch_graph.json` (267 nodes, Unity Y-up) | done |
| Zone skeleton graphs `root_graph_g1–g4.json` (via `split_roots.py`) | done |
| `AquiFuturo_RootA.fbx` + `AquiFuturo_RootB.fbx` + `AquiFuturo_Trunk.fbx` imported | done |
| `tools/tree_to_wav.py` — modal mass-spring synthesis from branch_graph (`strike_tour` excitation) | done |
| `tools/branch_synth.py` — per-class modal synthesis, all 5 node classes audible | done |
| `tools/pca_rave.py` — TSP tour → PCA latent → RAVE zone WAVs | done |

---

## M3 — Audio complete (done)

| Item | State |
|---|---|
| Five final tracks (track_voice, track_canopy, track_river, track_birds1, track_birds2) | done |
| All tracks 48 kHz stereo, 120 s, identical sample length, phase-locked | done |
| 20 ms raised-cosine fade-in/out applied — loop click eliminated | done |
| `tools/audio_manifest.json` — 5-track + 4 zone interaction clip registry | done |
| `rave_zone1–4.wav` RAVE interaction clips in `Assets/Audio/Interaction/` | done |
| All four pose mappings implemented (attention→LPF, azimuth→pan, tilt→layer balance, distance→gain) | done |
| LPF interpolation logarithmic in Hz (SPEC §9.3) | done |
| Per-track `LpfSensitivity`, `PanWidth`, `TiltBias` configurable via Inspector | done |
| `track_river` static bed — no modulation, always centred | done |
| Zone tap interaction: Box Collider raycast → `ZoneTrigger.Play(pan)` → RAVE clip | done |
| Tracking-loss muting (`IsTrackingMuted` → `_muteGain` ramp in TrackMixer) | done |
| Outdoor mix tuning | pending — `feat/polish-and-ui` |

---

## M4 — Polish + UI (in progress — `feat/polish-and-ui`)

| Item | State |
|---|---|
| Zone-based tap interaction wired and confirmed producing audio | done |
| `ZoneInteraction` + `ZoneTrigger` scripts | done |
| `InteractionZone` layer + Box Colliders for zones G1–G4 | done |
| Particle visual feedback (`ParticleSpawner`) | pending — `feat/polish-and-ui` |
| Root fade shader (opacity 1.0 at deepest node → 0.25 near y=0) | pending |
| HUD — confirm button, reset affordance, tracking-loss UI | pending |
| Placement adjustment gestures (yaw drag, pinch scale) | pending |
| Full state machine validated on device end-to-end | pending |
| Outdoor mix tuning on headphones | pending |
| Validate `_startImmediatelyForTesting` disabled before field sessions | pending |

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
| `validate_assets.py` GLB check still references `tree_full.glb` (dropped asset) — remove in `feat/polish-and-ui` | §5.4 | low |
| `unity/Assets/StreamingAssets/root_graph.json` no longer needed at runtime (zone interaction replaced node-based) — remove in `feat/polish-and-ui` | §10 | low |
| `_startImmediatelyForTesting` must be disabled on both `TrackMixer` and `ZoneInteraction` before any field session | §9.2 | high — field session risk |
| TestFlight first build not yet submitted — start Apple review early (1–3 day lead time) | §16.4 | high |
| Outdoor mix tuning not done | §17 M3 | high — needed before M6 |

---

## CI status

- `ruff check tools/` — not verified this session (run before any merge to dev)
- `python tools/validate_assets.py` — passes with 2 TODOs (audio tracks and GLB absent; validator warns, does not fail on missing optional assets)
- GitHub Actions workflow — present; runs validate_assets.py and ruff on push

---

## Key pending decisions

- **Loop length** — set to 120 s. All five tracks confirmed at exactly 5,760,000 samples @ 48 kHz. ✅
- **Pilot device floor** — stated as iPhone 12 / A14 in SPEC §13. Confirm with participant recruitment criteria.
- **IRB timeline** — approval lead time is the highest-variance schedule risk. Start this process now (SPEC §12).
- **Placement UX** — manual positioning confirmed for MVP. AR plane detection deferred to `feat/polish-and-ui`.
