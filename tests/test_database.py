import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

from database import initialize, connect, ExistingDuplicates, DuplicateRegistration
from scripts.resolve_duplicates import resolve
from scripts.migrate_sqlite_to_postgres import migrate


def legacy_database(path, duplicate=False):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE settings(id INTEGER PRIMARY KEY,value TEXT NOT NULL)')
        db.execute('INSERT INTO settings VALUES(1,?)', (json.dumps(dict(organizer='原主辦',contact='old@example.org',retention='活動後一年',open=True)),))
        db.execute('''CREATE TABLE registrations(id TEXT PRIMARY KEY,created TEXT NOT NULL,
            course_id TEXT NOT NULL,name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL,
            privacy INTEGER NOT NULL,portrait TEXT NOT NULL,signature TEXT NOT NULL,
            consent_text TEXT NOT NULL,status TEXT NOT NULL DEFAULT '待聯繫')''')
        db.execute('INSERT INTO registrations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   ('first','2026-10-01T10:00:00+08:00','practice-1','測試人','Test@example.org','0912345678',1,'decline','測試人','original snapshot','已確認'))
        if duplicate:
            db.execute('INSERT INTO registrations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       ('second','2026-10-02T10:00:00+08:00','practice-1','測試人',' test@EXAMPLE.org ','0912345678',1,'decline','測試人','second snapshot','待聯繫'))


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'old.sqlite3'
    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_upgrade_preserves_records_and_enforces_unique_index(self):
        legacy_database(self.path)
        initialize(url='',sqlite_path=self.path)
        initialize(url='',sqlite_path=self.path)
        with connect(url='',sqlite_path=self.path) as db:
            row=dict(db.execute('SELECT * FROM registrations').fetchone())
            self.assertEqual(row['email_key'],'test@example.org')
            self.assertEqual(row['consent_text'],'original snapshot')
            self.assertEqual(row['status'],'已確認')
        with self.assertRaises(DuplicateRegistration):
            with connect(write=True,url='',sqlite_path=self.path) as db:
                db.execute('INSERT INTO registrations(id,created,course_id,name,email,email_key,phone,privacy,portrait,signature,consent_text,status) SELECT ?,created,course_id,name,email,email_key,phone,privacy,portrait,signature,consent_text,status FROM registrations',('second',))
        with connect(url='',sqlite_path=self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) AS n FROM registrations').fetchone()['n'],1)

    def test_existing_duplicates_fail_closed_without_destroying_data(self):
        legacy_database(self.path,True)
        with self.assertRaises(ExistingDuplicates):
            initialize(url='',sqlite_path=self.path)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM registrations WHERE status <> '已取消'").fetchone()[0],2)
            self.assertNotIn('email_key',[r[1] for r in db.execute('PRAGMA table_info(registrations)')])

    def test_explicit_duplicate_resolution_backup_and_audit(self):
        legacy_database(self.path,True)
        self.assertEqual(resolve(self.path)['records_to_cancel'],1)
        backup=Path(self.temp.name)/'backup.sqlite3'
        result=resolve(self.path,backup,True)
        self.assertTrue(result['applied'])
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM registrations WHERE status <> '已取消'").fetchone()[0],2)
        initialize(url='',sqlite_path=self.path)
        with connect(url='',sqlite_path=self.path) as db:
            rows={r['id']:dict(r) for r in db.execute('SELECT * FROM registrations')}
            self.assertEqual(rows['first']['status'],'已確認')
            self.assertEqual(rows['second']['status'],'已取消')
            self.assertEqual(rows['second']['consent_text'],'second snapshot')
            self.assertEqual(db.execute('SELECT previous_status FROM duplicate_resolution_audit').fetchone()['previous_status'],'待聯繫')
        with self.assertRaises(FileExistsError):
            resolve(self.path,backup,True)

    def test_transaction_rolls_back_all_changes(self):
        legacy_database(self.path)
        initialize(url='',sqlite_path=self.path)
        with self.assertRaises(RuntimeError):
            with connect(write=True,url='',sqlite_path=self.path) as db:
                db.execute("UPDATE registrations SET status='已取消'")
                raise RuntimeError('simulate failure before commit')
        with connect(url='',sqlite_path=self.path) as db:
            self.assertEqual(db.execute('SELECT status FROM registrations').fetchone()['status'],'已確認')

    def test_production_configuration_fails_closed(self):
        base={**os.environ,'APP_ENV':'production','DATABASE_URL':'postgresql://localhost/life_order_test',
              'ADMIN_PASSWORD':'test-only-password','COOKIE_SECURE':'1','PUBLIC_ORIGIN':'https://registration.example','DATA_DIR':self.temp.name}
        for changes,message in [({'DATABASE_URL':''},'PostgreSQL'),({'ADMIN_PASSWORD':'short'},'ADMIN_PASSWORD'),
                                ({'COOKIE_SECURE':'0'},'COOKIE_SECURE'),({'PUBLIC_ORIGIN':''},'PUBLIC_ORIGIN'),
                                ({'PUBLIC_ORIGIN':'http://registration.example'},'PUBLIC_ORIGIN')]:
            with self.subTest(changes=list(changes)):
                result=subprocess.run([sys.executable,'-c','import server'],env={**base,**changes},capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn(message,result.stderr)
        self.assertFalse((Path(self.temp.name)/'registrations.sqlite3').exists())

    @unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'),'requires dedicated PostgreSQL test database')
    def test_sqlite_to_postgres_migration(self):
        import psycopg
        from psycopg import sql
        original=os.environ['TEST_DATABASE_URL']
        if 'life_order_test' not in original:
            self.fail('Dedicated test database is required')
        schema='migration_'+uuid.uuid4().hex
        with psycopg.connect(original) as db:
            db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        parts=urlsplit(original)
        query=dict(parse_qsl(parts.query));query['options']='-csearch_path='+schema
        target=urlunsplit(parts._replace(query=urlencode(query)))
        try:
            legacy_database(self.path,True)
            with self.assertRaises(ValueError):
                migrate(self.path,target)
            resolve(self.path,Path(self.temp.name)/'before-resolve.sqlite3',True)
            self.assertEqual(migrate(self.path,target)['source_records'],2)
            result=migrate(self.path,target,True,Path(self.temp.name)/'before-migrate.sqlite3')
            self.assertEqual(result['copied_records'],2)
            with connect(url=target) as db:
                rows={r['id']:dict(r) for r in db.execute('SELECT * FROM registrations')}
                self.assertEqual(rows['first']['consent_text'],'original snapshot')
                self.assertEqual(rows['second']['status'],'已取消')
                self.assertEqual(db.execute('SELECT count(*) AS n FROM duplicate_resolution_audit').fetchone()['n'],1)
                self.assertFalse(json.loads(db.execute('SELECT value FROM settings').fetchone()['value'])['open'])
            with self.assertRaises(ValueError):
                migrate(self.path,target,True,Path(self.temp.name)/'retry-backup.sqlite3')
            with connect(url=target) as db:
                self.assertEqual(db.execute('SELECT count(*) AS n FROM registrations').fetchone()['n'],2)
        finally:
            with psycopg.connect(original) as db:
                db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
