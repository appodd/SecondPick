"""Lint saved replay prose without inference or modifying the original report."""
import argparse
import json
from pathlib import Path

from shopping_agent.answer_copy_audit import audit_answer_copy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_answer_copy(json.loads(args.source.read_text(encoding="utf-8")))
    result["source_report"] = str(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({key: result[key] for key in ("state", "calls", "finding_count", "complete")}))
    return 0 if result["state"] == "checks_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
