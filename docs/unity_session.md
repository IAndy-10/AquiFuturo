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
