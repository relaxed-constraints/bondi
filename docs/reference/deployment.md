# Database deployment

Both deployment functions accept `version: str | None = None`. Explicit numeric
`major.minor.patch` versions select the Docker image for new deployments; omission
reuses an existing image or selects the pinned default for a new name. The selected
version is persisted in `Deployment.image`; conflicting explicit requests fail
without modifying the deployment. See [database versions](../deployment.md#database-versions)
for validation, defaults and legacy metadata behavior.

`deploy_couchbase(memory_limit_mb=4096)` accepts a positive integer container
limit in MiB and exposes it as `Deployment.memory_limit_mb` (None for MongoDB).
It does not change Couchbase service or bucket quotas. See the
[container memory guide](../deployment.md#container-memory) for saved-setting
conflicts, legacy metadata and resizing existing deployments.

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
