let data;
const $=s=>document.querySelector(s);
const info={practice:{tag:'動手實作・立即應用',desc:'透過實際操作，建立分類、整理、清潔與空間維護的基本能力。',n:'01'},foundation:{tag:'系統學習・建立專業',desc:'從空間規劃、物品分類到收納設計，建立專業整理知識與服務能力。',n:'02'},advanced:{tag:'進階提升・國際視野',desc:'結合台灣與韓國經驗，精進整理技術、專業服務與品質管理。',n:'03'}};
const date=s=>s.split('/').map(v=>v.replaceAll('-','.')).join(' — ');
const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Taipei'}).format(new Date());
function cards(filter='all'){
 $('#course-cards').replaceChildren();
 Object.keys(info).filter(k=>filter==='all'||k===filter).forEach(kind=>{
 const list=data.courses.filter(c=>c.kind===kind),c=list[0],i=info[kind],el=document.createElement('article');el.className='course-card '+kind;
 el.innerHTML=`<div class="card-art"><span>${i.n}</span><div class="abstract"></div><small>${i.tag}</small></div><div class="card-body"><p class="eyebrow">${list.length} 梯次 · 每梯 ${c.hours} 小時</p><h3>${c.title}</h3><p>${i.desc}</p><div class="price">NT$${c.price.toLocaleString()}<small> / 人</small></div><label>開課日期<select aria-label="${c.title}梯次">${list.map(v=>`<option value="${v.id}" ${v.date.slice(0,10)<today?'disabled':''}>${date(v.date)}${v.date.slice(0,10)<today?'（已結束）':''}</option>`).join('')}</select></label><button class="outline" type="button">選擇這堂課 ↗</button></div>`;
 el.querySelector('button').onclick=()=>{$('#course-select').value=el.querySelector('select').value;$('#course-select').dispatchEvent(new Event('change',{bubbles:true}));$('#registration').scrollIntoView({behavior:'smooth'});$('#course-select').focus({preventScroll:true});};$('#course-cards').append(el);
 });
}
fetch('/api/public').then(r=>{if(!r.ok)throw Error();return r.json();}).then(d=>{
 data=d;cards();d.courses.forEach(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=`${c.title}｜${date(c.date)}｜NT$${c.price.toLocaleString()}`;o.disabled=c.date.slice(0,10)<today;$('#course-select').append(o);});
 $('#privacy-text').textContent=d.notices.privacy;$('#portrait-text').textContent=d.notices.portrait;
 $('#opening').textContent=d.settings.open?'報名開放中・歡迎加入學習旅程':'課程預告中｜主辦單位完成個資告知設定後開放報名。';
}).catch(()=>{$('#opening').textContent='無法載入課程，請稍後重新整理。';});
 document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));if(data)cards(b.dataset.filter);});
// Use inline validation instead of browser popups so every missing field is visible.
const form = $('#registration-form');
const fieldNames = ['course_id', 'name', 'phone', 'line_id', 'email', 'privacy', 'portrait', 'signature'];
const fieldUI = new Map();
let validationAttempted = false;
let submitting = false;

for (const name of fieldNames) {
 const controls = [...form.querySelectorAll(`[name="${name}"]`)];
 const container = name === 'portrait' ? $('#portrait-group') : controls[0].closest('label');
 const error = document.createElement('span');
 error.id = `registration-${name}-error`;
 error.className = 'field-error';
 error.hidden = true;
 if (name === 'privacy') container.after(error);
 else container.append(error);
 for (const control of controls) {
  const ids = (control.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
  control.setAttribute('aria-describedby', [...new Set([...ids, error.id])].join(' '));
 }
 fieldUI.set(name, { controls, container, error });
}

function fieldError(name) {
 const control = fieldUI.get(name).controls[0];
 const value = control.value.trim();
 if (name === 'course_id') {
  if (!value) return '請選擇要報名的課程梯次。';
  const course = data?.courses.find(course => course.id === value);
  if (!course || control.selectedOptions[0]?.disabled || course.date.slice(0, 10) < today) return '請選擇有效且尚未結束的課程梯次。';
 }
 if (name === 'name') {
  if (!value) return '請填寫報名姓名。';
  if (value.length > 150) return '姓名請勿超過150個字元。';
 }
 if (name === 'phone') {
  if (!value) return '請填寫聯絡電話。';
  const digits = value.replace(/\D/g, '');
  if (!/^[+()\d\s-]{7,30}$/.test(value) || digits.length < 7 || digits.length > 15) return '請填寫有效電話，例如0912345678或02-2345-6789。';
 }
 if (name === 'line_id') {
  if (!value) return '請填寫LINE ID。';
  if (value.length > 100) return 'LINE ID請勿超過100個字元。';
 }
 if (name === 'email') {
  if (!value) return '請填寫電子郵件。';
  if (value.length > 150 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return '請填寫有效的電子郵件，例如name@example.com。';
 }
 if (name === 'privacy' && !control.checked) return '請閱讀並勾選個人資料蒐集、處理及利用同意。';
 if (name === 'portrait' && !fieldUI.get(name).controls.some(input => input.checked && ['agree', 'decline'].includes(input.value))) return '請選擇同意或不同意影像（肖像）授權；不同意不影響報名。';
 if (name === 'signature') {
  if (!value) return '請輸入完整姓名完成電子簽署。';
  if (value !== form.elements.namedItem('name').value.trim()) return '電子簽署姓名必須與報名姓名完全一致。';
  if (value.length > 150) return '電子簽署姓名請勿超過150個字元。';
 }
 return '';
}

function validateField(name) {
 const { controls, container, error } = fieldUI.get(name);
 const message = fieldError(name);
 error.textContent = message;
 error.hidden = !message;
 for (const control of controls) {
  if (message) control.setAttribute('aria-invalid', 'true');
  else control.removeAttribute('aria-invalid');
 }
 if (name === 'privacy' || name === 'portrait') container.classList.toggle('field-invalid', !!message);
 return !message;
}

function showMessage(text, isError = true) {
 const message = $('#form-message');
 message.textContent = text;
 message.classList.toggle('form-error', isError);
}

function clearValidation() {
 validationAttempted = false;
 for (const { controls, container, error } of fieldUI.values()) {
  error.textContent = '';
  error.hidden = true;
  container.classList.remove('field-invalid');
  controls.forEach(control => control.removeAttribute('aria-invalid'));
 }
}

function edited(event) {
 if (!validationAttempted || !fieldUI.has(event.target.name)) return;
 validateField(event.target.name);
 // A name change can invalidate an already entered signature.
 if (event.target.name === 'name') validateField('signature');
 if (fieldNames.every(name => !fieldError(name))) showMessage('', false);
}
form.addEventListener('input', edited);
form.addEventListener('change', edited);

form.onsubmit = async event => {
 event.preventDefault();
 if (submitting) return;
 validationAttempted = true;
 const invalid = fieldNames.filter(name => !validateField(name));
 if (invalid.length) {
  showMessage('請完成標示的必填欄位，並修正格式錯誤後再送出。');
  const { controls, container } = fieldUI.get(invalid[0]);
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  (invalid[0] === 'portrait' ? container : controls[0]).scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
  controls[0].focus({ preventScroll: true });
  return;
 }
 if (!data || !data.settings.open) {
  showMessage(data ? '目前尚未開放報名，請待主辦單位公告後再送出。' : '課程資料尚未載入完成，請稍後再試或重新整理頁面。');
  $('#form-message').focus();
  return;
 }
 const button = $('#submit');
 const buttonText = button.textContent;
 submitting = true;
 button.disabled = true;
 button.textContent = '報名資料送出中…';
 form.setAttribute('aria-busy', 'true');
 try {
  const body = Object.fromEntries(new FormData(form));
  for (const name of ['name', 'phone', 'line_id', 'email', 'signature']) body[name] = body[name].trim();
  body.privacy = form.elements.privacy.checked;
  body.notice = data.notices;
  const response = await fetch('/api/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || '報名未完成，請稍後再試。');
  form.reset();
  clearValidation();
  showMessage(`報名登記成功！編號：${result.id}。請保存編號，主辦單位將另行聯繫；本網站未收取費用。`, false);
 } catch (error) {
  showMessage(error.message || '傳送失敗，請稍後再試。');
 } finally {
  submitting = false;
  button.disabled = false;
  button.textContent = buttonText;
  form.removeAttribute('aria-busy');
  $('#form-message').focus();
 }
};
