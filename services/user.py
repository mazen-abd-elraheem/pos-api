from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.domain import User
from auth.security import hash_password

class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_employees(self):
        result = await self.db.execute(
            select(User).where(User.is_active == True).order_by(User.id)
        )
        return result.scalars().all()

    async def create_employee(self, data: dict):
        pw_hash = hash_password(data["password"])
        new_user = User(
            name=data["name"],
            username=data["username"],
            password=pw_hash,
            role=data.get("role", "cashier"),
            is_active=True
        )
        self.db.add(new_user)
        await self.db.commit()
        await self.db.refresh(new_user)
        return new_user.id

    async def update_employee(self, user_id: int, data: dict):
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False
            
        for key in ("name", "username", "role", "is_active"):
            if key in data and data[key] is not None:
                setattr(user, key, data[key])
                
        await self.db.commit()
        return True

    async def delete_employee(self, user_id: int):
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False
        
        user.is_active = False
        await self.db.commit()
        return True

    async def change_password(self, user_id: int, new_password: str):
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False
            
        user.password = hash_password(new_password)
        await self.db.commit()
        return True
