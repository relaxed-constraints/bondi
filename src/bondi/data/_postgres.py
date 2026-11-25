"""Synchronous writer for BONDI JSONB tables."""

from functools import partial

from ._writers import InsertBatchError


class PostgresWriter:
    backend = "postgresql"

    def __init__(self, target):
        try:
            import psycopg
            import simplejson
            from psycopg import sql
            from psycopg.types.json import Jsonb
        except ImportError:
            raise ImportError("Install bondi[postgresql] to load PostgreSQL collections") from None
        self.sql = sql
        self.jsonb = partial(
            Jsonb, dumps=partial(simplejson.dumps, use_decimal=True, allow_nan=False)
        )
        self.driver = psycopg
        self.client = psycopg.connect(target.uri, user=target.username, password=target.password)

    def preflight(self, dest, quota):
        schema, _, table = dest
        self.table = self.sql.Identifier(schema, table)
        relation = self.table.as_string(self.client)
        # Existing document tables only require their normal read/write privileges.
        if self.client.execute("SELECT to_regclass(%s)", (relation,)).fetchone()[0] is None:
            schema_exists = self.client.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)
            ).fetchone()
            if schema_exists is None:
                self.client.execute(
                    self.sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                        self.sql.Identifier(schema)
                    )
                )
            self.client.execute(
                self.sql.SQL(
                    "CREATE TABLE IF NOT EXISTS {} (document_id text PRIMARY KEY, "
                    "doc jsonb NOT NULL CHECK (jsonb_typeof(doc) = 'object'))"
                ).format(self.table)
            )
        self.client.execute(
            self.sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(self.table)
        )
        columns = self.client.execute(
            """SELECT a.attname, a.atttypid::regtype::text, a.attnotnull
               FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
               WHERE c.oid = %s::regclass AND c.relkind = 'r' AND a.attnum > 0
                 AND NOT a.attisdropped AND NOT c.relhassubclass AND NOT c.relispartition
                 AND NOT c.relrowsecurity AND a.attgenerated = ''""",
            (relation,),
        ).fetchall()
        constraints = self.client.execute(
            """SELECT contype::text, pg_get_constraintdef(oid) FROM pg_constraint
               WHERE conrelid = %s::regclass AND convalidated""",
            (relation,),
        ).fetchall()
        if (
            set(columns) != {("document_id", "text", True), ("doc", "jsonb", True)}
            or ("p", "PRIMARY KEY (document_id)") not in constraints
            or ("c", "CHECK ((jsonb_typeof(doc) = 'object'::text))") not in constraints
        ):
            raise ValueError("Incompatible PostgreSQL document table")
        return (
            self.client.execute(
                self.sql.SQL("SELECT 1 FROM {} LIMIT 1").format(self.table)
            ).fetchone()
            is not None
        )

    def prepare(self, dest, mode):
        if mode == "replace":
            self.client.execute(self.sql.SQL("TRUNCATE TABLE {}").format(self.table))
        self.client.commit()

    def insert_batch(self, dest, batch):
        try:
            with self.client.transaction(), self.client.cursor() as cur:
                with cur.copy(
                    self.sql.SQL("COPY {} (document_id, doc) FROM STDIN").format(self.table)
                ) as copy:
                    for key, doc in batch:
                        copy.write_row((key, self.jsonb(doc)))
        except self.driver.Error as exc:
            raise InsertBatchError(0, self.client.broken, type(exc).__name__) from None

    def upsert_one(self, dest, key, doc):
        with self.client.transaction():
            self.client.execute(
                self.sql.SQL(
                    "INSERT INTO {} (document_id, doc) VALUES (%s,%s) ON CONFLICT (document_id) "
                    "DO UPDATE SET doc = excluded.doc"
                ).format(self.table),
                (key, self.jsonb(doc)),
            )

    def close(self):
        self.client.close()
