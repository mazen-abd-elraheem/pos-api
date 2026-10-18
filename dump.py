import asyncio
from core.database import execute

async def main():
    await execute("UPDATE users SET password = 'password' WHERE username IN ('admin', 'master_admin');")
    print("Passwords reset to 'password' for admin and master_admin")

if __name__ == '__main__':
    asyncio.run(main())
