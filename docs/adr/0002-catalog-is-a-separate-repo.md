# 0002 — The catalog is a separate directory, pointed at by the tool

Status: accepted
Date: 2026-09-22

## Context

§41 says assets, collections, products and brand config are human-readable files under
version control. Master PNGs are the business asset; the tool is code.

## Decision

- A **catalog** is a directory outside the tool repo, identified by a root
  `catalog.toml`, located from the working directory or `--catalog`.
- The tool repo carries only a tiny fixture catalog under `tests/fixtures/catalog/`.
- Generated derivatives and overrides **are committed** in the catalog repo. Product
  ZIPs, previews and exports are build output and are not committed.

## Consequences

- Code history never contains real artwork; artwork history never contains code.
- A second catalog (another brand) is free.
- "Approved" refers to a real, committed file; a tracer upgrade cannot silently change
  what was approved.
