"""Store local policy and Python artifacts: python -m scripts.seed_patches."""
import asyncio

from app.config import Settings
from app.evolution_patches import seed_patch_versions
from app.persistence.mongo import connect


async def main():
    settings = Settings.from_env()
    client, db = connect(settings)
    try:
        count = await seed_patch_versions(db)
        print(f"Verified {count} local artifact versions in {settings.mongodb_db}.evolution_patch_versions")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
