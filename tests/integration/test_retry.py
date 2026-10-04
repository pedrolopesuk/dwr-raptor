"""Integration test: retries create new attempts without mutating history."""

from __future__ import annotations

import numpy as np
import pytest

from drw.execution.runner import Runner
from drw.schema.files import load_experiment_spec

pytestmark = pytest.mark.integration


def test_retry_links_new_attempt_and_preserves_original(repo_root):
    spec = load_experiment_spec(
        repo_root / "models" / "examples" / "predator-prey" / "experiment.yaml"
    )
    runner = Runner()
    result = runner.run(spec)
    original = result.runs[1]

    retried = runner.retry(original, spec)

    assert retried.attempt == original.attempt + 1
    assert retried.parent_run_id == original.run_id
    # The original record is unchanged.
    assert original.attempt == 1
    assert original.parent_run_id is None
    assert retried.run_id != original.run_id

    np.testing.assert_allclose(
        np.asarray(retried.result.output("prey").values, dtype=float),
        np.asarray(original.result.output("prey").values, dtype=float),
        rtol=0,
        atol=0,
    )
