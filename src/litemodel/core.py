import os
import sqlite3
from typing import Type, TypeAlias, Iterable, get_origin, Union, get_args
from jinja2 import Template
from contextlib import contextmanager

DATABASE_PATH = os.environ.get("DATABASE_PATH", "db.db")

print(f"DATABASE_PATH={DATABASE_PATH}")


SQLITE_PRAGMAS = (
    "PRAGMA journal_mode = WAL;",
    "PRAGMA busy_timeout = 5000;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA cache_size = 1000000000;",
    "PRAGMA foreign_keys = true;",
    "PRAGMA temp_store = memory;",
)

SQL_TYPE: TypeAlias = int | float | str | bytes | bool

SQL_TYPES = {
    int: "INTEGER",
    float: "REAL",
    str: "TEXT",
    bytes: "BLOB",
    bool: "INTEGER",
    None: "NULL",
}

CREATE_TABLE_TEMPLATE = """CREATE TABLE {{table}} (
        id INTEGER PRIMARY KEY,
        {%- for name, type in fields.items() %}
        {{name}} {{type.sqlite_type}}{{not_null.get(name,'')}}{% if not loop.last -%},{%- endif -%}
        {% endfor %}
    )"""

INSERT_TEMPLATE = """INSERT INTO {{table}} 
        (
        {%- for col_name in fields %}
        {{col_name}}{% if not loop.last -%},{%- endif -%}
        {% endfor %}
        )
    VALUES
        ({%- for col_name in fields %}?{% if not loop.last -%},{%- endif -%}{% endfor %})
"""

UPDATE_TEMPLATE = """UPDATE {{table}}
    SET 
        {% for field in fields %}
        {{field}} = ?{% if not loop.last -%},{%- endif -%}
        {% endfor %}
    WHERE
        {{where}} = ?
"""

FIND_BY_TEMPLATE = """SELECT * from {{table}} where {{field}} = ?"""

DELETE_BY_TEMPLATE = """DELETE FROM {{table}} WHERE {{field}} = ?"""


# Need to do something here so we just have one connection
# well two connections -- one for reading and one for writing
# for now this will do

CONNECTION = None


@contextmanager
def transaction(conn: sqlite3.Connection):
    # We must issue a "BEGIN" explicitly when running in auto-commit mode.
    conn.execute("BEGIN IMMEDIATE TRANSACTION")
    try:
        # Yield control back to the caller.
        yield
    except:
        conn.rollback()  # Roll back all changes if an exception occurs.
        raise
    else:
        conn.commit()


def get_conn() -> sqlite3.Connection:
    global CONNECTION
    if CONNECTION is None:
        CONNECTION = sqlite3.connect(
            DATABASE_PATH, timeout=5, detect_types=1, isolation_level=None
        )
        for pragma in SQLITE_PRAGMAS:
            CONNECTION.execute(pragma, [])
        CONNECTION.row_factory = sqlite3.Row
    return CONNECTION


def _sql(sql_statement: str, values: Iterable | None = None) -> sqlite3.Cursor:
    if values is None:
        values = []
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql_statement, values)
    return cur


def sql_run(sql_statement: str, values: Iterable | None = None):
    cur = _sql(sql_statement, values)
    conn = get_conn()
    conn.commit()
    return cur.lastrowid


def sql_select(sql_statement: str, values: Iterable | None = None):
    cur = _sql(sql_statement, values)
    yield from cur.fetchall()


def is_type_optional(type_: Type) -> bool:
    return get_origin(type_) is Union and type(None) in get_args(type_)


class Field:
    def __init__(self, name: str, _type: SQL_TYPE) -> None:
        self.name = name
        self.type = _type

    @property
    def sqlite_type(self) -> str:
        if is_type_optional(self.type):
            for type_ in SQL_TYPES:
                if type_ == self.type_when_not_null:
                    return SQL_TYPES[type_]
        if issubclass(self.type, Model):
            return SQL_TYPES[int]
        return SQL_TYPES[self.type]

    @property
    def type_when_not_null(self) -> Type:
        if not is_type_optional(self.type):
            return self.type
        for arg in get_args(self.type):
            if arg is not type(None):
                return arg

    def get_value(self, value: str) -> SQL_TYPE:
        if issubclass(self.type_when_not_null, Model):
            if value.isdigit():
                # handles case where inserting the foreign key by int instead of
                # an entire model
                return int(value)
            return value.id
        return value

    def __set__(self, instance, value):
        if issubclass(self.type_when_not_null, Model) and isinstance(value, int):
            value = self.type.find(value)
        instance._values[self.name] = value

    def __get__(self, instance, cls):
        if instance:
            return instance._values.get(self.name)
        else:
            return self

    def __str__(self) -> str:
        return f"{self.name}: {self.type}"

    def __repr__(self) -> str:
        return f"{self.name}: {self.type}"


class Model:
    def __init__(self, **kwargs) -> None:
        self._values = {"id": None}
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __init_subclass__(cls) -> None:
        cls.set_table_name()
        cls.set_fields()
        cls.set_cls_attributes()

    def __repr__(self):
        return f"<{self.__class__.__name__} id={self.id} %s>" % " ".join(
            f"{name}={getattr(self, name)!r}" for name in self._fields
        )

    @classmethod
    def set_table_name(cls) -> None:
        name = cls.__name__
        cls._name = "".join(
            ["_" + c.lower() if c.isupper() else c for c in name]
        ).lstrip("_")

    @classmethod
    def set_fields(cls) -> None:
        cls._fields = {
            name: Field(name, _type) for name, _type in cls.__annotations__.items()
        }

    @classmethod
    def set_cls_attributes(cls) -> None:
        for name, field in cls._fields.items():
            setattr(cls, name, field)
        setattr(cls, "id", Field("id", int))

    @classmethod
    def create_table(cls, delete_if_exists: bool = False) -> None:
        if delete_if_exists:
            cls.delete_table()
        template = Template(CREATE_TABLE_TEMPLATE)
        not_null = {}
        for x, y in cls._fields.items():
            not_null[x] = "" if is_type_optional(y.type) else " NOT NULL"
        sql_statement = template.render(
            {"table": cls._name, "fields": cls._fields, "not_null": not_null}
        )
        sql_run(sql_statement)

    @classmethod
    def delete_table(cls) -> None:
        sql_statement = f"DROP TABLE IF EXISTS {cls._name}"
        sql_run(sql_statement)

    @classmethod
    def find_by(cls, field_name: str, value: SQL_TYPE):
        template = Template(FIND_BY_TEMPLATE)
        sql_statement = template.render({"table": cls._name, "field": field_name})
        result = sql_select(sql_statement, (value,))
        return cls(**dict(next(result)))

    @classmethod
    def find(cls, id: int):
        return cls.find_by("id", id)

    @classmethod
    def delete_by(cls, field_name: str, value: SQL_TYPE):
        template = Template(DELETE_BY_TEMPLATE)
        sql_statement = template.render({"table": cls._name, "field": field_name})
        sql_run(sql_statement, (value,))

    @classmethod
    def all(cls):
        sql_statement = f"SELECT * from {cls._name}"
        rows = sql_select(sql_statement)
        for row in rows:
            yield cls(**dict(row))

    @property
    def fields(self) -> dict:
        return self.__class__._fields

    @property
    def table(self) -> str:
        return self.__class__._name

    def save(self):
        if self.id:
            return self._update()
        return self._insert()

    def delete(self) -> None:
        template = Template(DELETE_BY_TEMPLATE)
        sql_statement = template.render({"table": self.table, "field": "id"})
        sql_run(sql_statement, (self.id,))

    def _insert(self) -> None:
        template = Template(INSERT_TEMPLATE)
        field_keys = self.fields.keys()
        sql_statement = template.render({"table": self.table, "fields": field_keys})
        values = self._get_field_values(field_keys)
        self.id = sql_run(sql_statement, values)

    def _update(self) -> None:
        template = Template(UPDATE_TEMPLATE)
        field_keys = self.fields.keys()
        sql_statement = template.render(
            {"table": self.table, "fields": field_keys, "where": "id"}
        )
        values = self._get_field_values(field_keys)
        values.append(self.id)
        sql_run(sql_statement, values)

    def _get_field_values(self, field_keys: Iterable) -> list[SQL_TYPE]:
        values = []
        for key in field_keys:
            field: Field = self.fields[key]
            value = field.get_value(getattr(self, field.name))
            values.append(value)
        return values
