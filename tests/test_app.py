import concurrent.futures
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from database import connect


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.url = os.environ.get('TEST_DATABASE_URL', '')
        if cls.url and 'life_order_test' not in cls.url:
            raise RuntimeError('Use a dedicated life_order_test PostgreSQL database')
        cls.production = os.environ.get('TEST_PRODUCTION') == '1'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.base = f'http://127.0.0.1:{port}'
        cls.env = {**os.environ, 'DATABASE_URL': cls.url, 'DATA_DIR': cls.tmp.name,
                   'PORT': str(port), 'APP_ENV': 'production' if cls.production else 'development',
                   'COOKIE_SECURE': '1' if cls.production else '0',
                   'PUBLIC_ORIGIN': 'https://registration.example' if cls.production else '',
                   'ADMIN_PASSWORD': 'test-password-123456', 'ORGANIZER': '測試主辦',
                   'PRIVACY_EMAIL': 'privacy@example.org', 'DATA_RETENTION': '活動後一年'}
        if os.environ.get('TEST_GUNICORN') == '1':
            command = [sys.executable, '-m', 'gunicorn', '--bind', f'127.0.0.1:{port}',
                       '--workers', '1', '--worker-class', 'gthread', '--threads', '8', 'wsgi:application']
        else:
            command = [sys.executable, 'server.py']
        cls.command = command
        cls._start_server()

    @classmethod
    def _start_server(cls):
        cls.proc = subprocess.Popen(cls.command, cwd=ROOT, env=cls.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                cls.call('/api/public')
                break
            except OSError:
                if cls.proc.poll() is not None:
                    raise RuntimeError('Test server exited during startup')
                time.sleep(.1)
        else:
            raise RuntimeError('Test server not ready')

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.tmp.cleanup()

    def setUp(self):
        with connect(write=True, url=self.url, sqlite_path=Path(self.tmp.name)/'registrations.sqlite3') as db:
            db.execute('DELETE FROM registrations')
            config = dict(organizer='測試主辦', contact='privacy@example.org', retention='活動後一年', open=True)
            db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(config),))

    @classmethod
    def call(cls, path, data=None, cookie=None, origin=None):
        headers = {}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        if cookie:
            headers['Cookie'] = cookie
        if origin is None and cls.production:
            origin = cls.env['PUBLIC_ORIGIN']
        if origin:
            headers['Origin'] = origin
        req = urllib.request.Request(cls.base+path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=40)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            body = response.read()
            value = json.loads(body) if response.headers.get('Content-Type','').startswith('application/json') else body
            return response.status, value, response.headers

    def login(self):
        code, _, headers = self.call('/api/login', {'password': self.env['ADMIN_PASSWORD']})
        self.assertEqual(code, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        if self.production:
            self.assertIn('; Secure', headers['Set-Cookie'])
        return headers['Set-Cookie'].split(';')[0]

    def payload(self, **overrides):
        public = self.call('/api/public')[1]
        today = datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat()
        course = next(c for c in public['courses'] if c['date'][:10] >= today)
        return {**dict(course_id=course['id'], name='測試學員', email='test@example.org',
                       phone='0912345678', signature='測試學員', privacy=True,
                       portrait='decline', notice=public['notices']), **overrides}

    def test_concurrent_eight_submissions(self):
        barrier = threading.Barrier(8)
        body = self.payload()
        def submit(i):
            barrier.wait()
            return self.call('/api/register', {**body, 'email': ' Test@Example.org ' if i%2 else 'test@example.org'})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(submit, range(8)))
        self.assertEqual(sum(r[0] == 201 for r in results), 1)
        self.assertEqual(sum(r[0] == 409 for r in results), 7)
        for code, value, _ in results:
            if code == 409:
                self.assertIn('請勿重複送出', value['error'])
        with connect(url=self.url, sqlite_path=Path(self.tmp.name)/'registrations.sqlite3') as db:
            self.assertEqual(db.execute("SELECT count(*) AS n FROM registrations WHERE status <> '已取消'").fetchone()['n'], 1)
        print('  concurrency: 8 requests -> 1 accepted, 7 conflicts, 1 active row')

    def test_cancel_reregister_and_reactivation_conflict(self):
        cookie = self.login()
        body = self.payload()
        first = self.call('/api/register', body)[1]['id']
        self.assertEqual(self.call('/api/admin/status', dict(id=first,status='已取消'), cookie)[0], 200)
        self.assertEqual(self.call('/api/register', body)[0], 201)
        self.assertEqual(self.call('/api/admin/status', dict(id=first,status='已確認'), cookie)[0], 409)
        rows = self.call('/api/admin', cookie=cookie)[1]['registrations']
        self.assertEqual(sum(r['status'] != '已取消' for r in rows), 1)
        self.assertEqual(next(r['status'] for r in rows if r['id']==first), '已取消')

    def test_server_restart_preserves_registration_and_settings(self):
        body = self.payload()
        code, created, _ = self.call('/api/register', body)
        self.assertEqual(code, 201)
        type(self).proc.terminate()
        type(self).proc.wait(timeout=10)
        type(self)._start_server()
        self.assertTrue(self.call('/api/public')[1]['settings']['open'])
        cookie = self.login()
        rows = self.call('/api/admin', cookie=cookie)[1]['registrations']
        self.assertEqual([r['id'] for r in rows], [created['id']])
        self.assertEqual(self.call('/api/register', body)[0], 409)

    def test_same_email_different_course(self):
        body = self.payload()
        self.assertEqual(self.call('/api/register', body)[0], 201)
        courses = self.call('/api/public')[1]['courses']
        other = next(c for c in courses if c['id']!=body['course_id'] and c['date'] >= datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat())
        self.assertEqual(self.call('/api/register', {**body,'course_id':other['id']})[0], 201)

    def test_consent_validation_and_snapshot(self):
        body = self.payload()
        for change in [dict(privacy=False), dict(portrait=''), dict(signature='另一人')]:
            self.assertEqual(self.call('/api/register', {**body,**change})[0], 400)
        self.assertEqual(self.call('/api/register', {**body,'notice':{}})[0], 409)
        self.assertEqual(self.call('/api/register', body)[0], 201)
        cookie=self.login()
        row=self.call('/api/admin',cookie=cookie)[1]['registrations'][0]
        self.assertEqual(row['portrait'],'decline')
        self.assertEqual(json.loads(row['consent_text']), body['notice'])
        self.assertEqual(row['signature'],body['name'])
        self.assertEqual(self.call('/api/admin/export',cookie=cookie)[0],200)

    def test_admin_endpoints_require_authentication(self):
        for path in ['/api/admin','/api/admin/export']:
            self.assertEqual(self.call(path)[0],401)
        for path in ['/api/admin/settings','/api/admin/status','/api/logout']:
            self.assertEqual(self.call(path,{})[0],401)
        self.assertEqual(self.call('/api/login',{'password':'wrong'})[0],401)
        self.assertEqual(self.call('/api/admin',cookie='session=forged')[0],401)

    def test_logout_invalidates_session(self):
        cookie=self.login()
        self.assertEqual(self.call('/api/logout',{},cookie)[0],200)
        self.assertEqual(self.call('/api/admin',cookie=cookie)[0],401)

    def test_cross_site_requests_rejected(self):
        for path in ['/api/register','/api/login','/api/admin/settings','/api/admin/status']:
            self.assertEqual(self.call(path,{},origin='https://evil.example')[0],403)
        if self.production:
            self.assertEqual(self.call('/api/login',{},origin=False)[0],403)

    def test_public_pages_and_course_totals(self):
        for path in ['/','/admin','/app.js','/admin.js','/style.css']:
            code,body,headers=self.call(path)
            self.assertEqual(code,200);self.assertTrue(body)
            self.assertIn('Content-Security-Policy',headers)
        public=self.call('/api/public')[1]
        self.assertEqual(len(public['courses']),13)
        self.assertEqual(sum(c['hours'] for c in public['courses']),142)
        self.assertEqual(self.call('/.data/registrations.sqlite3')[0],404)
        self.assertEqual(self.call('/render.yaml')[0],404)


if __name__ == '__main__':
    unittest.main()
