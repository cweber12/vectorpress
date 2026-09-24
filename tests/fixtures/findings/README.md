# Findings trip SVGs

Hand-authored SVGs, outside the fixture catalog (`tests/fixtures/catalog/`), used to
prove `vpress validate --file` and the pure `validate_cut_file` entry point work on
*any* SVG, not only one this tool generated (§9's own scope bullet 5, issue #41). Each
one carries an XML comment naming the kind it trips (`<!-- trips: <kind> -->`) --
`xml.etree.ElementTree`'s default parser drops comments entirely, so validation never
sees or misreads them as a stray element.

Five of the eleven §9 kinds can only appear in a hand-edited SVG -- the §8 builder
rules them out by construction (`tests/integration/test_validate.py`'s own
`test_every_generated_fixture_cut_file_trips_none_of_issue_41s_five_kinds` proves
this against the real fixture catalog). This directory carries one trip SVG per kind,
plus one clean SVG that passes with no findings at all:

- `open_path.svg` -- a single unclosed subpath (no `Z`, and its end is not its start).
- `raster_content.svg` -- a plain closed piece plus a `<image>` element with a
  `data:` URI.
- `stray_object.svg` -- a plain closed piece plus a `<rect>` entirely outside the
  document's own `viewBox` (off canvas). The other three stray-object sub-cases
  (an empty group, an invisible element, a stray `<text>` element) are unit-tested
  directly (`tests/unit/test_validate_stray_object.py`) rather than given their own
  trip SVG, since all four collapse into the one `stray_object` finding kind.
- `duplicate_geometry.svg` -- the same hole cut twice from one big square, at the
  exact same position (stacked exactly). Two identical *holes* rather than two
  identical top-level pieces, deliberately: two equal-area top-level pieces would
  also report a `disconnected_fragments` finding (ADR 0007's own "no automatic
  bridging, every extra piece is reported"), which would trip a second kind on this
  fixture -- a hole never competes with a piece's own classification.
- `overlap.svg` -- two separate `<path>` elements whose boundaries genuinely cross:
  `b` is smaller than `a` and its own centroid lands inside `a`, so the piece/hole
  containment-parity grouping `vectorpress.validate._svg_geometry.parse_cut_file`
  uses for every other §9 detector would misclassify `b` as a hole of `a` -- part of
  `b`'s own boundary genuinely sticks out past `a`'s edge, which only a real
  edge-crossing test (`vectorpress.validate.overlap`, never that grouping) catches.
  Self-intersection (the other half of the `overlap` finding kind) is unit-tested
  directly (`tests/unit/test_validate_overlap.py`) with a small bowtie shape rather
  than given its own trip SVG, since both collapse into the one `overlap` kind.
- `clean.svg` -- a single closed, filled square: passes with no findings at all.

## The other six §9 kinds

The remaining six kinds -- `disconnected_fragments`, `accidental_dot`,
`tiny_isolated_shape`, `small_hole`, `narrow_feature`, `excessive_complexity` -- are
each already tripped by a *generated* subject in the fixture catalog
(`tests/fixtures/catalog/README.md`'s own "Assets" section names which one):
`giant_green_anemone`/`owl_limpet` (disconnected fragments), `gumboot_chiton`
(accidental dot), `bat_star` (tiny isolated shape), `keyhole_limpet`/`turban_snail`
(small hole), `nudibranch` (narrow feature), `coralline_algae` (excessive
complexity). Between that catalog and this directory, every one of the eleven §9
kinds is tripped at least once (`tests/integration/test_prd03_acceptance.py`'s own
acceptance walk-through test asserts this directly).

## A future PRD 4 home

Once PRD 4 defines an asset's `overrides/` layout (ADR 0003, ADR 0007), these trip
SVGs can move to live as a fixture asset's own override instead of this standalone
directory -- noted here per issue #41's own "PRD 4 can move them" call-out.
