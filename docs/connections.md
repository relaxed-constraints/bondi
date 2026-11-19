# Connection settings

BONDI separates a database's lifecycle, connection settings and collection names.

- A `Deployment` manages a named local Docker database.
- `MongoConnection` and `CouchbaseConnection` describe how to access an instance.
- `MongoCollectionRef` and `CouchbaseCollectionRef` identify a collection within it.

Connection settings are immutable values. Creating or reading them does not open
an SDK client, check readiness or start Docker. They need no cleanup. Their
representations omit URIs and credentials. Both classes reject non-string URIs
with `TypeError`; URI syntax validation remains with the native driver.

## Managed databases

Use the deployment's `connection` property for database operations:

```python
from bondi import FieldIndex, create_index
from bondi.data import load_demo_data
from bondi.deployment import deploy_mongodb
from bondi.mongodb import MongoCollectionRef, MongoExecutor, MongoFindQuery

deployment = deploy_mongodb(name="research")
connection = deployment.connection
collection = MongoCollectionRef("demo", "business")

load_demo_data(connection=connection, collection=collection)
create_index(connection, collection=collection, index=FieldIndex((("city", 1),)))

with MongoExecutor.from_connection(connection) as executor:
    result = executor.run(MongoFindQuery(collection, {}, limit=5))

deployment.stop()
```

Couchbase uses the same workflow: `deploy_couchbase(...).connection` includes the
URI and credentials required by `CouchbaseExecutor.from_connection()`.
The property is also available while a deployment is stopped; it does not imply
that the database is reachable. Deployment credentials are local administrator
credentials. Construct separate settings to use another database account.

`start()` waits for readiness and returns the deployment; `stop()` returns it
after stopping. `remove()` returns `None`. Closing an executor closes its owned
client; it does not stop or remove the deployment.

## External databases

Import settings from `bondi`:

```python
from bondi import MongoConnection, CouchbaseConnection

mongo = MongoConnection("mongodb://localhost:27017/")
couchbase = CouchbaseConnection(
    "couchbase://localhost",
    username="researcher",
    password=password,
)
```

Supply `password` from your credential source. MongoDB credentials can be in the
URI or supplied as `username=` and `password=`; supplied fields override their URI
counterparts, and omitted fields retain URI settings. Couchbase credentials are
separate from its connection string.

Pass settings as `connection=` to loaders and as the first `connection` argument
to index operations or executor `from_connection()` factories. Backend-specific
operations require the matching settings type. Collection references must also
match the backend. The native driver validates URI syntax when opening its client.

## Client ownership and options

Executors created with `from_connection()` own their clients. Use a context manager
or close them explicitly. Async factories follow their backend's setup semantics:
`AsyncMongoExecutor.from_connection()` constructs an executor without a readiness
probe; await `AsyncCouchbaseExecutor.from_connection()` before entering its async
context. Couchbase setup waits for the Query service.

Native `client_kwargs` (MongoDB) and `cluster_kwargs` (Couchbase) remain available
for driver options. Authentication comes from the connection settings;
`client_kwargs` must not contain `host`, `username` or `password` in any letter
case. `cluster_kwargs` must not contain `authenticator`.

For an existing native async client, construct `AsyncMongoExecutor(client)` or
`AsyncCouchbaseExecutor(cluster)` to borrow it. The caller retains ownership.
MongoDB sample estimators borrow executors and never create a second client.

See the [connection API](reference/connection.md), [execution guide](executor.md)
and [deployment guide](deployment.md).
