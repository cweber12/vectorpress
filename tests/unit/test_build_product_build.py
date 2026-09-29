"""build.product_build's private ``_swap_into_place``: the closest-to-
atomic directory swap ``vpress build`` uses to replace ``builds/<slug>/``
only on success (§35). Also ``_preview_upload_order_key``, the manifest's
own preview-name sort key (§16)."""

from pathlib import Path

import pytest

from vectorpress.build.product_build import (
    _preview_upload_order_key,  # pyright: ignore[reportPrivateUsage]
    _swap_into_place,  # pyright: ignore[reportPrivateUsage]
)


def _write(directory: Path, filename: str, content: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(content, encoding="utf-8")


def test_swap_into_place_replaces_an_existing_build(tmp_path: Path) -> None:
    target_dir = tmp_path / "builds" / "some_product"
    _write(target_dir, "old.txt", "old build")
    tmp_dir = tmp_path / "builds" / ".tmp-some_product-abc"
    _write(tmp_dir, "new.txt", "new build")

    _swap_into_place(tmp_dir, target_dir)

    assert (target_dir / "new.txt").read_text(encoding="utf-8") == "new build"
    assert not (target_dir / "old.txt").exists()
    assert not tmp_dir.exists()


def test_swap_into_place_creates_a_fresh_build_directory(tmp_path: Path) -> None:
    target_dir = tmp_path / "builds" / "some_product"
    tmp_dir = tmp_path / "builds" / ".tmp-some_product-abc"
    _write(tmp_dir, "new.txt", "new build")

    _swap_into_place(tmp_dir, target_dir)

    assert (target_dir / "new.txt").read_text(encoding="utf-8") == "new build"


def test_swap_into_place_restores_the_previous_build_when_the_final_rename_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure between renaming the old build aside and renaming the new
    one into place must not strand the old build under its temporary name
    (§35): the failed swap restores it to ``builds/<slug>/`` before
    re-raising, so a crash here still leaves a previous build intact at
    its own canonical path, not merely somewhere on disk."""
    target_dir = tmp_path / "builds" / "some_product"
    _write(target_dir, "old.txt", "old build")
    tmp_dir = tmp_path / "builds" / ".tmp-some_product-abc"
    _write(tmp_dir, "new.txt", "new build")

    original_rename = Path.rename

    def failing_rename(self: Path, target: Path) -> Path:
        if self == tmp_dir:
            raise OSError("simulated failure renaming the new build into place")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", failing_rename)

    with pytest.raises(OSError):
        _swap_into_place(tmp_dir, target_dir)

    assert target_dir.is_dir()
    assert (target_dir / "old.txt").read_text(encoding="utf-8") == "old build"
    assert not (target_dir / "new.txt").exists()


# --- _preview_upload_order_key: type number, page number, then canvas ------


def test_preview_upload_order_key_sorts_by_type_number_before_canvas_name() -> None:
    paths = ["previews/02-included-square.png", "previews/01-main-landscape.png"]

    assert sorted(paths, key=_preview_upload_order_key) == [
        "previews/01-main-landscape.png",
        "previews/02-included-square.png",
    ]


def test_preview_upload_order_key_sorts_contents_pages_numerically_not_lexicographically() -> None:
    """A plain lexicographic sort of the file name puts
    ``05-contents-10-...`` before ``05-contents-2-...`` (string comparison
    of "1" against "2"): this key compares the page number as an int
    instead, so page 10 still sorts after page 2."""
    paths = [
        "previews/05-contents-10-square.png",
        "previews/05-contents-2-square.png",
        "previews/05-contents-1-square.png",
    ]

    assert sorted(paths, key=_preview_upload_order_key) == [
        "previews/05-contents-1-square.png",
        "previews/05-contents-2-square.png",
        "previews/05-contents-10-square.png",
    ]


def test_preview_upload_order_key_sorts_canvas_within_one_type_and_page() -> None:
    paths = ["previews/04-variants-square.png", "previews/04-variants-landscape.png"]

    assert sorted(paths, key=_preview_upload_order_key) == [
        "previews/04-variants-landscape.png",
        "previews/04-variants-square.png",
    ]
