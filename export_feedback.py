"""Export tester feedback from the server database to a local JSON file."""

import argparse
import json
import os
import sqlite3
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Private JSON output file; do not commit it")
    parser.add_argument(
        "--database", default=str(Path(os.getenv("CACHE_DIR", "data")) / "workspaces.sqlite3")
    )
    args = parser.parse_args()
    database = Path(args.database).resolve()
    if not database.is_file():
        parser.error("Workspace database does not exist")
    db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        rows = db.execute("SELECT id, body, created FROM feedback ORDER BY created DESC").fetchall()
    finally:
        db.close()
    Path(args.output).write_text(
        json.dumps([{"id": i, "created": t, **json.loads(body)} for i, body, t in rows], indent=2),
        encoding="utf-8",
    )
    print(f"Exported {len(rows)} feedback entries.")


if __name__ == "__main__":
    main()
