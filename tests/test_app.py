import unittest, tempfile, subprocess, os, urllib.request, urllib.error, json, time, socket
from pathlib import Path

class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
        cls.base=f'http://127.0.0.1:{port}'
        cls.proc=subprocess.Popen(['python3','server.py'],cwd=Path(__file__).resolve().parents[1],env={**os.environ,'DATA_DIR':cls.tmp.name,'PORT':str(port),'ADMIN_PASSWORD':'test-password-123456','ORGANIZER':'部署測試主辦','PRIVACY_EMAIL':'deploy@example.org','DATA_RETENTION':'活動後一年'},stdout=subprocess.DEVNULL)
        for _ in range(50):
            try: cls.call('/api/public'); break
            except OSError: time.sleep(.1)
        else: raise RuntimeError('server not ready')
    @classmethod
    def tearDownClass(cls): cls.proc.terminate();cls.proc.wait();cls.tmp.cleanup()
    @classmethod
    def call(cls,path,data=None,cookie=None,origin=None):
        headers={}
        if data is not None: headers['Content-Type']='application/json'
        if cookie: headers['Cookie']=cookie
        if origin: headers['Origin']=origin
        req=urllib.request.Request(cls.base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers)
        try: r=urllib.request.urlopen(req)
        except urllib.error.HTTPError as e: r=e
        body=r.read();typ=r.headers.get('Content-Type','')
        return r.status,json.loads(body) if typ.startswith('application/json') else body,r.headers
    def test_full_registration_and_permissions(self):
        status,public,_=self.call('/api/public');self.assertEqual(status,200)
        self.assertEqual(public['settings']['organizer'],'部署測試主辦')
        self.assertEqual(public['settings']['contact'],'deploy@example.org')
        self.assertFalse(public['settings']['open'])
        self.assertEqual(len(public['courses']),13);self.assertEqual(sum(c['hours'] for c in public['courses']),142)
        self.assertEqual(self.call('/api/admin')[0],401)
        self.assertEqual(self.call('/.data/registrations.sqlite3')[0],404)
        self.assertEqual(self.call('/api/login',{'password':'wrong'})[0],401)
        code,_,headers=self.call('/api/login',{'password':'test-password-123456'});self.assertEqual(code,200)
        cookie=headers['Set-Cookie'].split(';')[0];self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.assertEqual(self.call('/api/admin/settings',{'open':True},cookie)[0],400)
        s={'organizer':'測試主辦單位','contact':'privacy@example.org','retention':'至2028年12月31日','open':True}
        self.assertEqual(self.call('/api/admin/settings',s,cookie)[0],200)
        public=self.call('/api/public')[1]
        d={'course_id':'practice-1','name':'測試學員','email':'test@example.org','phone':'0912345678','signature':'測試學員','privacy':True,'portrait':'decline','notice':public['notices']}
        self.assertEqual(self.call('/api/register',{**d,'privacy':False})[0],400)
        self.assertEqual(self.call('/api/register',{**d,'portrait':''})[0],400)
        self.assertEqual(self.call('/api/register',{**d,'signature':'另一人'})[0],400)
        self.assertEqual(self.call('/api/register',d,origin='https://evil.example')[0],403)
        self.assertEqual(self.call('/api/register',{**d,'notice':{}})[0],409)
        code,result,_=self.call('/api/register',d);self.assertEqual(code,201);self.assertTrue(result['id'])
        self.assertEqual(self.call('/api/register',d)[0],409)
        r=self.call('/api/admin',cookie=cookie)[1]['registrations'][0]
        self.assertEqual(r['portrait'],'decline');self.assertIn('測試主辦單位',r['consent_text'])
        self.assertEqual(self.call('/api/admin/status',{'id':r['id'],'status':'已確認'},cookie)[0],200)
        self.assertEqual(self.call('/api/register',{**d,'course_id':'practice-2','email':'second@example.org','portrait':'agree'})[0],201)
        code,export,_=self.call('/api/admin/export',cookie=cookie);self.assertEqual(code,200);self.assertIn('測試學員',export.decode('utf-8-sig'))
        self.assertEqual(self.call('/api/logout',{},cookie)[0],200)
        self.assertEqual(self.call('/api/admin',cookie=cookie)[0],401)
    def test_pages(self):
        for path in ['/','/admin','/app.js','/admin.js','/style.css']:
            status,body,headers=self.call(path);self.assertEqual(status,200);self.assertTrue(body);self.assertIn('Content-Security-Policy',headers)

if __name__=='__main__': unittest.main()
