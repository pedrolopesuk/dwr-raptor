# Test fixtures

`golden_values.json` is a **numerical regression corpus**, not an external
reference. The values were produced by the reference models at their declared
nominal parameters and are asserted to tight tolerance so that any unintended
change to the integrator, solver mapping or model definitions is caught.

The stronger scientific checks live alongside it and do not depend on this file:

* `tests/scientific/test_oscillator_analytic.py` compares the ODE integration to
  a closed-form solution.
* `tests/scientific/test_predator_prey_invariant.py` asserts the Lotka-Volterra
  conserved quantity is preserved.
* `tests/scientific/test_lorenz.py` asserts determinism and perturbation growth.

Regenerate the corpus only when a change to numerical behaviour is *intended*,
and record that change in `CHANGELOG.md`.
