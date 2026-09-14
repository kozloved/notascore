from __future__ import annotations

import json

from evaluation.paired_corpus import paired_inventory


def main() -> int:
    payload = paired_inventory()
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0 if payload["complete_slots"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
