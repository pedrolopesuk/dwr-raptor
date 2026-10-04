# Example: Lorenz

The Lorenz (1963) chaotic system. This example shows a small grid design (three
values of `rho`) over a system that is deterministic for a fixed configuration yet
sensitive to tiny perturbations.

```bash
python -m drw validate models/examples/lorenz/experiment.yaml
python -m drw run models/examples/lorenz/experiment.yaml --out .drw/lorenz
```

Because the system is chaotic, differences between the baseline and each variant
grow over the integration window; that growth is expected and is exactly what the
delta analysis reports.
