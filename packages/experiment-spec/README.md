# @drw/experiment-spec

TypeScript types and a minimal shape guard for the DRW `ExperimentSpec` contract,
plus the generated JSON Schemas under [`schema/`](./schema).

The Python Pydantic models in `packages/core` are the single source of truth.
Regenerate the JSON Schemas after any schema change:

```bash
python scripts/export_schemas.py --out packages/experiment-spec/schema
```

Build and test:

```bash
pnpm --filter @drw/experiment-spec build
pnpm --filter @drw/experiment-spec test
```

`validateExperimentSpecShape` is a fast UI-side guard only; the authoritative
scientific validation happens in Python (`drw.schema.experiment.validate_experiment`).
