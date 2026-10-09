"""Load and validate everything under content/ (PLAN.md 6.1).

`python -m server.content export <dir>` writes the normalised catalogue as
JSON (every default filled in) for the Node bots; the browser gets the same
JSON from `GET /api/catalogue`.
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

import yaml

from server.contracts import Catalogue

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"


def _yaml(path: Path):
    with path.open() as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def load_catalogue() -> Catalogue:
    cat_dir = CONTENT / "catalogue"
    effects = _yaml(cat_dir / "effects.yaml")
    return Catalogue(
        drones=_yaml(cat_dir / "drones.yaml"),
        effectors=_yaml(cat_dir / "effectors.yaml"),
        sensors=_yaml(cat_dir / "sensors.yaml"),
        effect_matrix=effects["effect_matrix"],
        laser_dwell=effects["laser_dwell"],
        weather=effects["weather"],
    )


def catalogue_json() -> dict:
    return load_catalogue().model_dump(mode="json")


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "export":
        out = Path(argv[1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "catalogue.json").write_text(json.dumps(catalogue_json(), indent=1))
        print(f"wrote {out / 'catalogue.json'}")
        return 0
    print("usage: python -m server.content export <dir>")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
