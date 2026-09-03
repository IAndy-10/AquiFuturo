# Changelog

All notable changes to AquiFuturo AR are recorded here.
Format: `<type>: <description>` — one line per milestone entry.

---

## Unreleased

- fix: smooth 2 s fade-out on test audio clip to eliminate end-of-clip click
- fix: instruction panel grammar — all three steps rewritten for clarity
- feat: interactionGainDb in InteractionSettingsConfig — zone one-shot level control (default −12 dB)
- feat: masterGainDb in AudioSettingsConfig — global soundtrack trim offset applied in TrackMixer
- docs: visual-finalupdate.md — Blender mesh spec, URP shader plan, option panel and tap sparks future features
- docs: update SPEC §2.2 §4 §5 §6.5 §7 §10 §14 §15 Appendix C — replace stale per-node interaction (RootInteraction, InteractionAudioPool, hit_<nodeclass>) with zone-based system; update track names to five-track set; fix bootstrap hierarchy and session wiring notes
- feat: zone-based interaction — 4 Box Collider zones (G1–G4) replace node-class RootInteraction; ZoneTrigger + ZoneInteraction scripts; RAVE zone clips (rave_zone1–4.wav) triggered on tap; pan driven by screen X
- feat: 5-track audio system — track_voice, track_canopy, track_river, track_birds1, track_birds2 replace old 4-track set; track_river is static bed (no modulation); all tracks 48 kHz stereo 120 s phase-locked
- fix: 20 ms raised-cosine fade-in/out on all looping tracks eliminates loop-point click
- fix: ZoneTrigger uses RequireComponent(AudioSource) — clip visible in Inspector; removes runtime-created AudioSource child
- fix: ZoneInteraction _startImmediatelyForTesting bypass for testing without AR placement flow
- docs: update SPEC §5.2–§5.4 §8 §9 §10 — 5-track manifest, FBX model requirements, manual placement, zone interaction
- docs: update README, STATUS — M1–M3 done, M4 in progress on feat/polish-and-ui
- feat: strike_tour excitation — replace broken tour_sweep (Gaussian envelope, quasi-static DC, ~110 dB below target band) with broadband click strike train; tree_to_wav.py gains --mode-tilt, --listen-sum abs, --highpass, --normalize rms
- feat: branch_synth.py — per-branch-class modal synthesis (trunk_base 20–120 Hz → terminal 1500–8000 Hz), per-class RMS levelling, A-weighted audibility report, --save-parts; all five classes audible in v4 renders
- feat: RAVE pipeline — pca_rave.py (TSP tour → PCA latent → WAV), split_roots.py (4-zone skeleton split), per-zone root_graph_g1–g4.json; data layout restructured to data/raw/ + data/processed/
- feat: physical modelling — tree_to_wav.py (modal mass-spring synthesis from branch_graph.json), simplify_graph.py (RDP 3D branch simplification 267→175 nodes); 6 × 120s WAV renders in physical-modelling/
- docs: M1 complete — placeholder AR placement, four test tracks sample-synced, LPF + pan responding to phone movement confirmed on device
- docs: update M2 status — roots FBX only in Unity; branch_graph.json used for geometry/audio extraction only, no Unity model needed; M2 complete
- docs: clarify Unity workflow — C# scripts managed by Claude Code, scene assembly done manually in Unity Editor (no Unity MCP)
- fix: spatial hash coordinate mismatch — RootGraphLoader stores hash in graph space, NearestNodeTo() back-projects world hit point via InverseTransformPoint; RootInteraction calls NearestNodeTo() instead of SpatialHash.NearestTo()
- refactor: gut RootMeshBuilder — remove procedural tube mesh; collision now on FBX MeshCollider; RootMeshBuilder only rebuilds spatial hash in world space
- feat: Unity FBX import — AquiFuturo_RootA/Trunk FBX assets, URP pipeline, ARLightEstimation (ambient + directional), TestScene for scale validation, scenes relocated to Assets/Scenes/
- feat: per-track modulation — TrackChannel gains IsStatic/LpfSensitivity/PanWidth; drone static, three tracks modulated independently; fix tilt mapping sign
- fix: M1 audio silence — add startImmediatelyForTesting flag to AudioSettingsConfig + TrackMixer; fix PoseAnalyzer null-config LPF fail-open
- feat: add tools/skeletonize.py — first iteration of mesh-to-root_graph.json pipeline (SPEC §6.4 / §5.1); Polyscope --viz flag; initial root_graph.json and branch_graph.json outputs
- chore: M0 — repo structure, CLAUDE.md, .gitignore, .gitattributes, docs stubs, validate_assets.py
- feat: blender-native skeleton extraction via MCP — boundary-ring method for skel_roots_main (545 nodes, 543 edges), geodesic shell + KDTree clustering for skel_branches (267 nodes, 266 edges); both placed in Skeletons collection
- feat: export Blender skeleton objects to assets_src/skel_roots_skeleton.json and assets_src/skel_branches_skeleton.json with Unity Y-up coordinates and KDTree radius estimation; no intermediate PLY files
- feat: graph_builder.py — pure stdlib + numpy replacement for skeletonize.py graph-analysis path; reads Blender-exported skeleton JSON, computes Strahler order, depth/branch orders, TSP 2-opt tour, node classification, writes SPEC §5.1 root_graph.json and branch_graph.json
- feat: validate branch_graph.json alongside root_graph.json in validate_assets.py
