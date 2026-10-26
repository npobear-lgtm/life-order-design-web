"""Browser regression tests with a disposable database; never submits real registrations."""
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


class RegistrationFormTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.base = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'DATABASE_URL': '', 'DATA_DIR': cls.temp.name, 'APP_ENV': 'development',
               'PUBLIC_ORIGIN': '', 'COOKIE_SECURE': '0', 'PORT': str(port),
               'ADMIN_PASSWORD': 'browser-test-only-password', 'ORGANIZER': '瀏覽器測試主辦',
               'PRIVACY_EMAIL': 'test@example.org', 'DATA_RETENTION': '活動後一年'}
        cls.proc = subprocess.Popen([sys.executable, 'server.py'], cwd=ROOT, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                with urllib.request.urlopen(cls.base+'/api/public', timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError('Browser test server not ready')
        cls.driver = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_PATH') or shutil.which('chromium')
        cls.browser = cls.driver.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()
        cls.proc.terminate()
        cls.proc.wait(timeout=10)
        cls.temp.cleanup()

    def setUp(self):
        self.configure(True)
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 900}, reduced_motion='reduce')
        self.page = self.context.new_page()
        self.requests = []
        self.errors = []
        self.page.on('request', lambda request: self.requests.append(request) if request.method=='POST' and request.url.endswith('/api/register') else None)
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.load()

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def configure(self, opened):
        with sqlite3.connect(Path(self.temp.name)/'registrations.sqlite3') as db:
            db.execute('DELETE FROM registrations')
            value = json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()[0])
            value['open'] = opened
            db.execute('UPDATE settings SET value=? WHERE id=1', (json.dumps(value),))

    def load(self):
        self.page.goto(self.base)
        expect(self.page.locator('#course-select option')).to_have_count(14)

    def field(self, name):
        return self.page.locator(f'#registration-form [name="{name}"]')

    def choose_course(self):
        value = self.page.locator('#course-select option').evaluate_all('(options) => options.find(option => option.value && !option.disabled).value')
        self.field('course_id').select_option(value)

    def fill_valid(self, portrait='decline'):
        self.choose_course()
        self.field('name').fill('  測試學員  ')
        self.field('phone').fill(' 0912345678 ')
        self.field('line_id').fill('student_line.id')
        self.field('email').fill('student@example.org')
        self.field('privacy').check()
        self.page.locator(f'[name="portrait"][value="{portrait}"]').check()
        self.field('signature').fill('測試學員')

    def submit(self):
        self.page.locator('#submit').click()

    def test_blank_form_shows_all_errors_focus_and_scroll_desktop_and_mobile(self):
        for width in [1440, 390]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':844})
                self.load()
                expect(self.page.locator('#submit')).to_be_enabled()
                expect(self.page.locator('[aria-invalid="true"]')).to_have_count(0)
                self.submit()
                expect(self.page.locator('.field-error:not([hidden])')).to_have_count(8)
                expect(self.field('course_id')).to_be_focused()
                expect(self.field('course_id')).to_be_in_viewport()
                self.assertEqual(self.field('course_id').evaluate('el => getComputedStyle(el).borderTopColor'),'rgb(179, 59, 53)')
                self.assertEqual(self.page.locator('#portrait-group').evaluate('el => getComputedStyle(el).borderTopColor'),'rgb(179, 59, 53)')
                self.assertEqual(self.field('privacy').locator('..').evaluate('el => getComputedStyle(el).borderTopColor'),'rgb(179, 59, 53)')
                expect(self.page.locator('#submit')).to_be_enabled()
                self.assertEqual(len(self.requests),0)

    def test_invalid_formats_and_mismatched_signature_never_call_api(self):
        self.fill_valid()
        self.field('phone').fill('abcdefg')
        self.field('email').fill('invalid-email')
        self.field('signature').fill('另一位學員')
        self.submit()
        expect(self.page.locator('.field-error:not([hidden])')).to_have_count(3)
        expect(self.field('phone')).to_be_focused()
        expect(self.page.locator('#registration-phone-error')).to_contain_text('有效電話')
        expect(self.page.locator('#registration-email-error')).to_contain_text('有效的電子郵件')
        expect(self.page.locator('#registration-signature-error')).to_contain_text('完全一致')
        self.assertEqual(len(self.requests),0)

    def test_progressive_corrections_focus_next_error_and_revalidate_name(self):
        self.submit()
        self.choose_course()
        expect(self.field('course_id')).not_to_have_attribute('aria-invalid','true')
        self.submit(); expect(self.field('name')).to_be_focused()
        self.field('name').fill('測試學員')
        self.submit(); expect(self.field('phone')).to_be_focused()
        self.field('phone').fill('02-2345-6789')
        self.submit(); expect(self.field('line_id')).to_be_focused()
        expect(self.page.locator('#registration-line_id-error')).to_contain_text('請填寫LINE ID')
        self.field('line_id').fill('student_line.id')
        self.submit(); expect(self.field('email')).to_be_focused()
        self.field('email').fill('student@example.org')
        self.submit(); expect(self.field('privacy')).to_be_focused()
        self.field('privacy').check()
        self.submit(); expect(self.field('portrait').first).to_be_focused()
        self.page.locator('[name="portrait"][value="decline"]').check()
        self.submit(); expect(self.field('signature')).to_be_focused()
        self.field('signature').fill('測試學員')
        expect(self.page.locator('.field-error:not([hidden])')).to_have_count(0)
        self.field('name').fill('修改姓名')
        expect(self.page.locator('#registration-signature-error')).to_contain_text('完全一致')
        self.field('signature').fill('修改姓名')
        expect(self.page.locator('.field-error:not([hidden])')).to_have_count(0)
        self.assertEqual(len(self.requests),0)

    def test_valid_submission_declining_portrait_saves_trimmed_values_and_resets(self):
        self.fill_valid()
        self.submit()
        expect(self.page.locator('#form-message')).to_contain_text('報名登記成功')
        self.assertEqual(len(self.requests),1)
        body=self.requests[0].post_data_json
        self.assertEqual(body['name'],'測試學員')
        self.assertEqual(body['phone'],'0912345678')
        self.assertEqual(body['signature'],'測試學員')
        self.assertEqual(body['portrait'],'decline')
        with sqlite3.connect(Path(self.temp.name)/'registrations.sqlite3') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM registrations').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT name,portrait FROM registrations').fetchone(),('測試學員','decline'))
        expect(self.field('name')).to_have_value('')
        expect(self.page.locator('[aria-invalid="true"]')).to_have_count(0)
        expect(self.page.locator('#submit')).to_be_enabled()

    def test_closed_registration_stays_clickable_explains_and_blocks_api(self):
        self.configure(False)
        self.load()
        expect(self.page.locator('#submit')).to_be_enabled()
        self.fill_valid()
        self.submit()
        expect(self.page.locator('#form-message')).to_contain_text('目前尚未開放報名')
        self.assertEqual(len(self.requests),0)
        expect(self.page.locator('#submit')).to_be_enabled()

    def test_api_conflict_preserves_fields_and_allows_retry(self):
        self.page.route('**/api/register',lambda route:route.fulfill(status=409,json={'error':'此電子郵件已報名這個課程梯次，請勿重複送出。'}))
        self.fill_valid(portrait='agree')
        self.submit()
        expect(self.page.locator('#form-message')).to_contain_text('請勿重複送出')
        expect(self.field('name')).to_have_value('  測試學員  ')
        expect(self.page.locator('#submit')).to_be_enabled()
        self.page.unroute('**/api/register')
        self.submit()
        expect(self.page.locator('#form-message')).to_contain_text('報名登記成功')
        self.assertEqual(len(self.requests),2)

    def test_inflight_request_blocks_double_submit_and_restores_button(self):
        pending=[]
        self.page.route('**/api/register',lambda route:pending.append(route))
        self.fill_valid()
        self.submit()
        expect(self.page.locator('#submit')).to_be_disabled()
        expect(self.page.locator('#registration-form')).to_have_attribute('aria-busy','true')
        self.page.locator('#registration-form').evaluate('form => form.requestSubmit()')
        self.assertEqual(len(self.requests),1)
        self.assertEqual(len(pending),1)
        pending[0].fulfill(status=201,json={'id':'browser-test'})
        expect(self.page.locator('#form-message')).to_contain_text('報名登記成功')
        expect(self.page.locator('#submit')).to_be_enabled()

    def test_keyboard_submit_and_course_card_clear_errors(self):
        self.field('name').fill('測試學員')
        self.field('name').press('Enter')
        expect(self.field('course_id')).to_be_focused()
        expect(self.page.locator('.field-error:not([hidden])')).to_have_count(7)
        self.page.locator('.course-card').first.get_by_role('button',name='選擇這堂課').click()
        expect(self.page.locator('#registration-course_id-error')).to_be_hidden()
        self.assertEqual(len(self.requests),0)

    def test_contact_row_alignment_and_line_id_storage(self):
        for width in [1440, 1024, 390]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 900})
                fields = [self.field(name).bounding_box() for name in ['name', 'phone', 'line_id']]
                above = self.field('course_id').bounding_box()
                below = self.field('email').bounding_box()
                self.assertAlmostEqual(fields[0]['x'], above['x'], delta=1)
                self.assertAlmostEqual(fields[0]['x'], below['x'], delta=1)
                self.assertAlmostEqual(fields[-1]['x']+fields[-1]['width'], above['x']+above['width'], delta=1)
                self.assertAlmostEqual(fields[-1]['x']+fields[-1]['width'], below['x']+below['width'], delta=1)
                if width > 800:
                    self.assertAlmostEqual(fields[0]['y'], fields[1]['y'], delta=1)
                    self.assertAlmostEqual(fields[1]['y'], fields[2]['y'], delta=1)
                    self.assertLess(fields[0]['x'], fields[1]['x'])
                    self.assertLess(fields[1]['x'], fields[2]['x'])
                else:
                    self.assertLess(fields[0]['y'], fields[1]['y'])
                    self.assertLess(fields[1]['y'], fields[2]['y'])
                    self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.fill_valid()
        self.field('line_id').fill('  student_line.id  ')
        self.submit()
        expect(self.page.locator('#form-message')).to_contain_text('報名登記成功')
        self.assertEqual(self.requests[0].post_data_json['line_id'], 'student_line.id')
        with sqlite3.connect(Path(self.temp.name)/'registrations.sqlite3') as db:
            self.assertEqual(db.execute('SELECT line_id FROM registrations').fetchone()[0], 'student_line.id')

    def test_line_id_length_error_prevents_api_call(self):
        self.fill_valid()
        self.field('line_id').evaluate("input => { input.value = 'x'.repeat(101); }")
        self.submit()
        expect(self.field('line_id')).to_be_focused()
        expect(self.page.locator('#registration-line_id-error')).to_contain_text('100個字元')
        self.assertEqual(len(self.requests), 0)

    def test_load_failure_keeps_button_enabled_and_does_not_submit(self):
        self.page.route('**/api/public',lambda route:route.fulfill(status=503,json={'error':'unavailable'}))
        self.page.goto(self.base)
        expect(self.page.locator('#opening')).to_contain_text('無法載入課程')
        expect(self.page.locator('#submit')).to_be_enabled()
        self.submit()
        expect(self.field('course_id')).to_be_focused()
        self.assertEqual(len(self.requests),0)


if __name__ == '__main__':
    unittest.main()
