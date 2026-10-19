/* Illustrated guide is self-contained and never reads personal courses or keys. */
(() => {
  'use strict';
  const sections = [
    {id:'start',label:'快速开始',title:'从第一份课件开始',image:'01-overview',intro:'先配置模型，再按课程上传课件。翻译与逐页讲解会自动在后台开始；阅读时可打开课小通AI继续提问，或生成课程总概括。',steps:[['选择课程','左侧是课程列表。先创建或选中一门课程，后续课件和总结会归入这门课程。'],['切换功能','顶部保留课件翻译、课小通AI和设置。课小通AI是悬浮窗，可以拖动、缩放、最小化和关闭；右上角可随时打开使用说明。'],['添加课件','点击“上传课件”，把可选中文字的 PDF 拖进去，或点击选择文件。']],note:'这里的截图来自软件实际页面，使用示例课程和离线演示内容。演示只说明操作方法，不代表真实 AI 的翻译或回答质量。'},
    {id:'settings',label:'配置智谱',title:'连接你的智谱 GLM 模型',image:'02-settings',intro:'设置页仅提供智谱服务，接口地址已固定。填写你自己的智谱 API Key，并选择要使用的 GLM 模型。',steps:[['填写智谱 API Key','在智谱开放平台创建 Key，粘贴到输入框。已有 Key 会继续保留，留空保存不会将它清除。请勿把 Key 发给别人或放进公开截图。'],['选择 GLM 主模型','可使用当前的 glm-4.5-flash，或填写你有使用权限的其他智谱 GLM 模型名称。课小通AI的逐页讲解、概括和追问使用这个模型。'],['选择翻译模式','“快速”使用 GLM-4-Flash-250414 翻译课件；也可以选择使用上方的主模型。'],['测试后保存','先点“测试连接”，通过后点“保存配置”。已有 Key 可以直接测试，无须重复粘贴；修改输入框不会自动保存。']],note:'没有 Key 时，可先在智谱开放平台创建自己的 API Key。本软件不提供共享 Key，实际可用模型和账户限制以智谱平台为准。'},
    {id:'course',label:'新建课程',title:'把不同课程的资料分开',image:'03-course',intro:'点击左侧“我的课程”旁的加号。建议用容易认出的课程名称，方便后续查找和汇总。',steps:[['填写课程名称','课程名称必填，例如“数据库基础”。'],['补充课程信息','课程代码、授课教师可按需填写，也可以留空。'],['创建并选中课程','点击“创建”。新课程会出现在左侧，确认选中后再上传课件。']],note:'删除课程会同时删除其中的课件和总结，操作前请核对课程名称。'},
    {id:'upload',label:'上传课件',title:'拖入 PDF，或点击选择',image:'04-upload',intro:'选好课程后，点击“上传课件”。弹窗内有拖拽区域，也可以使用“选择文件”按钮。',steps:[['核对所属课程','弹窗标题下方会显示课件将添加到哪门课程。'],['拖入或选择文件','从文件夹把一个 PDF 拖到虚线框内松开；也可以点击“选择文件”选取 PDF。'],['等待上传与翻译','保存有效模型配置后，上传成功会自动开始翻译。页面会显示任务进度，完成后显示双栏内容。']],note:'每次上传一个 PDF，单个不超过 80MB。当前主要处理有文字层的 PDF；扫描图片或图片中的文字不会自动识别翻译。'},
    {id:'reading',label:'对照阅读',title:'左侧看原文，右侧看译文',image:'05-reading',intro:'同一课程的课件排列在文件名下方，点击即可切换。翻译完成后，右侧会显示中文对照 PDF。',steps:[['查看状态和切换文件','文件名下方显示页数和处理状态，课件标签用于切换当前文件。'],['对照两栏阅读','左侧英文原版，右侧中文对照；滚动时两栏会同步定位，便于比较同一部分内容。'],['遇到问题再重试','翻译失败时，先查看页面提示、检查模型配置，再点击“重新翻译”。复杂术语和公式建议回看原文。']],note:'翻译用时会随文档长度、版式和服务商响应变化。顶部显示的连接状态不等于当前文档已经翻译完成，请以文档状态为准。'},
    {"id":"analysis","label":"逐页讲解","title":"用滚轮与滑块浏览每页讲解","image":"06-analysis","intro":"点击顶部“课小通AI”，进入“AI实时讲解”。每页的讲解按原文页码连续排列，可以直接上下滚动。","steps":[["滚轮浏览，滑块定位","在讲解区滚动鼠标滚轮继续看下一页；拖动右侧紫色滑块可以快速跳到某页，也可以点击页码目录。"],["按需跟随原文","开启“跟随阅读”后，阅读区和讲解区会按当前页联动。想单独浏览讲解时可以取消勾选。"],["查看分析进度","下方显示已完成页数。导入并解析文字后就会排队分析，关闭悬浮窗不影响后台生成；已完成内容保存到本地。"],["调整悬浮窗","拖动标题栏移动位置，拖动右下角调整大小。标题栏按钮可最小化、放大、恢复和关闭；关闭后可从顶部重新打开。"]],"note":"模型输出按页保存。生成中断后，重开软件会继续未完成的讲解；模型遗漏某页时会补做，不会重复生成已经完成的页面。图片页会明确提示无法读取，不会猜测图中内容。"},
    {"id":"chat","label":"继续提问","title":"围绕当前页或选中的课件追问","image":"07-chat","intro":"提问框在课小通AI底部。在“AI实时讲解”中，问题会使用当前页的内容；在“课程总概括”中，问题会使用选中的课件。","steps":[["先核对提问范围","提问框上方显示当前页或已选择的课件数量，确认后再提问。"],["输入具体问题","例如：“请用一个校园系统的例子解释这一页的概念。”点击发送或按 Enter，Shift + Enter 可以换行。"],["查看回复和历史记录","回复在提问框上方展开，可收起后继续阅读；历史对话保存在本机，可点击“历史对话”查看。"]],"note":"提问使用设置中的 API 主模型。模型可能存在遗漏或错误，重要定义、公式和作业要求请对照原文核实。"},
    {"id":"summary","label":"课程总概括","title":"选择一份或多份课件生成概括","image":"08-summary","intro":"在课小通AI中切换到“课程总概括”。当前课件的辅导分析会自动准备，也可以勾选同一门课程的多份课件。","steps":[["选择分析范围","“当前课件”分析正在阅读的文件；选择“选择多份”后，在清单中勾选本课程的资料。"],["生成并检查内容","点击生成。内容沿用原辅导分析的结构：课程定位、课件结构、核心概念、术语与重点、考点、现实应用和自测。"],["查看已保存概括或导出 PDF","同一范围的结果会保存在本地，可从“已保存”列表查看。生成完成后可导出 PDF；升级前的课程总结也保留在列表中。"]],"note":"重新生成会再次调用配置的 API 模型。生成较长概括需要等待，但可以关闭悬浮窗继续阅读；结果完成后会保存在本机。"},
    {id:'help',label:'常见问题',title:'遇到问题时，先检查这里',intro:'以下步骤可以帮助判断是文件、模型配置还是软件运行的问题。',faq:[['连接测试失败','确认已经联网，接口地址、模型名称和 Key 属于同一服务商；核对 Key 是否有效、账户是否存在限制。修改后重新测试并保存。'],['一直在翻译，或返回失败','先看页面具体错误提示。服务商排队、频率限制、网络问题或较长课件都可能增加等待时间。修正配置或稍后再试，然后点击“重新翻译”。'],['PDF 有图但没有中文，或版式不合适','检查原文件是否可以选中文字。扫描页和图片内文字需要先做文字识别；复杂表格、公式和版式仍应对照英文原文确认。'],['离线演示没有真正翻译','这是预期行为。离线演示只返回占位内容，用于熟悉流程；真实翻译需要自己的有效 API Key。'],['退出以后，课件还在吗？','桌面版会把课程和设置保存在当前 Windows 账户的数据目录中，退出、重开软件后仍保留。通过“文件 → 打开数据文件夹”可以找到它。'],['如何分享给别人？','发送完整的软件分享压缩包，对方完整解压后打开 exe，并填写自己的 Key。不要发送个人数据文件夹，也不要单独发送 exe。'],['桌面版无法打开怎么办？','先确认已完整解压，且 _internal 文件夹仍在。可从“帮助 → 打开日志文件夹”查看日志；启动错误窗口也会提示日志位置。']]}
  ];
  const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let dialog,zoom,body,nav,index=0,returnFocus;
  function create() {
    dialog=document.createElement('dialog');dialog.id='user-guide-dialog';dialog.className='cm-guide';dialog.setAttribute('aria-labelledby','user-guide-title');
    dialog.innerHTML='<div class="cm-guide-head"><div><h2 id="user-guide-title">使用说明</h2><p>真实页面 · 标注讲解 · 点击图片可放大</p></div><button type="button" class="cm-guide-close" aria-label="关闭使用说明">×</button></div><div class="cm-guide-layout"><nav class="cm-guide-nav" aria-label="使用说明目录"><span class="cm-guide-nav-label">从这里开始</span></nav><div class="cm-guide-body" tabindex="0" role="region" aria-label="图文操作步骤"></div></div>';
    document.body.appendChild(dialog);body=dialog.querySelector('.cm-guide-body');nav=dialog.querySelector('.cm-guide-nav');
    sections.forEach((section,i)=>{const button=document.createElement('button');button.type='button';button.dataset.guideStep=section.id;button.innerHTML=`<span>${String(i+1).padStart(2,'0')}</span>${escape(section.label)}`;button.addEventListener('click',()=>show(i));nav.appendChild(button)});
    dialog.querySelector('.cm-guide-close').addEventListener('click',()=>dialog.close());
    dialog.addEventListener('close',()=>{if(returnFocus?.isConnected)returnFocus.focus({preventScroll:true})});
    dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close()});
    zoom=document.createElement('dialog');zoom.id='user-guide-zoom';zoom.className='cm-guide-zoom';zoom.setAttribute('aria-labelledby','guide-zoom-title');
    zoom.innerHTML='<div class="cm-guide-head"><div><h2 id="guide-zoom-title">操作截图</h2><p>可滚动查看完整标注 · 按 Esc 返回说明</p></div><button type="button" class="cm-guide-close" aria-label="关闭放大截图">×</button></div><div class="cm-guide-zoom-scroll"><img alt=""></div>';
    document.body.appendChild(zoom);zoom.querySelector('button').addEventListener('click',()=>zoom.close());
    show(0);
  }
  function show(next) {
    index=Math.max(0,Math.min(sections.length-1,next));const section=sections[index];
    nav.querySelectorAll('button').forEach((button,i)=>{if(i===index)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current')});
    body.innerHTML=`<span class="cm-guide-kicker">${index===sections.length-1?'随时查阅':`第 ${index+1} 步 · ${escape(section.label)}`}</span><h3>${escape(section.title)}</h3><p class="cm-guide-intro">${escape(section.intro)}</p>`;
    if(section.image){
      const src=`/guide/images/${section.image}-annotated.png`;
      body.insertAdjacentHTML('beforeend',`<figure class="cm-guide-figure"><button type="button" class="cm-guide-image-button" aria-label="放大查看：${escape(section.title)}"><img src="${src}" alt="${escape(section.label)}的真实页面截图，图中有编号和操作标注" decoding="async"></button><figcaption><span>示例课程的实际页面，按图中编号操作</span><span>点击放大 ↗</span></figcaption></figure>`);
      body.querySelector('.cm-guide-image-button').addEventListener('click',()=>{const img=zoom.querySelector('img');img.src=src;img.alt=section.title+'的完整标注截图';zoom.querySelector('h2').textContent=section.label+' · 完整截图';zoom.showModal();zoom.querySelector('.cm-guide-zoom-scroll').scrollTo(0,0)});
    }
    if(section.steps)body.insertAdjacentHTML('beforeend',`<ol class="cm-guide-steps">${section.steps.map(([title,text],i)=>`<li><span class="step-number">${i+1}</span><div><strong>${escape(title)}</strong>${escape(text)}</div></li>`).join('')}</ol>`);
    if(section.note)body.insertAdjacentHTML('beforeend',`<p class="cm-guide-note">${escape(section.note)}</p>`);
    if(section.faq)body.insertAdjacentHTML('beforeend',`<div class="cm-guide-faq">${section.faq.map(([q,a])=>`<div><h4>${escape(q)}</h4><p>${escape(a)}</p></div>`).join('')}</div>`);
    body.insertAdjacentHTML('beforeend',`<div class="cm-guide-pager"><button type="button" class="btn" data-guide-prev ${index===0?'disabled':''}>← 上一步</button><span class="cm-guide-counter">${index+1} / ${sections.length}</span><button type="button" class="btn primary" data-guide-next>${index===sections.length-1?'开始使用':'下一步 →'}</button></div>`);
    body.querySelector('[data-guide-prev]').addEventListener('click',()=>show(index-1));
    body.querySelector('[data-guide-next]').addEventListener('click',()=>index===sections.length-1?dialog.close():show(index+1));
    body.scrollTop=0;
  }
  window.openCourseMateGuide=()=>{if(!dialog)create();if(dialog.open)return;returnFocus=document.activeElement;dialog.showModal()};
  document.getElementById('btn-user-guide')?.addEventListener('click',window.openCourseMateGuide);
  document.addEventListener('keydown',event=>{if(event.key==='F1'){event.preventDefault();window.openCourseMateGuide()}});
})();
