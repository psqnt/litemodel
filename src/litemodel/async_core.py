import os
import aiosqlite
from typing import Type, Iterable, get_origin, Union, get_args
from jinja2 import Template
from contextlib import contextmanager
from .constants import SQL_TYPES, SQL_TYPE
from .sql_templates import (
    CREATE_TABLE_TEMPLATE,
    DELETE_BY_TEMPLATE,
    INSERT_TEMPLATE,
    FIND_BY_TEMPLATE,
    UPDATE_TEMPLATE,
)
from .pool import DEFAULT_POOL_SIZE, ConnectionPool

_pool = None

DATABASE_PATH = os.environ.get("DATABASE_PATH", "db.db")

DEBUG = os.environ.get("DEBUG", False)
if DEBUG:
    print(f"DATABASE_PATH={DATABASE_PATH}")


class Field:
    def __init__(self, name: str, _type: SQL_TYPE) -> None:
        self.name = name
        self.type = _type

    @property
    def sqlite_type(self) -> str:
        print(f"{self.type=}")
        if is_type_optional(self.type):
            for type_ in SQL_TYPES:
                if type_ == self.type_when_not_null:
                    return SQL_TYPES[type_]
        if issubclass(self.type_when_not_null, Model):
            return SQL_TYPES[int]
        return SQL_TYPES[self.type]

    @property
    def type_when_not_null(self) -> Type:
        if not is_type_optional(self.type):
            return self.type
        for arg in get_args(self.type):
            if arg is not type(None):
                return arg

    def get_value(self, value: any) -> SQL_TYPE:
        print(f"{value=}")
        print(f"{type(value)=}")
        if value is None and is_type_optional(self.type):
            return None
        if issubclass(self.type_when_not_null, Model):
            if isinstance(value, str) and value.isdigit():
                # Handle case where value is a string ID (e.g., "1")
                return int(value)
            elif isinstance(value, Model):
                # Handle case where value is a Model instance (e.g., Address)
                return value.id
            else:
                raise ValueError(
                    f"Expected a string ID or {self.type_when_not_null.__name__} instance, got {type(value)}"
                )
        if DEBUG:
            print(f"{self.type=}")
            print(f"{value=}")
        if self.type is bool and value is None:
            return False
        return value

    def __set__(self, instance, value):
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
    def get_table_name(cls) -> str:
        return cls._name

    @classmethod
    def set_fields(cls) -> None:
        cls._fields = {
            name: Field(name, _type) for name, _type in cls.__annotations__.items()
        }

    @classmethod
    def get_field(cls, name) -> Field | None:
        return cls._fields.get(name)

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
        sql_statement = template.render(
            {"table": cls._name, "fields": cls._fields, "not_null": not_null}
        )
        await sql_run(sql_statement)

    @classmethod
    async def delete_table(cls) -> None:
        sql_statement = f"DROP TABLE IF EXISTS {cls._name}"
        await sql_run(sql_statement)

    @classmethod
    async def find_by(cls, **kwargs):
        """Find the first record matching all provided field-value pairs."""
        if not kwargs:
            raise ValueError("At least one field-value pair must be provided")
        field_names, values = zip(*kwargs.items()) if kwargs else ([], [])
        template = Template(FIND_BY_TEMPLATE)
        sql_statement = template.render({"table": cls._name, "fields": field_names})
        results = await sql_select(sql_statement, values)
        return await map_objects(cls, results, many=False)

    @classmethod
    async def find_many(cls, **kwargs):
        """Find all records matching all provided field-value pairs."""
        if not kwargs:
            raise ValueError("At least one field-value pair must be provided")
        field_names, values = zip(*kwargs.items()) if kwargs else ([], [])
        template = Template(FIND_BY_TEMPLATE)
        sql_statement = template.render({"table": cls._name, "fields": field_names})
        results = await sql_select(sql_statement, values)
        return await map_objects(cls, results, many=True)

    @classmethod
    async def find(cls, id: int):
        """Find a record by its ID."""
        return await cls.find_by(id=id)

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


async def init_db(
    pool_size: int = DEFAULT_POOL_SIZE,
    database_path: str = DATABASE_PATH,
    use_pool: bool = True,
):
    global _pool, DATABASE_PATH
    DATABASE_PATH = database_path
    if use_pool:
        _pool = ConnectionPool(pool_size, database_path)
        await _pool.initialize()


async def sql_run(
    sql_statement: str,
    values: Iterable | None = None,
    conn: aiosqlite.Connection | None = None,
):
    if conn is None and _pool is not None:
        conn = await _pool.get()
        try:
            cursor = await conn.execute(sql_statement, values)
            await conn.commit()
            lastrowid = cursor.lastrowid
        finally:
            await _pool.release(conn)
        return lastrowid
    elif conn is not None:
        cursor = await conn.execute(sql_statement, values)
        await conn.commit()
        return cursor.lastrowid
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql_statement, values)
            await db.commit()
            return cursor.lastrowid


async def sql_select(
    sql_statement: str,
    values: Iterable | None = None,
    conn: aiosqlite.Connection | None = None,
):
    if conn is None and _pool is not None:
        conn = await _pool.get()
        try:
            all_rows = []
            async with conn.execute(sql_statement, values) as cursor:
                async for row in cursor:
                    all_rows.append(row)
            return all_rows
        finally:
            await _pool.release(conn)
    elif conn is not None:
        all_rows = []
        async with conn.execute(sql_statement, values) as cursor:
            async for row in cursor:
                all_rows.append(row)
        return all_rows
    else:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql_statement, values) as cursor:
                all_rows = []
                async for row in cursor:
                    all_rows.append(row)
            return all_rows


def has_foreign_value(field: Field, column: str) -> bool:
    if column == "id":
        return False
    return issubclass(field.type_when_not_null, Model)


async def map_object(cls, **row):
    """Maps an object to the subclass of model, queries for foreign keys"""
    # This can't be done in __init__ (Model) or __set__ (Field) because
    # if we get a foreign key we need to reach out to db and get it
    # This would be an async call and these methods do not support async
    # So this initializes an instance of Model (subclasses) with foreign keys
    instance = cls()  # __init__ Model with no kwargs
    for column, value in row.items():
        field: Field = cls.get_field(column)
        if field and has_foreign_value(field, column) and isinstance(value, int):
            # field.type: Model
            value = await field.type_when_not_null.find(value)  # query foreign model
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
