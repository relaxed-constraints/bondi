# Local MongoDB deployments

BONDI can create and manage named local MongoDB instances using Docker Compose.
Install and start Docker with Compose v2 first. The Python package includes its
Compose asset: no repository clone or GitHub download is needed.

```python
from bondi.deployment import deploy_mongodb
from bondi.mongodb import MongoExecutor

# Create/start and wait until MongoDB is healthy.
database = deploy_mongodb(name="demo", port=27019)

with MongoExecutor.from_uri(database.uri) as executor:
    # Use executor.run(), explain(), profile(), etc.
    pass

print(database.status())  # "running"
database.stop()           # Retain data and container.
database.start()          # Wait for readiness again.
```

The default name is `mongodb` and the default port is `27017`. Choose another
port if an existing MongoDB already uses it. Each named deployment has an isolated
Compose project and data volume. These deployments do not adopt or modify the
older repository-level BONDI Compose containers.

## Reopen and inspect

```python
from bondi.deployment import get_deployment, list_deployments

# Loading a handle does not contact Docker or start the database.
database = get_deployment("demo")
print(database.uri)
print(database.image)
print(database.logs(tail=20))

for item in list_deployments():
    print(item.name, item.status())
```

Status is `running`, `starting`, `unhealthy`, `stopped`, or `removed`. Docker
connection failures raise an error rather than appearing as a stopped database.
Repeated `deploy_mongodb()` calls reuse matching configuration and wait for
readiness. A different requested port is rejected. Saved deployments retain their
original image/configuration when BONDI is upgraded; there is no automatic upgrade.

## Data ownership and removal

```python
database.remove()                   # Remove container/network; retain volume.
database.start()                    # Recreate using the retained data.
database.remove(delete_data=True)   # Permanently delete volume and configuration.
```

After deleting data, discard the handle; a new `deploy_mongodb()` creates a fresh
deployment. Retained configurations still appear in `list_deployments()` with
status `removed` when no container exists. There is no automatic cleanup when a
Python block or script ends. Closing an executor closes its connections, not Docker.

Configuration lives in `~/.bondi/deployments`. Set `BONDI_DEPLOYMENT_DIR` before
calling these functions to choose another directory. Keep it stable: the state
path contributes to project identity. Data lives in Docker named volumes, not in
this directory. Do not delete/edit the state directory to manage deployments.
Serialize lifecycle calls for a given deployment; concurrent management of the
same name is not supported.

## Startup and troubleshooting

Startup defaults to a 120-second deadline, including an initial Docker image pull.
Use `deploy_mongodb(..., timeout=300)` on a slower connection. On startup failure,
configuration and any volume are retained so you can inspect `logs()` and retry
`start()`. Forced interruption may leave a container running; use status to inspect it.

MongoDB uses the pinned `mongo:8.0.16` image and binds only to `127.0.0.1`.
This is an unauthenticated local research database. Python and Docker must be on
the same machine; remote Docker contexts are not supported. A script running on
a remote host can use this API with Docker on that host. Readiness is verified
inside the container with a MongoDB ping via its health check.

The CLI and Couchbase deployment API are not implemented yet. Existing manual
Compose instructions remain available in [Local databases](local-databases.md).
