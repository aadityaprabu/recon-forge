"""Generate the isolated scale-demo fixture, without changing MongoDB."""
from app.config import ROOT
from app.demo.scale_dataset import write_dataset

if __name__ == "__main__":
    result = write_dataset(ROOT / "ReconForge_Scale5000_Dataset")
    print(f"Generated {result['live_base_pairs']} live pairs and {result['historical_base_pairs']} historical pairs")
