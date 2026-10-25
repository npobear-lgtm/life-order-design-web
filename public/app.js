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
 el.querySelector('button').onclick=()=>{$('#course-select').value=el.querySelector('select').value;$('#registration').scrollIntoView({behavior:'smooth'});$('#course-select').focus({preventScroll:true});};$('#course-cards').append(el);
 });
}
fetch('/api/public').then(r=>{if(!r.ok)throw Error();return r.json();}).then(d=>{
 data=d;cards();d.courses.forEach(c=>{const o=document.createElement('option');o.value=c.id;o.textContent=`${c.title}｜${date(c.date)}｜NT$${c.price.toLocaleString()}`;o.disabled=c.date.slice(0,10)<today;$('#course-select').append(o);});
 $('#privacy-text').textContent=d.notices.privacy;$('#portrait-text').textContent=d.notices.portrait;
 $('#opening').textContent=d.settings.open?'報名開放中・歡迎加入學習旅程':'課程預告中｜主辦單位完成個資告知設定後開放報名。';$('#submit').disabled=!d.settings.open;
}).catch(()=>{$('#opening').textContent='無法載入課程，請稍後重新整理。';$('#submit').disabled=true;});
 document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));if(data)cards(b.dataset.filter);});
$('#registration-form').onsubmit=async e=>{e.preventDefault();const form=e.target,button=$('#submit'),msg=$('#form-message');button.disabled=true;try{const body=Object.fromEntries(new FormData(form));body.privacy=form.elements.privacy.checked;body.notice=data.notices;const r=await fetch('/api/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),v=await r.json();if(!r.ok)throw Error(v.error);form.reset();msg.textContent=`報名登記成功！編號：${v.id}。請保存編號，主辦單位將另行聯繫；本網站未收取費用。`;}catch(err){msg.textContent=err.message||'傳送失敗，請稍後再試';}finally{button.disabled=!data.settings.open;msg.focus();}};
