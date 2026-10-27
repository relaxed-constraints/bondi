# Queries and workloads

::: dbrtoolkit.query.Query
    options:
      show_root_heading: true
      heading_level: 2

::: dbrtoolkit.workload.WorkloadEntry
    options:
      show_root_heading: true
      heading_level: 2

::: dbrtoolkit.workload.Workload
    options:
      show_root_heading: true
      heading_level: 2

## Sequence access

`len(workload)` returns its entry count, iteration yields `WorkloadEntry` objects,
and `workload[index]` retrieves an entry. Use `entry.query` to access the concrete
query. These operations retain the workload's order and references.
