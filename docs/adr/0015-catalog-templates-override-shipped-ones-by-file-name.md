# 0015 — Catalog templates override shipped ones by file name, against a fixed template context

Status: accepted
Date: 2026-09-28

## Context

ADR 0008 says templates ship with the tool and a catalog may override them, without
saying how. Once a catalog overrides a template, its file names and the variables it
reads become a contract between the catalog repo and the tool.

## Decision

- Shipped templates are package data under `vectorpress/build/templates/<kind>/`
  (`previews/`, later `listing/`, `export/`). A file at
  `<catalog>/templates/<kind>/<same name>` replaces the shipped file of that name;
  the catalog folder is searched first, then the tool's. `{% extends %}` and blocks
  give partial overrides. The folder name is fixed, not configured in `brand.toml`
  or `catalog.toml`.
- Every template receives one fixed, documented context (for previews: `canvas`,
  `brand`, `product`, `members`, `featured`, `page`). Reading anything else fails the
  build naming the template (StrictUndefined).
- The build report lists every catalog override in use, so a catalog always sees
  which templates no longer track the shipped ones.
- Rights status and AI disclosure are not in the preview context: disclosure is a
  text-field concern of exporters, and keeping it out means a rights fix never makes
  previews out of date.

## Rejected alternatives

- **Declaring overrides in `brand.toml`.** Duplicates what the filesystem already
  says and can disagree with it.
- **A `vpress template copy` command.** A new tool write into a hand-authored area
  (ADR 0005); copying a file by hand suffices for one user.

## Consequences

- Renaming a shipped template, or removing a context variable, breaks catalog
  overrides; either is a change called out in the PR, like a snapshot update.
