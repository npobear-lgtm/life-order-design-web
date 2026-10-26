"""Transactions shared by the SQLite development and PostgreSQL production backends."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATABASE_URL = os.environ.get('DATABASE_URL', '')
SQLITE_PATH = Path(os.environ.get('DATA_DIR', ROOT / '.data')) / 'registrations.sqlite3'
UNIQUE_INDEX = 'registrations_one_active_email_course'
DUPLICATE_MESSAGE = '此電子郵件已報名這個課程梯次，請勿重複送出；如需修改資料，請聯絡主辦單位。'


def normalize_email(value):
    return value.strip().casefold()


class DuplicateRegistration(Exception):
    pass


class ExistingDuplicates(Exception):
    pass


class Connection:
    def __init__(self, raw, postgres):
        self.raw, self.postgres = raw, postgres

    def execute(self, sql, params=()):
        # Queries are application constants; only parameter markers are translated.
        return self.raw.execute(sql.replace('?', '%s') if self.postgres else sql, params)


@contextmanager
def connect(write=False, url=None, sqlite_path=None):
    target = DATABASE_URL if url is None else url
    postgres = bool(target)
    if postgres:
        import psycopg
        from psycopg.rows import dict_row
        raw = psycopg.connect(target, row_factory=dict_row, connect_timeout=10)
    else:
        path = Path(sqlite_path or SQLITE_PATH)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        raw = sqlite3.connect(path, timeout=30)
        raw.row_factory = sqlite3.Row
        raw.execute('PRAGMA busy_timeout=30000')
        raw.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
    try:
        yield Connection(raw, postgres)
        raw.commit()
    except Exception as exc:
        raw.rollback()
        if postgres:
            import psycopg
            duplicate = isinstance(exc, psycopg.errors.UniqueViolation) and exc.diag.constraint_name == UNIQUE_INDEX
        else:
            duplicate = isinstance(exc, sqlite3.IntegrityError) and 'registrations.course_id, registrations.email_key' in str(exc)
        if duplicate:
            raise DuplicateRegistration(DUPLICATE_MESSAGE) from None
        raise
    finally:
        raw.close()


def duplicate_groups(db):
    rows = db.execute("SELECT id, course_id, email, created FROM registrations WHERE status <> '已取消' ORDER BY created, id").fetchall()
    groups = {}
    for row in rows:
        groups.setdefault((row['course_id'], normalize_email(row['email'])), []).append(row['id'])
    return [ids for ids in groups.values() if len(ids) > 1]


def initialize(url=None, sqlite_path=None):
    with connect(write=True, url=url, sqlite_path=sqlite_path) as db:
        if db.postgres:
            # Serialize schema upgrades across simultaneous process starts.
            db.execute('SELECT pg_advisory_xact_lock(81726027)')
        db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
        db.execute('''CREATE TABLE IF NOT EXISTS registrations (
            id TEXT PRIMARY KEY, created TEXT NOT NULL, course_id TEXT NOT NULL,
            name TEXT NOT NULL, email TEXT NOT NULL, email_key TEXT NOT NULL,
            phone TEXT NOT NULL, privacy INTEGER NOT NULL, portrait TEXT NOT NULL,
            signature TEXT NOT NULL, consent_text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '待聯繫', line_id TEXT NOT NULL DEFAULT '')''')
        if db.postgres:
            columns = [r['column_name'] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='registrations'")]
        else:
            columns = [r['name'] for r in db.execute('PRAGMA table_info(registrations)')]
        if 'email_key' not in columns:
            db.execute('ALTER TABLE registrations ADD COLUMN email_key TEXT')
        if 'line_id' not in columns:
            db.execute("ALTER TABLE registrations ADD COLUMN line_id TEXT NOT NULL DEFAULT ''")
        # Never silently delete or cancel previously accepted registrations.
        groups = duplicate_groups(db)
        if groups:
            raise ExistingDuplicates(f'發現 {len(groups)} 組既有重複有效報名；請先備份，再執行 scripts/resolve_duplicates.py。')
        for row in db.execute('SELECT id,email,email_key FROM registrations').fetchall():
            key = normalize_email(row['email'])
            if row['email_key'] != key:
                db.execute('UPDATE registrations SET email_key=? WHERE id=?', (key, row['id']))
        db.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {UNIQUE_INDEX} ON registrations(course_id, email_key) WHERE status <> '已取消'")
        # Guard legacy SQLite tables whose added column could otherwise be NULL.
        if not db.postgres:
            for event in ['INSERT', 'UPDATE']:
                db.execute(f"""CREATE TRIGGER IF NOT EXISTS registrations_email_key_{event.lower()}
                    BEFORE {event} ON registrations WHEN NEW.email_key IS NULL OR NEW.email_key = ''
                    BEGIN SELECT RAISE(ABORT, 'email_key required'); END""")
        else:
            db.execute('ALTER TABLE registrations ALTER COLUMN email_key SET NOT NULL')
        initial = dict(organizer=os.environ.get('ORGANIZER', ''), contact=os.environ.get('PRIVACY_EMAIL', ''),
                       retention=os.environ.get('DATA_RETENTION', ''), open=False)
        db.execute('INSERT INTO settings(id,value) VALUES(1,?) ON CONFLICT(id) DO NOTHING', (json.dumps(initial, ensure_ascii=False),))
    if not (DATABASE_URL if url is None else url):
        os.chmod(sqlite_path or SQLITE_PATH, 0o600)


def next_registration_id(db, course_date):
    """Allocate within the registration write transaction; canceled IDs stay reserved.

    MMDD prefixes share one sequence, including courses in different years.
    Legacy random IDs are preserved and excluded from the numeric sequence.
    """
    from datetime import date
    import re
    prefix = date.fromisoformat(course_date[:10]).strftime('%m%d')
    if db.postgres:
        # Lock before reading the maximum; READ COMMITTED sees the prior winner.
        db.execute('SELECT pg_advisory_xact_lock(?)', (610000 + int(prefix),))
    # SQLite callers already hold BEGIN IMMEDIATE; PostgreSQL callers hold the
    # prefix-specific transaction lock until the registration commits/rolls back.
    rows = db.execute('SELECT id FROM registrations WHERE id LIKE ?', (prefix + '-%',)).fetchall()
    pattern = re.compile(re.escape(prefix) + r'-(\d{3,})')
    highest = max((int(match.group(1)) for row in rows
                   if (match := pattern.fullmatch(row['id']))), default=0)
    return f'{prefix}-{highest + 1:03d}'
