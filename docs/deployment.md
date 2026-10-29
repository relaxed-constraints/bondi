# Local database deployments

BONDI can create and manage named local MongoDB and Couchbase instances using Docker Compose.
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
bondi remove demo --keep-data    # Confirm removal; retain data and configuration.
bondi start demo                 # Recreate the container using retained data.
bondi remove demo                # Confirm permanent deletion of data/configuration.
bondi remove demo -y             # Skip confirmation (for automation).
```

`bondi deploy mongodb` defaults to name `mongodb` and port `27017`. Lifecycle
commands require the deployment name, avoiding an ambiguous “last used” instance.
Use `--timeout 300` on deploy/start/stop/remove to increase the operation deadline.
Use `bondi --help` or `bondi remove --help` to inspect command options.

Removal deletes data and saved configuration by default and asks `[y/N]`.
Only `y` or `yes` proceeds; Enter, other answers, or end-of-input cancel removal.
Use `--keep-data` to retain the volume and configuration, and `-y` / `--yes` to
skip confirmation for either mode. Cancellation returns exit code 1.
The Python API is unchanged: `remove()` retains data and
`remove(delete_data=True)` deletes it, without a prompt.
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
restore Docker access and run `bondi remove NAME`.

Failed starts of **existing** deployments never trigger automatic deletion. Their
data and configuration are retained. For a mismatched saved port, inspect the
existing deployment and either use another name or explicitly remove the old one
only when its data is disposable.

A forced process kill or machine crash cannot guarantee cleanup; inspect saved
deployments with `bondi list` before retrying.

MongoDB uses the pinned `mongo:8.0.16` image and binds only to `127.0.0.1`.
This is an unauthenticated local research database. Python and Docker must be on
the same machine; remote Docker contexts are not supported. A script running on
a remote host can use this API with Docker on that host. Readiness is verified
inside the container with a MongoDB ping via its health check.

## Couchbase deployments

Community is the default; Enterprise is available explicitly for users entitled
to use it. This API does not grant an Enterprise license. Both use pinned 7.6.2
images with Data, Query and Index services and a 4 GiB container memory limit.
Allow Docker sufficient memory, especially when running several databases.

```python
from bondi.deployment import deploy_couchbase
from bondi.couchbase import CouchbaseExecutor, CouchbaseQuery

database = deploy_couchbase(name="cb-demo")
print(database.console_url)  # http://127.0.0.1:8091/

with CouchbaseExecutor.from_uri(
    database.uri, username=database.username, password=database.password
) as executor:
    result = executor.run(CouchbaseQuery("SELECT RAW 1"), collect_results=True)
    print(result.documents)  # [1]
```

Deployment needs Docker but no Couchbase SDK. Executing through BONDI requires
`bondi[couchbase]`. Startup waits for management, cluster initialization, a healthy
bucket, and a successful SQL++ query. It creates an empty `demo` bucket (256 MiB,
no replicas), with its default scope and collection. It does **not** insert sample
data or create indexes. Create appropriate indexes before querying stored data.
Pass `bucket="research"` to choose another bucket at creation.

The local console credentials default to **Administrator / bondi-local**.
Use a custom `username`/`password` in Python, or supply a password through an
existing environment variable in the CLI. The CLI displays the default local password after deployment. Custom passwords
are identified by their environment variable rather than printed, and passwords
are excluded from the deployment object's repr. They are stored in plaintext in
`deployment.json`, created with owner-only permissions on POSIX systems. Keep
this state directory private. This is local research infrastructure, not a
production security setup.

```sh
bondi deploy couchbase
bondi status couchbase
bondi logs couchbase
bondi stop couchbase
bondi start couchbase
bondi remove couchbase --keep-data -y
```

Couchbase needs three **distinct** localhost ports. To coexist with another instance:

```sh
bondi deploy couchbase --name cb-other \
  --management-port 9091 --query-port 9093 --kv-port 11211 \
  --edition enterprise --timeout 300

# If MY_CB_PASSWORD is set in your environment:
bondi deploy couchbase --name private-demo --password-env MY_CB_PASSWORD
```

Python equivalents are `management_port`, `query_port`, `kv_port`, and `edition`.
There is no ambiguous Couchbase `--port` option. The returned `uri` uses the KV
port and external network mapping; `console_url` uses the management port.
BONDI configures alternate addresses so SDKs on the host can reach the mapped
query/KV ports. Python and Docker must run on the same machine.

Names are shared across backends: `demo` cannot refer to both MongoDB and Couchbase.
Repeating deployment with conflicting ports, edition, bucket or credentials raises
an error without revealing credential values. Use `get_deployment(name).start()`
or `bondi start NAME` to reuse saved settings. Retained volumes survive stop/start
and container removal/recreation; initialization does not reset existing data or
credentials. New-start failures roll back resources just as for MongoDB.

Implementation references: [cluster initialization](https://docs.couchbase.com/server/7.6/rest-api/rest-cluster-intro.html)
and [alternate addresses](https://docs.couchbase.com/server/7.6/rest-api/rest-set-up-alternate-address.html).


After MongoDB deployment, the CLI prints a `mongosh` connection command and links
for installing [MongoDB Shell](https://www.mongodb.com/docs/mongodb-shell/install/)
and [Database Tools](https://www.mongodb.com/docs/database-tools/installation/)
(`mongoimport`, `mongoexport`, `mongodump`, `mongorestore`). These tools are optional
on the host; BONDI deploys the database through Docker without installing them.
After Couchbase deployment, it prints the console URL, username, password source,
and bucket. The Python API stays quiet and returns these details on the deployment.

## Demo data

Managed deployments start empty. The source checkout includes eight fictional
businesses in `dev/business.json` for the guides and notebooks. Load these documents
into MongoDB's `demo.business` collection or Couchbase's
`demo._default.business` collection before running examples that use them.
For Couchbase, create the `business` collection and appropriate indexes first.
Use the connection details returned by the Python deployment API or printed by
`bondi deploy`. The older `scripts/init_databases.py` script targets the legacy
repository Compose services and must not be used to initialize managed deployments.
