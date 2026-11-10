# Execution results and summaries

::: bondi.execution.ExecutionResult
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.summary.QuerySummary
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.execution.DatabaseUnavailableError
    options:
      show_root_heading: true
      heading_level: 2

Availability errors have status `"error"`, retaining underlying exceptions as
`__cause__` where available. Probe timing is recorded separately in
`health_check_elapsed_ms`; `elapsed_ms` is zero if preflight prevented execution.
See [health checks](../executor.md#bounded-health-checks).
