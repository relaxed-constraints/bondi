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
workload-entry identifier. Patterns and workload weights are distinct from native
query syntax.

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
and follows BSON date/binary normalization. Execution remains future work.

## Open decisions

- License and release policy.
- Remaining native query contracts and their serialization formats.
- Sync versus async execution strategy.
- Schema types and sampling contracts.
- Backend support and compatibility policy.

Package/module names beyond the initial root are provisional.
