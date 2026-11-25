# Database deployment

The CLI supports name globs for start, stop and remove; see
[selection and confirmation semantics](../deployment.md#select-deployments-by-name-glob).
Multiple matches display the same Name, Status, URI, Image and Created rows and colors as
`bondi deployment list` before confirmation.
`Deployment.created_at` is a UTC datetime for new deployments and `None` for
older configurations; tables display `—` when it is unknown.
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

::: bondi.deployment.deploy_postgresql
    options:
      show_root_heading: true
      heading_level: 3
