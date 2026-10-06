# CSV ingestion fixtures

These files are **domain-neutral data fixtures** for the M11C CSV adapter tests.
They exist to prove that the same universal observation contract can represent
astrophysics, space, physics, biology and climate data - the adapter only ever
produces ordinary `Variable`s; there is no domain-specific logic anywhere.

* `astrophysics_lightcurve.csv` - time, flux, flux_err
* `space_trajectory.csv` - time, x, y, z, vx, vy, vz
* `physics_response.csv` - x, y, y_lo, y_hi
* `biology_replicates.csv` - time, replicate, concentration, concentration_stderr
* `climate_points.csv` - timestamp, latitude, longitude, altitude, temperature

Units and roles are **not** encoded here; tests supply them explicitly through the
import configuration.
