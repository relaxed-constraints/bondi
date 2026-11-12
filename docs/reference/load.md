# Load generation

See the [load generation guide](../load-generation.md) for phase, callback,
selection and cancellation contracts. The `generate_load()` methods are listed
under the [MongoDB](mongodb/executors.md) and [Couchbase](couchbase/executors.md)
executor references.

::: bondi.load.LoadResult
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.load.WeightedRandom
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.load.UniformRandom
    options:
      show_root_heading: true
      heading_level: 2

::: bondi.load.Sequential
    options:
      show_root_heading: true
      heading_level: 2

## Callback function types

Pass your own function as `on_result`; these aliases describe its signature.
Both receive one [LoadResult][bondi.load.LoadResult]. Synchronous executors accept
ordinary functions, while async executors also accept `async def` functions.

::: bondi.load.SyncLoadCallback
    options:
      show_root_heading: true
      heading_level: 3

::: bondi.load.LoadCallback
    options:
      show_root_heading: true
      heading_level: 3

::: bondi.load.ByPattern
    options:
      show_root_heading: true
      heading_level: 2
