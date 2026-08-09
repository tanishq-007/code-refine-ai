"""Small few-shot fix examples for fix generation."""
from __future__ import annotations

from typing import Dict, List

FIX_EXAMPLES: Dict[str, List[Dict]] = {
    "missing_docstring": [
        {
            "finding_type": "missing_docstring",
            "before": "def parse_config(path):\n    return path.strip()",
            "after": "def parse_config(path):\n    \"\"\"Parse a config path and return its trimmed string.\"\"\"\n    return path.strip()",
        }
    ],
    "magic_number": [
        {
            "finding_type": "magic_number",
            "before": "def format_total(total):\n    return total * 0.8",
            "after": "DISCOUNT_RATE = 0.8\n\ndef format_total(total):\n    return total * DISCOUNT_RATE",
        }
    ],
    "unused_import": [
        {
            "finding_type": "unused_import",
            "before": "import os\n\ndef load(path):\n    return path.strip()",
            "after": "def load(path):\n    return path.strip()",
        }
    ],
}


def get_examples(finding_type: str, limit: int = 2) -> List[Dict]:
    return FIX_EXAMPLES.get(finding_type, [])[:limit]
