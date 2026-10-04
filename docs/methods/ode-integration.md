# Method note: ODE integration

**Implementation:** `drw.numerics.ode.OdeModel` over
`scipy.integrate.solve_ivp`.

## What is computed

First-order systems `dy/dt = f(y, t; p)` on a fixed evaluation grid
`t_eval = linspace(t0, t1, n_points)`.

## Solver selection

| Choice | SciPy method | Use |
| --- | --- | --- |
| `auto` | `RK45` | Safe default for non-stiff systems. |
| `explicit` | `RK45` | Explicit adaptive Runge-Kutta. |
| `stiff` | `BDF` | Implicit, for stiff systems. |

The **actual** method and the tolerances (`rtol`, `atol`) used are recorded as an
`info` diagnostic on every run, so the trajectory is reproducible.

## Verification

* **Reference:** closed-form underdamped oscillator solution
  (`drw.models.oscillator.analytic_displacement`).
* **Tolerance:** `max |x_numeric - x_analytic| < 1e-6` over the default grid, with
  solver `rtol=1e-10`, `atol=1e-13`.
* **Secondary checks:** the Lotka-Volterra conserved quantity is preserved to
  `< 1e-5` over the trajectory; the undamped oscillator conserves energy to
  `< 1e-6` relative.

## When the result is not expected to match

* **Stiff systems** run with an explicit method (`auto`/`explicit`) may take
  impractically small steps or fail; the run is recorded as `FAILED` with
  `solver_failed`, not silently discarded.
* **Chaotic systems** (Lorenz) are only reproducible for a *fixed* configuration.
  A regression assertion on a chaotic trajectory is inherently tolerance-limited:
  the golden tolerance for Lorenz is `1e-3` versus `1e-6` for the non-chaotic
  models. See `tests/scientific/test_lorenz.py`.
* **Non-finite states** (NaN/Inf from `f`) surface as solver failure diagnostics;
  they are never treated as valid output. Even if `solve_ivp` reports
  `success=True`, a solution containing any non-finite value is a `FAILED` run
  with a `non_finite_output` diagnostic and **no outputs** (invariant: a run is
  `SUCCEEDED` only when every output value is finite). See ADR-0006.
* Runs are executed in an isolated child process by default, so a diverging or
  hanging integration is bounded by the wall-clock timeout (ADR-0005).
