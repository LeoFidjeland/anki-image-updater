#!/usr/bin/env python3
"""
Normalize Image Source on notes tagged with the app's "Replaced" tag (or a custom tag).

- Strips HTML and keeps a single plain https?:// URL (e.g. from <a href="...">).
- On *.wikimedia.org URLs, removes the ``oldid`` query parameter.
- Strips URL fragments (``#…``) for all links.
- On main Freepik / Unsplash / Pexels / Pixabay *page* URLs (not CDNs), strips
  query strings (UTM, share, SPA state). Other sites keep their query (e.g.
  Wikimedia ``?title=…``).

Requires Anki running with AnkiConnect. Uses the same settings.json field names as the GUI.

Usage (from repo root)::

    uv run python scripts/clean_image_sources.py
    uv run python scripts/clean_image_sources.py --dry-run
    uv run python scripts/clean_image_sources.py --tag Replaced
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from anki_client import AnkiClient, AnkiConnectError
from config_manager import ConfigManager
from utils import clean_image_source_field


async def _run(args: argparse.Namespace) -> int:
    cfg = ConfigManager()
    tag = (args.tag or cfg.get("DEFAULT_TAG") or "Replaced").strip()
    field = (args.field or cfg.get("DEFAULT_FIELD_SOURCE") or "Image Source").strip()

    anki = AnkiClient(url=args.url)
    query = f"tag:{tag}"
    try:
        note_ids = await anki.find_notes(query)
    except AnkiConnectError as e:
        print(f"AnkiConnect error: {e}", file=sys.stderr)
        return 1

    if not note_ids:
        print(f"No notes match query: {query!r}")
        return 0

    chunk = max(50, int(args.chunk))
    updated = 0
    unchanged = 0
    skipped_no_url = 0
    errors = 0

    for i in range(0, len(note_ids), chunk):
        batch = note_ids[i : i + chunk]
        try:
            infos = await anki.get_notes_info(batch)
        except AnkiConnectError as e:
            print(f"notesInfo error: {e}", file=sys.stderr)
            errors += len(batch)
            continue

        for info in infos:
            nid = info.get("noteId")
            fields = info.get("fields") or {}
            if field not in fields:
                print(f"Note {nid}: skip (no field {field!r} on this note type)")
                skipped_no_url += 1
                continue
            old_raw = (fields[field].get("value") or "").strip()
            if not old_raw:
                unchanged += 1
                continue

            new_val = clean_image_source_field(old_raw)
            if new_val is None:
                print(f"Note {nid}: could not extract http(s) URL from source field")
                skipped_no_url += 1
                continue

            if new_val == old_raw:
                unchanged += 1
                continue

            if args.verbose or args.dry_run:
                print(f"Note {nid}:")
                print(f"  was: {old_raw[:200]}{'…' if len(old_raw) > 200 else ''}")
                print(f"  now: {new_val}")

            if args.dry_run:
                updated += 1
                continue

            try:
                await anki.update_note_fields(nid, {field: new_val})
                updated += 1
            except AnkiConnectError as e:
                print(f"Note {nid}: update failed: {e}", file=sys.stderr)
                errors += 1

    print(
        f"Done. query={query!r} field={field!r} "
        f"notes={len(note_ids)} updated={updated} unchanged={unchanged} "
        f"skipped_no_url={skipped_no_url} errors={errors}"
        + (" (dry-run)" if args.dry_run else "")
    )
    return 0 if errors == 0 else 2


def main() -> None:
    p = argparse.ArgumentParser(
        description="Clean Image Source fields on notes with a given tag (default: Replaced)."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes only; do not write to Anki.",
    )
    p.add_argument(
        "--tag",
        default=None,
        help="Anki tag for findNotes (default: DEFAULT_TAG from app settings).",
    )
    p.add_argument(
        "--field",
        default=None,
        help="Field name to clean (default: DEFAULT_FIELD_SOURCE from settings).",
    )
    p.add_argument(
        "--url",
        default="http://localhost:8765",
        help="AnkiConnect URL (default: http://localhost:8765).",
    )
    p.add_argument(
        "--chunk",
        type=int,
        default=200,
        help="notesInfo batch size (default: 200).",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Log every change.")
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
