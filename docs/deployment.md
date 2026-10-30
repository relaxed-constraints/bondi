# Local database deployments

BONDI can create and manage named local MongoDB and Couchbase instances using Docker Compose.
Install and start Docker with Compose v2 first. 

## MongoDB deployments

MongoDB uses the pinned `mongo:8.0.16` image and binds only to `127.0.0.1`.
This is an unauthenticated local research database. Python and Docker must be on
the same machine; remote Docker contexts are not supported. A script running on
a remote host can use this API with Docker on that host. Readiness is verified
inside the container with a MongoDB ping via its health check.

### Deploy via Python API

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

### Deploy via command line

The `bondi` command calls the same deployment API. In a uv project, use
`uv run bondi`; in an activated Python environment, use `bondi` directly.
`python -m bondi` is also supported.

```sh
bondi deploy mongodb --name demo   # deploy database with name `demo` 
bondi status demo                  # check status
bondi list                         # show all deployments
bondi logs demo --tail 20          # show recent logs
bondi stop demo                    # stop the deployment
bondi start demo                   # start the deployment
bondi remove demo --keep-data      # remove deployment but keep data
bondi remove demo                  # with confirmation for deletion of data/configuration
bondi remove demo -y               # skip confirmation (for automation)
```

`bondi deploy mongodb` defaults to name `mongodb` and port `27017`. Lifecycle
commands require the deployment name. Use `--timeout 300` on deploy/start/stop/remove
to increase the operation deadline. Use `bondi --help` or `bondi <command> --help` to
inspect command options.

Removal deletes data and saved configuration by default and asks `[y/N]`.
Use `--keep-data` to retain the volume and configuration, and `-y` / `--yes` to
skip confirmation for either mode. Cancellation returns exit code 1.

After MongoDB deployment, the CLI prints a `mongosh` connection command and links
for installing [MongoDB Shell](https://www.mongodb.com/docs/mongodb-shell/install/)
and [Database Tools](https://www.mongodb.com/docs/database-tools/installation/)
(`mongoimport`, `mongoexport`, `mongodump`, `mongorestore`). These tools are optional
on the host; BONDI deploys the database through Docker without installing them.


### Reopen and inspect

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
readiness. A different requested port is rejected. 

### Data ownership and removal

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

### Startup and troubleshooting

Startup defaults to a 120-second deadline, including an initial Docker image pull.
Use `deploy_mongodb(..., timeout=300)` on a slower connection. Before creating a 
deployment, BONDI checks whether it can bind the requested
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

## Couchbase Deployments

For Couchbase deployments, ensure that the `bondi[couchbase]` variant is installed.

Community is the default; Enterprise is available explicitly for users entitled
to use it. This API does not grant an Enterprise license. Both use pinned 7.6.2
images with Data, Query and Index services and a 4 GiB container memory limit.
Allow Docker sufficient memory, especially when running several databases.

### Deployment via Python API

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

Startup waits for management, cluster initialization, a healthy
bucket, and a successful SQL++ query. It creates an empty `demo` bucket (256 MiB,
no replicas), with its default scope and collection. It does **not** insert sample
data or create indexes. Create appropriate indexes before querying stored data.
Pass `bucket="research"` to choose another bucket at creation.

The local console credentials default to **Administrator / bondi-local**.
Use a custom `username`/`password` in Python, or supply a password through an
existing environment variable in the CLI. 

### Deployment via CLI

The CLI displays the default local password after deployment. Custom passwords
are identified by their environment variable rather than printed, and passwords
are excluded from the deployment object's `repr`. They are stored in plaintext in
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
bondi remove couchbase -y
```

After Couchbase deployment, it prints the console URL, username, password source,
and bucket. 


### Alternate ports and editions

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


## Demo data

Managed deployments start empty. Load the eight fictional businesses used by the
guides and notebooks with `load_demo_data()` or `bondi load-demo-data`. The dataset
from `dev/business.json` is bundled with BONDI, so loading needs no source checkout,
network download, or particular working directory. Couchbase loading does not
require the optional Python SDK.

### Python API

```python
from bondi.deployment import get_deployment

mongo = get_deployment("mongo-demo")  # An existing, running MongoDB deployment.
result = mongo.load_demo_data()      # demo.business
print(result.document_count)         # 8

couchbase = get_deployment("cb-demo")  # An existing, running Couchbase deployment.
result = couchbase.load_demo_data(create_primary_index=True)
print(result.database, result.scope, result.collection)  # demo _default business
```

You can also call the method directly on the handle returned by `deploy_mongodb()`
or `deploy_couchbase()`. Loading does not start a stopped deployment: call `start()`
or `bondi start NAME` first.

Optional destinations:

```python
mongo.load_demo_data(database="research", collection="businesses")
couchbase.load_demo_data(scope="research", collection="businesses")
```

MongoDB defaults to database `demo` and collection `business`. Couchbase uses the
bucket saved in the deployment configuration, scope `_default`, and collection
`business`. Missing collections and Couchbase scopes are created automatically.
Destination names accept 1–63 letters, digits, underscores or hyphens and must not
start with a hyphen. The `database` option is MongoDB-only; `scope` and
`create_primary_index` are Couchbase-only. Inappropriate options raise an error.

### Command line

```sh
bondi load-demo-data mongo-demo
bondi load-demo-data cb-demo --create-primary-index

bondi load-demo-data mongo-demo --database research --collection businesses
bondi load-demo-data cb-demo --scope research --collection businesses
```

The CLI uses the saved deployment's backend and connection details and reports the
destination and document count. In a uv project, prefix these commands with `uv run`.

### Repeated loads and indexes

Loading **upserts** the eight documents using `business_id` as MongoDB's `_id` or
Couchbase's document key. Repeated loads create no duplicates. Documents with the
same demo IDs are replaced; unrelated documents are preserved. The returned
`DemoDataResult.document_count` counts documents loaded, including replacements,
rather than newly inserted documents. A failed load may leave partial writes;
retrying is safe. Serialize loads and deployment lifecycle operations.

Couchbase does not create a primary index by default. Use
`create_primary_index=True` or `--create-primary-index` to enable the SQL++ demo
queries. The option is safe to repeat. Leave it off when managing indexes yourself
for an experiment. MongoDB loading creates no additional indexes beyond the
collection's normal `_id` index.
