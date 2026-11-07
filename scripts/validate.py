#!/usr/bin/env python3
"""Validate a JSON file against a named schema.

Usage:
    python scripts/validate.py <schema_name> <json_file>
    python scripts/validate.py response fixtures/netflix.json
    python scripts/validate.py request fixtures/requests/req_netflix.json
    python scripts/validate.py stream-event fixtures/stream_event_sample.json
"""

import json
import sys
from pathlib import Path

try:
    import jsonschema
except ImportError:
    sys.exit("Install jsonschema: pip install jsonschema")

CONTRACTS_DIR = Path(__file__).parent.parent / "contracts"


def load_schema(name: str) -> dict:
    candidates = [
        CONTRACTS_DIR / f"{name}.schema.json",
        CONTRACTS_DIR / f"{name}",
    ]
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text())
    available = [p.stem.replace(".schema", "") for p in CONTRACTS_DIR.glob("*.schema.json")]
    sys.exit(f"Schema '{name}' not found. Available: {', '.join(available)}")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)

    schema_name, json_path_str = sys.argv[1], sys.argv[2]
    json_path = Path(json_path_str)

    if not json_path.exists():
        sys.exit(f"File not found: {json_path}")

    schema = load_schema(schema_name)
    instance = json.loads(json_path.read_text())

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))

    if errors:
        print(f"FAIL  {json_path}  ({len(errors)} error(s)):")
        for err in errors:
            path = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
            print(f"  [{path}] {err.message}")
        sys.exit(1)
    else:
        print(f"OK    {json_path}")


if __name__ == "__main__":
    main()
