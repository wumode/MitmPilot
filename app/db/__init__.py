import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any, Literal, Self, overload

from sqlalchemy import (
    Column,
    Engine,
    Identity,
    Integer,
    NullPool,
    QueuePool,
    Sequence,
    and_,
    create_engine,
    delete,
    inspect,
    select,
    text,
)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import (
    Session,
    as_declarative,
    declared_attr,
    scoped_session,
    sessionmaker,
)

from app.core.config import settings


def get_id_column():
    """Returns the appropriate ID column definition based on the database type."""
    if settings.DB_TYPE.lower() == "postgresql":
        # PostgreSQL uses SERIAL type to let the database handle sequences automatically.
        return Column(
            Integer, Identity(start=1, cycle=True), primary_key=True, index=True
        )
    else:
        # SQLite uses Sequence.
        return Column(Integer, Sequence("id"), primary_key=True, index=True)


@overload
def _get_database_engine(is_async: Literal[False] = False) -> Engine: ...


@overload
def _get_database_engine(is_async: Literal[True]) -> AsyncEngine: ...


def _get_database_engine(is_async: bool = False) -> Engine | AsyncEngine:
    """Get database connection parameters and set WAL mode.

    :param is_async: Whether to create an asynchronous engine
        - True: asynchronous engine
        - False: synchronous engine
    :return: Returns the corresponding database engine
    """
    # Select connection method based on database type
    if settings.DB_TYPE.lower() == "postgresql":
        return _get_postgresql_engine(is_async)
    else:
        return _get_sqlite_engine(is_async)


def _get_sqlite_engine(is_async: bool = False):
    """Get SQLite database engine."""
    # Connection parameters
    _connect_args = {
        "timeout": settings.DB_TIMEOUT,
    }
    # Additional configuration when WAL mode is enabled
    if settings.DB_WAL_ENABLE:
        _connect_args["check_same_thread"] = False

    # Create synchronous engine
    if not is_async:
        # Set poolclass and related parameters based on pool type
        _pool_class = NullPool if settings.DB_POOL_TYPE == "NullPool" else QueuePool

        # Database parameters
        _db_kwargs = {
            "url": f"sqlite:///{settings.CONFIG_PATH}/user.db",
            "pool_pre_ping": settings.DB_POOL_PRE_PING,
            "echo": settings.DB_ECHO,
            "poolclass": _pool_class,
            "pool_recycle": settings.DB_POOL_RECYCLE,
            "connect_args": _connect_args,
        }

        # When using QueuePool, add QueuePool-specific parameters
        if _pool_class == QueuePool:
            _db_kwargs.update(
                {
                    "pool_size": settings.DB_SQLITE_POOL_SIZE,
                    "pool_timeout": settings.DB_POOL_TIMEOUT,
                    "max_overflow": settings.DB_SQLITE_MAX_OVERFLOW,
                }
            )

        # Create database engine
        engine = create_engine(**_db_kwargs)

        # Set WAL mode
        _journal_mode = "WAL" if settings.DB_WAL_ENABLE else "DELETE"
        with engine.connect() as connection:
            current_mode = connection.execute(
                text(f"PRAGMA journal_mode={_journal_mode};")
            ).scalar()
            print(f"SQLite database journal mode set to: {current_mode}")

        return engine
    else:
        # Database parameters, can only use NullPool
        _db_kwargs = {
            "url": f"sqlite+aiosqlite:///{settings.CONFIG_PATH}/user.db",
            "pool_pre_ping": settings.DB_POOL_PRE_PING,
            "echo": settings.DB_ECHO,
            "poolclass": NullPool,
            "pool_recycle": settings.DB_POOL_RECYCLE,
            "connect_args": _connect_args,
        }
        # Create asynchronous database engine
        async_engine = create_async_engine(**_db_kwargs)

        # Set WAL mode
        _journal_mode = "WAL" if settings.DB_WAL_ENABLE else "DELETE"

        async def set_async_wal_mode():
            """Set WAL mode for asynchronous engine."""
            async with async_engine.connect() as _connection:
                result = await _connection.execute(
                    text(f"PRAGMA journal_mode={_journal_mode};")
                )
                _current_mode = result.scalar()
                print(f"Async SQLite database journal mode set to: {_current_mode}")

        try:
            asyncio.run(set_async_wal_mode())
        except Exception as e:
            print(f"Failed to set async SQLite WAL mode: {e}")

        return async_engine


def _get_postgresql_engine(is_async: bool = False):
    """Get PostgreSQL database engine."""
    # Build PostgreSQL connection URL
    if settings.DB_POSTGRESQL_PASSWORD:
        db_url = f"postgresql://{settings.DB_POSTGRESQL_USERNAME}:{settings.DB_POSTGRESQL_PASSWORD}@{settings.DB_POSTGRESQL_HOST}:{settings.DB_POSTGRESQL_PORT}/{settings.DB_POSTGRESQL_DATABASE}"
    else:
        db_url = f"postgresql://{settings.DB_POSTGRESQL_USERNAME}@{settings.DB_POSTGRESQL_HOST}:{settings.DB_POSTGRESQL_PORT}/{settings.DB_POSTGRESQL_DATABASE}"

    # PostgreSQL connection parameters
    _connect_args = {}

    # Create synchronous engine
    if not is_async:
        # Set poolclass and related parameters based on pool type
        _pool_class = NullPool if settings.DB_POOL_TYPE == "NullPool" else QueuePool

        # Database parameters
        _db_kwargs = {
            "url": db_url,
            "pool_pre_ping": settings.DB_POOL_PRE_PING,
            "echo": settings.DB_ECHO,
            "poolclass": _pool_class,
            "pool_recycle": settings.DB_POOL_RECYCLE,
            "connect_args": _connect_args,
        }

        # When using QueuePool, add QueuePool-specific parameters
        if _pool_class == QueuePool:
            _db_kwargs.update(
                {
                    "pool_size": settings.DB_POSTGRESQL_POOL_SIZE,
                    "pool_timeout": settings.DB_POOL_TIMEOUT,
                    "max_overflow": settings.DB_POSTGRESQL_MAX_OVERFLOW,
                }
            )

        # Create database engine
        engine = create_engine(**_db_kwargs)
        print(
            f"PostgreSQL database connected to {settings.DB_POSTGRESQL_HOST}:{settings.DB_POSTGRESQL_PORT}/{settings.DB_POSTGRESQL_DATABASE}"
        )

        return engine
    else:
        # Build asynchronous PostgreSQL connection URL
        async_db_url = f"postgresql+asyncpg://{settings.DB_POSTGRESQL_USERNAME}:{settings.DB_POSTGRESQL_PASSWORD}@{settings.DB_POSTGRESQL_HOST}:{settings.DB_POSTGRESQL_PORT}/{settings.DB_POSTGRESQL_DATABASE}"

        # Database parameters, can only use NullPool
        _db_kwargs = {
            "url": async_db_url,
            "pool_pre_ping": settings.DB_POOL_PRE_PING,
            "echo": settings.DB_ECHO,
            "poolclass": NullPool,
            "pool_recycle": settings.DB_POOL_RECYCLE,
            "connect_args": _connect_args,
        }
        # Create asynchronous database engine
        async_engine = create_async_engine(**_db_kwargs)
        print(
            f"Async PostgreSQL database connected to {settings.DB_POSTGRESQL_HOST}:{settings.DB_POSTGRESQL_PORT}/{settings.DB_POSTGRESQL_DATABASE}"
        )

        return async_engine


# Synchronous database engine
DBEngine: Engine = _get_database_engine(is_async=False)

# Asynchronous database engine
AsyncDBEngine: AsyncEngine = _get_database_engine(is_async=True)

# Synchronous session factory
SessionFactory = sessionmaker(bind=DBEngine)

# Asynchronous session factory
AsyncSessionFactory = async_sessionmaker(bind=AsyncDBEngine, class_=AsyncSession)

# Synchronous multi-threaded global database session
ScopedSession = scoped_session(SessionFactory)


def get_db() -> Generator:
    """Get a database session for web requests.

    :return: Session
    """
    db = None
    try:
        db = SessionFactory()
        yield db
    finally:
        if db:
            db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession]:
    """Get an asynchronous database session for web requests.

    :return: AsyncSession
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        finally:
            await session.close()


async def close_database():
    """Close all database connections and clean up resources."""
    try:
        # Dispose of the synchronous connection pool
        DBEngine.dispose()
        # Dispose of the asynchronous connection pool
        await AsyncDBEngine.dispose()
    except Exception as err:
        print(f"Error while disposing database connections: {err}")


def _get_args_db(args: tuple, kwargs: dict) -> Session | None:
    """Get the database Session object from the arguments."""
    db = None
    if args:
        for arg in args:
            if isinstance(arg, Session):
                db = arg
                break
    if kwargs:
        for _, value in kwargs.items():
            if isinstance(value, Session):
                db = value
                break
    return db


def _get_args_async_db(args: tuple, kwargs: dict) -> AsyncSession | None:
    """Get the asynchronous database AsyncSession object from the arguments."""
    db = None
    if args:
        for arg in args:
            if isinstance(arg, AsyncSession):
                db = arg
                break
    if kwargs:
        for _, value in kwargs.items():
            if isinstance(value, AsyncSession):
                db = value
                break
    return db


def _update_args_db(args: tuple, kwargs: dict, db: Session) -> tuple[tuple, dict]:
    """Update the database Session object in the arguments.

    When passing by keyword, update the value of db, otherwise update the 1st or 2nd
    argument.
    """
    if kwargs and "db" in kwargs:
        kwargs["db"] = db
    elif args:
        if args[0] is None:
            args = (db, *args[1:])
        else:
            args = (args[0], db, *args[2:])
    return args, kwargs


def _update_args_async_db(
    args: tuple, kwargs: dict, db: AsyncSession
) -> tuple[tuple, dict]:
    """Update the asynchronous database AsyncSession object in the arguments.

    When passing by keyword, update the value of db, otherwise update the 1st or 2nd
    argument.
    """
    if kwargs and "db" in kwargs:
        kwargs["db"] = db
    elif args:
        if args[0] is None:
            args = (db, *args[1:])
        else:
            args = (args[0], db, *args[2:])
    return args, kwargs


def db_update(func):
    """Decorator for database update operations.

    The first parameter must be a database session or a db parameter must exist.
    """

    def wrapper(*args, **kwargs):
        # Whether to close the database session
        _close_db = False
        # Get the database session from the arguments
        db = _get_args_db(args, kwargs)
        if not db:
            # If no database session is obtained, create one
            db = ScopedSession()
            # Mark that the database session needs to be closed
            _close_db = True
            # Update the database session in the arguments
            args, kwargs = _update_args_db(args, kwargs, db)
        try:
            # Execute the function
            result = func(*args, **kwargs)
            # Commit the transaction
            db.commit()
        except Exception as err:
            # Rollback the transaction
            db.rollback()
            raise err
        finally:
            # Close the database session
            if _close_db:
                db.close()
        return result

    return wrapper


def async_db_update(func):
    """Asynchronous decorator for database update operations.

    The first parameter must be an asynchronous database session or a db parameter must
    exist.
    """

    async def wrapper(*args, **kwargs):
        # Whether to close the database session
        _close_db = False
        # Get the asynchronous database session from the arguments
        db = _get_args_async_db(args, kwargs)
        if not db:
            # If no asynchronous database session is obtained, create one
            db = AsyncSessionFactory()
            # Mark that the database session needs to be closed
            _close_db = True
            # Update the asynchronous database session in the arguments
            args, kwargs = _update_args_async_db(args, kwargs, db)
        try:
            # Execute the function
            result = await func(*args, **kwargs)
            # Commit the transaction
            await db.commit()
        except Exception as err:
            # Rollback the transaction
            await db.rollback()
            raise err
        finally:
            # Close the database session
            if _close_db:
                await db.close()
        return result

    return wrapper


def db_query(func):
    """Decorator for database query operations.

    The first parameter must be a database session or a db parameter must exist.
    Note: When querying list data with db.query, you need to convert it to a list before returning.
    """

    def wrapper(*args, **kwargs):
        # Whether to close the database session
        _close_db = False
        # Get the database session from the arguments
        db = _get_args_db(args, kwargs)
        if not db:
            # If no database session is obtained, create one
            db = ScopedSession()
            # Mark that the database session needs to be closed
            _close_db = True
            # Update the database session in the arguments
            args, kwargs = _update_args_db(args, kwargs, db)
        try:
            # Execute the function
            result = func(*args, **kwargs)
        except Exception as err:
            raise err
        finally:
            # Close the database session
            if _close_db:
                db.close()
        return result

    return wrapper


def async_db_query(func):
    """Asynchronous decorator for database query operations.

    The first parameter must be an asynchronous database session or a db parameter must exist.
    Note: When querying list data with db.query, you need to convert it to a list before returning.
    """

    async def wrapper(*args, **kwargs):
        # Whether to close the database session
        _close_db = False
        # Get the asynchronous database session from the arguments
        db = _get_args_async_db(args, kwargs)
        if not db:
            # If no asynchronous database session is obtained, create one
            db = AsyncSessionFactory()
            # Mark that the database session needs to be closed
            _close_db = True
            # Update the asynchronous database session in the arguments
            args, kwargs = _update_args_async_db(args, kwargs, db)
        try:
            # Execute the function
            result = await func(*args, **kwargs)
        except Exception as err:
            raise err
        finally:
            # Close the database session
            if _close_db:
                await db.close()
        return result

    return wrapper


@as_declarative()
class Base:
    id: Any
    __name__: str

    @db_update
    def create(self, db: Session):
        db.add(self)

    @async_db_update
    async def async_create(self, db: AsyncSession):
        db.add(self)
        await db.flush()
        return self

    @classmethod
    @db_query
    def get(cls, db: Session, rid: int) -> Self:
        return db.query(cls).filter(and_(cls.id == rid)).first()

    @classmethod
    @async_db_query
    async def async_get(cls, db: AsyncSession, rid: int) -> Self:
        result = await db.execute(select(cls).where(and_(cls.id == rid)))
        return result.scalars().first()

    @db_update
    def update(self, db: Session, payload: dict):
        payload = {k: v for k, v in payload.items() if v is not None}
        for key, value in payload.items():
            setattr(self, key, value)
        if inspect(self).detached:
            db.add(self)

    @async_db_update
    async def async_update(self, db: AsyncSession, payload: dict):
        payload = {k: v for k, v in payload.items() if v is not None}
        for key, value in payload.items():
            setattr(self, key, value)
        if inspect(self).detached:
            db.add(self)

    @classmethod
    @db_update
    def delete(cls, db: Session, rid):
        db.query(cls).filter(and_(cls.id == rid)).delete()

    @classmethod
    @async_db_update
    async def async_delete(cls, db: AsyncSession, rid):
        result = await db.execute(select(cls).where(and_(cls.id == rid)))
        user = result.scalars().first()
        if user:
            await db.delete(user)

    @classmethod
    @db_update
    def truncate(cls, db: Session):
        db.query(cls).delete()

    @classmethod
    @async_db_update
    async def async_truncate(cls, db: AsyncSession):
        await db.execute(delete(cls))

    @classmethod
    @db_query
    def list(cls, db: Session) -> list[Self]:
        return db.query(cls).all()

    @classmethod
    @async_db_query
    async def async_list(cls, db: AsyncSession) -> Sequence[Self]:
        result = await db.execute(select(cls))
        return result.scalars().all()

    def to_dict(self):
        return {c.name: getattr(self, c.name, None) for c in self.__table__.columns}  # noqa

    @declared_attr
    def __tablename__(self) -> str:
        return self.__name__.lower()


class DbOper:
    """Base class for database operations."""

    def __init__(self, db: Session | AsyncSession = None):
        self._db = db
