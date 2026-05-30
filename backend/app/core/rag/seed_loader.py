"""
Seed data loader for RAG knowledge base.

Loads seed data from JSON files in `backend/data/` and provides typed
accessor functions. Keeps raw law blocks and HS code directory entries
separate from indexing logic.

Usage:
    from app.core.rag.seed_loader import load_seed_law_blocks, load_seed_hs_codes

    blocks = load_seed_law_blocks()   # list[dict]
    entries = load_seed_hs_codes()    # list[dict]
"""

import json
from pathlib import Path
from typing import List, Dict, Any

# ---------------------------------------------------------------------------
# Path resolution — data directory is backend/data/
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _load_json(filename: str) -> List[Dict[str, Any]]:
    """Load a JSON list of dicts from the data directory."""
    path = _DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Seed data file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Expected a JSON list in {path}, got {type(data).__name__}")
    return data


def load_seed_law_blocks() -> List[Dict[str, Any]]:
    """Load sample Customs & Tax Code seed blocks (5 entries)."""
    return _load_json("seed_law_blocks.json")


def load_seed_hs_codes() -> List[Dict[str, Any]]:
    """Load sample HS code directory entries (5 entries)."""
    return _load_json("seed_hs_codes.json")
