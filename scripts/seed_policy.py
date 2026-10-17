"""Run with python -m scripts.seed_policy to initialize only the policy."""
import asyncio

from app.config import Settings
from app.persistence.mongo import connect
from app.policies import seed_policy
from app.demo.generator import Dataset


async def main():
    settings = Settings.from_env()
    client, db = connect(settings)
    try:
        await db.harness_policies.create_index("version", unique=True)
        baseline = Dataset(settings.dataset_dir).baseline()
        await seed_policy(db, baseline)
        saved = await db.harness_policies.find_one({"version": baseline.version})
        assert saved["policy"] == baseline.model_dump()
        active = await db.control.find_one({"_id": "active_policy"})
        print(f"Verified {baseline.version} in {settings.mongodb_db}.harness_policies; "
              f"active policy: {active['policy']['version']}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
