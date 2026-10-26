import os, json, secrets, hmac, time, csv, io, threading
from urllib.parse import urlsplit
from database import connect, initialize, normalize_email, DuplicateRegistration, DUPLICATE_MESSAGE, next_registration_id, remember_registration_ids
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie

ROOT = Path(__file__).parent
SESSIONS = {}
COURSES = []
for kind, title, hours, price, dates in [
    ('practice', '實戰課', 8, 6600, ['2026-11-01','2026-11-29','2027-03-04','2027-05-06','2027-07-11','2027-09-09','2027-09-24','2027-09-30','2027-10-02']),
    ('foundation', '初階課', 16, 12800, ['2026-12-12/2026-12-13','2027-01-09/2027-01-10','2027-04-10/2027-04-11']),
    ('advanced', '台韓進階專業課', 22, 30000, ['2027-06-19/2027-06-22'])]:
    for i, date in enumerate(dates):
        COURSES.append(dict(id=f'{kind}-{i+1}', kind=kind, title=title, hours=hours, price=price, date=date))
COURSES.sort(key=lambda c: c['date'])

PRODUCTION = os.environ.get('APP_ENV') == 'production'
PUBLIC_ORIGIN = os.environ.get('PUBLIC_ORIGIN', '').rstrip('/')
if PRODUCTION:
    if not os.environ.get('DATABASE_URL', '').startswith(('postgres://', 'postgresql://')):
        raise RuntimeError('Production requires PostgreSQL DATABASE_URL; SQLite fallback is forbidden')
    if len(os.environ.get('ADMIN_PASSWORD', '')) < 12:
        raise RuntimeError('Production requires ADMIN_PASSWORD with at least 12 characters')
    if os.environ.get('COOKIE_SECURE') != '1':
        raise RuntimeError('Production requires COOKIE_SECURE=1')
    origin = urlsplit(PUBLIC_ORIGIN)
    if origin.scheme != 'https' or not origin.netloc or origin.path or origin.query or origin.fragment or origin.username is not None or origin.password is not None:
        raise RuntimeError('Production requires PUBLIC_ORIGIN as an HTTPS origin without a path')
LOGIN_LOCK = threading.Lock()
initialize()

def settings():
    with connect() as db: return json.loads(db.execute('SELECT value FROM settings WHERE id=1').fetchone()['value'])

def notices(s):
    return dict(version='2026-10-v1', privacy=f"個人資料蒐集告知｜蒐集者：{s['organizer'] or '尚待設定'}。目的：課程報名、繳費對帳、聯繫、學員管理及課務通知。類別：姓名、電子郵件、電話、LINE ID、轉帳帳號後五碼、報名課程、同意選項及簽署姓名。利用期間：{s['retention'] or '尚待設定'}；地區：臺灣及主辦單位使用之雲端服務所在地，方式為電子及必要紙本處理，對象限主辦單位、受託課務服務人員及必要之雲端代管服務提供者於上述目的必要範圍內使用。你可依個人資料保護法請求查詢、閱覽、複製、補充、更正、停止蒐集處理利用或刪除；聯絡：{s['contact'] or '尚待設定'} 0933-015-034 雄先生。不提供必要資料將無法完成報名。不將資料用於與課程無關的行銷。", portrait='活動記錄肖像授權｜可自由選擇，拒絕不影響報名。若同意，授權主辦單位於上述資料保存期間內，使用課程現場拍攝且包含本人肖像的照片與影片，於官方網站及官方社群公開發布，供本課程活動紀錄及課程介紹使用；網路公開可能跨境瀏覽。不提供第三人作其他商業用途，不作歪曲或有損名譽之使用。可透過個資聯絡方式撤回未來使用授權並申請移除主辦單位控制的內容；已由第三人合法轉載者可能無法完全收回。不同意者請於現場向工作人員表明，以安排避拍或去識別處理。')

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(30)
    def log_message(self, fmt, *args): pass  # Do not log personal data or session tokens.
    def send(self, status, obj, ctype='application/json; charset=utf-8', headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode() if ctype.startswith('application/json') else obj
        self.send_response(status)
        for k,v in {'Content-Type':ctype,'Content-Length':str(len(body)), 'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'same-origin','Content-Security-Policy':"default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'", **(headers or {})}.items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def admin(self):
        c = SimpleCookie(self.headers.get('Cookie',''))
        token = c.get('session')
        return token and SESSIONS.get(token.value, 0) > time.time()
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/api/public':
            s=settings(); return self.send(200,dict(courses=COURSES,settings=s,notices=notices(s)))
        if path.startswith('/api/admin'):
            if not self.admin(): return self.send(401,{'error':'請先登入'})
            with connect() as db: rows = [dict(r) for r in db.execute('SELECT * FROM registrations ORDER BY created DESC')]
            if path == '/api/admin/export':
                out=io.StringIO(); w=csv.writer(out); w.writerow(['編號','時間','課程','姓名','Email','電話','LINE ID','轉帳後五碼','肖像授權','簽署','狀態','告知與授權快照'])
                for r in rows:
                    values=[r[k] for k in ['id','created','course_id','name','email','phone','line_id','transfer_last5','portrait','signature','status','consent_text']]
                    w.writerow(["'"+str(v) if str(v).startswith(('=','+','-','@','\t','\r','\n')) else v for v in values])
                return self.send(200, ('\ufeff'+out.getvalue()).encode(), 'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="registrations.csv"'})
            return self.send(200,dict(registrations=rows,settings=settings()))
        files={'/':'index.html','/admin':'admin.html','/app.js':'app.js','/admin.js':'admin.js','/style.css':'style.css'}
        if path not in files: return self.send(404,{'error':'找不到頁面'})
        file=ROOT/'public'/files[path]
        typ='text/html' if file.suffix=='.html' else 'text/javascript' if file.suffix=='.js' else 'text/css'
        self.send(200,file.read_bytes(),typ+'; charset=utf-8')
    def do_POST(self):
        origin=self.headers.get('Origin')
        allowed = (PUBLIC_ORIGIN,) if PUBLIC_ORIGIN else ('http://'+self.headers.get('Host',''),'https://'+self.headers.get('Host',''))
        if (PRODUCTION and not origin) or (origin and origin not in allowed):
            return self.send(403,{'error':'不允許跨站請求'})
        if self.headers.get('Content-Type','').split(';')[0] != 'application/json': return self.send(415,{'error':'需要 JSON'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 20000: raise ValueError()
            d=json.loads(self.rfile.read(length))
            if not isinstance(d,dict): raise ValueError()
            self.post(d)
        except DuplicateRegistration: self.send(409, {'error': DUPLICATE_MESSAGE})
        except (ValueError, TypeError, KeyError): self.send(400,{'error':'請檢查輸入資料'})
    def post(self,d):
        path=self.path
        if path=='/api/login':
            # Global rate limiting bounds password guesses and memory use.
            now=time.time()
            with LOGIN_LOCK:
                attempts=getattr(self.server,'attempts',[])
                self.server.attempts=[t for t in attempts if now-t<60]
                if len(self.server.attempts)>=10: return self.send(429,{'error':'登入嘗試過多，請稍後再試'})
                self.server.attempts.append(now)
            password=os.environ.get('ADMIN_PASSWORD','')
            if len(password)<12: return self.send(503,{'error':'管理員尚未設定至少12字元的 ADMIN_PASSWORD'})
            if not hmac.compare_digest(str(d.get('password','')).encode(),password.encode()): return self.send(401,{'error':'密碼不正確'})
            for k,v in list(SESSIONS.items()):
                if v<now: del SESSIONS[k]
            token=secrets.token_urlsafe(32); SESSIONS[token]=now+28800
            secure='; Secure' if os.environ.get('COOKIE_SECURE')=='1' else ''
            return self.send(200,{'ok':True},headers={'Set-Cookie':f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800{secure}'})
        if path.startswith('/api/admin') or path=='/api/logout':
            if not self.admin(): return self.send(401,{'error':'請先登入'})
            if path=='/api/logout':
                c=SimpleCookie(self.headers.get('Cookie','')); SESSIONS.pop(c['session'].value,None)
                return self.send(200,{'ok':True},headers={'Set-Cookie':'session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})
            if path=='/api/admin/settings':
                s={k:str(d.get(k,'')).strip() for k in ['organizer','contact','retention']}
                if any(len(v)>500 for v in s.values()): raise ValueError()
                s['open']=d.get('open') is True
                if s['open'] and (not all(s[k] for k in ['organizer','contact','retention']) or '@' not in s['contact']): return self.send(400,{'error':'開放前請填妥主辦單位、聯絡信箱及保存期限'})
                with connect(write=True) as db: db.execute('UPDATE settings SET value=? WHERE id=1',(json.dumps(s,ensure_ascii=False),))
                return self.send(200,{'ok':True})
            if path=='/api/admin/delete':
                ids = d.get('ids')
                if not isinstance(ids, list) or not ids or any(not isinstance(rid, str) or not 1 <= len(rid) <= 64 for rid in ids):
                    return self.send(400, {'error': '請先勾選要刪除的報名資料。'})
                ids = sorted(set(ids))
                chunks = [ids[i:i+400] for i in range(0, len(ids), 400)]
                with connect(write=True) as db:
                    found = []
                    for chunk in chunks:
                        query = 'SELECT id FROM registrations WHERE id IN (' + ','.join('?' for _ in chunk) + ') ORDER BY id'
                        if db.postgres: query += ' FOR UPDATE'
                        found.extend(row['id'] for row in db.execute(query, tuple(chunk)).fetchall())
                    if len(found) != len(ids):
                        return self.send(409, {'error': '部分資料已不存在，未刪除任何資料；請重新整理名單後再操作。'})
                    # Keep only sequence high-water marks, never deleted personal data.
                    remember_registration_ids(db, found)
                    if db.postgres:
                        has_audit = db.execute("SELECT to_regclass('duplicate_resolution_audit') AS name").fetchone()['name'] is not None
                    else:
                        has_audit = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='duplicate_resolution_audit'").fetchone() is not None
                    for chunk in chunks:
                        placeholders = ','.join('?' for _ in chunk)
                        if has_audit:
                            db.execute('DELETE FROM duplicate_resolution_audit WHERE registration_id IN (' + placeholders + ')', tuple(chunk))
                        db.execute('DELETE FROM registrations WHERE id IN (' + placeholders + ')', tuple(chunk))
                return self.send(200, {'deleted': len(ids)})
            if path=='/api/admin/status':
                if d.get('status') not in ['待聯繫','已確認','已取消']: raise ValueError()
                with connect(write=True) as db:
                    cur=db.execute('UPDATE registrations SET status=? WHERE id=?',(d['status'],d['id']))
                return self.send(200 if cur.rowcount else 404,{'ok':bool(cur.rowcount)})
            return self.send(404,{'error':'找不到操作'})
        if path=='/api/register':
            s=settings()
            if not s['open']: return self.send(409,{'error':'尚未開放報名，請待主辦單位完成公告'})
            course=next((c for c in COURSES if c['id']==d.get('course_id')),None)
            if not course: raise ValueError()
            from datetime import datetime
            from zoneinfo import ZoneInfo
            if course['date'][:10]<datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat(): return self.send(400,{'error':'此梯次已結束'})
            values={k:str(d.get(k,'')).strip() for k in ['name','email','phone','signature']}
            line_id = d.get('line_id', '')
            if not isinstance(line_id, str) or not line_id.strip() or len(line_id.strip()) > 100: raise ValueError()
            line_id = line_id.strip()
            import re
            transfer_last5 = d.get('transfer_last5', '')
            if not isinstance(transfer_last5, str) or not re.fullmatch(r'[0-9]{5}', transfer_last5.strip()):
                return self.send(400, {'error': '請填寫5位數字的轉帳帳號後五碼。'})
            transfer_last5 = transfer_last5.strip()
            if not all(1<=len(v)<=150 for v in values.values()) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',values['email']) or not re.fullmatch(r'[+()\d\s-]{7,30}',values['phone']): raise ValueError()
            if values['signature']!=values['name'] or d.get('privacy') is not True or d.get('portrait') not in ['agree','decline']: return self.send(400,{'error':'請完成個資同意、肖像選擇，並以報名姓名簽署'})
            current=notices(s)
            if d.get('notice')!=current: return self.send(409,{'error':'告知內容已更新，請重新整理後閱讀及簽署'})
            with connect(write=True) as db:
                rid = next_registration_id(db, course['date'])
                db.execute('INSERT INTO registrations(id,created,course_id,name,email,email_key,phone,privacy,portrait,signature,consent_text,line_id,transfer_last5) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (rid,datetime.now(ZoneInfo('Asia/Taipei')).isoformat(),course['id'],values['name'],values['email'],normalize_email(values['email']),values['phone'],1,d['portrait'],values['signature'],json.dumps(current,ensure_ascii=False),line_id,transfer_last5))
            return self.send(201,{'id':rid})
        self.send(404,{'error':'找不到操作'})

if __name__=='__main__':
    if PRODUCTION:
        raise RuntimeError('Use gunicorn wsgi:application in production')
    print('Life Order server starting', flush=True)
    ThreadingHTTPServer((os.environ.get('HOST','127.0.0.1'),int(os.environ.get('PORT','8000'))),Handler).serve_forever()
