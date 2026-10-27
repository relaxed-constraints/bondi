"""Readable pattern summaries keep the distinctions used by research logs."""

from bondi.mongodb import MongoCollectionRef, MongoFindQuery, MongoQueryPattern


def test_display_typed_slots_fixed_literals_and_query_options():
    pattern = MongoQueryPattern.from_query(
        MongoFindQuery(
            MongoCollectionRef("demo", "business"),
            {
                "stars": {"$gte": 4},
                "city": {"$in": ["Sydney", "Melbourne"]},
                "missing": {"$exists": False},
                "typed": {"$type": "string"},
                "tags": {"$size": 3},
                "excluded": {"$nin": ["x"]},
                "nullable": None,
            },
            sort=(("stars", -1), ("city", 1)),
            projection={"city": 1, "_id": 0},
            skip=5,
            limit=20,
        )
    )
    assert str(pattern) == (
        "demo.business: city $in <2 × str> AND excluded $nin <1 × str> "
        "AND missing $exists False AND nullable $eq <null> AND stars $gte <int> "
        "AND tags $size <int> AND typed $type 'string' "
        "| sort={'stars': -1, 'city': 1} | projection={'_id': 0, 'city': 1} "
        "| skip=5 | limit=20"
    )
    assert repr(pattern).startswith("MongoQueryPattern(target=MongoCollectionRef(")


def test_print_omits_defaults_and_does_not_expose_sampled_values(capsys):
    target = MongoCollectionRef("demo", "business")
    first = MongoQueryPattern.from_query(MongoFindQuery(target, {"city": "Sydney"}))
    second = MongoQueryPattern.from_query(MongoFindQuery(target, {"city": "Melbourne"}))
    print(first)
    assert capsys.readouterr().out == "demo.business: city $eq <str>\n"
    assert str(first) == str(second)


def test_explicit_empty_projection_is_distinct_from_no_projection():
    pattern = MongoQueryPattern.from_query(
        MongoFindQuery(MongoCollectionRef("demo", "business"), {"x": True}, projection={})
    )
    assert str(pattern) == "demo.business: x $eq <bool> | projection={}"
