# 0007 — The cut file is a deterministic draft plus located findings; overrides are the primary path

Status: accepted
Date: 2026-09-22

## Context

§6.3 asks for a simplified cut file that "preserves meaningful identifying details".
No tracer knows what an identifying detail is.

## Decision

- The generated cut file = silhouette source + deterministic geometric cleanup at the
  reference size (island/hole removal, morphological opening, vertex simplification).
- Validation emits structured **findings** for every §9 problem, each with a location,
  so they can be drawn over the SVG and navigated to in an editor.
- The override workflow (§6.8) is the expected path for a meaningful share of cut
  files, not an exception. The tool's job is to make that loop fast and never lose the
  edit.
- **No automatic bridging or joining** of disconnected fragments. Report and leave.

## Consequences

- §39.3 "simplified cut-file SVG" is satisfied as a draft; §39.12 is fully satisfied.
- The review UI's key page is generated-vs-override with a findings overlay.
