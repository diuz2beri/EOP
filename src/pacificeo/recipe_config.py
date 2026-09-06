from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RecipeCatalog:
    backend: dict[str, Any]
    recipes: dict[str, dict[str, Any]]

    def require(self, name: str) -> dict[str, Any]:
        if name not in self.recipes:
            raise ValueError(f"Unknown product recipe: {name}")
        return self.recipes[name]


def load_catalog(path: str | Path = "config/recipes.yaml") -> RecipeCatalog:
    with Path(path).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if raw.get("version") != 1 or not raw.get("recipes") or not raw.get("backend"):
        raise ValueError("Recipe catalog must contain version 1, backend, and recipes")
    return RecipeCatalog(backend=raw["backend"], recipes=raw["recipes"])
