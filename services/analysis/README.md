# services/analysis (deferred)

Analysis service. **Not implemented as a service.**

Differential analysis currently lives in `drw.numerics.delta` and
`drw.numerics.metrics` and runs inside the local execution flow. A separate
service would only be justified once analyses are expensive enough to schedule
independently.
