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
- Do not commit to main or dev directly. Work on feat/<short-name>
  branches, merged into dev per git-workflow.md, then dev into main
  only for tagged field-test builds (SPEC.md §14.3).
- Do not use GameObject.Find or FindObjectOfType as a substitute for
  Inspector wiring — that is the wrong seam. If wiring is needed, write
  the code and leave the "Unity wiring required" note instead.

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
6. For any Python changes: `ruff check tools/` is clean.

## Order of work
Follow SPEC.md §17. Do not start M3 audio tuning before M1 places a placeholder
object in AR on a real device with four placeholder tracks audibly responding to
phone movement.
