import os
import aiosqlite
from typing import Type, TypeAlias, Iterable, get_origin, Union, get_args
from jinja2 import Template
from contextlib import contextmanager

DATABASE_PATH = os.environ.get("DATABASE_PATH", "db.db")

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


@contextmanager
def transaction(conn: aiosqlite.Connection):
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


def get_conn() -> aiosqlite.Connection:
    return aiosqlite.connect(
        database=DATABASE_PATH,
        timeout=5,
        detect_types=1,
        isolation_level=None,
        # check_same_thread: bool = True,
        # cached_statements: int = 128,
    )


async def sql_run(sql_statement: str, values: Iterable | None = None):
    async with get_conn() as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(sql_statement, values)
        await db.commit()
    return cursor.lastrowid


async def sql_select(sql_statement: str, values: Iterable | None = None):
    all_rows = []
    async with get_conn() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql_statement, values) as cursor:
            async for row in cursor:
                all_rows.append(row)
    return all_rows


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
        cls._name = ''.join(['_' + c.lower() if c.isupper() else c for c in name]).lstrip('_')

    @classmethod
    def get_table_name(cls) -> str:
        return cls._name

    @classmethod
    def set_fields(cls) -> None:
        cls._fields = {
            name: Field(name, _type) for name, _type in cls.__annotations__.items()
        }

    @classmethod
    def get_field(cls, name) -> Field | None:
        for name, field in cls._fields.items():
            if field.name == name:
                return field
        return None

    @classmethod
    def set_cls_attributes(cls) -> None:
        for name, field in cls._fields.items():
            setattr(cls, name, field)
        setattr(cls, "id", Field("id", int))

    @classmethod
    async def create_table(cls, delete_if_exists: bool = False) -> None:
        if delete_if_exists:
            await cls.delete_table()
        template = Template(CREATE_TABLE_TEMPLATE)
        not_null = {}
        for x, y in cls._fields.items():
            not_null[x] = "" if is_type_optional(y.type) else " NOT NULL"
        sql_statement = template.render({"table": cls._name, "fields": cls._fields, "not_null": not_null})
        await sql_run(sql_statement)

    @classmethod
    async def delete_table(cls) -> None:
        sql_statement = f"DROP TABLE IF EXISTS {cls._name}"
        await sql_run(sql_statement)

    @classmethod
    async def find_by(cls, field_name: str, value: SQL_TYPE):
        template = Template(FIND_BY_TEMPLATE)
        sql_statement = template.render({"table": cls._name, "field": field_name})
        results = await sql_select(sql_statement, (value,))
        return await map_objects(cls, results, many=False)

    @classmethod
    async def find(cls, id: int):
        return await cls.find_by("id", id)

    @classmethod
    async def delete_by(cls, field_name: str, value: SQL_TYPE):
        template = Template(DELETE_BY_TEMPLATE)
        sql_statement = template.render({"table": cls._name, "field": field_name})
        await sql_run(sql_statement, (value,))

    @classmethod
    async def delete(cls, id: int):
        return await cls.delete_by("id", id)

    @classmethod
    async def all(cls):
        sql_statement = f"SELECT * from {cls._name}"
        rows = await sql_select(sql_statement)
        return await map_objects(cls, rows, many=True)

    @property
    def fields(self) -> dict:
        return self.__class__._fields

    @property
    def table(self) -> str:
        return self.__class__._name

    async def save(self):
        if self.id:
            return await self._update()
        return await self._insert()

    async def delete_me(self) -> None:
        template = Template(DELETE_BY_TEMPLATE)
        sql_statement = template.render({"table": self.table, "field": "id"})
        await sql_run(sql_statement, (self.id,))

    async def _insert(self) -> None:
        template = Template(INSERT_TEMPLATE)
        field_keys = self.fields.keys()
        sql_statement = template.render({"table": self.table, "fields": field_keys})
        values = self._get_field_values(field_keys)
        self.id = await sql_run(sql_statement, values)

    async def _update(self) -> None:
        template = Template(UPDATE_TEMPLATE)
        field_keys = self.fields.keys()
        sql_statement = template.render(
            {"table": self.table, "fields": field_keys, "where": "id"}
        )
        values = self._get_field_values(field_keys)
        values.append(self.id)
        await sql_run(sql_statement, values)

    def _get_field_values(self, field_keys: Iterable) -> list[SQL_TYPE]:
        values = []
        for key in field_keys:
            field: Field = self.fields[key]
            value = field.get_value(getattr(self, field.name))
            values.append(value)
        return values


def has_foreign_value(field: Field, column: str) -> bool:
    if column == "id":
        return False
    if issubclass(field.type_when_not_null, Model):
        return True
    return False


async def map_object(cls, **row):
    """Maps an object to the subclass of model, queries for foreign keys"""
    # This can't be done in __init__ (Model) or __set__ (Field) because
    # if we get a foreign key we need to reach out to db and get it
    # This would be an async call and these methods do not support async
    # So this initializes an instance of Model (subclasses) with foreign keys
    instance = cls()  # __init__ Model with no kwargs
    for column, value in row.items():
        field: Field = cls.get_field(column)
        if has_foreign_value(field, column):
            # field.type: Model
            value = await field.type.find(value)  # query foreign model
        setattr(instance, column, value)
    return instance

async def map_objects(cls, rows, many: bool = False):
    """Maps objects to the subclass of model, queries for foreign keys"""
    if many:
        objects = []
        for row in rows:
            obj = await map_object(cls, **dict(row))
            objects.append(obj)
        return objects
    try:
        row = next(iter(rows))
    except StopIteration:
        return None
    return await map_object(cls, **dict(row))


def is_type_optional(type_: Type) -> bool:
    return get_origin(type_) is Union and type(None) in get_args(type_)
