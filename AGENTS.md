# Working on dbrtoolkit

Work as a friendly research peer: explain tradeoffs and challenge assumptions when
appropriate. This project is being built incrementally so the user can understand
each class.

- Read docs/architecture.md and docs/roadmap.md before implementation.
- Stay within the requested step. Do not implement future classes preemptively.
- Discuss new public contracts before implementing them.
- Keep runtime dependencies minimal and avoid dependencies on sibling checkouts.
- Keep research algorithms and experiment pipelines in consumer repositories.
- Use uv, pytest and Ruff. Update documentation with public behaviour changes.
- Run relevant tests, Ruff checks and a strict documentation build for changes.

- Implement new features on a `codex/` feature branch. After checks pass, commit
  the feature and merge it back into `main`. Preserve unrelated user changes.

- Use `Mongo` as the class-name prefix for MongoDB implementations (for example,
  `MongoExecutor`, `AsyncMongoExecutor`, and `MongoSampleEstimator`). Keep the
  `mongodb` module/backend identifier and the MongoDB product name unchanged.
