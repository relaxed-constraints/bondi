# Local databases with Docker

Use either database independently or run both. The toolkit and its offline tests
still work without Docker. This setup is for local development, not deployment.

## Start

Install and start Docker Desktop (or an existing Docker Engine with Compose).
On macOS, Docker runs a Linux VM. Allow at least 8 GB of VM memory to run both
services comfortably: the container limits are 2 GB for MongoDB and 4 GB for
Couchbase, plus VM overhead. These are development limits, not benchmark sizing.
Images are pinned to MongoDB 8.0.16 and Couchbase Community 7.6.2; Docker selects
the native architecture. The Couchbase pin is deliberate: Community 8.0.2 failed
a local stop/start test with a bucket-directory migration error. Initial downloads use disk space and can take a few minutes.

Run commands from the repository root:

```sh
# Choose either profile:
docker compose --profile mongodb up -d --wait
docker compose --profile couchbase up -d --wait

# Or start both:
docker compose --profile mongodb --profile couchbase up -d --wait
```

A health check means MongoDB answers ping or Couchbase's management API is up.
Couchbase still needs the initialization step below before SQL++ is usable.
No restart policy is configured; these containers are started explicitly.
Couchbase has a 60-second shutdown grace period, so stopping it may take a minute.

| Service | Host connection | Local data |
| --- | --- | --- |
| MongoDB | `mongodb://127.0.0.1:27017` | Volume `dbrtoolkit_mongodb-data` |
| Couchbase console | <http://127.0.0.1:8091> | Volume `dbrtoolkit_couchbase-data` |
| Couchbase SQL++ HTTP | `http://127.0.0.1:8093/query/service` | Same Couchbase volume |
| Couchbase SDK | `couchbase://127.0.0.1?network=external` | Same Couchbase volume |

All published ports bind to localhost. Port 27017 must be free; an existing MongoDB
on 27018 is unaffected. Couchbase also uses host port 11210 for SDK connections.
If a port is occupied, stop the conflicting service or resolve the conflict before
starting; do not silently redirect examples to another database.

## Initialize and load the sample

```sh
uv run python scripts/init_databases.py mongodb
uv run python scripts/init_databases.py couchbase
# Or initialize both running services:
uv run python scripts/init_databases.py all
```

The script needs Docker and Python, but no host `mongosh`, `mongoimport`, or Couchbase
SDK. MongoDB commands run inside its container. Couchbase uses the HTTP APIs.
Each backend must already be running under this repository's Compose project.

Initialization creates:

- MongoDB `demo.business`, with a `city_stars` index.
- Couchbase bucket `demo`, scope `_default`, collection `business`, with a primary
  index and `city_stars` secondary index. Only Data, Query and Index services run.
- Eight fictional businesses from `dev/business.json`, keyed by `business_id`.
  MongoDB also stores this key in `_id`; Couchbase stores it as the document key.

Running initialization again replaces those eight sample IDs, without removing
other documents. It preserves existing buckets/collections and creates missing
indexes. It then runs a sample query and explain on each backend. It is a sample
loader, not a migration system or a command to reset all your changes.

Couchbase's local-only credentials are **Administrator / dbrtoolkit-local**.
MongoDB has no authentication in this development environment. Do not expose this
configuration on a network. Couchbase credentials persist in its volume; if you
change them through the console, the initializer will not reset them automatically.
Community Edition has its own licensing and telemetry behavior; review the
[official image](https://hub.docker.com/_/couchbase) and
[cluster initialization reference](https://docs.couchbase.com/server/current/rest-api/rest-initialize-cluster.html).

## Try equivalent queries

If installed, host `mongosh` uses port 27017 by default. Otherwise:

```sh
docker compose exec mongodb mongosh demo --quiet --eval \
  'db.business.find({city: "Sydney", stars: {$gte: 4}}, {_id: 0}).toArray()'
```

Open the Couchbase console, sign in, and use the Query workbench:

```sql
SELECT b.*
FROM `demo`.`_default`.`business` AS b
WHERE b.city = 'Sydney' AND b.stars >= 4;
```

Prefix that SQL++ statement with `EXPLAIN` to inspect its plan. You can also use HTTP:

```sh
curl --fail --silent --show-error \
  -u Administrator:dbrtoolkit-local \
  http://127.0.0.1:8093/query/service \
  --data-urlencode 'statement=SELECT b.* FROM `demo`.`_default`.`business` b WHERE b.city = "Sydney" AND b.stars >= 4' \
  --data-urlencode 'scan_consistency=request_plus'
```

`request_plus` waits for indexing to catch up with writes. An HTTP 200 response can
still contain SQL++ errors: check `status` and `errors` in the JSON response.
The initializer checks these fields. Tiny samples demonstrate APIs, not performance.

The existing Yelp notebook targets a different dataset on port 27018; it is not
silently redirected to this synthetic sample. Couchbase execution and explain
parsing in the Python toolkit are the next feature, not part of this setup.

## Stop, restart and remove

```sh
# Stop one service, preserving its container and data:
docker compose stop mongodb
docker compose stop couchbase

# Restart using the profile's up command above. Initialization can be rerun.

# Remove both containers and their network, preserving the data volumes:
docker compose --profile mongodb --profile couchbase down

# Reset BOTH databases, permanently deleting this project's data volumes:
docker compose --profile mongodb --profile couchbase down -v
```

After a reset, start and initialize again. Images remain cached; stopping containers
does not stop Docker Desktop itself. No directories containing your research data
are mounted into the containers.

## Troubleshooting and integration tests

```sh
docker compose --profile mongodb --profile couchbase ps
docker compose logs --tail=80 mongodb
docker compose logs --tail=80 couchbase
```

If Docker cannot connect to its daemon, start Docker Desktop. If Couchbase times out,
check memory allocation and logs. The initializer waits for startup with bounded
retries; repeated errors are surfaced rather than ignored. Allow enough disk space
for both downloaded images and growing database volumes.

To run the existing MongoDB integration test against this disposable setup:

```sh
DBRTOOLKIT_TEST_MONGODB_URI=mongodb://127.0.0.1:27017 \
  uv run pytest tests/test_executor_mongodb.py
```

That test creates and removes its own uniquely named database. Never point it at
a database server where test writes are forbidden. Couchbase integration tests will
arrive with its executor; initialization already verifies a SQL++ query and explain.

## Optional Enterprise evaluation

Community remains the default. An isolated Enterprise 7.6.2 environment is available
for evaluating profiling during toolkit development. It uses a separate Compose
project and volume, so neither its initialization nor cleanup affects Community.
Use it under the applicable Enterprise license; this setup does not establish
permission for ongoing research, teaching, or testing uses. See the
[license terms](https://www.couchbase.com/license-agreement/).

```sh
docker compose -f compose.enterprise.yaml up -d --wait
uv run python scripts/init_databases.py couchbase-enterprise
```

- Console: <http://127.0.0.1:9091>
- Credentials: **Administrator / dbrtoolkit-local**
- Query HTTP endpoint: `http://127.0.0.1:9093/query/service`
- SDK connection: `couchbase://127.0.0.1:11211?network=external`
- Volume: `dbrtoolkit-enterprise_couchbase-data`

This adds another container with a 4 GB memory limit. Initialize with
`couchbase-enterprise` explicitly; `init_databases.py all` still targets only the
default Community and MongoDB environments. The Enterprise node advertises its
separate host ports to SDK clients and uses Plasma index storage.

```sh
# Stop, preserving data:
docker compose -f compose.enterprise.yaml stop
# Remove only the Enterprise environment and its evaluation data:
docker compose -f compose.enterprise.yaml down -v
```

The read-only edition probe can be rerun with an isolated SDK installation:

```sh
uv run --with couchbase==4.6.3 --no-project python \
  scripts/probe_couchbase_profile.py /tmp/couchbase-editions.json
```

Both environments must be initialized. It checks ordinary execution, EXPLAIN,
phase profiling, detailed profiling, a covering query and grouping. Saved responses
and observations are in `dev/probes/`. Enterprise 7.6.2 returned detailed profiles;
Community 7.6.2 silently omitted them. The toolkit API remains unchanged.
