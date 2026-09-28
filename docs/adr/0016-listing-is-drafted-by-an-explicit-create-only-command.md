# 0016 — A listing is drafted by an explicit, create-only command, never by a build

Status: accepted (supersedes 0005's "drafts a product's `[listing]` once, on first build")
Date: 2026-09-28

## Context

ADR 0005 lets the tool write one thing into a hand-authored file: a product's
`[listing]`, drafted on first build. Settling PRD 7 exposed two problems with making
that a build side effect. The package and ZIP are named from the listing's
`short_title` (PRD 6), so a first build drafting its own listing would name the
package from the slug and the second build would rename it. And a build that edits a
git-tracked hand-authored file breaks the otherwise clean rule that builds write only
under `builds/`.

## Decision

- `vpress listing draft <slug>` appends a `[listing]` table to `products/<slug>.toml`
  only when the file has no `listing` at all. Any listing present, even an invalid
  partial one, makes it refuse and write nothing. "Drafted once, then user-owned"
  means **create-only**: the tool never merges, fills gaps, or updates a listing. To
  redraft, delete the table and run the command again.
- The write appends raw text; it never round-trips the TOML, so no existing byte
  (comments, key order, line endings) changes. The result is re-parsed and validated
  as a product before an atomic replace. The appended table opens with a comment
  saying it was drafted, when, and that the tool never rewrites it.
- `vpress build` never writes `product.toml`. It refuses a product with no
  `[listing]`, naming the draft command.
- §18's derived values (asset count, formats, asset names, collection name, update
  date) are never stored in the listing; builds compute them from the manifest.
- Because a create-only listing can never be corrected by the tool, it holds only
  prose and choices, never facts that change with the product. The drafted
  `description` is the pitch (no counts); the drafted `title` names the kind of
  product, not how many. Exporters assemble the customer-facing description as the
  pitch, then a **contents summary** built from the manifest, then any disclosure.
- The draft never uses member tags (catalog-internal tags such as `detail-*` drive
  collection rules) and never enforces a marketplace limit; exporters report those.

## Consequences

- ADR 0005's rule now reads: the tool never rewrites a hand-authored file; its one
  write into one is appending a product's `[listing]` on explicit request,
  create-only.
- A product can exist and resolve without a listing, but cannot build.
