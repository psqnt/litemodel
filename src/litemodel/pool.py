import asyncio
import aiosqlite
import os
from collections import deque
from .constants import SQLITE_PRAGMAS


DEFAULT_POOL_SIZE = os.environ.get("DEFAULT_POOL_SIZE", 10)


class ConnectionPool:
    def __init__(self, size: int, database_path: str = DEFAULT_POOL_SIZE):
        self.size = size
        self.database_path = database_path
        self.pool = deque(maxlen=size)
        self.lock = asyncio.Lock()
        self._all_connections = set()

    async def initialize(self):
        async with self.lock:
            while len(self.pool) < self.size:
                conn = await aiosqlite.connect(
                    database=self.database_path,
                    timeout=5,
                    detect_types=1,
                    isolation_level=None,
                )
                conn.row_factory = aiosqlite.Row
                for pragma in SQLITE_PRAGMAS:
                    await conn.execute(pragma)
                await conn.commit()
                self.pool.append(conn)
                self._all_connections.add(conn)

    async def get(self) -> aiosqlite.Connection:
        async with self.lock:
            print(f"Get: pool size before = {len(self.pool)}")
            if not self.pool:
                conn = await aiosqlite.connect(
                    self.database_path,
                    timeout=5,
                    detect_types=1,
                    isolation_level=None,
                )
                conn.row_factory = aiosqlite.Row
                print(f"Get: created new connection {conn}")
                self._all_connections.add(conn)
                return conn
            conn = self.pool.popleft()
            print(f"Get: pool size after = {len(self.pool)}")
            return conn

    async def release(self, conn: aiosqlite.Connection):
        async with self.lock:
            print(f"Release: pool size before = {len(self.pool)}, adding {conn}")
            if len(self.pool) < self.size:
                self.pool.append(conn)
                print(f"Release: pool size after = {len(self.pool)}")
            else:
                await conn.close()
                print(f"Release: closed {conn}")
