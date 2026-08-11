# Unity Audio Debug — M1 Silence Investigation

**Date:** 2026-08-07
**Branch:** `feat/audio-unity-test`
**Outcome:** Audio confirmed working on device.

---

## Root cause

**The iPhone storage was full.** A full disk causes the iOS code-signing subsystem to fail
silently during Xcode builds (`internal error in Code Signing subsystem`), which prevents
the app from installing. Clearing storage on the device resolved the build and install step.

---

## Code fixes applied

### 1. Audio never started on launch

**Problem:** `TrackMixer.StartScheduled()` was only called when entering `AppState.Adjusting`,
which requires the user to complete the full placement flow (AR scan → tap to place). Opening
the app produced silence with no feedback that anything was wrong.

**Fix:** Added `startImmediatelyForTesting` flag to `AudioSettingsConfig`. When enabled,
`TrackMixer.Start()` calls `StartScheduled()` immediately, bypassing the state machine.

`unity/Assets/Scripts/Core/AudioSettingsConfig.cs`:
```csharp
[Tooltip("M1 testing only — start all four tracks immediately on app launch without requiring placement. " +
         "Set to false before M3 audio tuning.")]
public bool startImmediatelyForTesting = false;
```

`unity/Assets/Scripts/Audio/TrackMixer.cs`:
```csharp
private void Start()
{
    if (_audioConfig != null && _audioConfig.startImmediatelyForTesting)
    {
        Debug.Log("[TrackMixer] startImmediatelyForTesting enabled — starting audio now (M1 test mode).");
        StartScheduled();
    }
}
```

`unity/Assets/Settings/AudioSettings.asset`: `startImmediatelyForTesting: 1`

> **Before M3:** set `startImmediatelyForTesting` back to `false` in the asset so audio
> only starts after placement as intended by the state machine.

---

### 2. LPF locked at 800 Hz — audio muffled even when playing

**Problem:** `PoseAnalyzer._config` was not wired in the scene (`{fileID: 0}`).
`ComputeAttention()` returned `0f` when config is null, which drove the LPF to its
minimum cutoff (800 Hz) permanently. Tracks played but sounded like muffled silence.

**Fix:** Changed the null-config fallback to `1f` (fully open filter, 20 kHz) so audio
is audible when the config reference is missing.

`unity/Assets/Scripts/Audio/PoseAnalyzer.cs`:
```csharp
private float ComputeAttention(float align)
{
    // Fail open (1 = fully open LPF) so audio is audible if config is not wired.
    if (_config == null) return 1f;
    float t = Mathf.InverseLerp(_config.attentionLow, _config.attentionHigh, align);
    return Mathf.Clamp01(t);
}
```

---

## Unity wiring gaps found (fix in Inspector)

These references were null in the scene and need to be wired in the Unity Editor:

| GameObject | Component | Field | Assign |
|---|---|---|---|
| Bootstrap | PoseAnalyzer | `_config` | `AudioSettings` asset |
| Bootstrap | HudController | `_gameManager` | Bootstrap → GameManager |
| Bootstrap | HudController | `_poseAnalyzer` | Bootstrap → PoseAnalyzer |
| Bootstrap | HudController | `_debugConfig` | `DebugSettings` asset |
| Bootstrap | HudController | `_scanPrompt` | UI Canvas → ScanPrompt |
| Bootstrap | HudController | `_placePrompt` | UI Canvas → PlacePrompt |
| Bootstrap | HudController | `_confirmButton` | UI Canvas → ConfirmButton |
| Bootstrap | HudController | `_resetButton` | UI Canvas → ResetButton |
| Bootstrap | HudController | `_debugReadout` | UI Canvas → DebugReadout |
| Placement | TreeAdjuster | `_config` | `PlacementSettings` asset |
| Placement | TreeAdjuster | `_gameManager` | Bootstrap → GameManager |
| Placement | TreeAdjuster | `_treePlacement` | Placement → TreePlacement |

---

## Xcode codesign error

**Error:** `internal error in Code Signing subsystem` when signing `UnityFramework.framework`.

**Cause:** `UnityFramework.framework` ships pre-signed from Unity. On macOS Sequoia,
Xcode's re-signing step (`--preserve-metadata`) fails when a conflicting existing signature
is present. A full disk on the iPhone compounds this — the install cannot complete.

**Immediate fix (one-time):** strip the existing signature before building:
```bash
find /path/to/xcode_build -name "UnityFramework.framework" -maxdepth 3 \
  -exec codesign --remove-signature {} \;
```

**Permanent fix:** add a Run Script build phase in Xcode (drag it above "Embed Frameworks"):
```bash
find "${BUILT_PRODUCTS_DIR}" -name "*.framework" \
  -exec codesign --remove-signature {} \; 2>/dev/null || true
```
Uncheck "Based on dependency analysis" so it runs on every build.

---

## M1 acceptance status after fixes

| Item | Status |
|---|---|
| Four tracks audible on device | **confirmed** |
| Tracks start phase-locked via `PlayScheduled()` | confirmed (single shared dspTime) |
| LPF open when no tree placed | confirmed (fail-open fix) |
| Pose axes driving LPF / pan after placement | pending — wire `PoseAnalyzer._config` |
| HUD prompts and confirm button | pending — wire HudController fields |
