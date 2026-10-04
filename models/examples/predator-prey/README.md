# Example: predator-prey

The Lotka-Volterra predator-prey system. This example is the smallest complete
DRW workflow: a baseline, one perturbed variant, a differential comparison and an
evidence package.

```bash
# Validate without executing
python -m drw validate models/examples/predator-prey/experiment.yaml

# Execute and export evidence
python -m drw run models/examples/predator-prey/experiment.yaml --out .drw/predator-prey
```

The model declares a conserved quantity (`V = delta*x - gamma*ln(x) + beta*y -
alpha*ln(y)`); the scientific test suite asserts the integrator preserves it.
