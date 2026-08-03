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
