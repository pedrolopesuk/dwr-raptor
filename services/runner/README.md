# services/runner (deferred)

Remote/queued execution service. **Not implemented.**

Currently `drw.execution.runner.Runner` executes locally and in-process
(ADR-0004). This directory will host the process-pool / container worker when
long-running or untrusted models make isolation necessary.
