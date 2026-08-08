# Audio Interaction Pipeline — AquiFuturo AR

How iPhone movement translates into real-time audio modulation.

---

## Overview

The app plays four looping stereo tracks simultaneously. As the user moves, rotates, or
tilts the iPhone, four spatial axes are computed relative to the placed tree. Those axes
drive three audio parameters per track — low-pass filter cutoff, stereo pan, and volume —
every single frame. The result is a mix that responds continuously and physically to where
the user is standing and where they are looking.

```
iPhone movement
      │
      ▼
PoseAnalyzer          — reads AR camera transform, outputs 4 smoothed axes
      │
      ▼
TrackMixer.Update()   — maps axes → LPF cutoff, pan, gain (4 mappings, every frame)
      │
      ├─▶ TrackChannel [root_rave]   SetCutoffHz / SetPan / volume
      ├─▶ TrackChannel [soil]        SetCutoffHz / SetPan / volume
      ├─▶ TrackChannel [canopy]      SetCutoffHz / SetPan / volume
      └─▶ TrackChannel [drone]       SetCutoffHz / SetPan / volume
```

All values come from `AudioSettingsConfig` (a ScriptableObject). No magic numbers
in any runtime method.

---

## Files

| File | Namespace | Role |
|---|---|---|
| `Scripts/Audio/PoseAnalyzer.cs` | `AquiFuturo.Audio` | Computes the 4 pose axes from AR camera |
| `Scripts/Audio/TrackMixer.cs` | `AquiFuturo.Audio` | Applies the 4 mappings every frame |
| `Scripts/Audio/TrackChannel.cs` | `AquiFuturo.Audio` | Wraps one AudioSource + AudioLowPassFilter |
| `Scripts/Audio/ITrackSource.cs` | `AquiFuturo.Audio` | Interface for clip vs. streaming audio (MVP uses clip) |
| `Scripts/Core/AudioSettingsConfig.cs` | `AquiFuturo.Core` | ScriptableObject — all tunable numbers |
| `Settings/AudioSettings.asset` | — | The live instance of AudioSettingsConfig in the project |

---

## Stage 1 — PoseAnalyzer

**File:** `Scripts/Audio/PoseAnalyzer.cs`

Runs in `Update()` every frame. Reads the AR camera's world transform (cached in `Awake()`
via `ARCameraManager`) and computes four raw floating-point axes relative to the placed
tree. Each raw value is then smoothed with `Mathf.SmoothDamp` before being read by
`TrackMixer`.

### The tree reference

```csharp
private Transform _treeBase;
```

Set by `TreePlacement` after the user places the cylinder:
```csharp
public void SetTreeBase(Transform treeBase)   // called by TreePlacement.InstantiateTree()
public void ClearTreeBase()                   // called on ResetPlacement()
```

Until `_treeBase` is set, `Azimuth`, `Alignment`, and `Distance` are all `0`. `Tilt`
is always computed because the camera pitch is meaningful even before placement.

---

### The 4 axes

#### Azimuth
```csharp
azimuth = Vector3.SignedAngle(camFwdXZ.normalized, toTreeXZ.normalized, Vector3.up);
```
Horizontal signed angle (degrees) from where the camera is pointing to where the tree is.
- `0°` = camera forward is aimed directly at the tree
- `+90°` = tree is 90° to the right
- `-90°` = tree is 90° to the left

Only the XZ plane is used — vertical component is ignored so tilting the phone
up/down doesn't rotate the pan.

#### Alignment
```csharp
alignment = Vector3.Dot(camForward, toTree.normalized);
```
Dot product of camera forward with the direction to the tree.
- `1.0` = camera pointed exactly at the tree
- `0.0` = camera pointed 90° away
- `-1.0` = camera pointed directly away

This is the primary axis for `Attention` (see below).

#### Tilt
```csharp
tilt = camForward.y;
```
The Y component of the camera's forward vector.
- `+1.0` = phone pointing straight up (looking at canopy)
- `0.0` = phone horizontal
- `-1.0` = phone pointing straight down (looking at underground roots)

This is always computed, even with no tree placed.

#### Distance
```csharp
distance = toTreeXZ.magnitude;
```
Horizontal distance in metres from camera to tree base. Vertical difference is excluded
so distance doesn't change when the user crouches or stands.

---

### Smoothing

Every axis is smoothed independently with `Mathf.SmoothDamp` using smooth-time values
from `AudioSettingsConfig`. Velocity references are stored as private fields — never
local variables — to avoid allocations and to preserve the damping state across frames.

```csharp
private float _azimuthVel;
private float _alignmentVel;
private float _tiltVel;
private float _distanceVel;
```

Default smooth times (all configurable in `AudioSettings.asset`):

| Axis | Smooth time | Why |
|---|---|---|
| Azimuth | 0.20 s | Panning should feel responsive |
| Alignment | 0.35 s | Attention should lag slightly to avoid flicker |
| Tilt | 0.30 s | Layer balance should feel gradual |
| Distance | 0.50 s | Distance changes slowly in practice |

---

### Attention

```csharp
public float Attention { get; private set; }
```

Derived from `Alignment` via `InverseLerp`:

```csharp
float t = Mathf.InverseLerp(_config.attentionLow, _config.attentionHigh, align);
return Mathf.Clamp01(t);
```

Default thresholds from `AudioSettings.asset`:
- `attentionLow = 0.2` — below this alignment value, attention = 0 (filter fully closed)
- `attentionHigh = 0.85` — at this alignment, attention = 1 (filter fully open)

`Attention` is the only axis `TrackMixer` uses for the LPF mapping — not `Alignment`
directly — because the LPF mapping is logarithmic and needs a clean `[0, 1]` input.

**Fail-open rule:** If `AudioSettingsConfig` is not wired in the Inspector, `Attention`
returns `1f` (fully open filter) so audio is always audible rather than silently muffled.

---

### Pose logging

At 2 Hz, `PoseAnalyzer` sends the smoothed axes to `SessionLogger` for the CSV log:
```csharp
SessionLogger.Instance?.LogPose(Azimuth, Alignment, Tilt, Distance);
```

This generates the `pose` rows in the session CSV used for thesis analysis.

---

## Stage 2 — TrackMixer

**File:** `Scripts/Audio/TrackMixer.cs`

Reads the 4 smoothed axes from `PoseAnalyzer` and applies them to all 4 `TrackChannel`
instances every frame via `ApplyModulation()`.

### Lifecycle

```csharp
private bool _started;
```

The `_started` flag gates everything. `Update()` is a no-op until `StartScheduled()` has
been called.

#### StartScheduled()
```csharp
public void StartScheduled()
{
    if (_started) return;
    double startTime = AudioSettings.dspTime + _audioConfig.scheduleMarginSeconds;
    foreach (var track in _tracks)
        track.Source.PlayScheduled(startTime);
    _started = true;
}
```

All four `AudioSource` instances are scheduled at the exact same DSP time — a single
shared moment in the audio thread clock. This guarantees phase-lock: the four tracks
always stay in perfect sample-accurate sync, even after minutes of playback.

`scheduleMarginSeconds = 0.2s` ensures the scheduled time is never in the past even if
the frame runs late. A past scheduled time causes Unity to silently drop the play call.

#### When does StartScheduled() get called?

Two paths:

1. **Normal flow** — `HandleStateChanged()` fires when `GameManager` transitions to
   `AppState.Adjusting` (immediately after the user taps to place the tree):
   ```csharp
   private void HandleStateChanged(AppState prev, AppState next)
   {
       if (next == AppState.Adjusting)
           StartScheduled();
   }
   ```

2. **M1 test bypass** — if `AudioSettingsConfig.startImmediatelyForTesting = true`,
   `Start()` calls `StartScheduled()` on the first frame, bypassing the placement flow:
   ```csharp
   private void Start()
   {
       if (_audioConfig != null && _audioConfig.startImmediatelyForTesting)
           StartScheduled();
   }
   ```
   This flag is currently `true` in `AudioSettings.asset` for on-device M1 testing.
   **Set it to `false` before M3 audio tuning.**

---

### ApplyModulation()

Called from `Update()` on every frame after `_started = true`. Reads the 4 axes and
applies all 4 mappings to every `TrackChannel`.

```csharp
private void ApplyModulation()
```

#### Mapping 1 — Attention → LPF cutoff (logarithmic)

```csharp
float cutoffHz = _audioConfig.cutoffMinHz *
    Mathf.Pow(_audioConfig.cutoffMaxHz / _audioConfig.cutoffMinHz, attention);
```

This is a **logarithmic** interpolation in Hz — never linear. The formula is:

```
cutoff = cutoffMin × (cutoffMax / cutoffMin) ^ attention
```

At `attention = 0`: `cutoff = 800 Hz` (muffled, no focus)
At `attention = 1`: `cutoff = 20000 Hz` (wide open, full detail)
At `attention = 0.5`: `cutoff = ~4000 Hz` (mid-point on a log scale, not linear average)

Linear interpolation would sound wrong — the human ear perceives pitch logarithmically, so
equal perceptual steps in brightness require exponential steps in Hz.

**Distance ceiling:** after computing the attention-based cutoff, it is capped by an
`AnimationCurve` evaluated at the current distance:
```csharp
float ceiling = _audioConfig.distanceCutoffCeiling.Evaluate(distance);
cutoffHz = Mathf.Min(cutoffHz, ceiling);
```

This means at `8m` distance, the filter can never open above `3000 Hz` regardless of
how directly the user faces the tree. The mix stays dark and distant.

The final `cutoffHz` is applied identically to all 4 tracks via `ch.SetCutoffHz(cutoffHz)`.

---

#### Mapping 2 — Azimuth → stereo pan

```csharp
float panBase = Mathf.Sin(azimuthRad);
```

The sine of the azimuth angle is used as the pan base (not the raw angle). Sine maps
naturally to the pan range `[-1, 1]` and gives a smooth, perceptually correct spatial
impression — the pan widens quickly near `0°` (centre) and saturates toward `±90°`.

Each track applies its own `PanWidth` stored directly on the `TrackChannel`:

```csharp
ch.SetPan(panBase * ch.PanWidth);
```

Pan widths per track (set in Inspector — see §Per-track modulation update):
| Track | PanWidth | Effect |
|---|---|---|
| root_rave | 1.00 | Full ±1 range — widest spatial movement |
| canopy | 0.85 | Wide but slightly constrained |
| soil | 0.65 | Moderate — stable, grounded feel |
| drone | static | Always centred — never panned |

The drone is always centred (static branch, no pan call). The three active tracks sweep
the stereo field at different widths as the user rotates around the tree.

---

#### Mapping 3 — Tilt → per-track vertical layer balance

```csharp
float tiltGainDb = _audioConfig.tiltGainRangeDb * (ch.TiltBias * tilt);
```

`camera.forward.y` is positive when pointing up. `TiltBias` encodes which vertical layer
each track belongs to:

| Track | TiltBias | Behaviour |
|---|---|---|
| root_rave | −1.0 | Louder when phone points down (underground) |
| soil | −0.5 | Moderately louder when pointing down |
| canopy | +1.0 | Louder when phone points up (canopy) |
| drone | 0.0 | Static — tilt formula never reached |

Example trace — phone pointing up (`tilt = +0.8`), canopy (`TiltBias = +1`):
```
tiltGainDb = 6 × (1 × 0.8) = +4.8 dB  ✓ canopy boosted
```
Phone pointing down (`tilt = −0.8`), root_rave (`TiltBias = −1`):
```
tiltGainDb = 6 × (−1 × −0.8) = +4.8 dB  ✓ root_rave boosted
```

`tiltGainRangeDb = 6` by default — maximum ±6 dB lift or cut from tilt.

---

#### Mapping 4 — Distance → master gain offset

```csharp
float distGainDb = _audioConfig.distanceGainDb.Evaluate(distance);
```

An `AnimationCurve` maps distance to a dB offset applied to every track equally:

| Distance | Gain offset |
|---|---|
| 0 m | 0 dB |
| 4 m | −5 dB |
| 8 m | −14 dB |

This is not a physics-based `1/r²` falloff — it is a tuned artistic curve. The mix
gradually recedes as the user walks away from the tree. Beyond 8 m it stays at −14 dB
(the curve's post-infinity is clamped).

---

#### Final gain computation per track

```csharp
float totalDb = ch.BaseGainDb + tiltGainDb + distGainDb;
totalDb = Mathf.Clamp(totalDb, _audioConfig.gainMinDb, _audioConfig.gainMaxDb);
float linearGain = Mathf.Pow(10f, totalDb / 20f) * _muteGain;
ch.Source.volume = linearGain;
```

1. Sum `BaseGainDb` (authored per track) + tilt offset + distance offset
2. Clamp to `[-24, 0]` dB
3. Convert dB to linear: `10^(dB/20)`
4. Multiply by `_muteGain` (tracking-loss ramp — see below)
5. Write directly to `AudioSource.volume`

Per-track base gains (set in Inspector on each `TrackChannel`):
| Track | BaseGainDb |
|---|---|
| root_rave | −4 dB |
| soil | (Inspector value) |
| canopy | (Inspector value) |
| drone | −12 dB |

---

### Tracking-loss mute ramp

```csharp
private float _muteGain = 1f;
private float _muteGainVel;
```

If AR tracking is lost for more than `trackingLossMuteSeconds = 3s` (from
`PlacementSettingsConfig`), `GameManager.IsTrackingMuted` becomes `true`. `TrackMixer`
smoothly ramps `_muteGain` from `1` to `0` over `trackingLossRampSeconds = 1s`:

```csharp
bool shouldMute = _gameManager != null && _gameManager.IsTrackingMuted;
_muteGain = Mathf.SmoothDamp(_muteGain, shouldMute ? 0f : 1f, ref _muteGainVel, rampTime);
```

The `_muteGain` multiplier is applied after the dB-to-linear conversion, so the fade
is perceptually smooth (linear gain applied to an already-linear signal).

When tracking recovers, `_muteGain` ramps back to `1` over the same ramp time.

---

## Stage 3 — TrackChannel

**File:** `Scripts/Audio/TrackChannel.cs`

One instance per track. Wraps a `MonoBehaviour` that `RequireComponent`s both
`AudioSource` and `AudioLowPassFilter`, caches both in `Awake()`, and exposes
two setters that `TrackMixer` calls every frame.

### Awake() — enforces 2D audio

```csharp
_source.spatialBlend  = 0f;   // 2D — no positional falloff
_source.loop          = true;
_source.playOnAwake   = false;
```

`spatialBlend = 0` is enforced in code — not just in the Inspector — because any
accidental change in the Unity Editor would silently break the mix. 3D spatialization
was deliberately removed from the project (SPEC §9.6).

### SetCutoffHz(float hz)
```csharp
_lpf.cutoffFrequency = hz;
```
Writes directly to the `AudioLowPassFilter` component. Unity applies the filter on the
audio thread. No allocation.

### SetPan(float pan)
```csharp
_source.panStereo = Mathf.Clamp(pan, -1f, 1f);
```
`panStereo` is Unity's 2D pan control. Clamped to `[-1, 1]` before writing to prevent
out-of-range values if azimuth math produces edge cases.

### Inspector fields

| Field | Purpose |
|---|---|
| `_trackId` | Must match the `id` field in `audio_manifest.json` |
| `_baseGainDb` | Per-track authored base gain in dB |
| `_tiltBias` | `[-1, 1]` — how much tilt drives gain for this track |
| `_panWidthIndex` | Index into `AudioSettingsConfig.panWidths` |

---

## Stage 4 — AudioSettingsConfig

**File:** `Scripts/Core/AudioSettingsConfig.cs`
**Asset:** `Settings/AudioSettings.asset`

A `ScriptableObject` that holds every tunable value in the audio pipeline. No number
appears in `TrackMixer` or `PoseAnalyzer` code — all constants are fields here, editable
in the Inspector without recompiling.

### Key fields

| Field | Value | Used in |
|---|---|---|
| `cutoffMinHz` | 800 Hz | Mapping 1 — LPF floor |
| `cutoffMaxHz` | 20000 Hz | Mapping 1 — LPF ceiling |
| `attentionLow` | 0.2 | PoseAnalyzer — attention ramp start |
| `attentionHigh` | 0.85 | PoseAnalyzer — attention ramp end |
| `panWidths[4]` | 1.0 / 0.7 / 0.85 / 0.25 | Mapping 2 — per-track pan width |
| `tiltGainRangeDb` | 6 dB | Mapping 3 — max tilt-driven gain |
| `distanceGainDb` | AnimationCurve | Mapping 4 — distance → dB offset |
| `distanceCutoffCeiling` | AnimationCurve | Mapping 1 — distance → LPF ceiling |
| `gainMinDb` | −24 dB | Gain clamp floor |
| `gainMaxDb` | 0 dB | Gain clamp ceiling |
| `scheduleMarginSeconds` | 0.2 s | PlayScheduled() timing margin |
| `startImmediatelyForTesting` | true (M1) | Debug bypass — disable before M3 |

---

## ITrackSource interface

**File:** `Scripts/Audio/ITrackSource.cs`

A forward-looking abstraction that separates the audio content source from the playback
infrastructure:

```csharp
public interface ITrackSource
{
    string Id   { get; }   // matches audio_manifest.json 'id' field
    AudioClip Clip { get; } // null in streaming implementations
}
```

In the current MVP (M1/M2), each track's `AudioSource` is loaded with a static `.wav`
clip assigned directly in the Unity Inspector. `ITrackSource` is not yet wired at
runtime — it is the seam where the future RAVE streaming decoder will plug in without
touching `TrackMixer` or `TrackChannel`.

---

## Allocation rules

The entire audio update path runs every frame with zero heap allocations:
- No `new`, no LINQ, no string operations in any `Update()` or `ApplyModulation()`
- All component references (`AudioSource`, `AudioLowPassFilter`) cached in `Awake()`
- SmoothDamp velocity refs are stored private fields, not locals
- The `List<ARRaycastHit>` in `TreePlacement` is allocated once in field initialisation

---

## State machine integration

Audio is connected to `GameManager`'s state machine via an event:

```
AppState.Booting   → Scanning   → no audio
AppState.Scanning  → Placing    → no audio (waiting for AR plane)
AppState.Placing   → Adjusting  → StartScheduled() fires here
AppState.Adjusting → Experiencing → audio continues
```

`TrackMixer` subscribes to `GameManager.OnStateChanged` in `OnEnable()` and
unsubscribes in `OnDisable()`. This means if the `TrackMixer` GameObject is ever
deactivated, it cleanly removes the listener without leaking.

```csharp
private void OnEnable()  { _gameManager.OnStateChanged += HandleStateChanged; }
private void OnDisable() { _gameManager.OnStateChanged -= HandleStateChanged; }
```

---

## Version history

How the audio pipeline evolved across commits on `feat/audio-unity-test`.

---

### v1 — `2da4933` — Initial C# audio layer

**Commit:** `feat: add C# script layer for M0–M1 milestone`

First working implementation. All four concepts were in place — PoseAnalyzer, TrackMixer,
TrackChannel, AudioSettingsConfig — but modulation was uniform across all tracks.

**How it worked:**
- A single shared LPF cutoff (from `attention`) was written identically to all 4 tracks
- Pan width was stored in a `panWidths[]` array on `AudioSettingsConfig`, indexed by
  position in the `_tracks` array — track order in the Inspector determined which pan
  width each track received
- Tilt gain formula: `TiltBias × -tilt` (sign inverted — canopy was cut when pointing up)
- No concept of a static track — the drone was panned and filtered the same as the others
- Audio only started on `AppState.Adjusting` (after tree placement)

**Limitations:**
- All tracks received the same LPF response — no timbral differentiation
- Pan width was coupled to array position — reordering tracks in the Inspector silently
  broke the mix
- Drone had no stable anchor role — it moved spatially like the other tracks
- App produced silence on launch; required full placement flow to hear anything
- `PoseAnalyzer._config` null caused `ComputeAttention()` to return `0f` (fail-closed),
  locking the LPF at 800 Hz — audio was near-silent even when playing

---

### v2 — `8eeaa59` — M1 silence fixes

**Commit:** `fix: M1 audio silence — debug bypass, LPF fail-open, xcode build tracked`

Diagnosed and fixed the two issues that caused complete silence on device during M1
on-device testing.

**What changed:**

**1. `startImmediatelyForTesting` flag** (`AudioSettingsConfig` + `TrackMixer.Start()`)
Audio no longer requires the placement flow to start. When this flag is `true` in
`AudioSettings.asset`, `TrackMixer.Start()` calls `StartScheduled()` on the first frame.
Necessary because the HudController was not wired (no confirm button, no UI feedback),
making it impossible to know whether the state machine was even advancing.

```csharp
// TrackMixer.Start()
if (_audioConfig != null && _audioConfig.startImmediatelyForTesting)
    StartScheduled();
```

**2. `ComputeAttention` fail-open** (`PoseAnalyzer`)
Changed from returning `0f` (fully closed LPF) to `1f` (fully open) when `_config`
is null. A missing Inspector reference now produces audible audio instead of silence.

```csharp
// Before: if (_config == null) return 0f;
if (_config == null) return 1f;
```

**Still uniform at this point:** all four tracks still received the same LPF cutoff, the
same distance-based pan width lookup, and the tilt sign was still inverted.

---

### v3 — `cfe63b4` — Per-track modulation

**Commit:** `feat: per-track modulation — static drone, independent LPF/pan/tilt per track`

Redesigned `TrackChannel` and `TrackMixer` so each track owns its modulation behaviour.
Spatial (pan) is now the primary expressive axis.

**What changed:**

**1. Static vs. active track split**
`TrackChannel` gains an `_isStatic` field. When `true`, `TrackMixer` takes a separate
branch that skips all four mappings:

```csharp
if (ch.IsStatic)
{
    ch.SetCutoffHz(_audioConfig.cutoffMaxHz);  // always open
    ch.SetPan(0f);                              // always centred
    ch.Source.volume = Mathf.Pow(10f, staticDb / 20f) * _muteGain;
    continue;
}
```

The drone is the only static track. It holds the centre while the three active tracks
move spatially around it — the contrast makes the spatial movement perceptible.

**2. Per-track LPF sensitivity**
`_lpfSensitivity` scales how deeply `attention` drives the filter on each track.
Instead of one shared cutoff, each track gets its own effective attention:

```csharp
float effectiveAttention = attention * ch.LpfSensitivity;
float cutoffHz = _audioConfig.cutoffMinHz *
    Mathf.Pow(_audioConfig.cutoffMaxHz / _audioConfig.cutoffMinHz, effectiveAttention);
```

| Track | LpfSensitivity | Max cutoff at full attention |
|---|---|---|
| root_rave | 1.0 | 20 000 Hz — full brightness |
| canopy | 0.8 | ~14 000 Hz |
| soil | 0.5 | ~4 000 Hz — always warm |

**3. Pan width moved to TrackChannel**
`panWidths[]` removed from `AudioSettingsConfig`. Each track stores its own `_panWidth`:

```csharp
ch.SetPan(panBase * ch.PanWidth);
```

No longer order-dependent. The track carries its spatial character regardless of where
it appears in the `_tracks` array.

| Track | PanWidth | Role |
|---|---|---|
| root_rave | 1.0 | Widest — most spatial |
| canopy | 0.85 | Wide |
| soil | 0.65 | Moderate |
| drone | static | Always centred |

**4. Tilt sign fix**
`TiltBias × -tilt` → `TiltBias × tilt`. Canopy now correctly gets louder when the phone
points up; root_rave gets louder when pointing down.

---

## M3 tuning checklist

Before M3 audio tuning begins:

- [ ] Set `startImmediatelyForTesting = false` in `AudioSettings.asset`
- [ ] Wire `PoseAnalyzer._config → AudioSettings` in Unity Inspector
- [ ] Set per-track Inspector values (see v3 in §Version history)
- [ ] Tune `distanceGainDb` curve outdoors with headphones
- [ ] Tune `_lpfSensitivity` per track by ear — soil should stay warm at all distances
- [ ] Tune `_panWidth` per track — root_rave spatial width is the dominant spatial cue
- [ ] Confirm `attentionLow` / `attentionHigh` thresholds feel natural when walking around the tree
- [ ] Confirm LPF logarithmic mapping sounds smooth across full attention range
