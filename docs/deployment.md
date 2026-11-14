# Local database deployments

BONDI creates named MongoDB and Couchbase deployments with Docker Compose.
You can use either the command-line interface (CLI) or the Python API.
Both methods create the same kind of deployment and share its saved settings.

Start Docker with Compose v2 before you continue.
Python and Docker must run on the same machine.
Remote Docker contexts are not supported.
You can run BONDI on a remote server if Docker also runs there.

Each deployment has its own container, Compose project and data volume.
Choose a unique name and unused ports for each deployment.

## Deploy via command line

Use `bondi` in an activated Python environment.
In a uv project, use `uv run bondi`.
You can also use `python -m bondi`.

Create a MongoDB deployment:

```sh
bondi deployment create mongodb --name mongo-demo
```

Choose a different port or database version:

```sh
bondi deployment create mongodb --name mongo-other --port 27019 --version 8.0.16
```

Create a Couchbase deployment with a bucket named `research`:

```sh
bondi deployment create couchbase --name cb-demo --bucket research
```

Choose another Couchbase edition and separate ports:

```sh
bondi deployment create couchbase --name cb-other --edition enterprise \
  --management-port 9091 --query-port 9093 --kv-port 11211
```

Use Enterprise only if your license permits it.
BONDI does not provide an Enterprise license.

Deployment commands wait until the database is ready.
They print connection details when startup succeeds.
Use `bondi deployment create mongodb --help` or `bondi deployment create couchbase --help` to see all options.

## Deploy via Python API

The API returns a `Deployment` object with connection details and lifecycle methods.

```python
from bondi.deployment import deploy_mongodb, deploy_couchbase

mongo = deploy_mongodb(name="mongo-demo")
print(mongo.uri)

couchbase = deploy_couchbase(name="cb-demo", bucket="research")
print(couchbase.uri)
print(couchbase.console_url)
```

These are alternatives to the CLI examples above.
Matching requests reuse the same saved deployments.

Pass options as keyword arguments:

```python
mongo_other = deploy_mongodb(
    name="mongo-other",
    port=27019,
    version="8.0.16",
    timeout=300,
)

cb_other = deploy_couchbase(
    name="cb-other",
    edition="enterprise",
    management_port=9091,
    query_port=9093,
    kv_port=11211,
)
```

Use the returned details to create an executor:

```python
from bondi.mongodb import MongoExecutor

with MongoExecutor.from_uri(mongo.uri) as executor:
    # Run queries here.
    pass
```

For Couchbase executors, install `bondi[couchbase]`:

```python
from bondi.couchbase import CouchbaseExecutor, CouchbaseQuery

with CouchbaseExecutor.from_uri(
    couchbase.uri,
    username=couchbase.username,
    password=couchbase.password,
) as executor:
    result = executor.run(CouchbaseQuery("SELECT RAW 1"), collect_results=True)
    print(result.documents)  # [1]
```

Deployment itself does not require the optional Couchbase SDK.
See the [execution guide](executor.md) for queries, explain and profiling.

## Inspect, stop and restart

Use the saved deployment name for lifecycle commands:

```sh
bondi deployment list
bondi deployment status mongo-demo
bondi deployment logs mongo-demo --tail 20
bondi deployment stop mongo-demo
bondi deployment start mongo-demo
```

The Python API provides the same operations:

```python
from bondi.deployment import get_deployment, list_deployments

database = get_deployment("mongo-demo")
print(database.uri)
print(database.image)
print(database.status())
print(database.logs(tail=20))

database.stop()
database.start()

for item in list_deployments():
    print(item.name, item.status())
```

`get_deployment()` reads saved configuration. It does not contact Docker or start the database.
`stop()` retains the container and data.
`start()` reuses saved settings and waits for readiness.
Closing an executor does not stop Docker.
Scripts and Python blocks do not remove deployments when they end.

| Status | Meaning |
|---|---|
| `running` | The container and required readiness checks pass |
| `starting` | The container runs, but readiness checks do not yet pass |
| `unhealthy` | Docker reports repeated health-check failures while the container runs |
| `stopped` | The container exists but does not run |
| `removed` | No container exists, but saved configuration remains |

Docker access errors raise an error. They do not appear as `stopped`.
For removed containers, the CLI checks whether the data volume still exists.
It shows `removed (data retained)` when that volume exists.
This checks volume presence, not data integrity.
A failed volume check reports an error.

The CLI shows running deployments in green and unhealthy deployments in red.
Starting and stopped deployments use yellow.
Removed deployments use dim grey.
Redirected output has no automatic colour. Raw logs keep their original text.

## Data ownership and removal

**Removal deletes data and saved configuration by default.**

The CLI asks for confirmation:

```sh
bondi deployment remove mongo-demo
```

Use `--keep-data` to retain the data volume and configuration:

```sh
bondi deployment remove mongo-demo --keep-data
bondi deployment start mongo-demo
```

Use `-y` or `--yes` to skip confirmation in either removal mode.
Cancellation returns exit code 1.

Python removal does not ask for confirmation:

```python
database.remove(keep_data=True)  # Retain data and configuration.
database.start()  # Recreate the container with that data.
database.remove()  # Delete data and configuration.
```

After default removal, discard the old Python handle.
Deploy again to create a fresh database.
Retained configurations remain in `list_deployments()` even when their containers are absent.

Configuration lives in `~/.bondi/deployments`.
Set `BONDI_DEPLOYMENT_DIR` before using the API to choose another location.
Keep this path stable because it contributes to each Compose project identity.
Data lives in Docker named volumes, outside this directory.

Use BONDI lifecycle commands to manage deployments.
Do not delete the configuration directory as a substitute for removal.
Edit saved files only for the explicit memory-resizing procedure below.
Do not manage the same deployment concurrently from multiple processes.

## MongoDB deployments

The default deployment name is `mongodb` and the default port is `27017`.
New deployments use `mongo:8.0.16` unless you select another version.
MongoDB binds to `127.0.0.1` and runs without authentication for local research.
BONDI checks readiness with a MongoDB ping inside the container.

Repeated deployment requests reuse matching settings.
Conflicting ports or images raise an error.
Memory settings have separate reuse rules, described below.
Managed deployments do not adopt older repository-level Compose containers.

After deployment, the CLI prints a `mongosh` command and installation links for
[MongoDB Shell](https://www.mongodb.com/docs/mongodb-shell/install/) and
[Database Tools](https://www.mongodb.com/docs/database-tools/installation/).
The tools include `mongoimport`, `mongoexport`, `mongodump` and `mongorestore`.
They are optional host tools. BONDI does not need them to deploy MongoDB.

## Couchbase deployments

Before creating a missing bucket, BONDI waits for healthy nodes and a successful
`SELECT RAW 1` query. The checks share the startup timeout and use no fixed delay.
This avoids the first-bucket startup issue reproduced with Community 8.0.0.
It does not repair existing bucket directories that already conflict.

The default name is `couchbase`. Community is the default edition.
New deployments use version `7.6.2` unless you select another version.
They enable the Data, Query and Index services.

Startup waits for management access, cluster initialization, a healthy bucket and a successful SQL++ query.
It creates an empty `demo` bucket with a 256 MiB quota and no replicas.
The bucket contains its default scope and collection.
Deployment does not insert sample data or create indexes.
Use `bucket="research"` or `--bucket research` to select another bucket at creation.

### Ports and credentials

Couchbase needs three distinct localhost ports:

| Service | Python option | CLI option | Default |
|---|---|---|---|
| Management console | `management_port` | `--management-port` | 8091 |
| Query | `query_port` | `--query-port` | 8093 |
| Key-value | `kv_port` | `--kv-port` | 11210 |

There is no Couchbase `--port` option.
`uri` uses the key-value port. `console_url` uses the management port.
BONDI configures alternate addresses so host SDKs can reach mapped query and key-value ports.

Default credentials are `Administrator` / `bondi-local`.
Pass `username` and `password` in Python to choose other credentials.
The CLI can read a password from an existing environment variable:

```sh
bondi deployment create couchbase --name private-demo --password-env MY_CB_PASSWORD
```

The CLI prints the default password for local demos.
For custom passwords, it prints the environment variable name instead.
A deployment object's representation excludes passwords.
However, `deployment.json` stores credentials in plaintext.
BONDI creates it with owner-only permissions on POSIX systems.
Keep this directory and its backups private.
These deployments are for local research, not production security.

Deployment names must be unique across backends.
For example, `demo` cannot name both a MongoDB deployment and a Couchbase deployment.
Conflicting ports, edition, bucket or credentials cause an error.
Error messages do not reveal credential values.
Stop/start and container recreation preserve existing data and credentials.

For implementation details, see Couchbase's
[cluster initialization](https://docs.couchbase.com/server/7.6/rest-api/rest-cluster-intro.html)
and [alternate addresses](https://docs.couchbase.com/server/7.6/rest-api/rest-set-up-alternate-address.html) documentation.

## Load data

Deployments start empty.
Use the [dataset loading guide](datasets.md) to load files, Python documents or Hugging Face datasets.

### Demo data

Use [demo dataset loading](datasets.md#load-the-packaged-demo) to load eight
fictional businesses. Data loading is separate from deployment management.

## Database versions

Use a numeric `major.minor.patch` version:

```python
mongo = deploy_mongodb("example-mongo", version="8.0.16")
cb = deploy_couchbase("example-cb", version="7.6.12", edition="enterprise")
print(mongo.image)  # mongo:8.0.16
print(cb.image)  # couchbase:enterprise-7.6.12
```

```sh
bondi deployment create mongodb --name example-mongo --version 8.0.16
bondi deployment create couchbase --name example-cb --version 7.6.12 --edition enterprise
```

For new names, omission selects MongoDB 8.0.16 or Couchbase 7.6.2.
For saved names, omission reuses the saved image.
An explicit version must match that image exactly.
Otherwise, BONDI rejects the request before contacting Docker or changing files.
Other settings must also match, subject to the MongoDB memory rules below.

BONDI rejects aliases such as `latest`, partial versions, suffixes and arbitrary image references.
A valid version string does not guarantee an available image or compatible initialization.
Docker resolves the tag at startup.
BONDI reports Docker errors, such as missing images or unsupported platforms.
It does not discover available versions.

The saved `image` field records the selected image.
It is not a measurement of the running server.
Older configurations and custom saved images remain usable when you omit the version.
Reuse, stop/start and removal with retained data preserve saved Compose files.

Deployment does not upgrade databases, downgrade databases or migrate data.
Use a new name and free ports for a different version.
Use `bondi deployment start NAME` or `get_deployment(NAME).start()` to reuse all saved settings.

## MongoDB memory limits

For a new deployment, you can set the container cap and WiredTiger cache separately:

```python
db = deploy_mongodb(
    "mongo-limited",
    port=27020,
    memory_limit_mb=1024,
    wiredtiger_cache_size_gb=0.25,
)
```

```sh
bondi deployment create mongodb --name mongo-limited --port 27020 \
  --memory-limit-mb 1024 --wiredtiger-cache-size-gb 0.25
bondi deployment status mongo-limited
```

| Option | Meaning | Accepted values |
|---|---|---|
| `memory_limit_mb` | Container memory cap in MiB | Positive integer |
| `wiredtiger_cache_size_gb` | WiredTiger cache in GiB | Finite number from 0.25 to 10000 |

Booleans are not valid values.
MongoDB names its cache option `--wiredTigerCacheSizeGB`.
An explicit cache must be smaller than an explicit container cap for a new deployment.
This check does not guarantee enough spare memory.
Queries, other server components and filesystem caching also need memory.
BONDI does not select a spare-memory percentage or change Docker Desktop's memory allocation.

Both options default to `None`.
A new deployment then has no explicit container cap and uses automatic MongoDB cache sizing.
For an existing deployment, `None` retains its saved setting.

For different valid memory values on an existing deployment, BONDI warns and ignores the requested changes.
Omitted or matching values produce no warning.
Invalid individual values still fail validation.
BONDI checks whether the cache fits the cap only for new deployments.
Port and image conflicts still raise errors.

Both values persist in `deployment.json` and appear on the `Deployment` object.
Stop/start retains them.
`bondi deployment status` reports saved settings, not current resource use.
Older metadata without these fields reports `None`, shown as “not explicitly saved”.
A manually edited Compose file can still contain limits.

BONDI does not rewrite existing Compose files or infer settings from manual edits.
Passing a matching option does not adopt a manual override.
Use a new name and free port for a deployment with different memory settings.
Do not delete an existing database merely to apply these options.

## Container memory

Couchbase defaults to a 4096 MiB container cap.
Set another cap when you create it:

```python
database = deploy_couchbase(name="cb-large", memory_limit_mb=16384)
print(database.memory_limit_mb)  # 16384
```

```sh
bondi deployment create couchbase --name cb-large --memory-limit-mb 16384
```

These are alternative ways to create the same deployment.
The value must be a positive integer in MiB.
It limits the container, not individual Couchbase service or bucket quotas.
Initialization still uses small demo allocations.

Configure experiment-specific quotas separately.
Leave room for Query and other services.
For example, 8192 MiB for Data plus 1024 MiB for Index exceeds a 4096 MiB container cap.
Docker also needs enough memory for other running databases.
Increasing Docker Desktop's allocation alone does not change the container cap.

Conflicting Couchbase memory requests fail before contacting Docker.
Repeat the saved limit when calling `deploy_couchbase`.
Alternatively, use `bondi deployment start NAME` or `get_deployment(NAME).start()`.
Older metadata without a memory field uses 4096 MiB.
Saved Compose files, including manual overrides, remain unchanged.
The handle reports saved settings, not current Docker usage.

### Resize an existing Couchbase deployment

This procedure retains data. It changes saved configuration directly.

1. Stop the deployment with `bondi deployment stop NAME`.
2. Ensure no other process manages this deployment during the change.
3. Copy `deployment.json` and `compose.json` from `~/.bondi/deployments/NAME` to a private backup location.
   Use your `BONDI_DEPLOYMENT_DIR` instead if configured. These files can contain credentials.
4. Set `"memory_limit_mb": 16384` at the top level of `deployment.json`.
5. Set `"mem_limit": "16384m"` under `services.couchbase` in `compose.json`.
   Preserve the project identity, volumes and all other fields.
6. Run `bondi deployment start NAME --timeout 300`.
7. Reload any existing Python deployment handle.

Compose recreates the container with the same named volume.
BONDI waits for readiness.
Do not use `bondi deployment remove NAME` to resize because its default deletes data.
If startup fails, the saved deployment's configuration and data remain available for recovery.

## Startup and troubleshooting

Default startup deadlines are 120 seconds for MongoDB and 300 seconds for Couchbase.
These include the initial image download.
Use `timeout=300` in Python or `--timeout 300` in the CLI to allow more time.
Start, stop and remove also accept a timeout.

Before creating a deployment, BONDI checks whether the requested localhost ports are free.
An occupied port fails before BONDI creates saved configuration or Docker resources.
Another process can still take a port after this check.

If a new deployment fails during startup, BONDI attempts to remove all its new resources.
This includes failures from a timeout or Ctrl-C.
The diagnostic retains the startup error.
You can retry with another port after successful cleanup.

If cleanup also fails, BONDI retains configuration and provides a cleanup command.
Restore Docker access before running `bondi deployment remove NAME`.
A failed start of an existing deployment never causes automatic data deletion.
Inspect saved settings before choosing another name or removing disposable data.

A forced process kill or machine crash can prevent cleanup.
Check `bondi deployment list` before retrying.

CLI errors go to stderr:

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | Operation failed or user cancelled removal |
| 2 | Invalid command syntax |
| 130 | Interrupted |

For method signatures, see the [deployment API reference](reference/deployment.md).

Deployment port checks allow recently closed TCP connections (`TIME_WAIT`).
An active listener still prevents a new deployment from using that port.
Docker performs the final port binding; the check does not reserve the port.
