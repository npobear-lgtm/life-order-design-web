const $ = selector => document.querySelector(selector);
let rows = [], courses = [], visibleRows = [], deleting = false;
const selected = new Set();

async function api(path, body) {
 const response = await fetch(path, body ? {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {});
 const data = await response.json();
 if (!response.ok) throw Error(data.error || '操作失敗');
 return data;
}
function cell(tr, text) {
 const td = document.createElement('td');
 td.textContent = text;
 tr.append(td);
 return td;
}
function syncSelection() {
 const count = visibleRows.filter(row => selected.has(row.id)).length;
 $('#select-all').checked = count > 0 && count === visibleRows.length;
 $('#select-all').indeterminate = count > 0 && count < visibleRows.length;
 $('#select-all').disabled = deleting || !visibleRows.length;
 $('#selection-count').textContent = `已勾選${count}筆`;
 $('#delete-selected').disabled = deleting || !count;
 for (const selector of ['#search', '#filter-course', '#filter-portrait']) $(selector).disabled = deleting;
}
function render() {
 const query = $('#search').value.trim().toLowerCase();
 const course = $('#filter-course').value, portrait = $('#filter-portrait').value;
 visibleRows = rows.filter(row => (!course || row.course_id === course) && (!portrait || row.portrait === portrait) &&
  [row.id,row.name,row.email,row.phone,row.line_id || '',row.transfer_last5 || ''].some(value => value.toLowerCase().includes(query)));
 const visibleIds = new Set(visibleRows.map(row => row.id));
 for (const id of selected) if (!visibleIds.has(id)) selected.delete(id);
 $('#rows').replaceChildren();
 $('#count').textContent = `共 ${rows.length} 筆登記 / ${rows.filter(row => row.status !== '已取消').length} 筆有效`;
 $('#empty').hidden = visibleRows.length > 0;
 for (const row of visibleRows) {
  const tr = document.createElement('tr');
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'selection-checkbox row-selection';
  checkbox.setAttribute('aria-label', `選取 ${row.id} ${row.name}`);
  checkbox.checked = selected.has(row.id);
  checkbox.disabled = deleting;
  checkbox.onchange = () => { if (checkbox.checked) selected.add(row.id); else selected.delete(row.id); syncSelection(); };
  cell(tr, '').append(checkbox);
  cell(tr, row.id+' / '+row.created.slice(0,16).replace('T',' '));
  const foundCourse = courses.find(course => course.id === row.course_id);
  cell(tr, foundCourse ? foundCourse.title+' '+foundCourse.date : row.course_id);
  cell(tr, row.name);
  cell(tr, row.email+' / '+row.phone);
  cell(tr, row.line_id || '—');
  cell(tr, row.transfer_last5 || '—');
  cell(tr, row.portrait === 'agree' ? '同意' : '不同意・請避拍');
  const status = document.createElement('select');
  status.setAttribute('aria-label', row.name+'的報名狀態');
  status.disabled = deleting;
  for (const value of ['待聯繫','已確認','已取消']) {
   const option = document.createElement('option');
   option.textContent = value; option.selected = row.status === value; status.append(option);
  }
  status.onchange = async () => {
   try { await api('/api/admin/status', {id:row.id, status:status.value}); row.status=status.value; render(); $('#admin-message').textContent='已更新報名狀態'; }
   catch (error) { status.value=row.status; $('#admin-message').textContent=error.message; }
  };
  cell(tr, '').append(status);
  const detail = document.createElement('details'), summary = document.createElement('summary'), text = document.createElement('p');
  summary.textContent='查看簽署';
  const snapshot=JSON.parse(row.consent_text);
  text.textContent=`簽署人：${row.signature}\n時間：${row.created}\n個資同意：${row.privacy?'是':'否'}\n肖像授權：${row.portrait==='agree'?'同意':'不同意'}\n版本：${snapshot.version}\n${snapshot.privacy}\n${snapshot.portrait}`;
  detail.append(summary,text); cell(tr,'').append(detail); $('#rows').append(tr);
 }
 syncSelection();
}
async function load() {
 const data = await api('/api/admin');
 rows=data.registrations; selected.clear();
 $('#login').hidden=true; $('#dashboard').hidden=false;
 for (const key of ['organizer','contact','retention']) $('#settings').elements[key].value=data.settings[key];
 $('#settings').elements.open.checked=data.settings.open; render();
}
$('#select-all').onchange = event => {
 for (const row of visibleRows) { if (event.target.checked) selected.add(row.id); else selected.delete(row.id); }
 render();
};
$('#delete-selected').onclick = async () => {
 if (deleting || !selected.size) return;
 const ids = visibleRows.filter(row => selected.has(row.id)).map(row => row.id);
 if (!ids.length || !window.confirm(`確定永久刪除已勾選的${ids.length}筆報名資料（包含簽署與授權紀錄）？此操作無法復原。`)) return;
 deleting=true; $('#delete-selected').setAttribute('aria-busy','true'); render();
 try {
  const result=await api('/api/admin/delete',{ids});
  const removed=new Set(ids); rows=rows.filter(row => !removed.has(row.id)); selected.clear();
  $('#admin-message').textContent=`已刪除${result.deleted}筆報名資料。`;
 } catch (error) { $('#admin-message').textContent=error.message || '刪除失敗，請稍後再試。'; }
 finally { deleting=false; $('#delete-selected').removeAttribute('aria-busy'); render(); $('#admin-message').focus(); }
};
$('#login').onsubmit=async event => {
 event.preventDefault();
 try { await api('/api/login',{password:event.target.elements.password.value}); event.target.reset(); await load(); $('#admin-message').textContent=''; }
 catch (error) { $('#admin-message').textContent=error.message; }
};
$('#settings').onsubmit=async event => {
 event.preventDefault(); const data=Object.fromEntries(new FormData(event.target)); data.open=event.target.elements.open.checked;
 try { await api('/api/admin/settings',data); $('#admin-message').textContent='設定已儲存'; }
 catch (error) { $('#admin-message').textContent=error.message; }
};
$('#logout').onclick=async () => { try { await api('/api/logout',{}); location.reload(); } catch (error) { $('#admin-message').textContent=error.message; } };
for (const selector of ['#search','#filter-course','#filter-portrait']) $(selector).addEventListener('input', () => { selected.clear(); render(); });
api('/api/public').then(data => {
 courses=data.courses;
 for (const course of courses) { const option=document.createElement('option'); option.value=course.id; option.textContent=course.title+' '+course.date; $('#filter-course').append(option); }
 return load();
}).catch(error => { if (error.message !== '請先登入') $('#admin-message').textContent=error.message; });
