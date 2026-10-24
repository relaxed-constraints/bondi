# Architecture decisions

## Purpose and ownership

The toolkit owns reusable database interactions and representations. Individual
research projects consume it from separate repositories. Models, embeddings,
training strategies, research-specific evaluation and yanex experiment pipelines
remain in those projects.

The existing index-advisor repository is a source of useful implementations,
not a dependency of the new toolkit. Extract code deliberately and verify its
behaviour against the new contracts. The toolkit should not depend on mdbrtools.

## Native queries first

Represent MongoDB find queries, MongoDB aggregation pipelines and Couchbase
SQL++ queries natively. No database-independent intermediate query representation
is planned. An LLM translation project can consume and produce native queries;
prompts, translation attempts and repair strategies belong in that project.

Structural validity, database acceptance and semantic equivalence are separate
outcomes. A query fingerprint identifies a stored representation, not semantic
equivalence. Version-1 MongoDB find envelopes use Canonical Extended JSON and SHA-256 fingerprints.

## Data and execution boundaries

Saved queries should include logical targets and semantics-affecting options.
Credentials, connections, timeouts, profiling controls and index hints belong in
execution configuration. The precise option boundaries will be reviewed when
implementing each backend.

Workloads preserve order and duplicate entries. A query fingerprint is not a
workload-entry identifier. Pattern membership is separate from native query syntax. Weights are deferred
until a concrete consumer requires them.

Keep execution, explain collection and repeated measurement separate. Preserve
raw explain responses alongside parsed information. Do not force backend plans
into a universal plan tree before a concrete need is established.

## Small contracts, introduced gradually

Prefer dataclasses for data, small protocols for shared behaviour, and composition
for implementation reuse. Implement native query types before finalising their
shared protocol. Shared interfaces must not assume MongoDB syntax.

Schema inference should be usable on local documents without a database. Inferred
schemas describe observations, not guarantees about an entire dataset.

## Dependencies and experiments

Keep runtime dependencies minimal. Backend, notebook and research integrations
will be introduced only as needed. Yanex remains the experiment tracking tool;
the toolkit owns the correctness of any measurement procedure it implements.

## Promoting project code into the toolkit

A candidate should have a concrete cross-project use case, an interface independent
of its originating research method, documented semantics and limitations, focused
tests, a small example, and proportionate dependencies. A second consumer is useful
evidence, not a mandatory prerequisite for obvious shared infrastructure.

## MongoDB collection reference

`MongoCollectionRef` is an immutable value object containing database and collection
names. It has no deployment identity or connection. Both names must be nonempty
strings without null characters; names are preserved exactly. Full server naming
validation is deferred. Equality and hashing use both names. There is no common
backend parent class, namespace parsing or serialization API yet.

## MongoDB find query

`MongoFindQuery` is a mutable dataclass with a required target and filter dictionary,
optional projection, ordered tuple sort, nonnegative skip and optional positive
limit. None represents no limit; zero is rejected. Only integer 1/-1 sorts are
supported initially. Validation is structural and runs at construction, explicitly via validate(), and
before serialization or fingerprinting.
Filter and projection are deep-copied at construction; later assignments and edits
are not intercepted. Queries have value equality but are unhashable. Public to_json(), from_json() and fingerprint() methods own persistence and
representation identity. PyMongo is a required dependency for bson.json_util.
Serialization preserves order, rejects ambiguous Extended JSON document wrappers,
and follows BSON date/binary normalization. Execution is provided by AsyncMongoDBExecutor.

## MongoDB aggregation query

`MongoAggregateQuery` contains a starting collection target and required pipeline
list. It follows the mutable, deep-copy-at-construction contract of MongoFindQuery.
Each top-level stage must have exactly one string key starting with $ followed by
a name. Empty pipelines and write stages are representable. Stage semantics and
nested pipelines are deferred to MongoDB; execution policy is a separate concern.
Collectionless and database-level aggregation are not yet represented.

Both query types use private serialization helpers, without inheriting from each
other. Aggregation uses a version-1 mongodb.aggregate envelope with target and
pipeline, preserving stage and document order. Existing find JSON and fingerprints
remain unchanged.

## Couchbase SQL++ query

`CouchbaseQuery` contains exact statement text, named parameters, positional
parameters and an optional native query-context string. It has no single target
collection. Only one parameter style may be nonempty. It is mutable and unhashable,
with deep-copied parameters at construction and explicit validation thereafter.
Validation accepts plain JSON values and rejects nonfinite floats and cycles;
it does not parse SQL++, check placeholders or assert read-only execution.

Its version-1 couchbase.sqlpp envelope uses standard JSON. Fingerprints include
statement/context text and parameter order without semantic normalization. The
class needs no Couchbase SDK; connections and execution controls remain separate.

## Shared query contract and workloads

The Query protocol declares a class-level backend identifier and instance methods
validate(), to_json() and fingerprint(). Native classes satisfy it structurally;
no inheritance or runtime-checkable protocol is required. Runtime entry validation
checks member availability and delegates to the query, not method signatures.

WorkloadEntry retains a query reference and optional nonnegative integer pattern_id.
IDs are local identifiers, not list positions. Workload shallow-copies its input
list but retains entry/query references, preserving order and duplicates. Explicit
deepcopy is available when isolation is needed. Workload validates a common backend
at construction and on explicit validate(); different MongoDB named databases and
collections may coexist. Empty workloads are valid. Later edits are not intercepted.
Workload.save/load persist one versioned entry per UTF-8 JSONL line. Native query
objects retain their own envelopes and decoding rules. Loading creates independent
objects and reports bad entries with line numbers. Saving uses atomic sibling-file
replacement. Built-in query kinds only are supported; weights and pattern-registry
management remain deferred.

## Async MongoDB executor

A single public executor owns single-query and workload operations; there is no
separate runner class. It accepts a borrowed AsyncMongoClient or creates an owned
one via from_uri, closed through async context management or close(). Inputs are
used by reference and must not be mutated during execution. Workloads prevalidate
all query types and use bounded asyncio workers, returning input-aligned lists of
ExecutionResult or None for unstarted entries. Successful runs consume all cursor
batches, optionally retaining documents. Explain collects queryPlanner diagnostics; profile collects executionStats (or
allPlansExecution) diagnostics. Both return raw responses, without query rows or
automatic parsing, and have corresponding workload methods.

Expected database/timeout failures become workload results; single operations raise.
Stop-on-error drains in-flight operations but stops scheduling. Caller cancellation
and programming errors propagate after cleanup. Status derives from the original
exception. A per-query PyMongo timeout context covers initial execution and cursor
consumption. Native query_kwargs/command_kwargs are supported with reserved-field
checks. There is no write guard, input snapshot, executor retry, warmup or repetition
feature. PyMongo >=4.13 is required for the stable async API.

## Open decisions

- License and release policy.
- Remaining native query contracts and their serialization formats.
- Sync versus async execution strategy.
- Schema types and sampling contracts.
- Backend support and compatibility policy.

Package/module names beyond the initial root are provisional.

## Shared summaries and explicit parsing

`QuerySummary` lives in `dbrtoolkit.summary` and is a frozen six-field value object
returned by the pure
`summarize_explain(raw)` function. The executor continues to return raw documents;
summary extraction is explicit and offline. None means unavailable, not zero.
Winning-plan stages exclude pipeline operators and SBE textual/physical stage names.
Examination counts describe whole-operation work only when scope is understood;
no recursive summation of counters or time estimates. Split pipelines retain final
output counts but may lack other metrics. Sharded and nested-read interpretations
are deferred. Projects keep the raw document for custom fields; no extensibility
registry or universal cross-backend plan model is introduced.

## Local development databases

Opt-in Compose profiles provide separate MongoDB and Couchbase services with pinned
images, localhost ports and named volumes. A shared synthetic fixture is loaded
through native database interfaces. Initialization is repeatable and separate from
container startup; no database dependencies are added to the library. Development
credentials and resource limits are intentionally local-only.

Execution results store native diagnostics in `raw`, optional collected output in
`documents` (including scalar or array rows), and nonfatal operation `warnings`.
They do not contain a parsed summary. Backend parsers remain independently usable
on saved responses; unknown or non-comparable measurements remain `None`.


## Async Couchbase executor

The optional `couchbase` extra supplies the SDK; importing native queries does not
require it. `AsyncCouchbaseExecutor` supports borrowed clusters and an awaited
`from_uri()` factory for owned clusters. All six operations retain the established
workload ordering, concurrency and error policy. No common public executor base
class is introduced.

Run requests basic metrics; explain prefixes SQL++ with EXPLAIN and returns the
native plan; profile requests TIMINGS and returns execution metadata. Run/profile
fully consume rows and optionally retain them, including scalar and array rows.
Missing detailed profiling yields a warning and preserves basic metrics. Metadata
uses public SDK accessors converted to JSON-compatible values; profile trees stay
native. Explicit `summarize_explain()` and `summarize_execution()` functions return
QuerySummary offline without the SDK. Supported native operator trees supply plan
fields; SDK execution_ms/result_count supply time and output counts. Document/index
examination totals stay unavailable. Unknown plan layouts preserve valid basic metrics.

SDK consistency defaults remain in force unless query_kwargs overrides them.
Per-query deadlines cover consumption and SDK execution. Statement bindings,
context and operation modes cannot be overridden through the options escape hatch.
