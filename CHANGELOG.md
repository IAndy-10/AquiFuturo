# Changelog

All notable changes to AquiFuturo AR are recorded here.
Format: `<type>: <description>` — one line per milestone entry.

---

## Unreleased

- docs: update M2 status — roots FBX only in Unity; branch_graph.json used for geometry/audio extraction only, no Unity model needed; M2 complete

- feat: Unity FBX import — AquiFuturo_RootA/Trunk FBX assets, URP pipeline, ARLightEstimation (ambient + directional), TestScene for scale validation, scenes relocated to Assets/Scenes/
- feat: per-track modulation — TrackChannel gains IsStatic/LpfSensitivity/PanWidth; drone static, three tracks modulated independently; fix tilt mapping sign
- fix: M1 audio silence — add startImmediatelyForTesting flag to AudioSettingsConfig + TrackMixer; fix PoseAnalyzer null-config LPF fail-open
- feat: add tools/skeletonize.py — first iteration of mesh-to-root_graph.json pipeline (SPEC §6.4 / §5.1); Polyscope --viz flag; initial root_graph.json and branch_graph.json outputs
- chore: M0 — repo structure, CLAUDE.md, .gitignore, .gitattributes, docs stubs, validate_assets.py
- feat: blender-native skeleton extraction via MCP — boundary-ring method for skel_roots_main (545 nodes, 543 edges), geodesic shell + KDTree clustering for skel_branches (267 nodes, 266 edges); both placed in Skeletons collection
- feat: export Blender skeleton objects to assets_src/skel_roots_skeleton.json and assets_src/skel_branches_skeleton.json with Unity Y-up coordinates and KDTree radius estimation; no intermediate PLY files
- feat: graph_builder.py — pure stdlib + numpy replacement for skeletonize.py graph-analysis path; reads Blender-exported skeleton JSON, computes Strahler order, depth/branch orders, TSP 2-opt tour, node classification, writes SPEC §5.1 root_graph.json and branch_graph.json
- feat: validate branch_graph.json alongside root_graph.json in validate_assets.py
