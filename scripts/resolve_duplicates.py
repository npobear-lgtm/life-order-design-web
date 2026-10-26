"""Explicitly resolve legacy SQLite duplicates; preserve every original record."""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import Connection, duplicate_groups


def resolve(source, backup=None, apply=False):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError('Source database does not exist')
    if apply:
        if not backup or Path(backup).resolve() == source:
            raise ValueError('--apply requires a separate --backup path')
        destination = Path(backup)
        # Exclusive creation prevents overwriting any previous backup.
        with destination.open('xb'):
            pass
        destination.chmod(0o600)
        with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as src, sqlite3.connect(destination) as dst:
            src.backup(dst)
    db = sqlite3.connect(source)
    db.row_factory = sqlite3.Row
    try:
        db.execute('BEGIN IMMEDIATE')
        groups = duplicate_groups(Connection(db, False))
        count = sum(len(ids)-1 for ids in groups)
        if apply:
            db.execute('CREATE TABLE IF NOT EXISTS duplicate_resolution_audit (registration_id TEXT PRIMARY KEY, previous_status TEXT NOT NULL, resolved_at TEXT NOT NULL, reason TEXT NOT NULL)')
            for ids in groups:
                for rid in ids[1:]:
                    old = db.execute('SELECT status FROM registrations WHERE id=?', (rid,)).fetchone()['status']
                    db.execute('INSERT INTO duplicate_resolution_audit VALUES(?,?,?,?)',
                               (rid, old, datetime.now(timezone.utc).isoformat(), 'retain earliest created/id registration'))
                    db.execute("UPDATE registrations SET status='已取消' WHERE id=?", (rid,))
            db.commit()
        else:
            db.rollback()
        return {'duplicate_groups': len(groups), 'records_to_cancel': count, 'applied': apply}
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--backup')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(resolve(args.source, args.backup, args.apply)))
