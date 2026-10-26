"""Offline, atomic SQLite -> PostgreSQL migration; destination must be empty."""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import connect, initialize, duplicate_groups, Connection, normalize_email

FIELDS = ['id','created','course_id','name','email','phone','privacy','portrait','signature','consent_text','status']


def migrate(source, target, apply=False, backup=None):
    source = Path(source).resolve()
    if not source.is_file() or not target.startswith(('postgres://', 'postgresql://')):
        raise ValueError('Existing source SQLite and PostgreSQL DATABASE_URL are required')
    with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as raw:
        raw.row_factory = sqlite3.Row
        raw.execute('BEGIN')
        if duplicate_groups(Connection(raw, False)):
            raise ValueError('Resolve existing active duplicates before migrating')
        rows = [dict(r) for r in raw.execute('SELECT * FROM registrations ORDER BY created,id')]
        config = json.loads(raw.execute('SELECT value FROM settings WHERE id=1').fetchone()['value'])
        audit_exists = raw.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='duplicate_resolution_audit'").fetchone()
        audits = [dict(r) for r in raw.execute('SELECT * FROM duplicate_resolution_audit')] if audit_exists else []
        # Preserve a consistent source snapshot. Stop all writers before running --apply.
        if apply:
            if not backup or Path(backup).resolve() == source:
                raise ValueError('--apply requires a separate --backup path')
            destination = Path(backup)
            with destination.open('xb'):
                pass
            destination.chmod(0o600)
            with sqlite3.connect(destination) as dst:
                raw.backup(dst)
    if not apply:
        return {'source_records': len(rows), 'audit_records': len(audits), 'applied': False}
    initialize(url=target)
    # One transaction: a failure cannot leave a partially copied database.
    with connect(write=True, url=target) as db:
        db.execute('LOCK TABLE registrations, settings IN EXCLUSIVE MODE')
        if db.execute('SELECT count(*) AS n FROM registrations').fetchone()['n']:
            raise ValueError('Destination is not empty; refusing to overwrite or merge')
        config['open'] = False
        db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(config, ensure_ascii=False),))
        fields = FIELDS + ['email_key']
        for row in rows:
            db.execute(f"INSERT INTO registrations({','.join(fields)}) VALUES({','.join('?' for _ in fields)})",
                       tuple(row[k] for k in FIELDS) + (normalize_email(row['email']),))
        db.execute('CREATE TABLE IF NOT EXISTS duplicate_resolution_audit (registration_id TEXT PRIMARY KEY, previous_status TEXT NOT NULL, resolved_at TEXT NOT NULL, reason TEXT NOT NULL)')
        for row in audits:
            db.execute('INSERT INTO duplicate_resolution_audit VALUES(?,?,?,?)',
                       tuple(row[k] for k in ['registration_id','previous_status','resolved_at','reason']))
        copied = db.execute('SELECT count(*) AS n FROM registrations').fetchone()['n']
        if copied != len(rows):
            raise ValueError('Migration count mismatch')
    return {'source_records': len(rows), 'copied_records': copied, 'audit_records': len(audits), 'applied': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--backup')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.source, os.environ.get('DATABASE_URL',''), args.apply, args.backup)))
    except Exception:
        # Drivers can include connection details; never print a DSN or personal data.
        raise SystemExit('Migration failed; destination transaction rolled back. Check source, empty destination, network and credentials securely.')
