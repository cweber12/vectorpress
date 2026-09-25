"""Launch an editor (or the OS default opener) on a derivative, and resolve
which file ``vpress open`` targets (§6.8, §24, ADR 0005, ADR 0007).

Deciding *what* to open shares its reviewability gate with
:mod:`vectorpress.pipeline.review`
(:func:`~vectorpress.pipeline.generate.reviewable_output_filename`): a
derivative type with no recipe, or one that is missing or impossible for
this asset, has no file to open -- the same as it has none to approve.
Actually spawning a process is kept behind one small, injectable function
(:func:`launch_editor`) so tests can assert the exact command without
spawning anything real.
"""

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from vectorpress.catalog.overrides import (
    create_override_from_generated,
    effective_derivative,
    override_path,
)
from vectorpress.catalog.provenance import DERIVED_DIRNAME, read_derivative_bytes
from vectorpress.domain.asset import Asset
from vectorpress.domain.catalog_config import CatalogConfig
from vectorpress.domain.derivative_type import DerivativeType
from vectorpress.domain.recipe import RECIPES
from vectorpress.pipeline.generate import reviewable_output_filename

#: An injectable launcher's shape: ``argv`` is the resolved command to run,
#: or ``None`` when no ``editor`` is configured (the OS default opener
#: applies) -- paired with the file's path either way, so a launcher that
#: only cares about the path (the ``None`` case) still has it.
Launcher = Callable[[list[str] | None, Path], None]


def _os_default_launch(path: Path) -> None:
    """Open ``path`` with the OS's own default handler for its file type --
    the fallback when ``catalog.toml`` sets no ``editor``."""
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]  # Windows-only API
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def default_launcher(argv: list[str] | None, path: Path) -> None:
    """Run ``argv`` (an editor command with ``path`` already appended), or
    fall back to :func:`_os_default_launch` when ``argv`` is ``None``.
    Returns immediately: neither branch waits for the launched process."""
    if argv is not None:
        subprocess.Popen(argv)
        return
    _os_default_launch(path)


def launch_editor(
    path: Path, editor_command: Sequence[str] | None, launcher: Launcher | None = None
) -> None:
    """Launch ``editor_command`` with ``path`` appended, or the OS default
    opener when ``editor_command`` is ``None`` (no ``editor`` configured in
    ``catalog.toml``).

    ``launcher`` is the injection seam (:data:`Launcher`): production code
    leaves it unset, which selects :func:`default_launcher`; a test passes
    one that records the call instead of spawning anything.
    """
    argv = [*editor_command, str(path)] if editor_command is not None else None
    (launcher or default_launcher)(argv, path)


@dataclass(frozen=True)
class OpenTarget:
    """One file ``vpress open`` resolved to launch an editor on."""

    path: Path
    is_override: bool


def resolve_open_target(
    asset: Asset,
    asset_dir_path: Path,
    derivative_type: DerivativeType,
    config: CatalogConfig | None,
    *,
    generated_only: bool = False,
    start_override: bool = False,
) -> tuple[OpenTarget | None, str | None]:
    """Which file ``vpress open`` launches an editor on, or the reason it
    cannot (§6.8, §24).

    Gated on the *generated* file's own reviewability
    (:func:`~vectorpress.pipeline.generate.reviewable_output_filename`), the
    same rule approve/reject/regenerate apply: a derivative type with no
    recipe, or one that is ``missing`` or ``impossible`` for this asset, has
    nothing to open -- whether or not an override happens to sit under
    ``overrides/`` already, since ``--override`` itself copies from the
    generated file (it needs one to exist too).

    Default (neither flag): the effective derivative (CONTEXT.md "Effective
    derivative") -- the override if one exists, else the generated file.
    ``generated_only`` (``--generated``): always the generated file under
    ``derived/``, even when an override exists. ``start_override``
    (``--override``): the override, starting one by copying the current
    generated file into ``overrides/`` the first time one is seen
    (:func:`~vectorpress.catalog.overrides.create_override_from_generated`,
    which also records its provenance immediately) -- never overwriting an
    override already there.
    """
    output_filename, error = reviewable_output_filename(
        asset, asset_dir_path, derivative_type, config
    )
    if output_filename is None:
        assert error is not None  # reviewable_output_filename always pairs one with the other
        return None, error

    derived_dir = asset_dir_path / DERIVED_DIRNAME

    if generated_only:
        return OpenTarget(derived_dir / output_filename, is_override=False), None

    if start_override:
        generated_bytes = read_derivative_bytes(derived_dir, output_filename)
        assert generated_bytes is not None  # CURRENT/STALE means the file exists on disk
        recipe = RECIPES[derivative_type]
        override = create_override_from_generated(
            asset, asset_dir_path, recipe, output_filename, generated_bytes
        )
        return OpenTarget(override, is_override=True), None

    effective = effective_derivative(asset_dir_path, output_filename)
    assert effective is not None  # CURRENT/STALE means the generated file exists on disk
    path = (
        override_path(asset_dir_path, output_filename)
        if effective.is_override
        else derived_dir / output_filename
    )
    return OpenTarget(path, is_override=effective.is_override), None
