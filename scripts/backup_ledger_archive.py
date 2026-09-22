"""Back up, verify, or restore local ledger evidence without accessing services.

ZIP files contain unencrypted private statement bytes. Keep them local and private.
All paths must remain under the repository backups directory. Restore requires a
new destination directory and never merges or overwrites existing evidence.
Restore verifies everything first, then copies exclusively into a reserved new
directory. Publication is not atomic: interruption leaves the partial directory
for inspection, and retry must choose another new destination.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.ledger.archive import backup, restore, verify  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("backup", help="Create an unencrypted local evidence ZIP")
    create.add_argument("source", type=Path)
    create.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify", help="Verify all evidence bytes and manifest entries")
    check.add_argument("archive", type=Path)
    recover = commands.add_parser("restore", help="Restore into a new directory")
    recover.add_argument("archive", type=Path)
    recover.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            result = backup(args.source, args.output, root=ROOT)
        elif args.command == "restore":
            result = restore(args.archive, args.destination, root=ROOT)
        else:
            result = verify(args.archive, root=ROOT)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"status": "failed", "reason": "ledger_archive_failed"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
