# Database deployment

The CLI supports name globs for start, stop and remove; see
[selection and confirmation semantics](../deployment.md#select-deployments-by-name-glob).
Multiple matches display the same Name, Status and URI rows and colors as
`bondi deployment list` before confirmation.
Python deployment lookups continue to take exact names.

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
