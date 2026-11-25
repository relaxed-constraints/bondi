"""PostgreSQL catalog inspection and DDL. Each mutation commits independently."""

import math

from bondi.indexes import FieldIndex

from .indexes import postgres_index_name


def connect(settings, timeout):
    try:
        import psycopg
    except ImportError:
        raise ImportError("Install bondi[postgresql] to manage PostgreSQL indexes") from None
    client = psycopg.connect(
        settings.uri,
        user=settings.username,
        password=settings.password,
        connect_timeout=max(1, math.ceil(timeout)),
        autocommit=True,
    )
    try:
        milliseconds = str(min(2147483647, math.ceil(timeout * 1000)))
        client.execute(
            "SELECT pg_catalog.set_config('statement_timeout', %s, false)", (milliseconds,)
        )
    except BaseException:
        client.close()
        raise
    return client


def inspect(client, collection):
    row = client.execute(
        """SELECT t.oid, t.relkind, t.relispartition FROM pg_catalog.pg_class t
           JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace
           WHERE n.nspname=%s AND t.relname=%s""",
        (collection.schema, collection.table),
    ).fetchone()
    if row is None:
        raise ValueError(f"PostgreSQL table does not exist: {collection.table}")
    oid, kind, partition = row
    if kind != "r" or partition:
        raise ValueError("PostgreSQL index lifecycle requires an ordinary, unpartitioned table")
    return dict(
        client.execute(
            """SELECT c.relname,
                  i.indisprimary OR i.indisunique OR i.indisexclusion OR i.indisreplident
           FROM pg_catalog.pg_index i JOIN pg_catalog.pg_class c ON c.oid=i.indexrelid
           WHERE i.indrelid=%s ORDER BY c.relname""",
            (oid,),
        ).fetchall()
    )


def create(client, collection, index):
    from psycopg import sql

    name = postgres_index_name(collection, index)
    table = sql.Identifier(collection.schema, collection.table)
    # Check relation kind before DDL: creating on a partitioned parent recurses.
    inspect(client, collection)
    if isinstance(index, FieldIndex) or index.method == "btree":
        keys = []
        for key, direction in index.keys:
            if isinstance(index, FieldIndex):
                # Each dotted segment is literal data, even if it contains SQL punctuation.
                path = sql.SQL(", ").join(sql.Literal(segment) for segment in key.split("."))
                expr = sql.SQL("doc #> ARRAY[{}]::text[]").format(path)
            else:
                expr = sql.SQL(key)
            keys.append(
                sql.SQL("({}) {}").format(expr, sql.SQL("ASC" if direction == 1 else "DESC"))
            )
        spec = sql.SQL("btree ({})").format(sql.SQL(", ").join(keys))
    else:
        spec = sql.SQL("gin (({}) pg_catalog.{})").format(
            sql.SQL(index.expression), sql.Identifier(index.operator_class)
        )
    ddl = sql.SQL("CREATE INDEX {} ON {} USING {}").format(sql.Identifier(name), table, spec)
    if not isinstance(index, FieldIndex) and index.condition is not None:
        ddl += sql.SQL(" WHERE ") + sql.SQL(index.condition)
    client.execute(ddl, prepare=True)
    return name


def drop(client, collection, name):
    from psycopg import sql

    # Hold a table lock while rechecking ownership and protection, through commit.
    with client.transaction():
        client.execute(
            sql.SQL("LOCK TABLE ONLY {} IN ACCESS EXCLUSIVE MODE").format(
                sql.Identifier(collection.schema, collection.table)
            )
        )
        existing = inspect(client, collection)
        if name not in existing:
            return False
        if existing[name]:
            raise ValueError(f"Cannot remove protected PostgreSQL index: {name}")
        client.execute(
            sql.SQL("DROP INDEX {} RESTRICT").format(sql.Identifier(collection.schema, name))
        )
    return True
