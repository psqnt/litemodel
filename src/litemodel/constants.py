from typing import TypeAlias


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
