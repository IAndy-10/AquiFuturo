# Visual Layer Pipeline — AquiFuturo AR

How the scanned root skeleton becomes interactive 3D geometry in the AR scene.

---

## Overview

The app loads a skeleton graph of a real oak tree root system (`root_graph.json`) and
procedurally builds tube geometry from it at placement time. The mesh is anchored to the
AR world, assigned to the `RootMesh` physics layer, and raycasted against on every touch.
When the user taps a root, the nearest graph node drives a one-shot audio event and a
particle burst.

```
root_graph.json  (StreamingAssets)
      │
      ▼
RootGraphLoader       — parses schema, builds node/edge lists + SpatialHash in Start()
      │
      ▼
RootMeshBuilder       — one tapered tube per edge, combined into a single mesh+collider
      │                  parented to the placed tree anchor
      ▼
RootMesh layer        — Physics.Raycast target for touch interactions
      │
      ▼
RootInteraction       — touch → raycast → SpatialHash.NearestTo() → node class
      │
      ├─▶ InteractionAudioPool   one-shot sound per node class
      └─▶ ParticleSpawner        burst at hit point and normal
```

All tunables (tube sides, material) live in `RootMeshConfig` (a ScriptableObject).
No magic numbers in any runtime method.

---

## Files

| File | Namespace | Role |
|---|---|---|
| `Scripts/Graph/RootGraphLoader.cs` | `AquiFuturo.Graph` | Loads and validates `root_graph.json`, builds `SpatialHash` |
| `Scripts/Graph/RootGraph.cs` | `AquiFuturo.Graph` | In-memory data model — nodes, edges, bounds |
| `Scripts/Graph/RootMeshBuilder.cs` | `AquiFuturo.Graph` | Generates procedural tube mesh from graph edges |
| `Scripts/Graph/RootMeshConfig.cs` | `AquiFuturo.Graph` | ScriptableObject — tube quality and material |
| `Scripts/Graph/SpatialHash.cs` | `AquiFuturo.Graph` | 3D cell grid for O(1) nearest-node lookup on touch |
| `Scripts/Interaction/RootInteraction.cs` | `AquiFuturo.Interaction` | Touch → raycast → node → audio + particles |
| `StreamingAssets/root_graph.json` | — | Real scan data — sbcast_oak_01, 545 nodes, 543 edges |
| `Settings/RootMeshSettings.asset` | — | Live instance of `RootMeshConfig` |

---

## Stage 1 — RootGraphLoader

**File:** `Scripts/Graph/RootGraphLoader.cs`

Runs in `Start()`. Reads `root_graph.json` from `Application.streamingAssetsPath`,
validates the schema version, deserialises nodes and edges into `RootGraph`, then builds
the `SpatialHash` immediately. The hash must be ready before the first touch — lazy
initialisation would cause a one-frame freeze that appears as a dropped touch in the CSV
log (SPEC §10).

### Schema guard

```csharp
if (raw.schema_version != RootGraph.SupportedVersion)
    throw new InvalidOperationException(
        $"schema_version '{raw.schema_version}' is not supported. " +
        $"Expected '{RootGraph.SupportedVersion}'.");
```

A mismatch throws immediately — it is never silently accepted. The current supported
version is `"1.1"`.

### The graph data

`RootGraph` holds two flat lists:

```csharp
public IReadOnlyList<RootNode> Nodes { get; }
public IReadOnlyList<RootEdge> Edges { get; }
```

Each `RootNode` carries:

| Field | Type | Meaning |
|---|---|---|
| `Id` | int | Stable index into the node list |
| `Position` | Vector3 | World position in `unity_y_up` metres |
| `Radius` | float | Tube radius at this node in metres |
| `DepthOrder` | int | Topological depth from trunk_base |
| `BranchOrder` | int | Branching generation (0 = main axis) |
| `IsTerminal` | bool | True if the node has no children |
| `Class` | string | `trunk_base` · `primary` · `lateral` · `fine` · `terminal` |

Each `RootEdge` carries source node id, target node id, and segment length in metres.

### sbcast_oak_01 — node class breakdown

| Class | Count | Depth in tree |
|---|---|---|
| `trunk_base` | 1 | Ground-level attachment point |
| `primary` | 103 | Main radial roots |
| `lateral` | 169 | Secondary branches |
| `fine` | 230 | Tertiary fine roots |
| `terminal` | 42 | Tips — no children |

**Spatial extent:** X[−0.96, 2.65 m] · Y[−4.94, −0.64 m] · Z[−2.03, 1.50 m].
The entire system is underground — Y is negative throughout, with the shallowest point
(trunk_base) at Y = −0.64 m and the deepest tips at Y = −4.94 m.

### SpatialHash

Built immediately after parsing:

```csharp
SpatialHash = new SpatialHash(cellSize);
foreach (var node in Graph.Nodes)
    SpatialHash.Insert(node);
```

`cellSize` comes from `InteractionSettingsConfig.spatialHashCellSize` (default 0.25 m).
The hash partitions 3D space into a grid of fixed-size cells. `NearestTo(point)` checks
only cells within one cell radius of the query point — no linear scan over all 545 nodes.

---

## Stage 2 — RootMeshBuilder

**File:** `Scripts/Graph/RootMeshBuilder.cs`

Called once by `TreePlacement.InstantiateTree()` immediately after the tree is placed.
Builds a combined procedural mesh and attaches it to the tree instance's transform.

### Origin alignment

The `trunk_base` node is the natural attachment point — it is the shallowest node in
the graph, sitting just below the soil surface. Its position is subtracted from all node
positions before building the mesh:

```csharp
foreach (RootNode node in graph.Nodes)
{
    ...
    if (node.Class == "trunk_base")
        originOffset = node.Position;
}

// Per edge:
Vector3 localStart = startPos - originOffset;
Vector3 localEnd   = endPos   - originOffset;
```

This means when `RootMeshBuilder` is parented to the placed tree at `localPosition =
Vector3.zero`, the trunk_base node aligns exactly with the AR tap point on the ground.
The root system hangs underground from there.

### Tube geometry

For each edge, `CreateTubeMesh()` generates a tapered tube using the radii of its two
endpoint nodes:

```
start ring  — startRadius  (source node radius)
end ring    — endRadius    (target node radius)
```

Roots taper naturally: primary roots at ~12 cm radius, fine roots at ~1 cm. Each tube
uses a configurable number of sides (`RootMeshConfig.tubeSides`, default 6).

```csharp
// Build orthonormal basis perpendicular to the tube axis
Vector3 perp = Mathf.Abs(Vector3.Dot(dir, Vector3.up)) < 0.99f
    ? Vector3.Cross(dir, Vector3.up).normalized
    : Vector3.Cross(dir, Vector3.right).normalized;
Vector3 perp2 = Vector3.Cross(dir, perp).normalized;

// Two rings of vertices, one at each endpoint
verts[i]         = start + ring * startRadius;
verts[sides + i] = end   + ring * endRadius;
```

### Combined mesh

All 543 tube meshes are combined into a single `Mesh` via `CombineMeshes` before being
assigned to `MeshFilter` and `MeshCollider`:

```csharp
var combined = new Mesh { name = "RootGraphMesh" };
combined.indexFormat = IndexFormat.UInt32;
combined.CombineMeshes(combines.ToArray(), mergeSubMeshes: true, useMatrices: true);
```

`IndexFormat.UInt32` is used to future-proof for larger graphs — the current graph
at 6 sides × 543 edges produces ~6 500 vertices, well within 16-bit range, but denser
scan data or the branch system would exceed it.

The temporary per-edge meshes are destroyed immediately after `CombineMeshes` returns.
The combined mesh is then shared between `MeshFilter` (renderer) and `MeshCollider`
(physics), so touch raycasts hit the same geometry the user sees.

### Vertex budget (sbcast_oak_01 at tubeSides = 6)

| | Count |
|---|---|
| Edges | 543 |
| Vertices per tube | 12 (2 rings × 6 sides) |
| Triangles per tube | 12 (6 quads × 2 tris) |
| Total vertices | ~6 516 |
| Total triangles | ~6 516 |

### RootMesh layer

The combined mesh GameObject is assigned to the `RootMesh` physics layer:

```csharp
int layer = LayerMask.NameToLayer("RootMesh");
_meshRoot.layer = layer;
```

`RootInteraction` raycasts exclusively against this layer — it never hits the default
layer or AR plane geometry. If the layer does not exist in Project Settings, a warning
is logged and the mesh falls back to layer 0 (raycasts will still hit it, but so will
everything else).

### Reset

`ClearMesh()` is called by `TreePlacement.ResetPlacement()`. It destroys `_meshRoot`
and nulls the reference. The next `BuildMesh()` call starts fresh.

---

## Stage 3 — RootInteraction

**File:** `Scripts/Interaction/RootInteraction.cs`

Processes touch input during `AppState.Experiencing`. Raycasts against the `RootMesh`
layer, resolves the nearest graph node via the `SpatialHash`, debounces repeated touches
per node, then fires a one-shot audio event and a particle burst.

### Touch → raycast

```csharp
Ray ray = _arCamera.ScreenPointToRay(screenPos);
if (!Physics.Raycast(ray, out RaycastHit hit, maxDist, _rootMeshLayerMask))
    return;
```

`maxDist` comes from `InteractionSettingsConfig.raycastDistanceM` (default 10 m).
The layer mask ensures the raycast only tests the combined root mesh — no false hits
on AR planes or other geometry.

### Raycast → nearest node

The hit point is a position on the tube surface, not a node position. The `SpatialHash`
resolves the nearest graph node to that surface point:

```csharp
RootNode node = _graphLoader.SpatialHash.NearestTo(hit.point);
```

The node's `Class` field (`primary`, `lateral`, `fine`, etc.) drives which one-shot
sound the `InteractionAudioPool` selects. Different root classes sound different.

### Debounce

Each node has an independent cooldown timer. Rapid repeated touches on the same node
are ignored:

```csharp
if (_lastTouchTime.TryGetValue(node.Id, out float last) &&
    Time.time - last < debounceSeconds)
    return;
_lastTouchTime[node.Id] = Time.time;
```

`debounceSeconds` = `InteractionSettingsConfig.debounceMs / 1000f` (default 120 ms).

### Pan and logging

The one-shot audio is panned toward the touch azimuth:
```csharp
float panValue = Mathf.Sin(_poseAnalyzer.Azimuth * Mathf.Deg2Rad);
_audioPool?.Play(node.Class, panValue, pitchVar);
```

Every touch is logged to the session CSV:
```csharp
SessionLogger.Instance?.LogRootTouch(node.Id, node.Class,
    Vector3.Distance(_arCamera.transform.position, hit.point));
```

---

## RootMeshConfig

**File:** `Scripts/Graph/RootMeshConfig.cs`
**Asset:** `Settings/RootMeshSettings.asset`

ScriptableObject holding visual tunables for the root mesh.

| Field | Default | Purpose |
|---|---|---|
| `tubeSides` | 6 | Polygon sides per cross-section (3–12) |
| `rootMaterial` | null | Material applied to combined mesh; Unity default if null |

`tubeSides` is the primary performance/quality trade-off. At 6, roots look faceted but
render cheaply. At 12 they read as round on device. Adjust by eye in the Inspector
without recompiling.

---

## Allocation rules

The mesh build runs once at placement — not in `Update()`. No allocations occur at
runtime after the mesh is constructed:
- `Dictionary` lookups in `RootInteraction` use `TryGetValue` — no boxing
- `_lastTouchTime` dictionary is allocated once in field initialisation
- `Physics.Raycast` with a pre-computed layer mask allocates nothing
- The camera reference is cached in `Awake()` — never `Camera.main` in the touch path

---

## State machine integration

```
AppState.Placing    → user taps AR plane
                         TreePlacement.InstantiateTree()
                         RootMeshBuilder.BuildMesh(treeInstance.transform)  ← mesh appears
                         GameManager.OnTreePlaced()

AppState.Adjusting  → user adjusts scale/rotation via TreeAdjuster
                         RootMesh moves with the tree (parented)

AppState.Experiencing → RootInteraction.Update() activates
                         touch → raycast → node → audio + particle

[Reset]             → TreePlacement.ResetPlacement()
                         RootMeshBuilder.ClearMesh()  ← mesh destroyed
```

---

## Unity wiring

| GameObject | Component | Field | Wired to |
|---|---|---|---|
| `Placement` | `Tree Placement` | `Root Mesh Builder` | `Placement` (self) |
| `Placement` | `Root Mesh Builder` | `Config` | `Settings/RootMeshSettings.asset` |
| `Placement` | `Root Mesh Builder` | `Graph Loader` | `Graph` |
| `Interaction` | `Root Interaction` | `Graph Loader` | `Graph` |
| `Interaction` | `Root Interaction` | `Game Manager` | `Bootstrap` |
| `Interaction` | `Root Interaction` | `Pose Analyser` | `Bootstrap` |

`Audio Pool` and `Particle Spawner` on `Root Interaction` are intentionally left unwired
until those systems are built. Null guards prevent crashes — touch interactions silently
skip audio and particles until then.

**Project Settings → Tags and Layers:** `RootMesh` is assigned to User Layer 3.

---

## Version history

### v1 — `55743ad` — feat/tree-to-unity

**Commit:** `feat: add RootMeshBuilder, RootMeshConfig, and root_graph.json to StreamingAssets`

First working visual layer. Real scan data (sbcast_oak_01) is loaded, parsed, and
rendered as procedural tube geometry. The mesh is interactive via the existing
`RootInteraction` + `SpatialHash` infrastructure.

**What shipped:**
- `RootMeshBuilder` with `BuildMesh` / `ClearMesh` public API
- `RootMeshConfig` ScriptableObject — `tubeSides` and `rootMaterial`
- `root_graph.json` copied to `StreamingAssets` — `RootGraphLoader` now finds it on boot
- `TreePlacement` updated to call `BuildMesh` on placement and `ClearMesh` on reset
- Tapered tubes: each edge uses independent source/target radii — natural tapering from
  primary roots (~12 cm) down to terminal tips (~1 cm)
- Combined mesh strategy: 543 per-edge meshes merged into one draw call
- `IndexFormat.UInt32` for future-proofing against larger graphs

**Not yet done (next iterations):**
- Material and shading (tube mesh currently uses Unity default diffuse)
- Branch graph (`branch_graph.json`) not yet loaded or rendered
- No LOD — full 543-edge mesh at all distances
- Visual aesthetics: colour by node class, transparency, subsurface scattering, etc.

---

---

### v2 — `6700abc` — Unity scene wiring

**Commit:** `chore: wire RootMeshBuilder and RootInteraction in Unity scene`

Full scene wiring completed. The visual pipeline is connected end-to-end in the Unity
Editor and ready for Play Mode testing.

**What was done:**
- Added `RootMesh` layer to Project Settings → Tags and Layers (User Layer 3)
- Created `Graph` GameObject with `RootGraphLoader` component
- Created `Interaction` GameObject with `RootInteraction` component
- Created `Settings/RootMeshSettings.asset` from `RootMeshConfig` ScriptableObject
- Wired all six Inspector references (see Unity wiring table above)
- `Audio Pool` and `Particle Spawner` left unwired — those systems not yet in scene

---

## Aesthetics iteration log

This section will be updated as the visual appearance is developed.
Each iteration should document: what changed, what parameter drives it, and why.

_(Pending — aesthetics work begins after Unity wiring is confirmed working on device.)_
