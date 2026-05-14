import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.server import create_app
from app.db.session import _engine, _session_factory
from app.db import session as db_session_module
from app.db.init_db import create_tables


TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    await create_tables(engine)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def test_session_factory(test_engine):
    factory = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    return factory


@pytest_asyncio.fixture()
async def db_session(test_session_factory):
    async with test_session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="session")
async def app(test_engine, test_session_factory):
    """FastAPI test application with in-memory DB injected."""
    # Patch the module-level engine and factory used by get_session
    db_session_module._engine = test_engine
    db_session_module._session_factory = test_session_factory

    application = create_app()
    application.state.engine = test_engine
    return application


@pytest_asyncio.fixture()
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
