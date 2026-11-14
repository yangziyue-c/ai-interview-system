"""CLI: evaluate paired RAG/KG scoring ablations from JSONL."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.scoring_ablation import load_rows, summarize  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="JSONL with off/kb/kg/both scores")
    parser.add_argument("--output", default="", help="optional JSON output path")
    args = parser.parse_args()
    result = summarize(load_rows(args.input))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
