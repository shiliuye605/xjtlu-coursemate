/* 课小通AI: modeless floating reader, persistent analysis owned by the service. */
(() => {
  'use strict';
  const q=s=>document.querySelector(s),esc=window.escapeStudyText||escapeText;
  function escapeText(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
  const panel=document.createElement('section');panel.id='study-window';panel.className='study-window hidden';panel.setAttribute('role','dialog');panel.setAttribute('aria-modal','false');panel.setAttribute('aria-labelledby','study-title');
  panel.innerHTML=`
    <header class="study-head"><div class="study-brand"><span class="study-spark" aria-hidden="true">✦</span><span id="study-title">课小通AI</span></div><span class="study-grip" aria-hidden="true">⠿</span><div class="study-controls"><button type="button" id="study-minimize" title="最小化" aria-label="最小化课小通AI">−</button><button type="button" id="study-maximize" title="放大" aria-label="放大课小通AI">□</button><button type="button" id="study-close" title="关闭窗口，后台继续分析" aria-label="关闭课小通AI">×</button></div></header>
    <div class="study-model" id="study-model">读取模型配置…</div>
    <div class="study-tabs" role="tablist" aria-label="课小通AI功能"><button id="study-tab-pages" type="button" role="tab" aria-selected="true" aria-controls="study-pages-content">AI实时讲解</button><button id="study-tab-overview" type="button" role="tab" aria-selected="false" aria-controls="study-overview-content">课程总概括</button></div>
    <div id="study-document" class="study-document">先选择一份课件</div>
    <div id="study-pages-content" class="study-content" role="tabpanel" aria-labelledby="study-tab-pages"><div class="study-page-tools"><span id="study-page-indicator">第 — 页 / 共 — 页</span><div class="study-page-tools-right"><label class="study-follow"><input id="study-follow" type="checkbox" checked>跟随阅读</label><button type="button" id="study-directory" class="study-link" aria-expanded="false">☷ 页码目录</button></div></div><p class="study-scroll-hint">滚轮浏览讲解 · 拖动右侧滑块快速定位</p><div id="study-page-stream" class="study-page-stream" tabindex="0" aria-label="逐页讲解，可用滚轮浏览和拖动滚动条"></div><div id="study-page-menu" class="study-page-menu hidden" aria-label="选择页码"></div><div class="study-progress"><div class="study-progress-line"><strong id="study-progress-text">等待课件</strong><span id="study-progress-state"></span></div><div class="study-progress-track"><div id="study-progress-bar"></div></div><small id="study-progress-note">上传后自动分析 · 已完成内容保存到本地</small></div></div>
    <div id="study-overview-content" class="study-content hidden" role="tabpanel" aria-labelledby="study-tab-overview"><div class="study-overview-toolbar"><div class="study-scope"><label><input type="radio" name="study-scope" value="current" checked>当前课件</label><label><input type="radio" name="study-scope" value="multiple">选择多份 <span id="study-selected-count"></span></label></div><div id="study-scope-list" class="study-scope-list hidden"></div><div class="study-overview-actions"><button id="study-generate" type="button" class="btn primary">生成课程概括</button><a id="study-export" class="btn hidden" download>导出 PDF</a></div><div id="study-overview-meta" class="study-overview-meta"></div><div class="study-history-row"><label for="study-overview-history">已保存</label><select id="study-overview-history" aria-label="查看已保存的课程概括"><option value="">当前选择范围</option></select></div></div><div class="study-overview-scroll"><div id="study-overview-body" class="study-overview-body md-render"></div></div></div>
    <div id="study-chat-drawer" class="study-chat-drawer hidden"><div class="study-chat-drawer-head"><span id="study-chat-title">继续提问</span><button type="button" class="study-link" id="study-chat-hide">收起</button></div><div id="study-chat-log" class="study-chat-log" aria-live="polite"></div></div>
    <footer class="study-footer"><div class="study-chat-tools"><span id="study-chat-context" class="study-chat-context">基于当前课件提问</span><button type="button" id="study-history" class="study-link">历史对话</button></div><div class="study-composer"><textarea id="study-question" rows="1" placeholder="这页没看懂？继续问课小通…" aria-label="向课小通AI提问"></textarea><button type="button" id="study-send" class="study-send" title="发送问题" aria-label="发送问题">➤</button></div></footer>`;
  document.body.appendChild(panel);
  const launcher=document.createElement('div');launcher.id='study-launcher';launcher.className='study-launcher hidden';launcher.innerHTML='<button type="button" id="study-reopen"><span class="study-spark" aria-hidden="true">✦</span>课小通AI <small id="study-mini-status">准备讲解</small><span aria-hidden="true">⤢</span></button><button type="button" class="study-icon" id="study-mini-close" title="隐藏入口，后台继续分析" aria-label="隐藏课小通AI悬浮入口">×</button>';document.body.appendChild(launcher);
  let prefs={mode:'open',tab:'pages',maximized:false,follow:true,bounds:null},prefTimer;
  let courseId=0,docId=0,currentPage=1,readerPage=1,revision='',pageData=null,contextToken=0,scopeToken=0;
  let overview=null,overviews=[],selected=new Set(),multiple=false,historyChoice='',legacySummary=null;
  let inPoll=false,chatSending=false,chatKey='',programmaticUntil=0,drag=null;
  const stream=q('#study-page-stream'),chatLog=q('#study-chat-log');
  const scrollWrap=document.createElement('div');scrollWrap.className='study-scroll-wrap';stream.before(scrollWrap);scrollWrap.appendChild(stream);
  const rail=document.createElement('div');rail.className='study-scroll-rail';rail.innerHTML='<input id="study-page-slider" type="range" min="1" max="1" value="1" step="1" aria-label="拖动滑块定位讲解页面" title="拖动滑块，快速定位页码"><span id="study-slider-page" aria-hidden="true">1</span>';scrollWrap.appendChild(rail);
  const pageStates=new Map();

  function savePrefs(){
    clearTimeout(prefTimer);prefTimer=setTimeout(()=>api('/study/preferences',{method:'PUT',body:JSON.stringify(prefs)}).catch(()=>{}),250);
  }
  function rememberBounds(){if(prefs.maximized||prefs.mode!=='open')return;const r=panel.getBoundingClientRect();prefs.bounds={x:r.x,y:r.y,width:r.width,height:r.height};savePrefs()}
  function clampBounds(){
    if(prefs.maximized)return;
    const width=Math.max(360,Math.min(prefs.bounds?.width||480,innerWidth-24));
    const height=Math.max(420,Math.min(prefs.bounds?.height||760,innerHeight-88));
    const x=Math.min(Math.max(8,prefs.bounds?.x??innerWidth-width-22),innerWidth-width-8);
    const y=Math.min(Math.max(70,prefs.bounds?.y??innerHeight-height-18),innerHeight-height-8);
    Object.assign(panel.style,{width:width+'px',height:height+'px',left:x+'px',top:y+'px',right:'auto',bottom:'auto'});
  }
  function applyMode(){
    panel.classList.toggle('hidden',prefs.mode!=='open');launcher.classList.toggle('hidden',prefs.mode!=='minimized');panel.classList.toggle('maximized',prefs.maximized);
    q('#btn-study-ai')?.classList.toggle('open',prefs.mode==='open');q('#study-maximize').textContent=prefs.maximized?'❐':'□';q('#study-maximize').setAttribute('aria-label',prefs.maximized?'恢复课小通AI大小':'放大课小通AI');
    q('#study-maximize').title=prefs.maximized?'恢复大小':'放大';clampBounds();
  }
  function open(){prefs.mode='open';applyMode();savePrefs();if(prefs.follow&&prefs.tab==='pages')scrollToPage(readerPage,false);refresh()}
  function close(){prefs.mode='closed';applyMode();savePrefs();q('#btn-study-ai')?.focus({preventScroll:true})}
  q('#btn-study-ai').addEventListener('click',open);q('#study-reopen').addEventListener('click',open);
  q('#study-close').addEventListener('click',close);q('#study-mini-close').addEventListener('click',close);
  q('#study-minimize').addEventListener('click',()=>{rememberBounds();prefs.mode='minimized';applyMode();savePrefs()});
  q('#study-maximize').addEventListener('click',()=>{if(!prefs.maximized)rememberBounds();prefs.maximized=!prefs.maximized;applyMode();savePrefs()});
  panel.querySelector('.study-head').addEventListener('pointerdown',event=>{
    if(event.button!==0||event.target.closest('button')||prefs.maximized)return;
    const r=panel.getBoundingClientRect();drag={x:event.clientX,y:event.clientY,left:r.left,top:r.top};event.currentTarget.setPointerCapture(event.pointerId);event.preventDefault();
  });
  panel.querySelector('.study-head').addEventListener('pointermove',event=>{
    if(!drag)return;
    panel.style.left=Math.max(8,Math.min(innerWidth-panel.offsetWidth-8,drag.left+event.clientX-drag.x))+'px';
    panel.style.top=Math.max(70,Math.min(innerHeight-panel.offsetHeight-8,drag.top+event.clientY-drag.y))+'px';
  });
  panel.querySelector('.study-head').addEventListener('pointerup',()=>{if(drag){drag=null;rememberBounds()}});
  panel.querySelector('.study-head').addEventListener('pointercancel',()=>{drag=null});
  panel.addEventListener('pointerup',event=>{if(event.target===panel)rememberBounds()});
  let resized=false;new ResizeObserver(()=>{if(resized&&prefs.mode==='open'&&!prefs.maximized){const r=panel.getBoundingClientRect();if(prefs.bounds&&(Math.abs(r.width-prefs.bounds.width)>2||Math.abs(r.height-prefs.bounds.height)>2))rememberBounds()}resized=true}).observe(panel);
  window.addEventListener('resize',()=>{clampBounds()});
  panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.stopPropagation();if(!q('#study-page-menu').classList.contains('hidden'))hideDirectory();else if(!q('#study-chat-drawer').classList.contains('hidden'))q('#study-chat-drawer').classList.add('hidden');else close()}});

  function settingsChanged(){
    const cfg=state.settings;q('#study-model').textContent=cfg?.ready?`${cfg.model==='mock-llm'?'离线演示':'API已配置'} · ${cfg.model}`:'请先在设置中配置 API Key';q('#study-model').classList.toggle('warn',!cfg?.ready);
  }
  function setTab(tab){
    prefs.tab=tab;q('#study-tab-pages').setAttribute('aria-selected',String(tab==='pages'));q('#study-tab-overview').setAttribute('aria-selected',String(tab==='overview'));
    q('#study-pages-content').classList.toggle('hidden',tab!=='pages');q('#study-overview-content').classList.toggle('hidden',tab!=='overview');hideDirectory();q('#study-chat-drawer').classList.add('hidden');savePrefs();updateChatContext();
    if(tab==='overview')loadOverviews();else if(prefs.follow)scrollToPage(readerPage,false);
  }
  q('#study-tab-pages').addEventListener('click',()=>setTab('pages'));q('#study-tab-overview').addEventListener('click',()=>setTab('overview'));
  q('#study-follow').addEventListener('change',event=>{prefs.follow=event.target.checked;savePrefs();if(prefs.follow)scrollToPage(readerPage,false)});

  function chosenIds(){return multiple?[...selected].filter(id=>state.docs.some(d=>d.id===id)).sort((a,b)=>a-b):(docId?[docId]:[])}
  function updateChatContext(){q('#study-chat-context').textContent=prefs.tab==='pages'?`当前课件 · 第 ${currentPage} 页`:`当前课程 · 已选择 ${chosenIds().length} 份课件`;q('#study-question').placeholder=prefs.tab==='pages'?'这页没看懂？继续问课小通…':'针对选中的课件，继续问课小通…'}
  function contextChanged(){
    const nextCourse=state.courseId||0,nextDoc=state.doc?.id||0,changed=nextCourse!==courseId||nextDoc!==docId;
    if(nextCourse!==courseId){selected=new Set();multiple=false;historyChoice='';q('input[name="study-scope"][value="current"]').checked=true}
    courseId=nextCourse;docId=nextDoc;
    q('#study-document').textContent=state.doc?.filename||'先在左侧选择课程，再上传或选择课件';
    if(changed){
      contextToken++;scopeToken++;currentPage=readerPage=1;revision='';pageData=null;overview=null;overviews=[];historyChoice='';legacySummary=null;pageStates.clear();stream.innerHTML='';selected=new Set(docId?[docId]:[]);q('#study-chat-drawer').classList.add('hidden');chatKey='';
      q('#study-overview-history').innerHTML='<option value="">当前选择范围</option>';renderOverview(null);hideDirectory();updatePageLabel();renderProgress(null);
    }
    renderScopeList();updateChatContext();settingsChanged();if(!docId)renderPages({total:0,pages:[],counts:{},configured:!!state.settings?.ready});if(changed)refresh();
  }
  function visibleArticle(){const top=stream.getBoundingClientRect().top+18;return [...stream.querySelectorAll('.study-page')].find(el=>el.getBoundingClientRect().bottom>top)||stream.querySelector('.study-page:last-child')}
  function updatePageLabel(){
    const total=pageData?.total||state.doc?.page_count||0;
    q('#study-page-indicator').textContent=`第 ${currentPage||'—'} 页 / 共 ${total||'—'} 页`;
    const slider=q('#study-page-slider');slider.max=Math.max(1,total);slider.value=Math.min(Math.max(1,currentPage),Math.max(1,total));slider.disabled=total<2;slider.setAttribute('aria-valuetext',`第 ${currentPage} 页，共 ${total} 页`);
    const badge=q('#study-slider-page');badge.textContent=currentPage;badge.style.top=`calc(${total>1?100*(currentPage-1)/(total-1):0}% - ${total>1?28*(currentPage-1)/(total-1):0}px)`;updateChatContext();
  }
  q('#study-page-slider').addEventListener('input',event=>scrollToPage(+event.target.value));
  function pagePlaceholder(row){
    if(row.status==='failed')return `<div class="study-page-placeholder error">${esc(row.error||'本页讲解未完成')}<br><button type="button" class="study-link" data-study-retry>重试未完成页面</button></div>`;
    if(row.status==='running')return '<div class="study-page-placeholder">正在用配置的 API 模型讲解这一页…<br>完成后会自动显示并保存到本地。</div>';
    return `<div class="study-page-placeholder">${pageData?.configured?'已加入后台分析队列，生成后自动显示。':'请先配置 API Key，再开始翻译；系统会同步准备逐页讲解。'}<br>无需保持本窗口打开。</div>`;
  }
  function renderPages(data){
    if(data.unchanged)data.pages=pageData?.pages||[];
    pageData=data;renderProgress(data);if(data.unchanged){updatePageLabel();return}
    if(!data.pages?.length){stream.innerHTML=`<div class="study-empty"><strong>${data.document_status==='failed'?'课件尚未完成处理':docId?'正在准备逐页讲解':'先选择一份课件'}</strong>${data.document_status==='failed'?esc(data.document_error||'请查看翻译错误提示并重试。'):docId?'导入并开始翻译后，软件会在解析出文字时自动分析。':'在左侧选择课程，上传 PDF 即可开始。'}</div>`;updatePageLabel();return}
    const anchor=visibleArticle(),offset=anchor?anchor.getBoundingClientRect().top-stream.getBoundingClientRect().top:0;
    for(const row of data.pages){
      let article=q(`#study-page-${row.page_number}`);if(!article){article=document.createElement('article');article.id=`study-page-${row.page_number}`;article.className='study-page';article.dataset.page=row.page_number;stream.appendChild(article)}
      const key=JSON.stringify([row.status,row.markdown,row.error]);if(pageStates.get(row.page_number)===key)continue;pageStates.set(row.page_number,key);article.dataset.status=row.status;
      const label=({done:'已保存',pending:'等待生成',running:'生成中',failed:'需要重试',unreadable:'图片 / 空白页'})[row.status]||row.status;
      article.innerHTML=`<div class="study-page-label"><span>第 ${row.page_number} 页</span><span>${label}</span></div>`+(row.markdown?`<div class="md-render">${mdRender(row.markdown)}</div>`:pagePlaceholder(row));
      article.querySelector('[data-study-retry]')?.addEventListener('click',retryPages);
    }
    stream.querySelector('.study-empty')?.remove();
    if(anchor?.isConnected)stream.scrollTop+=anchor.getBoundingClientRect().top-stream.getBoundingClientRect().top-offset;
    revision=data.revision;updatePageLabel();
  }
  function renderProgress(data){
    const counts=data?.counts||{},total=data?.total||state.doc?.page_count||0,done=counts.done||0,unreadable=counts.unreadable||0;
    q('#study-progress-text').textContent=docId?`已讲解 ${done} / ${total||'—'} 页`:'等待课件';q('#study-mini-status').textContent=docId?`讲解 ${done}/${total||'—'}`:'选择课件';
    q('#study-progress-bar').style.width=(total?100*done/total:0)+'%';
    q('#study-progress-state').textContent=data?.queue_error?'请检查模型配置':counts.running?'后台分析中':counts.pending?'排队生成中':counts.failed?`${counts.failed} 页可重试`:total&&done===total?'本地已保存':unreadable?`${unreadable} 页需看原文`:'';
    q('#study-progress-note').innerHTML=counts.failed?'<button type="button" class="study-link" id="study-retry-all">重试未完成页面</button> · 已完成内容保留':unreadable?`有 ${unreadable} 页没有可提取文字，请查看原页 · 其余结果保存到本地`:'上传后自动分析 · 已完成内容保存到本地';q('#study-retry-all')?.addEventListener('click',retryPages);
  }
  async function retryPages(){if(!docId)return;try{await api(`/study/documents/${docId}/retry`,{method:'POST'});revision='';refresh();toast('已加入重试队列，保留已完成讲解','ok')}catch(e){toast(e.message,'err')}}
  function scrollToPage(number,syncReader=true){
    const article=q(`#study-page-${number}`);if(!article)return;
    programmaticUntil=performance.now()+350;stream.scrollTop+=article.getBoundingClientRect().top-stream.getBoundingClientRect().top-6;currentPage=number;updatePageLabel();
    if(syncReader&&prefs.follow)window.courseMateGoToPage?.(number);
  }
  let scrollFrame;
  stream.addEventListener('scroll',()=>{cancelAnimationFrame(scrollFrame);scrollFrame=requestAnimationFrame(()=>{const article=visibleArticle();if(!article)return;const next=+article.dataset.page;if(next===currentPage)return;currentPage=next;updatePageLabel();if(performance.now()>programmaticUntil&&prefs.follow&&prefs.mode==='open'){programmaticUntil=performance.now()+350;window.courseMateGoToPage?.(next)}})});
  function readerPageChanged(number){readerPage=number;if(performance.now()<programmaticUntil)return;if(prefs.follow&&prefs.mode==='open'&&prefs.tab==='pages')scrollToPage(number,false)}
  function hideDirectory(){q('#study-page-menu').classList.add('hidden');q('#study-directory').setAttribute('aria-expanded','false')}
  q('#study-directory').addEventListener('click',()=>{const menu=q('#study-page-menu');if(!menu.classList.contains('hidden'))return hideDirectory();menu.innerHTML='';for(let n=1;n<=(pageData?.total||0);n++){const button=document.createElement('button');button.type='button';button.textContent=n;button.className=(pageData.pages?.[n-1]?.status||'')+(n===currentPage?' current':'');button.setAttribute('aria-label',`跳到第 ${n} 页`);button.addEventListener('click',()=>{scrollToPage(n);hideDirectory()});menu.appendChild(button)}menu.classList.remove('hidden');q('#study-directory').setAttribute('aria-expanded','true')});

  function renderScopeList(){
    q('#study-scope-list').classList.toggle('hidden',!multiple);
    const list=q('#study-scope-list'),description=state.docs.map(d=>`${d.id}:${d.filename}`).join('|');
    if(list.dataset.docs!==description){list.dataset.docs=description;list.innerHTML=state.docs.map(doc=>`<label><input type="checkbox" value="${doc.id}" ${selected.has(doc.id)?'checked':''}><span>${esc(doc.filename)}</span></label>`).join('')||'<span>当前课程还没有课件</span>';list.querySelectorAll('input').forEach(input=>input.addEventListener('change',()=>{if(input.checked)selected.add(+input.value);else selected.delete(+input.value);historyChoice='';scopeChanged()}))}
    else list.querySelectorAll('input').forEach(input=>input.checked=selected.has(+input.value));
    q('#study-selected-count').textContent=multiple?`（${chosenIds().length}）`:'';
  }
  q('input[name="study-scope"][value="current"]').addEventListener('change',()=>{multiple=false;historyChoice='';scopeChanged()});
  q('input[name="study-scope"][value="multiple"]').addEventListener('change',()=>{multiple=true;if(!selected.size&&docId)selected.add(docId);historyChoice='';scopeChanged()});
  function scopeChanged(){scopeToken++;overview=null;q('#study-overview-history').value='';renderScopeList();renderOverview(null);q('#study-chat-drawer').classList.add('hidden');updateChatContext();loadOverviews()}
  function matchOverview(){const ids=chosenIds().join(',');return overviews.find(row=>row.document_ids.slice().sort((a,b)=>a-b).join(',')===ids&&row.status!=='invalid')||null}
  async function loadOverviews(){
    if(!courseId)return;const token=contextToken,scope=scopeToken,course=courseId;
    try{
      const result=await api(`/study/courses/${course}/overviews`);if(token!==contextToken||scope!==scopeToken)return;overviews=result;
      const previous=q('#study-overview-history').value;
      q('#study-overview-history').innerHTML='<option value="">当前选择范围</option>'+result.filter(row=>row.status==='done').map(row=>`<option value="${row.id}">${esc(row.updated_at)} · ${row.document_ids.length} 份 · ${esc(row.documents.map(d=>d.filename).join('、'))}</option>`).join('')+(legacySummary?.markdown?'<option value="legacy">原课程总结（旧版）</option>':'');
      q('#study-overview-history').value=previous;
      if(historyChoice==='legacy')return renderLegacy();
      overview=historyChoice?result.find(row=>String(row.id)===historyChoice):matchOverview();renderOverview(overview);
    }catch(e){q('#study-overview-meta').textContent='读取概括失败：'+e.message}
  }
  function renderOverview(row){
    const body=q('#study-overview-body'),meta=q('#study-overview-meta'),button=q('#study-generate'),exportLink=q('#study-export');
    const busy=row&&['pending','running'].includes(row.status);
    button.disabled=!!busy;button.textContent=busy?'正在生成…':row?.status==='done'?'重新生成':'生成课程概括';exportLink.classList.toggle('hidden',!row?.pdf_url);if(row?.pdf_url)exportLink.href=row.pdf_url;
    meta.textContent=row?.status==='done'?`已保存到本地 · ${row.document_ids.length} 份课件 · ${row.updated_at}`:row?.status==='failed'?`生成失败：${row.error}`:row?.status==='running'?'正在使用配置的 API 模型分析所选课件；关闭窗口后仍会继续。':row?.status==='pending'?'已加入后台队列，完成后自动显示。':`已选择 ${chosenIds().length} 份课件；概括按课程结构、概念、考点、应用与自测组织。`;
    const key=row?`${row.id}/${row.status}/${row.updated_at}/${row.markdown?.length}`:'empty/'+chosenIds().join(',');
    if(body.dataset.content!==key){body.dataset.content=key;body.innerHTML=row?.markdown?mdRender(row.markdown):`<div class="study-empty"><strong>${busy?'正在生成课程总概括':'查看当前课件，或组合多份课件'}</strong>${busy?'内容会保存到本地，不需要一直打开窗口。':'当前课件会自动生成辅导分析；也可以勾选本课程的多份资料，再点击生成。'}</div>`}
  }
  function renderLegacy(){
    if(!legacySummary)return;q('#study-overview-meta').textContent='这是升级前保存的课程总结，原有内容和 PDF 保留。';q('#study-overview-body').dataset.content='legacy';q('#study-overview-body').innerHTML=mdRender(legacySummary.markdown);q('#study-export').classList.toggle('hidden',!legacySummary.pdf_url);if(legacySummary.pdf_url)q('#study-export').href=legacySummary.pdf_url;q('#study-generate').disabled=false;q('#study-generate').textContent='生成当前选择的概括';
  }
  q('#study-overview-history').addEventListener('change',event=>{
    historyChoice=event.target.value;
    const row=historyChoice==='legacy'?null:overviews.find(item=>String(item.id)===historyChoice);
    const ids=historyChoice==='legacy'?legacySummary?.included:row?.document_ids;
    if(ids?.length){selected=new Set(ids);multiple=ids.length!==1||ids[0]!==docId;q('input[name="study-scope"][value="'+(multiple?'multiple':'current')+'"]').checked=true;renderScopeList();updateChatContext();q('#study-chat-drawer').classList.add('hidden')}
    if(historyChoice==='legacy'){overview=null;renderLegacy()}else {overview=row||matchOverview();renderOverview(overview)}
  });
  q('#study-generate').addEventListener('click',async()=>{
    const ids=chosenIds();if(!courseId||!ids.length)return toast('请先选择一份或多份课件','err');
    const token=contextToken,scope=scopeToken;q('#study-generate').disabled=true;
    try{const row=await api(`/study/courses/${courseId}/overviews`,{method:'POST',body:JSON.stringify({document_ids:ids,force:overview?.status==='done'||overview?.status==='failed'})});if(token!==contextToken||scope!==scopeToken)return;historyChoice='';overview=row;renderOverview(row);loadOverviews()}catch(e){q('#study-generate').disabled=false;toast(e.message,'err')}
  });

  function chatScope(){return {course_id:courseId,document_id:prefs.tab==='pages'?docId:0,page_number:prefs.tab==='pages'?currentPage:0,document_ids:prefs.tab==='overview'?chosenIds():[]}}
  function keyFor(scope){return [scope.course_id,scope.document_id,scope.page_number,scope.document_ids.join(',')].join('/')}
  async function history(scope,all=false){let route=`/chat/history?course_id=${scope.course_id}`;if(!all)route+=`&document_id=${scope.document_id}&page_number=${scope.page_number}`+(scope.document_ids.length?'&scope_key='+encodeURIComponent(scope.document_ids.join(',')):'');return api(route)}
  function appendMessage(role,text){const message=document.createElement('div');message.className='study-message '+role;message.innerHTML=`<b>${role==='user'?'我':'课小通AI'}</b><div class="md-render">${mdRender(text)}</div>`;chatLog.appendChild(message);chatLog.scrollTop=chatLog.scrollHeight;return message.querySelector('.md-render')}
  q('#study-chat-hide').addEventListener('click',()=>q('#study-chat-drawer').classList.add('hidden'));
  q('#study-history').addEventListener('click',async()=>{if(!courseId)return;const token=contextToken;try{const rows=await history(chatScope(),true);if(token!==contextToken)return;q('#study-chat-drawer').classList.remove('hidden');q('#study-chat-title').textContent='本课程历史对话 · 新提问仍使用当前范围';chatLog.innerHTML='';for(const row of rows)appendMessage(row.role,row.content);if(!rows.length)chatLog.textContent='还没有对话，输入问题即可开始。'}catch(e){toast(e.message,'err')}});
  async function send(){
    const question=q('#study-question').value.trim();if(chatSending||!question)return;if(!courseId||!docId)return toast('请先选择课件','err');if(!state.settings?.ready){switchToSettings();return toast('请先配置并保存 API Key','err')}
    const scope=chatScope(),key=keyFor(scope);if(prefs.tab==='overview'&&!scope.document_ids.length)return toast('请先选择要提问的课件','err');
    chatSending=true;q('#study-send').disabled=true;q('#study-question').value='';q('#study-question').style.height='auto';
    q('#study-chat-drawer').classList.remove('hidden');q('#study-chat-title').textContent=scope.page_number?`第 ${scope.page_number} 页 · 继续提问`:`${scope.document_ids.length} 份课件 · 继续提问`;
    let bubble;
    try{
      const previous=await history(scope);chatLog.innerHTML='';previous.slice(-12).forEach(m=>appendMessage(m.role,m.content));appendMessage('user',question);bubble=appendMessage('assistant','正在连接模型…');chatKey=key;
      const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...scope,messages:[...previous.slice(-12).map(m=>({role:m.role,content:m.content})),{role:'user',content:question}]})});
      if(!response.ok){let msg=response.statusText;try{msg=(await response.json()).detail||msg}catch{}throw Error(msg)}
      const reader=response.body.getReader(),decoder=new TextDecoder();let text='';while(true){const part=await reader.read();if(part.done)break;text+=decoder.decode(part.value,{stream:true});if(chatKey===key){bubble.innerHTML=mdRender(text);chatLog.scrollTop=chatLog.scrollHeight}}
      if(chatKey===key)bubble.innerHTML=mdRender(text||'模型未返回内容，请重试。');
    }catch(e){if(bubble&&chatKey===key)bubble.innerHTML=mdRender('调用失败：'+e.message);else toast(e.message,'err')}
    finally{chatSending=false;q('#study-send').disabled=false}
  }
  q('#study-send').addEventListener('click',send);q('#study-question').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();send()}});q('#study-question').addEventListener('input',event=>{event.target.style.height='auto';event.target.style.height=Math.min(85,event.target.scrollHeight)+'px'});

  async function refresh(){
    if(inPoll||!docId)return;inPoll=true;const token=contextToken,id=docId;
    try{const data=await api(`/study/documents/${id}/pages?revision=${encodeURIComponent(revision)}`);if(token!==contextToken)return;renderPages(data);if(prefs.tab==='overview')await loadOverviews();if(!legacySummary&&courseId){const course=courseId;const result=await api(`/courses/${course}/summary`).catch(()=>null);if(course===courseId)legacySummary=result}}
    catch(e){if(token===contextToken)q('#study-progress-state').textContent='读取失败，稍后自动重试'}finally{inPoll=false}
  }
  window.StudyAI={open,close,contextChanged,readerPageChanged,settingsChanged,refresh,scrollToPage};
  api('/study/preferences').then(value=>{prefs={...prefs,...value};q('#study-follow').checked=prefs.follow;applyMode();setTab(prefs.tab)}).catch(()=>applyMode());
  contextChanged();setInterval(refresh,2500);
})();
