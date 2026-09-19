from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

def get_engine(url: str):
    return create_async_engine(url, echo=False)

def get_session_maker(engine):
    return async_sessionmaker(
        engine, 
        class_=AsyncSession, 
        expire_on_commit=False
    )
