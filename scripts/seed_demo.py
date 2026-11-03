# scripts/seed_demo.py
# 创建演示账号 demo / demo123456（幂等）。
# 只写 users 表，不碰知识库数据（medical_cases / qa_pairs / case_chunks）。
#
# 用法：
#   python scripts/seed_demo.py

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.security import hash_password  # noqa: E402
from backend.db import repositories as repo  # noqa: E402
from backend.db.migrations import run_migrations  # noqa: E402
from backend.db.session import AsyncSessionLocal, dispose_engine  # noqa: E402

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo123456"


async def main() -> None:
    await run_migrations()
    async with AsyncSessionLocal() as db:
        existing = await repo.get_user_by_username(db, DEMO_USERNAME)
        if existing:
            print(f"演示账号已存在：{DEMO_USERNAME} / {DEMO_PASSWORD}")
        else:
            await repo.create_user(
                db,
                username=DEMO_USERNAME,
                password_hash=hash_password(DEMO_PASSWORD),
                display_name="演示用户",
                age=32,
                gender="female",
            )
            await db.commit()
            print(f"已创建演示账号：{DEMO_USERNAME} / {DEMO_PASSWORD}")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
