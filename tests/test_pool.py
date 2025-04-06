import asyncio
import aiosqlite
import pytest
from litemodel.pool import ConnectionPool


@pytest.fixture
async def pool():
    pool = ConnectionPool(size=2, database_path="test.db")
    await pool.initialize()
    yield pool
    for conn in pool._all_connections:
        if conn._running:
            await conn.close()
    pool.pool.clear()
    pool._all_connections.clear()


@pytest.mark.asyncio
async def test_initialize_creates_connections(pool):
    assert len(pool.pool) == 2
    for conn in pool.pool:
        assert isinstance(conn, aiosqlite.Connection)
        assert conn._running


@pytest.mark.asyncio
async def test_get_returns_connection(pool):
    conn = await pool.get()
    assert isinstance(conn, aiosqlite.Connection)
    assert len(pool.pool) == 1


@pytest.mark.asyncio
async def test_release_returns_connection(pool):
    conn = await pool.get()
    await pool.release(conn)
    assert len(pool.pool) == 2


@pytest.mark.asyncio
async def test_release_closes_excess_connections(pool):
    conn1 = await pool.get()  # 2 -> 1
    conn2 = await pool.get()  # 1 -> 0
    await pool.release(conn1)  # 0 -> 1
    await pool.release(conn2)  # 1 -> 2 (pool full)
    extra_conn = await aiosqlite.connect("test.db")
    await pool.release(extra_conn)  # Pool full, should close extra_conn
    assert len(pool.pool) == 2
    assert not extra_conn._running


@pytest.mark.asyncio
async def test_concurrent_access(pool):
    async def get_and_release():
        conn = await pool.get()
        await asyncio.sleep(0.01)
        await pool.release(conn)

    await asyncio.gather(*[get_and_release() for _ in range(4)])
    assert len(pool.pool) == 2
