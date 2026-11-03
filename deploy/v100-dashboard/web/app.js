'use strict';
const $ = id => document.getElementById(id);
const form = $('settings-form');
let status = null, dirty = false, busy = false, testAbort = null;
let samples = [], cpus = [];
const names = {running:'Работает',unloaded:'Выгружена',starting:'Запускается',loading:'Загрузка',unloading:'Выгрузка',stopping:'Остановка',stopped:'Остановлен',error:'Ошибка'};
const labels = {overview:['Обзор','Всё под контролем','Модель, ресурсы и производительность — в одном месте.'],settings:['Настройки','Настройте под себя','Контекст, генерация и управление движком.'],playground:['Песочница','От идеи к коду','Проверьте модель на своей задаче.']};
const defaults = {context:262144,kv_resident:32768,spec:4,spec_min_p:0.5,temperature:0.7,max_tokens:65536,thinking:false};
const number = (v, digits=0) => Number.isFinite(Number(v)) && v !== null && v !== undefined ? Number(v).toLocaleString('ru-RU',{maximumFractionDigits:digits}) : '—';
function toast(text) { $('toast').textContent=text; $('toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').hidden=true,4000); }
async function api(path, data, opts={}) {
  const res=await fetch(path,{...opts,...(data!==undefined?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{})});
  const body=await res.json(); if(!res.ok) throw new Error(body.error?.message||`HTTP ${res.status}`); return body;
}
function showView(view) {
  if(!labels[view]) return;
  document.querySelectorAll('.view').forEach(e=>e.hidden=e.id!=='view-'+view);
  document.querySelectorAll('.nav-item').forEach(e=>e.classList.toggle('active',e.dataset.view===view));
  $('crumb').textContent=labels[view][0]; $('page-title').replaceChildren(document.createTextNode(labels[view][1]),Object.assign(document.createElement('span'),{textContent:'.'}));
  $('page-description').textContent=labels[view][2]; history.replaceState(null,'','#'+view); window.scrollTo({top:0});
}
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>showView(b.dataset.view)));
window.addEventListener('hashchange',()=>showView(location.hash.slice(1)||'overview'));
showView(location.hash.slice(1)||'overview');
$('api-url').textContent=location.origin+'/v1';
$('copy-api').addEventListener('click',async()=>{
  try { await navigator.clipboard.writeText(location.origin+'/v1'); toast('Адрес API скопирован'); }
  catch { toast('Адрес API: '+location.origin+'/v1'); }
});
function fillSettings(values) {
  for(const [k,v] of Object.entries(values||{})) { const field=form.elements.namedItem(k); if(!field)continue; if(field.type==='checkbox')field.checked=v;else field.value=v; }
}
form.addEventListener('input',()=>{dirty=true;$('pending').textContent='Не сохранено';});
$('restore').addEventListener('click',()=>{fillSettings(defaults);dirty=true;$('pending').textContent='Не сохранено';toast('Пресет восстановлен в форме. Нажмите «Сохранить».');});
form.addEventListener('submit',async e=>{
 e.preventDefault(); const values={}; for(const k of Object.keys(defaults)){const f=form.elements.namedItem(k);values[k]=f.type==='checkbox'?f.checked:Number(f.value);}
 const b=form.querySelector('[type=submit]');b.disabled=true;
 try{await api('/dashboard/settings',values);dirty=false;toast('Сохранено. Перезапустите сервер, чтобы применить.');await poll();}catch(err){toast(err.message);}finally{b.disabled=false;}
});
async function action(name) {
 if(!status||status.action)return;
 if(name==='restart'&&dirty){toast('Сначала сохраните изменения в форме');return;}
 try{await api('/dashboard/control',{action:name});toast('Операция принята: '+({start:'запуск',stop:'остановка',restart:'перезапуск',load:'загрузка',unload:'выгрузка'}[name]));await poll();}catch(e){toast(e.message);}
}
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>action(b.dataset.action)));
function path(values,w,h,max) { return values.map((v,i)=>(i?'L':'M')+(i*w/Math.max(1,values.length-1)).toFixed(1)+','+(h-Math.min(max,Math.max(0,v||0))/max*h).toFixed(1)).join(' '); }
function draw() {
 const top=Math.max(10,Math.ceil(Math.max(...samples,0)/25)*25);
 $('chart-max').textContent=top;$('chart-mid').textContent=top/2;
 const d=path(samples,700,170,top);
 // Only local numeric samples are interpolated; model output never enters HTML.
 $('main-chart').innerHTML='<defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#c6d8b7" stop-opacity=".65"/><stop offset="1" stop-color="#f4f8ed" stop-opacity=".2"/></linearGradient></defs>'+[0,85,170].map(y=>`<line x1="0" x2="700" y1="${y}" y2="${y}" stroke="#edf1e6" stroke-dasharray="4 5"/>`).join('')+(samples.length>1?`<path d="${d} L700,170 L0,170 Z" fill="url(#area)"/><path d="${d}" fill="none" stroke="#92ae7c" stroke-width="2" vector-effect="non-scaling-stroke"/>`:'');
 $('spark-speed').innerHTML=samples.length>1?`<path d="${path(samples,230,30,top)}"/>`:'';
 $('spark-cpu').innerHTML=cpus.length>1?`<path d="${path(cpus,230,30,100)}"/>`:'';
}
function text(id,value){$(id).textContent=value;}
function renderMetrics(m){
 const h=m.hardware||{},live=m.live||{},tot=m.totals||{},eng=m.engine||{},rows=m.requests||[];
 const current=Number(h.tok_s||live.tok_s||0);
 samples.push(current);cpus.push(Number(h.cpu||0));samples=samples.slice(-60);cpus=cpus.slice(-60);draw();
 text('speed',number(current,1));text('speed-note',live.state==='idle'?'Сейчас нет активной генерации':'Генерация в процессе');
 text('vram',number(h.gpu_mem_used/2**30,1));const pct=h.gpu_mem_total?100*h.gpu_mem_used/h.gpu_mem_total:0;$('vram-meter').style.width=Math.min(100,pct)+'%';text('vram-note',number(pct,1)+'% занято · '+number((h.gpu_mem_total-h.gpu_mem_used)/2**30,1)+' GiB свободно');
 text('cpu',number(h.cpu,1));text('requests',number(tot.requests));text('queue','В очереди: '+number(live.queued));text('tokens',number(tot.output_tokens)+' выходных токенов');
 text('prefill',number(h.prefill_tok_s_mean,1)+' ток/с');text('gpu-util',number(h.gpu_util)+'%');text('temperature',number(h.gpu_temp)+' °C');text('power',number(h.gpu_power)+' W');
 text('ram',number(h.ram_used/2**30,1)+' / '+number(h.ram_total/2**30,1)+' GiB');text('context-label',number(eng.max_context)+' ток.');text('request-count',rows.length);
 $('request-rows').replaceChildren();
 if(!rows.length){const row=document.createElement('tr'),cell=document.createElement('td');cell.colSpan=6;cell.className='empty';cell.textContent='Запросов пока нет. Отправьте первый в песочнице.';row.append(cell);$('request-rows').append(row);}
 rows.slice(0,6).forEach(r=>{
   const tr=document.createElement('tr');const when=r.finished||r.at||r.time||r.started;const date=when?new Date(when*1000).toLocaleTimeString('ru-RU'):'—';
   const vals=[date,'Qwen3.8 · Coder',number(r.prompt_tokens??r.prompt)+' / '+number(r.generated??r.output_tokens),number(r.decode_tok_s??r.tok_s,1)+' ток/с',number(r.duration_s??r.elapsed_s??r.wallclock_s,2)+' с',r.error?'Ошибка':'Завершён'];
   vals.forEach((v,i)=>{const td=document.createElement('td');if(i===5){const span=document.createElement('span');span.className='result';span.textContent=v;td.append(span);}else td.textContent=v;tr.append(td);});$('request-rows').append(tr);
 });
}
async function poll(){
 if(busy)return;busy=true;
 try{
  status=await api('/dashboard/status');text('connection','На связи');text('state',names[status.state]||status.state);
  text('uptime',Math.floor(status.uptime/3600)+'ч '+Math.floor(status.uptime%3600/60)+'м');
  if(!dirty)fillSettings(status.settings);
  text('pending',dirty?'Не сохранено':status.pending?'Нужен перезапуск':'Сохранено');
  text('output-label',number(status.settings.max_tokens)+' ток.');text('kv-label',number(status.settings.kv_resident/1024)+'K resident');text('spec-label',status.settings.spec+' · p ≥ '+status.settings.spec_min_p);
  document.querySelectorAll('[data-action]').forEach(b=>{b.disabled=!!status.action;});
  const unload=$('unload');const off=status.state==='unloaded';unload.dataset.action=off?'load':'unload';unload.textContent=off?'▷  Загрузить модель':'◧  Выгрузить модель';
  const note=status.error||(status.action?'Выполняется операция. Загрузка модели может занять несколько минут.':status.pending?'Есть сохранённые настройки. Примените их перезапуском сервера.':status.state==='stopped'?'Сервер остановлен. Запустите его в настройках.':'');
  $('notice').hidden=!note;text('notice',note);
  if(status.health){try{renderMetrics(await api('/metrics'));}catch{ text('chart-state','Метрики временно недоступны'); }}
  else{text('speed','—');text('speed-note','Инференс недоступен');text('chart-state','Нет соединения с движком');}
 }catch(e){text('connection','Нет соединения');text('state','Недоступен');text('notice',e.message);$('notice').hidden=false;}
 finally{busy=false;}
}
$('refresh').addEventListener('click',poll);
setInterval(()=>text('clock',new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})),1000);
setInterval(poll,2000);poll();
$('cancel').addEventListener('click',()=>testAbort?.abort());
$('prompt-form').addEventListener('submit',async e=>{
 e.preventDefault(); if(testAbort)return;
 testAbort=new AbortController();$('send').disabled=true;$('cancel').disabled=false;text('answer','');text('reasoning','');$('reasoning-block').hidden=true;text('test-status','Генерация…');const start=performance.now();
 try{
  const res=await fetch('/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json'},signal:testAbort.signal,body:JSON.stringify({model:status?.health?.model||'qwen3.8-flash-next-coder-iq1_m',messages:[{role:'user',content:$('prompt').value}],max_tokens:Number($('test-tokens').value),stream:true,chat_template_kwargs:{enable_thinking:$('test-thinking').checked}})});
  if(!res.ok){const err=await res.json();throw new Error(err.error?.message||res.statusText);}
  const reader=res.body.getReader(),decoder=new TextDecoder();let buffer='',done=false;
  while(!done){const chunk=await reader.read();done=chunk.done;buffer+=decoder.decode(chunk.value||new Uint8Array(),{stream:!done});buffer=buffer.replace(/\r\n/g,'\n');const parts=buffer.split('\n\n');buffer=parts.pop();
   for(const part of parts){for(const line of part.split('\n')){if(!line.startsWith('data:'))continue;const value=line.slice(5).trim();if(value==='[DONE]')continue;let obj;try{obj=JSON.parse(value);}catch{continue;}if(obj.error)throw new Error(obj.error.message);const delta=obj.choices?.[0]?.delta||{};if(delta.content)$('answer').textContent+=delta.content;if(delta.reasoning_content){$('reasoning-block').hidden=false;$('reasoning').textContent+=delta.reasoning_content;}}}
  }
  text('test-status',number((performance.now()-start)/1000,1)+' с · Готово');
 }catch(err){if(err.name==='AbortError'){text('test-status','Ожидание остановлено');}else{text('test-status','Ошибка');text('answer',err.message);}}
 finally{testAbort=null;$('send').disabled=false;$('cancel').disabled=true;poll();}
});
