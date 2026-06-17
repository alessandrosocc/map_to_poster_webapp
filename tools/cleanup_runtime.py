#!/usr/bin/env python3
"""Clean runtime cache and generated posters not needed by the homepage."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "homepage_posters.json"
POSTERS_DIR = ROOT / "posters"
CACHE_PATHS = [
    ROOT / "webapp" / ".cache",
]


def load_keep_set() -> set[str]:
    with MANIFEST.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"{MANIFEST} deve contenere una lista di file")
    return {Path(str(item)).name for item in data}


def clean_cache() -> int:
    removed = 0
    for path in CACHE_PATHS:
        if path.exists():
            shutil.rmtree(path)
            removed += 1
    return removed


def clean_posters(keep: set[str]) -> tuple[int, int]:
    removed = 0
    kept = 0
    if not POSTERS_DIR.exists():
        return removed, kept

    for path in POSTERS_DIR.iterdir():
        if not path.is_file():
            continue
        if path.name in keep:
            kept += 1
            continue
        path.unlink()
        removed += 1

    return removed, kept


def main() -> None:
    keep = load_keep_set()
    removed_cache = clean_cache()
    removed_posters, kept_posters = clean_posters(keep)
    print(f"Cache runtime rimosse: {removed_cache}")
    print(f"Poster mantenuti per homepage: {kept_posters}")
    print(f"File rimossi da posters/: {removed_posters}")


if __name__ == "__main__":
    main()
