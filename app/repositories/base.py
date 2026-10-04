"""Base async repository providing common CRUD primitives."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base


class BaseRepository[ModelType: Base]:
    """Generic repository implementation for SQLAlchemy models."""

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, entity_id: uuid.UUID | str) -> ModelType | None:
        uid = uuid.UUID(str(entity_id)) if isinstance(entity_id, str) else entity_id
        result = await self.session.execute(select(self.model).where(self.model.id == uid))
        return result.scalar_one_or_none()

    async def add(self, entity: ModelType) -> ModelType:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: ModelType) -> None:
        await self.session.delete(entity)
        await self.session.flush()
