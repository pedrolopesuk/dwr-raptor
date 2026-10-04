"""Export JSON Schemas for the typed DRW contracts.

The Pydantic models are the single source of truth. This script materializes them
as JSON Schema so the TypeScript workspace package (`@drw/experiment-spec`) and
any external tool can consume the same contract without a Python runtime.

Usage:
    python scripts/export_schemas.py [--out packages/experiment-spec/schema]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from drw.schema.experiment import ExperimentSpec
from drw.schema.model import ModelSchema
from drw.schema.serialization import dumps_pretty

TARGETS = {
    "model-schema.schema.json": ModelSchema,
    "experiment-spec.schema.json": ExperimentSpec,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="packages/experiment-spec/schema")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for filename, model in TARGETS.items():
        path = out / filename
        path.write_text(dumps_pretty(model.model_json_schema()) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
