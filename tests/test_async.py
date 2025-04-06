import aiosqlite
import pytest
from litemodel.async_core import Model, Field, init_db
from typing import Optional


# Test models
class Address(Model):
    street: str
    city: Optional[str]


class User(Model):
    name: str
    age: int
    address: Optional[Address]


@pytest.fixture(scope="module")
async def db():
    await init_db(pool_size=2, database_path="test.db", use_pool=True)
    yield
    async with aiosqlite.connect("test.db") as conn:
        await conn.execute("DROP TABLE IF EXISTS address")
        await conn.execute("DROP TABLE IF EXISTS user")
        await conn.commit()
    from litemodel.async_core import _pool

    for conn in _pool.pool:
        await conn.close()
    _pool.pool.clear()


@pytest.mark.asyncio
async def test_field_mapping():
    assert Address.street.sqlite_type == "TEXT"
    assert Address.city.sqlite_type == "TEXT"
    assert User.address.sqlite_type == "INTEGER"


@pytest.mark.asyncio
async def test_create_table(db):
    await Address.create_table(delete_if_exists=True)
    async with aiosqlite.connect("test.db") as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='address'"
        )
        result = await cursor.fetchone()
        assert result is not None
        assert result["name"] == "address"


@pytest.mark.asyncio
async def test_insert_and_find(db):
    await Address.create_table(delete_if_exists=True)
    address = Address(street="123 Main St", city="Springfield")
    await address.save()
    assert address.id is not None

    found = await Address.find(address.id)
    assert found.street == "123 Main St"
    assert found.city == "Springfield"


@pytest.mark.asyncio
async def test_foreign_key(db):
    await Address.create_table(delete_if_exists=True)
    await User.create_table(delete_if_exists=True)
    address = Address(street="456 Elm St")
    await address.save()
    user = User(name="Alice", age=30, address=address)
    await user.save()

    found_user = await User.find(user.id)
    assert found_user.name == "Alice"
    assert found_user.address.street == "456 Elm St"


@pytest.mark.asyncio
async def test_update(db):
    await User.create_table(delete_if_exists=True)
    user = User(name="Bob", age=25)
    await user.save()
    user.age = 26
    await user.save()

    updated = await User.find(user.id)
    assert updated.age == 26


@pytest.mark.asyncio
async def test_delete(db):
    await User.create_table(delete_if_exists=True)
    user = User(name="Charlie", age=40)
    await user.save()
    await user.delete_me()

    deleted = await User.find(user.id)
    assert deleted is None


@pytest.mark.asyncio
async def test_find_by_single(db):
    await Address.create_table(delete_if_exists=True)
    address = Address(street="123 Main St", city="Springfield")
    await address.save()
    found = await Address.find_by(street="123 Main St")
    assert found.street == "123 Main St"
    assert found.city == "Springfield"


@pytest.mark.asyncio
async def test_find_by_multiple(db):
    await User.create_table(delete_if_exists=True)
    user = User(name="Alice", age=30)
    await user.save()
    found = await User.find_by(name="Alice", age=30)
    assert found.name == "Alice"
    assert found.age == 30


@pytest.mark.asyncio
async def test_find_many(db):
    await User.create_table(delete_if_exists=True)
    users = [User(name=f"User{i}", age=20 + i) for i in range(3)]
    for u in users:
        await u.save()
    results = await User.find_many(age=21)
    assert len(results) == 1
    assert results[0].name == "User1"


@pytest.mark.asyncio
async def test_find(db):
    await User.create_table(delete_if_exists=True)
    user = User(name="Bob", age=25)
    await user.save()
    found = await User.find(user.id)
    assert found.name == "Bob"


@pytest.mark.asyncio
async def test_find_by_no_args(db):
    await User.create_table(delete_if_exists=True)
    with pytest.raises(
        ValueError, match="At least one field-value pair must be provided"
    ):
        await User.find_by()


# --- Field Class Tests ---
@pytest.mark.asyncio
async def test_field_sqlite_type_simple(db):
    """Test that Field maps Python types to SQLite types correctly."""
    field = Field("name", str)
    assert field.sqlite_type == "TEXT"


@pytest.mark.asyncio
async def test_field_sqlite_type_optional(db):
    """Test that optional types still map correctly."""
    field = Field("city", Optional[str])
    assert field.sqlite_type == "TEXT"


@pytest.mark.asyncio
async def test_field_sqlite_type_foreign_key(db):
    """Test that foreign key fields map to INTEGER."""
    field = Field("address", Optional[Address])
    assert field.sqlite_type == "INTEGER"


@pytest.mark.asyncio
async def test_field_get_value_simple(db):
    """Test get_value for simple types."""
    field = Field("age", int)
    assert field.get_value(42) == 42


@pytest.mark.asyncio
async def test_field_get_value_foreign_key(db):
    """Test get_value for foreign keys with Model instance."""
    address = Address(street="123 Main St")
    field = Field("address", Address)
    assert field.get_value(address) == address.id  # None initially, but intent is clear


@pytest.mark.asyncio
async def test_field_get_value_string_id(db):
    """Test get_value with string ID for foreign key."""
    field = Field("address", Address)
    assert field.get_value("5") == 5
