from __future__ import annotations

from typing import Any

import pytest
import re

from renus.db.query.ast import escape_like
from renus.db.mongodb.compiler import like_to_regex

from renus.db import (
    Avg,
    Condition,
    ConfigurationError,
    Count,
    DatabaseField,
    Field,
    HavingCondition,
    Include,
    Logical,
    Max,
    Min,
    Operator,
    Path,
    Projection,
    Q,
    Query,
    QueryAST,
    Model,
    RelationAny,
    Sum,
)


class UserAddress(Model):
    street: str
    city: str

class Post(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    title: str
    user_id: int

class User(Model):
    id: int = Field(database=DatabaseField(primary_key=True, generated=True))
    name: str
    age: int
    active: bool = True
    role: str = "member"
    score: float = 0.0
    profile: UserAddress
    posts: list[Post]

def test_equality_and_inequality_operators():
    cond_eq = User.name == "Alice"
    assert isinstance(cond_eq, Condition)
    assert cond_eq.operator == Operator.EQ
    assert cond_eq.path == User.name
    assert cond_eq.value == "Alice"

    cond_ne = User.name != "Bob"
    assert isinstance(cond_ne, Condition)
    assert cond_ne.operator == Operator.NE
    assert cond_ne.path == User.name
    assert cond_ne.value == "Bob"

def test_numeric_comparisons():
    gt = User.age > 18
    assert gt.operator == Operator.GT
    assert gt.value == 18

    ge = User.age >= 21
    assert ge.operator == Operator.GE
    assert ge.value == 21

    lt = User.score < 100.0
    assert lt.operator == Operator.LT
    assert lt.value == 100.0

    le = User.score <= 50.5
    assert le.operator == Operator.LE
    assert le.value == 50.5

def test_set_and_null_predicates():
    in_cond = User.role.in_(["admin", "moderator"])
    assert in_cond.operator == Operator.IN
    assert in_cond.value == ["admin", "moderator"]

    not_in_cond = User.role.not_in(["banned", "suspended"])
    assert not_in_cond.operator == Operator.NOT_IN
    assert not_in_cond.value == ["banned", "suspended"]

    null_cond = User.name.is_null()
    assert null_cond.operator == Operator.IS_NULL
    assert null_cond.value is None

    not_null_cond = User.name.is_not_null()
    assert not_null_cond.operator == Operator.IS_NOT_NULL
    assert not_null_cond.value is None

def test_pattern_and_range_predicates():
    like_cond = User.name.like("Al%")
    assert like_cond.operator == Operator.LIKE
    assert like_cond.value == "Al%"

    regex_cond = User.name.regex(r"^[A-Z][a-z]+$")
    assert regex_cond.operator == Operator.REGEX
    assert regex_cond.value == r"^[A-Z][a-z]+$"

    between_cond = User.age.between(18, 65)
    assert between_cond.operator == Operator.BETWEEN
    assert between_cond.value == (18, 65)

def test_logical_and_or_not_combinations():
    c1 = User.age >= 18
    c2 = User.active == True
    c3 = User.role == "admin"

    and_cond = c1 & c2
    assert isinstance(and_cond, Logical)
    assert and_cond.operator == Operator.AND
    assert and_cond.children == (c1, c2)

    or_cond = c1 | c3
    assert isinstance(or_cond, Logical)
    assert or_cond.operator == Operator.OR
    assert or_cond.children == (c1, c3)

    not_cond = ~c1
    assert isinstance(not_cond, Logical)
    assert not_cond.operator == Operator.NOT
    assert not_cond.children == (c1,)

    compound = (c1 & c2) | c3
    assert compound.operator == Operator.OR
    assert compound.children[0] == and_cond
    assert compound.children[1] == c3

def test_q_expressions():

    q1 = Q(User.age >= 18)
    assert q1.operator == Operator.GE
    assert q1.value == 18

    q_multi = Q(User.age >= 18, User.active == True)
    assert isinstance(q_multi, Logical)
    assert q_multi.operator == Operator.AND
    assert len(q_multi.children) == 2

    q_inv = ~Q(User.role == "banned")
    assert q_inv.operator == Operator.NOT

    combined = Q(User.age >= 18) & Q(User.active == True)
    assert combined.operator == Operator.AND

    with pytest.raises(ValueError, match="at least one condition"):
        Q()

def test_nested_paths():
    bio_path = User.profile.city
    assert isinstance(bio_path, Path)
    assert bio_path.parts == ("profile", "city")
    assert str(bio_path) == "profile.city"

    cond = User.profile.city == "Berlin"
    assert cond.path == bio_path
    assert cond.value == "Berlin"

def test_relationship_any_predicate():
    post_filter = Post.title.like("Python%")
    rel_pred = User.posts.any(post_filter)

    assert isinstance(rel_pred, RelationAny)
    assert rel_pred.relation == User.posts
    assert rel_pred.condition == post_filter

def test_query_projection():
    q = Query(User).select(User.id, User.name)
    assert q.ast.projection is not None
    assert isinstance(q.ast.projection, Projection)
    assert q.ast.projection.paths == (User.id, User.name)

def test_query_ordering():

    ord_asc = User.name.asc()
    assert not ord_asc.descending
    assert ord_asc.path == User.name

    ord_desc = User.age.desc()
    assert ord_desc.descending
    assert ord_desc.path == User.age


    q = Query(User).order_by(User.name.asc(), User.age.desc())
    assert len(q.ast.ordering) == 2
    assert q.ast.ordering[0].path == User.name
    assert not q.ast.ordering[0].descending
    assert q.ast.ordering[1].path == User.age
    assert q.ast.ordering[1].descending

    q_raw = Query(User).order_by(User.name)
    assert len(q_raw.ast.ordering) == 1
    assert not q_raw.ast.ordering[0].descending

def test_offset_limit_pagination():
    q = Query(User).offset(10).limit(20)
    assert q.ast.offset == 10
    assert q.ast.limit == 20

def test_paginate_coerces_untrusted_types():
    q = Query(User).paginate("2", "10")
    assert q.ast.offset == 10
    assert q.ast.limit == 10

def test_paginate_clamps_negative_and_zero():
    q = Query(User).paginate(0, "5")
    assert q.ast.offset == 0
    assert q.ast.limit == 5
    q_neg = Query(User).paginate(1, -5)
    assert q_neg.ast.limit == 0

def test_limit_offset_dialect_coerces_values():
    from renus.db.sqlite.dialect import SQLiteDialect

    dialect = SQLiteDialect()
    sql = dialect.limit_offset("SELECT 1", "5", "10")
    assert sql == "SELECT 1 LIMIT 5 OFFSET 10"
    # Non-numeric expressions now fail closed instead of being interpolated.
    with pytest.raises(ValueError):
        dialect.limit_offset("SELECT 1", "(SELECT CASE WHEN 1=1 THEN 1 ELSE 999999 END)", None)

def test_page_size_pagination():
    q_p1 = Query(User).paginate(page=1, size=25)
    assert q_p1.ast.offset == 0
    assert q_p1.ast.limit == 25

    q_p3 = Query(User).paginate(page=3, size=20)
    assert q_p3.ast.offset == 40
    assert q_p3.ast.limit == 20

    q_neg = Query(User).paginate(page=0, size=10)
    assert q_neg.ast.offset == 0

def test_cursor_pagination():
    cursor_token = {"id": 100, "created_at": "2024-01-01T00:00:00Z"}
    q = Query(User).cursor(cursor_token, field=User.id)
    assert q.ast.cursor == cursor_token
    assert q.ast.cursor_field == User.id

def test_includes():
    q = Query(User).include(User.posts, User.profile)
    assert len(q.ast.includes) == 2
    assert q.ast.includes[0].path == User.posts
    assert q.ast.includes[1].path == User.profile

    nested_inc = Include(User.posts, nested=(Include(Post.title),))
    q_nested = Query(User).include(nested_inc)
    assert q_nested.ast.includes[0].nested[0].path == Post.title

def test_aggregations():

    cnt = Count(User.id)
    assert cnt.function == "count"
    assert cnt.path == User.id
    assert not cnt.distinct

    cnt_dist = Count(User.id, distinct=True)
    assert cnt_dist.distinct is True

    s = Sum(User.score)
    assert s.function == "sum"

    a = Avg(User.age)
    assert a.function == "avg"

    mn = Min(User.score)
    assert mn.function == "min"

    mx = Max(User.score)
    assert mx.function == "max"

def test_query_aggregate_and_group_by():
    q = (
        Query(User)
        .group_by(User.role, User.active)
        .aggregate(
            total_users=Count(User.id),
            avg_age=Avg(User.age),
            max_score=Max(User.score),
        )
    )

    assert q.ast.group_by == (User.role, User.active)
    assert len(q.ast.aggregates) == 3

    aggs = {a.alias: a for a in q.ast.aggregates}
    assert aggs["total_users"].function == "count"
    assert aggs["avg_age"].function == "avg"
    assert aggs["max_score"].function == "max"

def test_having_clauses():
    having_cond = Count(User.id) >= 5
    assert isinstance(having_cond, HavingCondition)
    assert having_cond.operator == Operator.GE
    assert having_cond.value == 5

    q = (
        Query(User)
        .group_by(User.role)
        .having(having_cond)
    )
    assert len(q.ast.having) == 1
    assert q.ast.having[0] == having_cond

def test_soft_delete_and_distinct_flags():
    q_default = Query(User)
    assert not q_default.ast.with_deleted
    assert not q_default.ast.only_deleted

    q_with = q_default.with_deleted()
    assert q_with.ast.with_deleted is True
    assert q_with.ast.only_deleted is False

    q_only = q_default.only_deleted()
    assert q_only.ast.with_deleted is True
    assert q_only.ast.only_deleted is True

    q_dist = q_default.distinct()
    assert q_dist.ast.distinct is True

def test_query_immutability():
    base = Query(User).where(User.active == True)
    q1 = base.where(User.age >= 18).limit(10)
    q2 = base.where(User.age < 18).limit(5)

    assert len(base.ast.filters) == 1
    assert base.ast.limit is None

    assert len(q1.ast.filters) == 2
    assert q1.ast.limit == 10

    assert len(q2.ast.filters) == 2
    assert q2.ast.limit == 5

class FakeRepository:
    def __init__(self, model: type):
        self.model = model
        self.last_ast: QueryAST | None = None

    async def _query(self, ast: QueryAST) -> list[Any]:
        self.last_ast = ast
        return [
            User(
                id=1,
                name="Alice",
                age=25,
                profile=UserAddress(street="A", city="B"),
                posts=[],
            )
        ]

    async def _count(self, ast: QueryAST) -> int:
        self.last_ast = ast
        return 42

    async def _exists(self, ast: QueryAST) -> bool:
        self.last_ast = ast
        return True

    async def delete_many_ast(self, ast: QueryAST) -> int:
        self.last_ast = ast
        return 3

@pytest.mark.asyncio
async def test_unbound_query_execution_raises():
    q = Query(User).where(User.age >= 18)

    with pytest.raises(ConfigurationError, match="without a bound repository"):
        await q.all()

    with pytest.raises(ConfigurationError, match="without a bound repository"):
        await q.first()

    with pytest.raises(ConfigurationError, match="without a bound repository"):
        await q.count()

    with pytest.raises(ConfigurationError, match="without a bound repository"):
        await q.exists()


@pytest.mark.asyncio
async def test_bound_query_execution():
    repo = FakeRepository(User)
    q = Query(repo).where((User.age >= 18) & (User.active == True)).order_by(User.name).limit(20)

    results = await q.all()
    assert len(results) == 1
    assert results[0].name == "Alice"
    assert repo.last_ast is not None
    assert repo.last_ast.limit == 20

    first_res = await q.first()
    assert first_res is not None
    assert first_res.name == "Alice"
    assert repo.last_ast.limit == 1

    count_val = await q.count()
    assert count_val == 42

    assert await q.exists() is True



def test_escape_like_escapes_wildcards_and_escape_char():
    assert escape_like("100%") == "100!%"
    assert escape_like("a_b") == "a!_b"
    assert escape_like("a!b") == "a!!b"
    assert escape_like("john smith") == "john smith"


def test_like_to_regex_treats_wildcards_literally_when_escaped():
    pattern = f"%{escape_like('a_b')}%"
    rx = like_to_regex(pattern)
    assert re.search(rx, "xx a_b yy")
    assert not re.search(rx, "axb")


def test_like_to_regex_percent_literal():
    rx = like_to_regex(f"%{escape_like('100%')}%")
    assert re.search(rx, "discount 100% off")
    assert not re.search(rx, "100 apples")
