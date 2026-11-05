"""SQLite persistence layer built on Python's standard ``sqlite3`` module.

The application used to depend on Flask-SQLAlchemy.  This module replaces that
dependency with a small, focused persistence layer that keeps the same
declarative model style (``db.Model``, ``db.Column``, ``db.session`` ...), but
generates and executes plain SQL through the standard-library ``sqlite3``
driver.  No third-party ORM is imported anywhere in the project.

Only the features used by this application are implemented; the goal is a
clear academic implementation rather than a general purpose ORM.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, time
from decimal import Decimal

from flask import current_app, g, has_app_context

# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
_MODELS: dict[str, type] = {}
_TABLES: dict[str, type] = {}
_TABLE_RANK: dict[str, int] = {}


# ---------------------------------------------------------------------------
# column types
# ---------------------------------------------------------------------------
class _Type:
    sqlite_type = "TEXT"

    def to_db(self, value):
        return value

    def from_db(self, value):
        return value


class IntegerType(_Type):
    sqlite_type = "INTEGER"

    def to_db(self, value):
        return None if value is None else int(value)

    def from_db(self, value):
        return None if value is None else int(value)


class FloatType(_Type):
    sqlite_type = "REAL"

    def to_db(self, value):
        return None if value is None else float(value)

    def from_db(self, value):
        return None if value is None else float(value)


class NumericType(_Type):
    sqlite_type = "REAL"

    def __init__(self, precision=None, scale=None):
        self.precision = precision
        self.scale = scale

    def to_db(self, value):
        if value is None:
            return None
        return float(value)

    def from_db(self, value):
        if value is None:
            return None
        return Decimal(str(value)).quantize(Decimal("0.01"))


class StringType(_Type):
    sqlite_type = "TEXT"

    def __init__(self, length=None):
        self.length = length

    def to_db(self, value):
        return None if value is None else str(value)

    def from_db(self, value):
        return value


class BooleanType(_Type):
    sqlite_type = "INTEGER"

    def to_db(self, value):
        if value is None:
            return None
        return 1 if value else 0

    def from_db(self, value):
        return None if value is None else bool(value)


class DateTimeType(_Type):
    sqlite_type = "TEXT"

    def to_db(self, value):
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S.%f")
        return str(value)

    def from_db(self, value):
        if value is None or isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            try:
                return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None


class TimeType(_Type):
    sqlite_type = "TEXT"

    def to_db(self, value):
        if value is None:
            return None
        if isinstance(value, time):
            return value.strftime("%H:%M:%S")
        return str(value)

    def from_db(self, value):
        if value is None or isinstance(value, time):
            return value
        try:
            return time.fromisoformat(str(value))
        except ValueError:
            return None


# Alias used by the model declarations (``db.String(120)`` / ``db.Integer``).
Integer = IntegerType
Float = FloatType
Numeric = NumericType
String = StringType
Text = StringType
Boolean = BooleanType
DateTime = DateTimeType
Time = TimeType


class ForeignKey:
    """Marker for a foreign key target such as ``"users.id"``."""

    def __init__(self, target: str):
        self.target = target

    @property
    def table(self) -> str:
        return self.target.split(".", 1)[0]

    @property
    def column(self) -> str:
        return self.target.split(".", 1)[1] if "." in self.target else "id"


def _type_instance(spec) -> _Type:
    if isinstance(spec, _Type):
        return spec
    if isinstance(spec, type) and issubclass(spec, _Type):
        return spec()
    return StringType()


# ---------------------------------------------------------------------------
# expressions / columns
# ---------------------------------------------------------------------------
class Expression:
    """A parameterised SQL fragment."""

    __slots__ = ("sql", "params", "tables")

    def __init__(self, sql: str, params=None, tables=None):
        self.sql = sql
        self.params = list(params or [])
        self.tables = list(tables or [])

    def __and__(self, other):
        other = _as_expression(other)
        return Expression(
            f"({self.sql} AND {other.sql})",
            self.params + other.params,
            self.tables + other.tables,
        )

    def __or__(self, other):
        other = _as_expression(other)
        return Expression(
            f"({self.sql} OR {other.sql})",
            self.params + other.params,
            self.tables + other.tables,
        )

    def __invert__(self):
        return Expression(f"(NOT {self.sql})", self.params, self.tables)

    # -- comparison operators (enable db.func.lower(col) == value etc.) ------
    __hash__ = object.__hash__

    def _cmp(self, op, other):
        if isinstance(other, (Expression, Column)):
            return Expression(
                f"{self.sql} {op} {other.sql}",
                self.params + other.params,
                self.tables + other.tables,
            )
        if other is not None and not isinstance(other, bool):
            return Expression(f"{self.sql} {op} ?", self.params + [other], self.tables)
        return NotImplemented

    def __eq__(self, other):
        if other is None or isinstance(other, bool):
            return NotImplemented
        return self._cmp("=", other)

    def __ne__(self, other):
        if other is None or isinstance(other, bool):
            return NotImplemented
        return self._cmp("<>", other)

    def __lt__(self, other):
        return self._cmp("<", other)

    def __le__(self, other):
        return self._cmp("<=", other)

    def __gt__(self, other):
        return self._cmp(">", other)

    def __ge__(self, other):
        return self._cmp(">=", other)


def _as_expression(value) -> Expression:
    if isinstance(value, (Expression, Column)):
        return value
    if isinstance(value, bool):
        return Expression("1" if value else "0")
    if value is None:
        return Expression("1")
    return Expression(str(value))


class OrderBy:
    __slots__ = ("column", "direction")

    def __init__(self, column, direction="ASC"):
        self.column = column
        self.direction = direction

    @property
    def sql(self):
        return f"{self.column.sql} {self.direction}"

    @property
    def params(self):
        return self.column.params


class _QueryDescriptor:
    """Expose ``Model.query`` without a database connection at class definition."""

    def __init__(self, model):
        self.model = model

    def __get__(self, obj, owner=None):
        return Query(owner or self.model)


class Column:
    """A table column that also supports SQLAlchemy-style expressions."""

    __hash__ = object.__hash__

    def __init__(
        self,
        type_,
        *args,
        primary_key=False,
        nullable=True,
        unique=False,
        index=False,
        default=None,
        onupdate=None,
    ):
        self.type = _type_instance(type_)
        self.primary_key = primary_key
        self.nullable = nullable
        self.unique = unique
        self.index = index
        self.default = default
        self.onupdate = onupdate
        self.foreign_key = None
        for arg in args:
            if isinstance(arg, ForeignKey):
                self.foreign_key = arg
        self.name = None
        self.table = None

    # -- schema helpers -----------------------------------------------------
    @property
    def fk_table(self):
        return self.foreign_key.table if self.foreign_key else None

    @property
    def sql(self) -> str:
        return f'"{self.table}"."{self.name}"'

    @property
    def tables(self):
        return [self.table]

    @property
    def params(self):
        return []

    # -- comparison operators ----------------------------------------------
    def _binary(self, op, value):
        if isinstance(value, Column):
            return Expression(f"{self.sql} {op} {value.sql}", [], value.tables)
        return Expression(f"{self.sql} {op} ?", [self.type.to_db(value)], [self.table])

    def __eq__(self, other):
        return self._binary("=", other)

    def __ne__(self, other):
        return self._binary("<>", other)

    def __lt__(self, other):
        return self._binary("<", other)

    def __le__(self, other):
        return self._binary("<=", other)

    def __gt__(self, other):
        return self._binary(">", other)

    def __ge__(self, other):
        return self._binary(">=", other)

    def is_(self, value):
        if value is None:
            return Expression(f"{self.sql} IS NULL", [], [self.table])
        return Expression(f"{self.sql} = ?", [self.type.to_db(value)], [self.table])

    def isnot(self, value):
        if value is None:
            return Expression(f"{self.sql} IS NOT NULL", [], [self.table])
        return Expression(f"{self.sql} <> ?", [self.type.to_db(value)], [self.table])

    def in_(self, values):
        values = list(values or [])
        if not values:
            return Expression("0")
        placeholders = ", ".join("?" for _ in values)
        params = [self.type.to_db(value) for value in values]
        return Expression(f"{self.sql} IN ({placeholders})", params, [self.table])

    def notin_(self, values):
        return ~self.in_(values)

    def like(self, pattern):
        return Expression(f"{self.sql} LIKE ?", [self.type.to_db(pattern)], [self.table])

    def ilike(self, pattern):
        return Expression(
            f"LOWER({self.sql}) LIKE LOWER(?)",
            [self.type.to_db(pattern)],
            [self.table],
        )

    def desc(self):
        return OrderBy(self, "DESC")

    def asc(self):
        return OrderBy(self, "ASC")


class _Func:
    """Very small SQL function namespace (``db.func.count`` etc.)."""

    @staticmethod
    def _wrap(name, column):
        column = _as_expression(column)
        return Expression(f"{name}({column.sql})", column.params, column.tables)

    def lower(self, column):
        return self._wrap("LOWER", column)

    def upper(self, column):
        return self._wrap("UPPER", column)

    def count(self, column=None):
        if column is None:
            return Expression("COUNT(*)")
        return self._wrap("COUNT", column)

    def avg(self, column):
        return self._wrap("AVG", column)

    def sum(self, column):
        return self._wrap("SUM", column)

    def min(self, column):
        return self._wrap("MIN", column)

    def max(self, column):
        return self._wrap("MAX", column)


def _or(*expressions):
    expressions = [_as_expression(item) for item in expressions if item is not None]
    if not expressions:
        return Expression("0")
    sql = "(" + " OR ".join(item.sql for item in expressions) + ")"
    params = [param for item in expressions for param in item.params]
    tables = [table for item in expressions for table in item.tables]
    return Expression(sql, params, tables)


def _and(*expressions):
    expressions = [_as_expression(item) for item in expressions if item is not None]
    if not expressions:
        return Expression("1")
    sql = "(" + " AND ".join(item.sql for item in expressions) + ")"
    params = [param for item in expressions for param in item.params]
    tables = [table for item in expressions for table in item.tables]
    return Expression(sql, params, tables)


# ---------------------------------------------------------------------------
# relationships
# ---------------------------------------------------------------------------
class Backref:
    def __init__(self, name: str, lazy: str = "select"):
        self.name = name
        self.lazy = lazy


class Relationship:
    """Descriptor implementing the relationship subset used by the app."""

    def __init__(
        self,
        target: str,
        back_populates: str | None = None,
        backref: Backref | None = None,
        uselist: bool | None = None,
        lazy: str = "select",
        cascade: str = "",
        foreign_keys=None,
    ):
        self.target_name = target
        self.back_populates = back_populates
        self.backref = backref
        self.uselist_setting = uselist
        self.lazy = lazy
        self.cascade = cascade or ""
        self.foreign_keys = foreign_keys
        self.name = None
        self.owner = None
        self.target_cls = None
        self.direction = None  # many_to_one | one_to_many | one_to_one
        self.fk_model = None
        self.fk_name = None
        self.resolve_backref_done = False

    # -- resolution ---------------------------------------------------------
    def resolve(self) -> bool:
        target = _MODELS.get(self.target_name)
        if target is None:
            return False
        self.target_cls = target
        owner_cols = self.owner.__table_columns__
        target_cols = target.__table_columns__

        explicit = self.foreign_keys
        if explicit is not None:
            specs = explicit if isinstance(explicit, (list, tuple)) else [explicit]
            for spec in specs:
                if isinstance(spec, Column):
                    model = _MODELS.get(spec.table)
                    if spec.table == self.owner.__tablename__:
                        model = self.owner
                    elif spec.table == target.__tablename__:
                        model = target
                    self.fk_model, self.fk_name = model, spec.name
                    break
                if isinstance(spec, str) and "." in spec:
                    table, column = spec.split(".", 1)
                    model = _MODELS.get(table) or _TABLES.get(table)
                    if model is not None:
                        self.fk_model, self.fk_name = model, column
                        break

        if self.fk_name is None:
            source_fks = [
                col for col in owner_cols.values()
                if col.fk_table == target.__tablename__
            ]
            target_fks = [
                col for col in target_cols.values()
                if col.fk_table == self.owner.__tablename__
            ]
            if source_fks:
                self.fk_model, self.fk_name = self.owner, source_fks[0].name
            elif target_fks:
                self.fk_model, self.fk_name = target, target_fks[0].name
            else:
                return False

        if self.fk_model is self.owner:
            self.direction = "many_to_one"
        else:
            self.direction = "one_to_one" if self.uselist_setting is False else "one_to_many"
        return True

    @property
    def uselist(self) -> bool:
        return self.direction == "one_to_many"

    @property
    def fk_column(self) -> Column:
        return self.fk_model.__table_columns__[self.fk_name]

    # -- descriptor protocol ------------------------------------------------
    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        return obj._get_related(self)

    def __set__(self, obj, value):
        obj._set_related(self, value)


def _resolve_relationships() -> None:
    """Resolve pending relationships and attach backrefs."""
    for model in list(_MODELS.values()):
        for rel in list(model.__relationships__.values()):
            if rel.direction is None and not rel.resolve():
                continue
            if rel.backref and not rel.resolve_backref_done:
                target = rel.target_cls
                if target is None:
                    continue
                inverse = Relationship(
                    rel.owner.__name__,
                    uselist=not rel.uselist,
                    lazy=rel.backref.lazy,
                )
                inverse.name = rel.backref.name
                inverse.owner = target
                inverse.target_cls = rel.owner
                inverse.fk_model = rel.fk_model
                inverse.fk_name = rel.fk_name
                inverse.direction = "one_to_many" if rel.direction == "many_to_one" else "many_to_one"
                if rel.direction == "one_to_one":
                    inverse.direction = "many_to_one"
                setattr(target, inverse.name, inverse)
                target.__relationships__[inverse.name] = inverse
                rel.resolve_backref_done = True


class RelatedList(list):
    """A loaded relationship collection with the helpers used by the app."""

    def __init__(self, items, owner=None, rel=None):
        super().__init__(items)
        self.owner = owner
        self.rel = rel

    def all(self):
        return list(self)

    def count(self):
        return len(self)

    def first(self):
        return self[0] if self else None

    def filter_by(self, **kwargs):
        def matches(item):
            return all(getattr(item, key, None) == value for key, value in kwargs.items())

        return RelatedList([item for item in self if matches(item)], self.owner, self.rel)

    def append(self, item):
        super().append(item)
        if self.owner is None or self.rel is None:
            return
        owner, rel = self.owner, self.rel
        session = _get_session()
        child_fk = rel.fk_name
        if owner.id is not None:
            setattr(item, child_fk, owner.id)
            session.add(item)
        else:
            owner._pending_children.append((item, child_fk))
            if owner._persisted or owner in session._new:
                session.add(item)


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------
class _Statement:
    """Raw SQL wrapper returned by :func:`text`."""

    def __init__(self, sql: str):
        self.sql = sql


def text(sql: str) -> _Statement:
    return _Statement(sql)


class Session:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self._new: list = []
        self._dirty: dict = {}
        self._deleted: list = []
        self._identity: dict = {}
        self._inserting: set = set()
        self._closed = False

    # -- change tracking ----------------------------------------------------
    def add(self, obj) -> None:
        if obj is None:
            return
        if obj._persisted or obj in self._new or obj in self._inserting:
            return
        self._new.append(obj)
        self._dirty.pop(obj, None)
        for child, _fk in obj._pending_children:
            self.add(child)

    def mark_dirty(self, obj, column_name: str) -> None:
        if obj._persisted:
            self._dirty.setdefault(obj, set()).add(column_name)

    def delete(self, obj) -> None:
        if obj is None:
            return
        if obj in self._deleted:
            return
        for rel in list(type(obj).__relationships__.values()):
            if rel.direction is None:
                continue
            if "delete" not in (rel.cascade or ""):
                continue
            related = obj._get_related(rel)
            if rel.uselist:
                for child in list(related):
                    self.delete(child)
            elif related is not None:
                self.delete(related)
        self._deleted.append(obj)
        self._dirty.pop(obj, None)
        if obj in self._new:
            self._new.remove(obj)

    # -- loading ------------------------------------------------------------
    def _load(self, model, row):
        pk = model.__pk__
        pk_value = row[pk.name]
        key = (model.__name__, pk_value)
        existing = self._identity.get(key)
        if existing is not None:
            return existing
        obj = model.__new__(model)
        object.__setattr__(obj, "_persisted", True)
        object.__setattr__(obj, "_loaded", False)
        object.__setattr__(obj, "_rel_cache", {})
        object.__setattr__(obj, "_pending_children", [])
        object.__setattr__(obj, "_pending_fks", [])
        for name, column in model.__table_columns__.items():
            object.__setattr__(obj, name, column.type.from_db(row[name]))
        object.__setattr__(obj, "_loaded", True)
        self._identity[key] = obj
        return obj

    def get(self, model, pk):
        if pk is None:
            return None
        try:
            pk = int(pk)
        except (TypeError, ValueError):
            return None
        key = (model.__name__, pk)
        cached = self._identity.get(key)
        if cached is not None:
            return cached
        return Query(model).filter(model.__pk__ == pk).first()

    # -- transactions -------------------------------------------------------
    def flush(self) -> None:
        self._flush()

    def commit(self) -> None:
        self._flush()
        self.connection.commit()

    def rollback(self) -> None:
        self.connection.rollback()
        self._new.clear()
        self._dirty.clear()
        self._deleted.clear()
        self._identity.clear()
        self._inserting.clear()

    def close(self) -> None:
        if self._closed:
            return
        if self._new or self._dirty or self._deleted or self._inserting:
            self.connection.rollback()
        self.connection.close()
        self._closed = True

    def execute(self, statement):
        if isinstance(statement, _Statement):
            return self.connection.execute(statement.sql)
        return self.connection.execute(str(statement))

    def _apply_pending_fks(self, obj) -> None:
        remaining = []
        for fk_name, target in getattr(obj, "_pending_fks", []):
            if target.id is not None:
                object.__setattr__(obj, fk_name, target.id)
                obj._rel_cache.pop(fk_name, None)
            else:
                remaining.append((fk_name, target))
        obj._pending_fks = remaining

    def _insert(self, obj) -> None:
        model = type(obj)
        self._apply_pending_fks(obj)
        columns = []
        values = []
        for name, column in model.__table_columns__.items():
            if column.primary_key and getattr(obj, name, None) is None:
                continue
            value = getattr(obj, name, None)
            if value is None and column.default is not None:
                value = column.default() if callable(column.default) else column.default
                object.__setattr__(obj, name, value)
            columns.append(name)
            values.append(column.type.to_db(value))

        table = model.__tablename__
        placeholders = ", ".join("?" for _ in columns)
        column_sql = ", ".join(f'"{name}"' for name in columns)
        is_mssql = getattr(self.connection, "kind", "sqlite") == "mssql"
        pk = model.__pk__
        if is_mssql:
            # Same-batch identity fetch: SCOPE_IDENTITY() is NULL in a later
            # batch, so the id is returned through OUTPUT INSERTED.
            output = f' OUTPUT INSERTED."{pk.name}"' if pk else ""
            sql = f'INSERT INTO "{table}" ({column_sql}){output} VALUES ({placeholders})'
        else:
            sql = f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})'
        cursor = self.connection.execute(sql, values)
        if getattr(obj, pk.name, None) is None:
            if is_mssql:
                row = cursor.fetchone()
                new_id = row[0] if row else None
            else:
                new_id = cursor.lastrowid
            object.__setattr__(obj, pk.name, new_id)
        object.__setattr__(obj, "_persisted", True)
        self._identity[(model.__name__, getattr(obj, pk.name))] = obj

        # Children that point at this row (one-to-many / one-to-one).
        pending = getattr(obj, "_pending_children", [])
        obj._pending_children = []
        for child, fk_name in pending:
            setattr(child, fk_name, getattr(obj, pk.name))
            if not child._persisted and child not in self._new:
                self.add(child)

    def _update(self, obj, changed) -> None:
        model = type(obj)
        pk = model.__pk__
        assignments = []
        values = []
        written = set()
        for name in changed:
            column = model.__table_columns__.get(name)
            if column is None or column.primary_key:
                continue
            assignments.append(f'"{name}" = ?')
            values.append(column.type.to_db(getattr(obj, name, None)))
            written.add(name)

        # Apply ``onupdate`` columns (for example ``updated_at``) whenever the
        # row changes, mirroring the declarative behaviour the app expects.
        for name, column in model.__table_columns__.items():
            if name in written or name in changed or column.primary_key:
                continue
            if column.onupdate is None:
                continue
            value = column.onupdate() if callable(column.onupdate) else column.onupdate
            object.__setattr__(obj, name, value)
            assignments.append(f'"{name}" = ?')
            values.append(column.type.to_db(value))

        if not assignments:
            return
        values.append(getattr(obj, pk.name))
        sql = f'UPDATE "{model.__tablename__}" SET {", ".join(assignments)} WHERE "{pk.name}" = ?'
        self.connection.execute(sql, values)

    def _delete(self, obj) -> None:
        model = type(obj)
        pk = model.__pk__
        if getattr(obj, pk.name, None) is None:
            return
        self.connection.execute(
            f'DELETE FROM "{model.__tablename__}" WHERE "{pk.name}" = ?',
            [getattr(obj, pk.name)],
        )

    def _flush(self) -> None:
        # Insert in dependency order.  ``_insert`` may queue children that were
        # attached through a relationship, so keep draining until stable.
        while self._new:
            batch = self._new
            self._new = []
            self._inserting = set(batch)
            ordered = sorted(batch, key=lambda item: _table_rank(type(item).__tablename__))
            for obj in ordered:
                self._insert(obj)
            self._inserting.clear()

        for obj, changed in list(self._dirty.items()):
            if obj._persisted:
                self._update(obj, changed)
        self._dirty.clear()

        for obj in self._deleted:
            self._delete(obj)
            key = (type(obj).__name__, getattr(obj, type(obj).__pk__.name, None))
            self._identity.pop(key, None)
        self._deleted.clear()

    # -- query entry point --------------------------------------------------
    def query(self, *entities):
        if not entities:
            raise ValueError("db.session.query() needs at least one column")
        first = entities[0]
        if isinstance(first, type) and issubclass(first, Model):
            return Query(first)
        columns = [_as_expression(item) for item in entities]
        table = None
        for column in columns:
            if column.tables:
                table = column.tables[0]
                break
        model = _TABLES.get(table)
        if model is None:
            raise ValueError("Could not determine table for query")
        return Query(model, select_columns=columns)


def _table_rank(table: str) -> int:
    if not _TABLE_RANK:
        _rebuild_table_rank()
    return _TABLE_RANK.get(table, 99)


def _rebuild_table_rank() -> None:
    """Topologically order tables by their foreign keys."""
    _TABLE_RANK.clear()
    tables = list(_TABLES)
    deps = {}
    for table in tables:
        model = _TABLES[table]
        deps[table] = {
            column.fk_table
            for column in model.__table_columns__.values()
            if column.fk_table and column.fk_table in _TABLES and column.fk_table != table
        }
    rank = {}
    remaining = set(tables)
    while remaining:
        progressed = False
        for table in list(remaining):
            if deps[table] <= set(rank):
                rank[table] = len(rank)
                remaining.remove(table)
                progressed = True
        if not progressed:  # circular reference: keep a stable order
            for table in sorted(remaining):
                rank[table] = len(rank)
            break
    _TABLE_RANK.update(rank)


# ---------------------------------------------------------------------------
# query object
# ---------------------------------------------------------------------------
class Pagination:
    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = (total + per_page - 1) // per_page if per_page else 0

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def prev_num(self):
        return self.page - 1 if self.has_prev else None

    @property
    def next_num(self):
        return self.page + 1 if self.has_next else None

    @property
    def first(self):
        if not self.total:
            return 0
        return (self.page - 1) * self.per_page + 1

    @property
    def last(self):
        return min(self.page * self.per_page, self.total)

    def iter_pages(self, left_edge=1, left_current=2, right_current=2, right_edge=1):
        last = 0
        for number in range(1, self.pages + 1):
            if (
                number <= left_edge
                or (number >= self.page - left_current and number <= self.page + right_current)
                or number > self.pages - right_edge
            ):
                if last + 1 != number:
                    yield None
                yield number
                last = number


class Query:
    def __init__(self, model, select_columns=None):
        self.model = model
        self.select_columns = select_columns
        self._filters: list = []
        self._joins: list = []
        self._order: list = []
        self._group_by: list = []
        self._distinct = False
        self._limit = None
        self._offset = 0

    # -- builders -----------------------------------------------------------
    def filter(self, *expressions):
        for expression in expressions:
            self._filters.append(_as_expression(expression))
        return self

    def filter_by(self, **kwargs):
        for name, value in kwargs.items():
            column = self.model.__table_columns__.get(name)
            if column is None:
                raise AttributeError(f"{self.model.__name__} has no column '{name}'")
            self._filters.append(column == value)
        return self

    def join(self, target, onclause=None):
        if not isinstance(target, type) or not issubclass(target, Model):
            raise TypeError("join() expects a model class")
        if onclause is None:
            onclause = self._infer_join(target)
        expression = _as_expression(onclause)
        self._joins.append(
            (f'JOIN "{target.__tablename__}" ON {expression.sql}', expression.params)
        )
        return self

    def _infer_join(self, target):
        for column in self.model.__table_columns__.values():
            if column.fk_table == target.__tablename__:
                return column == target.__pk__
        for column in target.__table_columns__.values():
            if column.fk_table == self.model.__tablename__:
                return column == self.model.__pk__
        raise ValueError(f"Cannot infer join between {self.model.__name__} and {target.__name__}")

    def order_by(self, *terms):
        for term in terms:
            if isinstance(term, Column):
                self._order.append(OrderBy(term, "ASC"))
            elif isinstance(term, OrderBy):
                self._order.append(term)
            elif isinstance(term, Expression):
                self._order.append(OrderBy(term, "ASC"))
            elif isinstance(term, str):
                self._order.append(OrderBy(Expression(term), "ASC"))
        return self

    def group_by(self, *terms):
        for term in terms:
            self._group_by.append(_as_expression(term))
        return self

    def distinct(self):
        self._distinct = True
        return self

    def limit(self, value):
        self._limit = int(value)
        return self

    def offset(self, value):
        self._offset = int(value)
        return self

    # -- SQL ----------------------------------------------------------------
    def _from_clause(self):
        sql = f'"{self.model.__tablename__}"'
        params = []
        for join_sql, join_params in self._joins:
            sql += f" {join_sql}"
            params.extend(join_params)
        return sql, params

    def _where_clause(self):
        if not self._filters:
            return "", []
        sql = " AND ".join(f"({item.sql})" for item in self._filters)
        params = [param for item in self._filters for param in item.params]
        return f" WHERE {sql}", params

    def _select_clause(self):
        if self.select_columns is None:
            return f'"{self.model.__tablename__}".*'
        return ", ".join(item.sql for item in self.select_columns)

    def _order_clause(self):
        if not self._order:
            return ""
        return " ORDER BY " + ", ".join(
            f"{term.column.sql} {term.direction}" if hasattr(term, "column") else term.sql
            for term in self._order
        )

    def _build(self, include_order=True):
        from_sql, params = self._from_clause()
        where_sql, where_params = self._where_clause()
        sql = f"SELECT {'DISTINCT ' if self._distinct else ''}{self._select_clause()} FROM {from_sql}"
        params.extend(where_params)
        sql += where_sql
        if self._group_by:
            sql += " GROUP BY " + ", ".join(item.sql for item in self._group_by)
            for item in self._group_by:
                params.extend(item.params)
        if include_order:
            sql += self._order_clause()
        return sql, params

    # -- execution ----------------------------------------------------------
    def all(self):
        sql, params = self._build()
        is_mssql = getattr(_get_session().connection, "kind", "sqlite") == "mssql"
        if self._limit is not None or self._offset:
            if is_mssql:
                # Aggregate selects must not get a non-grouped ORDER BY.
                select_clause = self._select_clause()
                aggregate = any(
                    fn in select_clause.upper()
                    for fn in ("COUNT(", "AVG(", "SUM(", "MIN(", "MAX(")
                )
                if not self._order and not aggregate:
                    pk = self.model.__pk__
                    if pk is not None:
                        sql += f" ORDER BY {pk.sql} ASC"
                if self._offset:
                    sql += " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
                    params.extend([self._offset, self._limit or 1000000000])
                elif self._limit:
                    if sql.startswith("SELECT DISTINCT "):
                        sql = sql.replace("SELECT DISTINCT ", "SELECT DISTINCT ", 1)
                        head, body = "SELECT DISTINCT ", sql[len("SELECT DISTINCT "):]
                    else:
                        head, body = "SELECT ", sql[len("SELECT "):]
                    sql = f"{head}TOP (?) {body}"
                    params = [self._limit] + params
            else:
                if self._limit is not None:
                    sql += " LIMIT ?"
                    params.append(self._limit)
                if self._offset:
                    sql += " OFFSET ?"
                    params.append(self._offset)
        session = _get_session()
        rows = session.connection.execute(sql, params).fetchall()
        if self.select_columns is not None:
            return [tuple(row) for row in rows]
        return [session._load(self.model, row) for row in rows]

    def first(self):
        saved = self._limit
        self._limit = 1
        try:
            rows = self.all()
        finally:
            self._limit = saved
        return rows[0] if rows else None

    def scalar(self):
        row = self.first()
        if row is None:
            return None
        if isinstance(row, tuple):
            return row[0] if row else None
        return row

    def count(self):
        from_sql, params = self._from_clause()
        where_sql, where_params = self._where_clause()
        params.extend(where_params)
        group_sql = ""
        if self._group_by:
            group_sql = " GROUP BY " + ", ".join(item.sql for item in self._group_by)
        sql = (
            f"SELECT COUNT(*) AS n FROM (SELECT {'DISTINCT ' if self._distinct else ''}"
            f"{self._select_clause()} FROM {from_sql}{where_sql}{group_sql}) AS _sub"
        )
        row = _get_session().connection.execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    def paginate(self, page=1, per_page=20, error_out=False):
        page = max(1, int(page or 1))
        total = self.count()
        pages = (total + per_page - 1) // per_page if per_page else 0
        if error_out and page > max(1, pages):
            raise LookupError("Page not found")
        self._limit = per_page
        self._offset = (page - 1) * per_page
        items = self.all()
        return Pagination(items, page, per_page, total)

    def update(self, values):
        model = self.model
        assignments = []
        params = []
        for name, value in values.items():
            column = model.__table_columns__.get(name)
            if column is None:
                continue
            assignments.append(f'"{name}" = ?')
            params.append(column.type.to_db(value))
        if not assignments:
            return 0
        from_sql, from_params = self._from_clause()
        where_sql, where_params = self._where_clause()
        params.extend(from_params)
        params.extend(where_params)
        sql = f'UPDATE "{model.__tablename__}" SET {", ".join(assignments)}{where_sql}'
        cursor = _get_session().connection.execute(sql, params)
        _get_session()._identity = {
            key: obj for key, obj in _get_session()._identity.items()
            if key[0] != model.__name__
        }
        return cursor.rowcount

    def delete(self):
        from_sql, from_params = self._from_clause()
        where_sql, where_params = self._where_clause()
        params = from_params + where_params
        sql = f'DELETE FROM "{self.model.__tablename__}"{where_sql}'
        cursor = _get_session().connection.execute(sql, params)
        return cursor.rowcount


# ---------------------------------------------------------------------------
# declarative models
# ---------------------------------------------------------------------------
class ModelMeta(type):
    def __new__(mcls, name, bases, namespace):
        cls = super().__new__(mcls, name, bases, namespace)
        if name == "Model" and not any(isinstance(base, ModelMeta) for base in bases):
            return cls
        if "__tablename__" not in namespace:
            return cls
        columns = {}
        relationships = {}
        for key, value in namespace.items():
            if isinstance(value, Column):
                value.name = key
                value.table = cls.__tablename__
                columns[key] = value
            elif isinstance(value, Relationship):
                value.name = key
                value.owner = cls
                relationships[key] = value
        cls.__table_columns__ = columns
        cls.__relationships__ = relationships
        cls.query = _QueryDescriptor(cls)
        cls.__pk__ = next(
            (column for column in columns.values() if column.primary_key),
            columns.get("id"),
        )
        cls.__fk_to_rel__ = {}
        _MODELS[name] = cls
        _TABLES[cls.__tablename__] = cls
        _TABLE_RANK.clear()
        _resolve_relationships()
        # Map foreign-key columns to their relationship for cache invalidation.
        for rel in relationships.values():
            if rel.direction == "many_to_one" and rel.fk_name:
                cls.__fk_to_rel__.setdefault(rel.fk_name, []).append(rel)
        return cls


class Model(metaclass=ModelMeta):
    __tablename__ = None
    __table_columns__: dict = {}
    __relationships__: dict = {}
    __pk__ = None

    def __init__(self, **kwargs):
        object.__setattr__(self, "_persisted", False)
        object.__setattr__(self, "_loaded", False)
        object.__setattr__(self, "_rel_cache", {})
        object.__setattr__(self, "_pending_children", [])
        object.__setattr__(self, "_pending_fks", [])
        for name, column in type(self).__table_columns__.items():
            if column.default is not None and not callable(column.default):
                object.__setattr__(self, name, column.default)
            else:
                object.__setattr__(self, name, None)
        object.__setattr__(self, "_loaded", True)
        for key, value in kwargs.items():
            setattr(self, key, value)

    # -- attribute handling -------------------------------------------------
    def __setattr__(self, name, value):
        cls = type(self)
        if name in cls.__relationships__:
            cls.__relationships__[name].__set__(self, value)
            return
        object.__setattr__(self, name, value)
        if name.startswith("_") or not getattr(self, "_loaded", False):
            return
        if name in cls.__table_columns__ and getattr(self, "_persisted", False):
            _get_session().mark_dirty(self, name)
        for rel in cls.__fk_to_rel__.get(name, []):
            self._rel_cache.pop(rel.name, None)

    # -- relationships ------------------------------------------------------
    def _get_related(self, rel):
        if rel.name in self._rel_cache:
            return self._rel_cache[rel.name]
        session = _get_session()
        if rel.direction == "many_to_one":
            value = getattr(self, rel.fk_name, None)
            related = session.get(rel.target_cls, value) if value is not None else None
        elif rel.direction == "one_to_many":
            if self.id is None:
                related = RelatedList([], self, rel)
            else:
                related = RelatedList(
                    Query(rel.target_cls).filter_by(**{rel.fk_name: self.id}).all(),
                    self,
                    rel,
                )
        else:  # one_to_one
            related = None
            if self.id is not None:
                related = (
                    Query(rel.target_cls).filter_by(**{rel.fk_name: self.id}).first()
                )
        self._rel_cache[rel.name] = related
        return related

    def _set_related(self, rel, value):
        if rel.uselist:
            items = list(value or [])
            current = RelatedList([], self, rel)
            for item in items:
                current.append(item)
            self._rel_cache[rel.name] = current
            return

        if value is None:
            self._rel_cache[rel.name] = None
            if rel.direction == "many_to_one":
                self.__setattr__(rel.fk_name, None)
            return

        session = _get_session()
        if rel.direction == "many_to_one":
            self._rel_cache[rel.name] = value
            if value.id is not None:
                self.__setattr__(rel.fk_name, value.id)
            else:
                self._pending_fks.append((rel.fk_name, value))
                self._rel_cache.pop(rel.name, None)
            session.add(value)
        else:
            self._rel_cache[rel.name] = value
            if self.id is not None:
                setattr(value, rel.fk_name, self.id)
                session.add(value)
            else:
                self._pending_children.append((value, rel.fk_name))
                if self._persisted or self in session._new:
                    session.add(value)


# ---------------------------------------------------------------------------
# database facade
# ---------------------------------------------------------------------------
class SessionProxy:
    def __getattr__(self, item):
        return getattr(_get_session(), item)


class Database:
    def __init__(self):
        self.Model = Model
        self.Column = Column
        self.ForeignKey = ForeignKey
        self.relationship = Relationship
        self.backref = Backref
        self.session = SessionProxy()
        self.func = _Func()
        self.Integer = IntegerType
        self.Float = FloatType
        self.Numeric = NumericType
        self.String = StringType
        self.Text = StringType
        self.Boolean = BooleanType
        self.DateTime = DateTimeType
        self.Time = TimeType
        self.or_ = _or
        self.and_ = _and
        self.text = text

    # -- app wiring ---------------------------------------------------------
    def init_app(self, app):
        app.extensions["sqlite_db"] = self
        app.teardown_appcontext(self._teardown)

    @staticmethod
    def _teardown(_exception=None):
        session = g.pop("_sqlite_session", None)
        if session is not None:
            session.close()

    # -- schema -------------------------------------------------------------
    _SQL_TYPE_MAP = None  # built lazily, shared between models' DDL calls

    def create_all(self):
        session = _get_session()
        is_mssql = getattr(session.connection, "kind", "sqlite") == "mssql"
        _rebuild_table_rank()
        created_tables: list[str] = []
        for table in sorted(_TABLES, key=lambda name: _table_rank(name)):
            model = _TABLES[table]
            columns = []
            for column in model.__table_columns__.values():
                if is_mssql:
                    sql = f'"{column.name}" {self._tsql_type(column)}'
                    if column.primary_key:
                        sql += " IDENTITY(1,1) PRIMARY KEY"
                    elif not column.nullable:
                        sql += " NOT NULL"
                    if column.unique:
                        sql += " UNIQUE"
                else:
                    sql = f'"{column.name}" {column.type.sqlite_type}'
                    if column.primary_key:
                        sql += " PRIMARY KEY AUTOINCREMENT"
                    elif not column.nullable:
                        sql += " NOT NULL"
                    if column.unique:
                        sql += " UNIQUE"
                columns.append(sql)
            if is_mssql:
                exists = session.connection.execute(
                    "SELECT COUNT(*) FROM sys.tables WHERE name = ?", (table,)
                ).fetchone()
                table_exists = bool(exists and exists[0])
                if not table_exists:
                    session.connection.execute(
                        f'CREATE TABLE "{table}" ({", ".join(columns)})'
                    )
            else:
                session.connection.execute(
                    f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(columns)})'
                )
            created_tables.append(table)
            for column in model.__table_columns__.values():
                if not column.index or column.primary_key:
                    continue
                if is_mssql:
                    index_name = f"ix_{table}_{column.name}"
                    exists = session.connection.execute(
                        "SELECT COUNT(*) FROM sys.indexes WHERE name = ? AND object_id"
                        " = OBJECT_ID(?)",
                        (index_name, table),
                    ).fetchone()
                    if exists and exists[0]:
                        continue
                    sql = f'CREATE INDEX "{index_name}" ON "{table}" ("{column.name}")'
                else:
                    sql = (
                        f'CREATE INDEX IF NOT EXISTS "ix_{table}_{column.name}" '
                        f'ON "{table}" ("{column.name}")'
                    )
                session.connection.execute(sql)
        if is_mssql:
            # SQL Server CREATE TABLE uese separate statements for FK constraints.
            self._add_mssql_constraints(session, created_tables)
        session.connection.commit()

    @staticmethod
    def _tsql_type(column) -> str:
        type_name = column.type.__class__.__name__
        if type_name == "IntegerType":
            return "INT"
        if type_name == "FloatType":
            return "FLOAT"
        if type_name == "NumericType":
            if column.type.precision and column.type.scale:
                return f"DECIMAL({column.type.precision},{column.type.scale})"
            return "FLOAT"
        if type_name == "BooleanType":
            return "INT"
        if type_name == "DateTimeType":
            return "DATETIME2"
        if type_name == "TimeType":
            return "TIME"
        # StringType / Text
        if column.type.length:
            return f"NVARCHAR({column.type.length})"
        return "NVARCHAR(MAX)"

    def _add_mssql_constraints(self, session, tables) -> None:
        """Add foreign key constraints after every table exists."""
        for table in tables:
            model = _TABLES[table]
            for column in model.__table_columns__.values():
                if not column.foreign_key:
                    continue
                name = f"FK_{table}_{column.name}"
                exists = session.connection.execute(
                    "SELECT COUNT(*) FROM sys.foreign_keys WHERE name = ?", (name,)
                ).fetchone()
                if exists and exists[0]:
                    continue
                session.connection.execute(
                    f"ALTER TABLE \"{table}\" ADD CONSTRAINT {name}"
                    f" FOREIGN KEY (\"{column.name}\")"
                    f" REFERENCES \"{column.foreign_key.table}\""
                    f" (\"{column.foreign_key.column}\")"
                )

    def drop_all(self):
        session = _get_session()
        is_mssql = getattr(session.connection, "kind", "sqlite") == "mssql"
        if is_mssql:
            # Drop every FK constraint first, otherwise SQL Server refuses drops.
            rows = session.connection.execute(
                "SELECT t.name, f.name FROM sys.foreign_keys f"
                " JOIN sys.tables t ON f.parent_object_id = t.object_id"
            ).fetchall()
            for table, constraint in [(r[0], r[1]) for r in rows]:
                session.connection.execute(
                    f'ALTER TABLE "{table}" DROP CONSTRAINT {constraint}'
                )
        for table in reversed(list(_TABLES)):
            session.connection.execute(f'DROP TABLE IF EXISTS "{table}"')
        session.connection.commit()


class _Row:
    """Name- and index-based result row (the ``sqlite3.Row`` equivalent)."""

    __slots__ = ("_map", "_values")

    def __init__(self, columns, values):
        self._map = dict(zip(columns, values))
        self._values = list(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._map.keys()


class _Cursor:
    """Cursor wrapper that returns name-indexable rows on SQL Server."""

    def __init__(self, raw):
        self.raw = raw
        self.columns = (
            [c[0] for c in raw.description] if getattr(raw, "description", None) else []
        )

    @property
    def rowcount(self):
        return self.raw.rowcount

    @property
    def lastrowid(self):
        return getattr(self.raw, "lastrowid", None)

    def fetchone(self):
        values = self.raw.fetchone()
        if values is None or not self.columns:
            return values
        return _Row(self.columns, values)

    def fetchall(self):
        rows = self.raw.fetchall()
        if not self.columns:
            return rows
        return [_Row(self.columns, row) for row in rows]

    def __iter__(self):
        return iter(self.fetchall() if self.columns else self.raw)

    def close(self):
        self.raw.close()


class _Connection:
    """Uniform connection facade for SQLite (sqlite3) and SQL Server (pyodbc)."""

    def __init__(self, raw, kind: str):
        self.raw = raw
        self.kind = kind  # "sqlite" | "mssql"

    def execute(self, sql, params=None):
        cursor = (
            self.raw.execute(sql, params)
            if params is not None else self.raw.execute(sql)
        )
        return cursor if self.kind == "sqlite" else _Cursor(cursor)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def _connect_mssql(conn_str: str):
    """SQL Server connection (SRS 3.11 - T-SQL / SSMS deliverable)."""
    import pyodbc  # optional dependency, only needed for the SQL Server mode

    connection = pyodbc.connect(conn_str, timeout=30)
    try:
        connection.setdecoding(pyodbc.SQL_WCHAR, encoding="utf-16le")
        connection.setencoding(encoding="utf-16le")
    except AttributeError:  # pragma: no cover - older pyodbc
        pass
    try:
        connection.execute("SET QUOTED_IDENTIFIER ON")
    except Exception:  # pragma: no cover
        pass
    return connection


def _connect_sqlite(path: str):
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=OFF")
    return connection


def _get_session() -> Session:
    if not has_app_context():
        raise RuntimeError("Database access requires an active Flask application context")
    try:
        session = g._sqlite_session
    except AttributeError:
        session = None
    if session is None:
        use_mssql = current_app.config.get("USE_MSSQL", True)
        mssql = current_app.config.get("MSSQL_CONN_STR") if use_mssql else ""
        if mssql:
            connection = _Connection(_connect_mssql(mssql), "mssql")
        else:
            path = current_app.config.get("DATABASE_PATH")
            if not path:
                raise RuntimeError("DATABASE_PATH is not configured")
            connection = _Connection(_connect_sqlite(path), "sqlite")
        session = Session(connection)
        g._sqlite_session = session
    return session


db = Database()
