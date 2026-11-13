# Database deployment

For command names, options and output behaviour, see the
[CLI guide](../deployment.md#deploy-via-command-line).
The CLI adds retained-volume information to `removed`; `Deployment.status()`
continues to return the plain status string.
Use `bondi --help` or `bondi COMMAND --help` for the command reference.

Both deployment functions accept `version: str | None = None`. Explicit numeric
`major.minor.patch` versions select the Docker image for new deployments; omission
reuses an existing image or selects the pinned default for a new name. The selected
version is persisted in `Deployment.image`; conflicting explicit requests fail
without modifying the deployment. See [database versions](../deployment.md#database-versions)
for validation, defaults and legacy metadata behavior.

`deploy_couchbase(memory_limit_mb=4096)` accepts a positive integer container
limit in MiB and exposes it as `Deployment.memory_limit_mb` (also configurable for MongoDB).
It does not change Couchbase service or bucket quotas. See the
[container memory guide](../deployment.md#container-memory) for saved-setting
conflicts, legacy metadata and resizing existing deployments.

MongoDB additionally accepts `memory_limit_mb: int | None = None` and
`wiredtiger_cache_size_gb: float | None = None`. Cache values are finite numbers
from 0.25 to 10000 GiB; container caps are positive integer MiB. New deployments
require the cache to be smaller than the container cap after unit conversion. Omitted values preserve
defaults for new deployments and existing settings for reused deployments.
Differing explicit MongoDB memory values emit `UserWarning` and are ignored.
This differs from Couchbase, where memory conflicts still raise `ValueError`.
The handle exposes both saved values; legacy MongoDB metadata yields `None`.
See [MongoDB memory limits](../deployment.md#mongodb-memory-limits) for units,
warnings, manual-override limitations and CLI examples.

::: bondi.deployment.deploy_mongodb
    options:
      show_root_heading: true
      heading_level: 3

::: bondi.deployment.deploy_couchbase
    options:
      show_root_heading: true
      heading_level: 3

::: bondi.deployment.get_deployment
    options:
      show_root_heading: true
      heading_level: 3

::: bondi.deployment.list_deployments
    options:
      show_root_heading: true
      heading_level: 3

::: bondi.deployment.Deployment
    options:
      show_root_heading: true
      heading_level: 3

::: bondi.deployment.DemoDataResult
    options:
      show_root_heading: true
      heading_level: 3
