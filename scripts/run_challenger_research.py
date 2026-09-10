"""Run the fixed research comparison against a local daily OHLCV JSON file."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.challenger_research import run_challenger_research  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    source = args.input.read_bytes()
    result = run_challenger_research(json.loads(source))
    result["input_file_sha256"] = sha256(source).hexdigest()
    result["runner_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
    serialized = json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(serialized + "\n")


if __name__ == "__main__":
    main()
