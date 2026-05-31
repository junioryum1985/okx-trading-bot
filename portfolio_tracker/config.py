import yaml
from pathlib import Path
from typing import List, Dict


def load_config(path: str = "config.yaml") -> List[Dict]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    wallets = data.get("wallets", [])
    if not wallets:
        raise ValueError("No wallets found in config file")

    return wallets
