# Method note: descriptive uncertainty summary

**Implementation:** `drw.uncertainty` (`compute_uncertainty`,
`uncertainty_for_experiment`). Activated by declaring the `uncertainty` analysis in
an experiment.

## What it computes

For each **scalar** output declared by the model, over the experiment's existing
**variant runs** (the sampled design; the baseline reference is excluded):

| Statistic | Definition |
| --- | --- |
| `requested_variants` | number of sampled variant runs (per-run count) |
| `valid_samples` (`n`) | number of finite scalar values used for this output |
| `excluded_samples` | `requested_variants - valid_samples`, broken down by reason |
| `mean` | arithmetic mean of the valid values |
| `std` | **sample** standard deviation, `ddof = 1` |
| `minimum`, `maximum` | min / max of the valid values |
| `p05`, `p50`, `p95` | 5th / 50th / 95th percentiles |

### Count semantics (summary vs per-output)

`requested_variants` is a **per-run** count. The summary-level
`valid_output_samples` and `excluded_output_samples` are **totals summed across the
declared scalar outputs** ("output-samples"), so a model with more than one scalar
output can legitimately show `valid_output_samples > requested_variants`; the
**per-output** `valid_samples` / `excluded_samples` are authoritative. The CLI, the
report and the UI label the two kinds of count explicitly.

## Quantile algorithm (fixed and recorded)

Percentiles use `numpy.percentile(values, [5, 50, 95], method="linear")` - the
library default: linear interpolation between the two nearest order statistics
(Hyndman & Fan type 7). The method string `"linear"` is stored in the summary
(`quantile_method`) so the numbers can be reproduced.

## Sampling assumptions

The summary describes the **sampling design the experiment already ran**: inputs
are drawn independently and uniformly over the declared factor bounds (exactly as
`drw.numerics.sampling.expand_design` draws them). No prior distribution is
defined and no distribution is fitted. A `grid` design is flagged
(`note`) because its nodes are not a random sample.

## Exclusions and failure semantics

Every variant run is accounted for; nothing is fabricated or replaced with zero:

* `run_failed` - the run did not succeed;
* `run_timed_out` - the run hit its wall-clock timeout;
* `output_missing` - the scalar output was not produced by that run;
* `non_finite` - the value was `NaN`/`Inf` (runs are already `FAILED` with no
  outputs per ADR-0006; this is defence in depth).

With **fewer than two** valid samples the standard deviation is `null` and the
output is flagged `sufficient = false`; with **zero** valid samples every
statistic is `null` (`note = "no valid samples: statistics are undefined"`). A
model with **no scalar outputs** yields an empty summary with an explicit note
(`"no scalar outputs are declared: there is nothing to summarize"`).

## Determinism and reproducibility

Given the same design (method, `n_samples`, `seed`) and the same model/code/
environment, the summary is deterministic - it is a pure function of the run
metrics. It inherits the project's existing reproducibility limitations (no
cross-machine/cross-platform bitwise guarantee).

## Evidence and interfaces

* **Evidence:** an additive `uncertainty.json` artifact (manifest kind
  `uncertainty`) is added **only when the summary exists**; it is SHA-256 hashed
  and covered by `drw verify`. Experiments without the analysis are unchanged
  (the manifest `files` list does not change).
* **Core:** `Runner` attaches the summary to the result when declared; the stored
  `results.json` gains an `uncertainty` key only for such experiments.
* **CLI:** `drw uncertainty <experiment_id> [--workspace <dir>]` (read-only).
* **Bridge:** `uncertainty` op (read-only), computed from stored runs.
* **Web:** the results view shows an "Uncertainty" tab with a descriptive-only
  banner.

## What this is **not**

Not a probability distribution, a confidence interval, a Bayesian posterior, a
global (variance-based) Sobol sensitivity analysis, or scientific validation.
Confidence intervals and global sensitivity are explicitly out of scope for this
milestone.
