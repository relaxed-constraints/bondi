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

## Command line

The `bondi` command calls the same deployment API. In a uv project, use
`uv run bondi`; in an activated Python environment, use `bondi` directly.
`python -m bondi` is also supported. These deployment features are unreleased;
until the next release, use a source checkout with `uv sync`.

```sh
bondi deploy mongodb --name demo --port 27019
bondi status demo
bondi list
bondi logs demo --tail 20
bondi stop demo
bondi start demo
bondi remove demo                # Retain data and saved configuration.
bondi start demo                 # Recreate the container using retained data.
bondi remove demo --delete-data  # Permanently delete data and configuration.
```

`bondi deploy mongodb` defaults to name `mongodb` and port `27017`. Lifecycle
commands require the deployment name, avoiding an ambiguous “last used” instance.
Use `--timeout 300` on deploy/start/stop/remove to increase the operation deadline.
Use `bondi --help` or `bondi remove --help` to inspect command options.

`--delete-data` is explicit authorization to delete the deployment's data;
there is no additional interactive prompt, so commands work in automated scripts.
Listing includes saved configurations whose containers have been removed.
No command automatically manages another deployment or the older manual Compose setup.

Exit codes are `0` for success, `1` for operational errors (such as unavailable
Docker or missing deployment files), `2` for invalid command syntax, and `130`
for interruption. `status` reports a stopped/removed deployment successfully;
it does not use the exit code as a database health signal. Failed new deployments
are cleaned up automatically. Existing deployments retain
their data and configuration for inspection with `logs` and retries with `start`.

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
Use `deploy_mongodb(..., timeout=300)` on a slower connection. Before creating a deployment, BONDI checks whether it can bind the requested
localhost port. An occupied port fails without creating metadata or Docker resources.
This is an advisory check: Docker can still encounter a port race afterwards.

If a **new** deployment fails during startup (including timeout or Ctrl-C), BONDI
attempts to remove its container, network, volume and metadata. You can then retry
the same name with another port. The startup error is preserved in the diagnostic.
If cleanup fails too, metadata is retained and the error gives a cleanup command;
restore Docker access and run `bondi remove NAME --delete-data`.

Failed starts of **existing** deployments never trigger automatic deletion. Their
data and configuration are retained. For a mismatched saved port, inspect the
existing deployment and either use another name or explicitly remove the old one
with `--delete-data` only when its data is disposable.

A forced process kill or machine crash cannot guarantee cleanup; inspect saved
deployments with `bondi list` before retrying.

MongoDB uses the pinned `mongo:8.0.16` image and binds only to `127.0.0.1`.
This is an unauthenticated local research database. Python and Docker must be on
the same machine; remote Docker contexts are not supported. A script running on
a remote host can use this API with Docker on that host. Readiness is verified
inside the container with a MongoDB ping via its health check.

Couchbase deployment support is not implemented yet. Existing manual Compose
instructions remain available in [Local databases](local-databases.md).
