"""User repository for managing user identities and notification preferences."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.notification import NotificationPreference
from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def get_by_oauth_sub(self, oauth_sub: str) -> User | None:
        stmt = (
            select(User)
            .options(selectinload(User.notification_preference))
            .where(User.oauth_sub == oauth_sub)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(self, oauth_sub: str, email: str | None = None) -> User:
        user = await self.get_by_oauth_sub(oauth_sub)
        if user:
            if email and user.email != email:
                user.email = email
                await self.session.flush()
            return user

        user = User(
            id=uuid.uuid4(),
            oauth_sub=oauth_sub,
            email=email,
        )
        self.session.add(user)
        await self.session.flush()

        pref = NotificationPreference(
            id=uuid.uuid4(),
            user_id=user.id,
            email_enabled=True,
        )
        self.session.add(pref)
        await self.session.flush()
        return user
