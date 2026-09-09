const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
 research:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14M15 15l5 5',
 profile:'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8M4 21v-2a6 6 0 0 1 6-5h4a6 6 0 0 1 6 5v2',
 library:'M4 3h12l4 4v14H4zM15 3v5h5M8 12h8M8 16h6',
 projects:'M3 5h7l2 3h9v12H3z',
 memory:'M8 3h8l4 4v10l-4 4H8l-4-4V7zM9 8h6M9 12h6M9 16h3',
 history:'M3 11a9 9 0 1 1 3 8M3 4v7h7M12 7v5l3 2',
 skills:'M12 3l3 6 6 3-6 3-3 6-3-6-6-3 6-3z',
 settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2',
 send:'M12 20V4M5 11l7-7 7 7',
 plus:'M12 5v14M5 12h14',
 globe:'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20M2 12h20M12 2c-6 5-6 15 0 20M12 2c6 5 6 15 0 20',
 arrow:'M5 12h14M13 6l6 6-6 6',
 attach:'M8 13l7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7l9-9',
 alumni:'M8 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6M2 20v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3M17 5a3 3 0 0 1 0 6M17 13a4 4 0 0 1 5 4v3',
 policy:'M12 2l8 4v6c0 5-8 10-8 10S4 17 4 12V6zM8 12l3 3 5-6',
 living:'M3 11l9-8 9 8M6 10v11h12V10M10 21v-7h4v7',
 close:'M6 6l12 12M6 18L18 6',
};
const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name]||paths.library}"/></svg>`;
const labels = {research:'研究',profile:'个人档案',projects:'目标项目',library:'资料库',memory:'长期记忆',history:'研究记录',social:'平台连接',skills:'Skills 与信息源',settings:'设置'};
const skillNames = {'bg-match':'BG 匹配','policy-check':'政策核查','alumni-paths':'校友路径','program-study':'项目培养','living-costs':'生活与成本','program-compare':'项目比较'};
const statusNames = {queued:'排队中',running:'研究中',completed:'已完成',failed:'需要处理',cancelled:'已停止',interrupted:'已暂停',limited:'已达上限'};
const accessNames = {full_text:'已读取正文',snippet:'仅搜索摘要',user_import:'用户导入',visible_text:'浏览器可见内容'};
let state = null, page = 'research', currentRun = null, poll = null, toastTimer = null;
let attachments = new Set(), projectSelection = new Set();

async function api(path, options={}) {
 const response = await fetch('/api'+path, { ...options, headers:{'Content-Type':'application/json','X-Application-Helper':'1',...(options.headers||{})} });
 const data = await response.json();
 if (!response.ok) {
  const detail = Array.isArray(data.detail) ? data.detail.map(x=>`${x.loc.slice(1).join('.')}: ${x.msg}`).join('；') : data.detail;
  throw new Error(detail || '请求失败，请重试');
 }
 return data;
}
function toast(message) { $('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),5000); }
function date(value) { return value ? new Intl.DateTimeFormat('zh-CN',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value)) : '未记录'; }
function tag(text, variant='') { return `<span class="tag ${variant}">${esc(text)}</span>`; }
function runTag(run) { return tag(statusNames[run.status]||run.status,['failed','limited','interrupted'].includes(run.status)?'warning':run.status==='completed'?'':'neutral'); }
function empty(title, description, kind='library') { return `<div class="empty">${icon(kind)}<strong>${esc(title)}</strong><p>${esc(description)}</p></div>`; }
function heading(eyebrow,title,description,action='') { return `<div class="page-intro"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1><p>${description}</p></div>${action}</div>`; }
function input(label,name,value='',type='text',placeholder='') { return `<label>${label}<input name="${name}" type="${type}" value="${esc(value)}" placeholder="${esc(placeholder)}" ${type==='password'?'autocomplete="new-password"':''}></label>`; }
function textarea(label,name,value='',placeholder='') { return `<label>${label}<textarea name="${name}" placeholder="${esc(placeholder)}">${esc(value)}</textarea></label>`; }
function button(text,action,variant='',extra='') { return `<button type="button" class="btn ${variant}" data-action="${action}" ${extra}>${text}</button>`; }
function safeLink(url,text) { try { const u=new URL(url); if(['http:','https:'].includes(u.protocol))return `<a class="text-link" href="${esc(u.href)}" target="_blank" rel="noopener noreferrer">${esc(text)} ↗</a>`; } catch {} return ''; }
function openDialog(title,body) { $('#dialog-body').innerHTML=`<div class="dialog-header"><h2>${esc(title)}</h2><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭">${icon('close')}</button></div><div class="dialog-content">${body}</div>`; if(!$('#dialog').open)$('#dialog').showModal(); }
async function refresh() { state=await api('/state'); renderNav(); }
function renderNav() { $('#nav').innerHTML=Object.entries(labels).map(([key,label],i)=>`${i===6?'<div class="nav-divider"></div>':''}<a href="#${key}" class="nav-item ${page===key?'active':''}" ${page===key?'aria-current="page"':''}>${icon(key)}<span>${label}</span>${key==='history'?`<span class="count">${state.runs.length||'—'}</span>`:''}</a>`).join(''); }
function navigate(target) { if(location.hash==='#'+target)route();else location.hash=target; }
function route() {
 clearTimeout(poll);const route=location.hash.slice(1).split('/');page=labels[route[0]]?route[0]:'research';currentRun=route[0]==='run'?route[1]:null;
 if(currentRun)page='history';$('#breadcrumb').textContent=`工作空间 / ${currentRun?'研究详情':labels[page]}`;$('#sidebar').classList.remove('open');renderNav();
 if(currentRun){renderRun();return;}
 ({research:renderHome,profile:renderProfile,settings:renderSettings,library:renderLibrary,memory:renderMemory,projects:renderProjects,history:renderHistory,social:renderSocial,skills:renderSkills}[page])();
}
function composer(placeholder='告诉我你正在考虑的问题，或粘贴一个项目链接…',followup=false) { return `<form id="research-form" class="composer ${followup?'run-followup':''}"><textarea name="question" aria-label="研究问题" placeholder="${placeholder}" required minlength="2" maxlength="6000"></textarea><div class="composer-bottom"><div class="row"><button type="button" class="btn subtle" data-action="attach">${icon('attach')} 添加资料</button><span class="attach-label" id="attach-label">${attachments.size?attachments.size+' 份已选择':''}</span></div><div class="row"><span class="composer-hint">${followup?'追问将携带本次报告与证据':'按需调查 · 自动加载 Skills'}</span><button type="submit" class="send" aria-label="开始研究">${icon('send')}</button></div></div></form>`; }
function renderHome() {
 const p=state.profile;const fields=['university','major','gpa','targets','intake','goals'];const completed=fields.filter(k=>p[k]).length;
 const prompts=[['profile','我的 BG，适合哪些项目？','结合背景与真实案例，找到申请方向','根据我的个人档案，分析目标项目的官方门槛、相似录取与拒录案例，以及我需要补强的方面。'],['policy','政策里的细节，适用于我吗？','核对原文、适用条件和例外','请帮我核查目标地区与我的申请相关的签证及学校特殊政策，列出适用条件、官方原文和待核实的问题。'],['alumni','这个项目，毕业后去了哪里？','追踪可核实的校友教育与职业路径','请调查我的目标项目近年校友的毕业去向，区分第一份工作和当前工作，并明确样本覆盖率与未知信息。'],['living','去那里生活，要准备些什么？','从住房与通勤到真实生活预算','根据我的目标地区和预算，调查住房、交通及落地准备，注明价格时间和适用条件。']];
 $('#main').innerHTML=`<div class="home-grid"><section class="hero"><div class="welcome-top"><span class="tiny-line"></span> 为你的下一站，做更好的决定</div><h1>把信息变成<br><em>你的下一步。</em></h1><p>了解你的背景，连接分散的线索。<br>从选校到落地，让每一个决定都有依据。</p>${composer()}${!state.settings.model?'<div class="configuration-banner"><span>开始前，连接你的大模型 API。个人档案与资料库已可使用。</span><button data-action="navigate" data-page="settings">去设置 ↗</button></div>':'<div class="composer-hint">研究会使用你允许分享的个人档案；每项发现保留来源。</div>'}<div class="section-label"><span>从一个问题开始</span><small>RESEARCH STARTERS</small></div><div class="prompt-grid">${prompts.map(([i,t,d,q])=>`<button class="prompt-card" data-action="prompt" data-prompt="${esc(q)}">${icon(i)}<strong>${t}</strong><p>${d}</p></button>`).join('')}</div><div class="section-label"><span>最近的研究</span><a class="text-link" href="#history">全部记录 ↗</a></div>${state.runs.length?state.runs.slice(0,3).map(run=>`<a href="#run/${run.id}" class="recent-row"><div><strong>${esc(run.question.slice(0,58))}</strong><small>${date(run.created_at)} · ${run.sources.length} 个来源</small></div>${runTag(run)}</a>`).join(''):empty('第一条线索，从这里开始','你的研究过程、证据和结论会保存在这里。','research')}</section><aside><div class="profile-mini"><div class="row between">${tag('PERSONAL PROFILE')}<span class="muted">↗</span></div><h3>${p.university?'你的申请画像':'让研究更了解你'}</h3><p>${p.university?esc([p.university,p.major].filter(Boolean).join(' · ')):'添加学术背景、申请目标与偏好，获得更贴近你的分析。'}</p><div class="progress-track"><div class="progress-fill" id="profile-progress"></div></div><div class="row between"><small>基础资料</small><small>${completed} / ${fields.length}</small></div><a class="btn" href="#profile">${completed?'编辑个人档案':'完善个人档案'} ${icon('arrow')}</a></div><div class="method-column"><div class="mini-title">一次研究，如何发生</div>${[['01','理解你的问题','结合个人背景，选择相关调查方法。'],['02','沿着线索查证','读取公开资料，交叉核对证据。'],['03','形成可执行的建议','明确依据、未知事项与下一步。']].map(([n,t,d])=>`<div class="method-step"><span class="step-number">${n}</span><div><strong>${t}</strong><small>${d}</small></div></div>`).join('')}<div class="footnote">来源不完整时，会如实说明。<br>你的档案与研究记录保存在本机。</div></div></aside></div>`;
 $('#profile-progress').style.width=(completed/fields.length*100)+'%';
}
function renderProfile() { const p=state.profile;$('#main').innerHTML=heading('YOUR STARTING POINT','个人档案','用你真实的背景，让每次调查更有针对性。未确定的内容可以留空。')+`<div class="form-actions"><button type="button" class="btn" data-action="resume-import">导入简历 PDF</button></div><form id="profile-form" class="stack"><section class="card"><div class="form-heading"><h2>学术背景</h2><small>保留成绩原始计分制，不会自动换算 GPA。</small></div><div class="form-grid">${input('称呼（仅用于本地展示）','display_name',p.display_name,'text','可选')}${input('本科 / 当前院校','university',p.university,'text','院校名称')}${input('专业方向','major',p.major,'text','例如：计算机科学')}${input('GPA / 均分 / 排名','gpa',p.gpa,'text','例如：3.6/4.0，前 15%')}${input('语言与标准化考试','language',p.language,'text','例如：IELTS 7.0；注明单项')}${input('申请学位','degree',p.degree,'text','例如：授课型硕士 / 博士')}<div class="wide">${textarea('科研与项目经历','research',p.research,'方向、个人贡献、成果与时间')}</div><div class="wide">${textarea('实习与工作经历','experience',p.experience,'职责、持续时间与成果')}</div></div></section><section class="card"><div class="form-heading"><h2>你的下一站</h2><small>目标可以逐渐清晰，随时回来更新。</small></div><div class="form-grid">${input('目标入学时间','intake',p.intake,'text','例如：2027 Fall')}${input('预算','budget',p.budget,'text','注明币种、总预算或每年预算')}<div class="wide">${textarea('目标地区与项目','targets',p.targets,'国家、城市、大学、具体学位项目')}</div><div class="wide">${textarea('长期目标与偏好','goals',p.goals,'就业、科研、生活方式，以及你最重视的因素')}</div></div><div class="form-actions"><small>${p.updated_at?'上次更新 '+date(p.updated_at):'保存后将用于后续研究，可在设置中关闭分享给模型。'}</small><button class="btn primary" type="submit">保存档案</button></div></section></form>`; }
const resumeLabels={university:'院校与教育阶段',major:'专业方向',gpa:'GPA / 均分 / 排名',language:'语言与考试',research:'科研与项目经历',experience:'实习与工作经历',targets:'目标地区与项目',degree:'申请学位',intake:'入学时间',budget:'预算',goals:'目标与偏好'};
function resumeDialog(){openDialog('导入简历 PDF',`<form id="resume-upload" class="stack"><p>先在本机提取文字，再由你选择的模型整理为档案。原始 PDF 不保存到资料库。</p><label>简历 PDF（5 MB、20 页以内）<input type="file" name="file" accept=".pdf,application/pdf" required></label><small>支持中英文文本 PDF，扫描件暂不支持 OCR。</small><button type="submit" class="btn primary">提取文字</button></form>`);}
function resumeReview(result){openDialog('确认简历解析结果',`<form id="resume-review" class="stack"><p>勾选要填入的字段。已有内容默认不勾选；选中后会替换该字段。你仍需点击「保存档案」才会持久保存。</p>${result.warnings.map(x=>`<p class="help-note">${esc(x)}</p>`).join('')}${Object.entries(result.fields).filter(([key])=>resumeLabels[key]).map(([key,item])=>{const current=$('#profile-form [name="'+key+'"]')?.value||'';return `<section class="card"><label class="check-row"><input type="checkbox" name="select_${key}" ${current?'':'checked'}>${esc(resumeLabels[key])}</label>${current?`<p>现有内容：${esc(current)}</p>`:''}${textarea('建议内容（可修改）',key,item.value)}<details><summary>查看简历原文</summary><pre>${esc(item.evidence)}</pre></details></section>`;}).join('')}<button type="submit" class="btn primary">填入选中字段</button></form>`);}

function renderSettings() { const s=state.settings;$('#main').innerHTML=heading('MAKE IT YOURS','连接与设置','连接你选择的模型服务，并控制研究的时间和用量。')+`<form id="settings-form" class="stack"><section class="card"><div class="form-heading"><h2>大模型连接</h2><small>支持 Chat Completions 兼容接口。模型需要支持工具调用。</small></div><div class="form-grid">${input('服务地址 Base URL','base_url',s.base_url,'url','https://api.deepseek.com')}${input('模型名称','model',s.model,'text','填写服务商提供的模型 ID')}<div class="wide">${input('API Key','api_key','','password',s.api_key_configured?'已保存 · 留空保持不变':'本机模型可不填')}<small class="field-help">密钥仅保存在本机设置文件，不回传到网页，不进入模型上下文。</small><label class="check-row"><input type="checkbox" name="clear_api_key">清除已保存的模型 Key</label></div></div></section><section class="card"><div class="form-heading"><h2>联网搜索</h2><small>Tavily 负责发现网页，采集器负责读取允许访问的正文。</small></div>${input('Tavily Search Key','search_key','','password',s.search_key_configured?'已保存 · 留空保持不变':'tvly-…')}<small class="field-help">未连接搜索时，仍可基于导入资料和直接提供的公开链接研究。</small><label class="check-row"><input type="checkbox" name="clear_search_key">清除已保存的搜索 Key</label></section><section class="card"><div class="form-heading"><h2>研究预算与隐私</h2><small>预算按实际请求尝试计数，已发出的失败请求也计数。累计达到 Token 预算的 80% 开始收尾，超出预算后停止常规研究；重复发送的上下文也计入累计量。</small></div><div class="form-grid">${input('最多分析轮数（3–40）','max_steps',s.max_steps,'number')}${input('最多搜索次数（0–30）','max_searches',s.max_searches,'number')}${input('最多读取页面（0–50）','max_pages',s.max_pages,'number')}${input('每次模型输出 Token 上限','max_output_tokens',s.max_output_tokens,'number')}${input('累计 Token 预算（1万–100万）','max_total_tokens',s.max_total_tokens,'number')}${input('单次研究时限（秒，30–1800）','timeout_seconds',s.timeout_seconds,'number')}<div class="wide"><label class="check-row"><input name="profile_to_model" type="checkbox" ${s.profile_to_model?'checked':''}>研究时向所选模型发送个人档案与已确认记忆</label><small class="field-help">关闭后仍会发送你的问题、你选择的资料，以及追问所需的上次报告和证据。称呼不会加入档案上下文。</small></div></div><div class="form-actions"><button type="button" class="btn" data-action="test-model">测试模型连接</button><button type="button" class="btn" data-action="test-search">测试搜索连接</button><button class="btn primary" type="submit">保存设置</button></div><p class="help-note">连接测试会保存当前设置并发起一次实际 API 请求。当前版本仅在本机开放，不直接部署到公网。</p></section></form>`; }
function renderLibrary(filter='') {
 $('#main').innerHTML=heading('YOUR EVIDENCE DESK','资料库','保存公开网页、笔记文字和 PDF，让有价值的信息成为可复用的证据。',button(icon('plus')+' 添加资料','import','primary'))+`<div class="row between wrap"><input class="search-input" id="library-filter" aria-label="筛选资料" placeholder="按标题或网址筛选…" value="${esc(filter)}"><small>${state.evidence.length} 份资料</small></div><div id="library-list"></div><p class="help-note">用户导入的内容保留来源标签。扫描 PDF、图片 OCR 与受限平台自动采集尚未接入。</p>`; renderLibraryList(filter);
}
function renderLibraryList(filter) { const items=state.evidence.filter(x=>(x.title+' '+x.url).toLowerCase().includes(filter.toLowerCase()));$('#library-list').innerHTML=items.length?items.map(x=>`<div class="evidence-row"><div class="doc-icon">${icon('library')}</div><div class="info"><button class="text-link" data-action="evidence" data-id="${x.id}"><strong>${esc(x.title)}</strong></button><div class="row">${tag(accessNames[x.access]||'资料',x.access==='snippet'?'warning':'')}${x.truncated?tag('内容已截断','warning'):''}<small>${date(x.fetched_at)}</small></div><p>${esc(x.url||'本地导入 · 未提供原文链接')}</p></div><div class="actions">${button('用于研究','use-evidence','subtle',`data-id="${x.id}"`)}${button('删除','delete-evidence','subtle',`data-id="${x.id}"`)}</div></div>`).join(''):empty(filter?'没有匹配的资料':'为你的研究，留下一份依据',filter?'试试其他关键词。':'导入一篇笔记，或读取一个学校项目页面。'); }
function importDialog(mode='text') { openDialog('添加研究资料',`<div class="tab-row">${[['text','粘贴文字'],['url','读取网页'],['pdf','上传 PDF']].map(([k,n])=>`<button class="${mode===k?'active':''}" data-action="import-mode" data-mode="${k}">${n}</button>`).join('')}</div><form id="import-form" data-mode="${mode}" class="stack">${mode==='url'?`${input('公开网页或 PDF 链接','url','','url','https://…')}<p class="help-note">将检查 robots.txt 并读取正文。登录、验证码或受限平台会显示未完成原因。</p>`:`${input('资料标题','title','','text','例如：某项目招生说明 / 校友访谈笔记')}${mode==='pdf'?'<label>PDF 文件（不超过 5 MB）<input name="file" type="file" accept="application/pdf,.pdf" required></label>':textarea('资料正文','content','','粘贴你有权使用的内容，至少 20 字')}${input('原文链接（可选）','url','','url','https://…')}${input('内容发表日期（可选）','published_at','','date')}`}<div class="form-actions"><button type="submit" class="btn primary">${mode==='url'?'读取并保存':'保存资料'}</button></div></form>`); }
function renderMemory() { const confirmed=state.memories.filter(x=>x.status==='confirmed'),suggested=state.memories.filter(x=>x.status==='suggested');const list=items=>items.map(m=>`<div class="memory-card"><div class="info"><p>${esc(m.text)}</p><div class="row">${tag(m.status==='confirmed'?'已确认':'待确认',m.status==='suggested'?'warning':'')}<small>${date(m.updated_at)}</small>${m.run_id?`<a class="text-link" href="#run/${m.run_id}">来自研究 ↗</a>`:''}</div></div><div class="actions">${m.status==='suggested'?button('确认','confirm-memory','',`data-id="${m.id}"`):''}${button('编辑','edit-memory','subtle',`data-id="${m.id}"`)}${button('删除','delete-memory','subtle',`data-id="${m.id}"`)}</div></div>`).join('');$('#main').innerHTML=heading('WHAT MATTERS TO YOU','长期记忆','保存明确的偏好和约束。模型提出的记忆建议，需要你确认后才会用于后续研究。',button(icon('plus')+' 添加记忆','add-memory','primary'))+(suggested.length?`<section class="card"><h2>等待你确认 <small>${suggested.length}</small></h2>${list(suggested)}</section><div class="divider"></div>`:'')+(confirmed.length?`<section class="card"><h2>已确认的记忆</h2>${list(confirmed)}</section>`:empty('记住对你重要的事','例如：优先考虑两年制项目；更看重科研机会。','memory'))+`<p class="help-note">删除后不会再加入新研究的记忆上下文。历史研究保留当时的上下文快照；如需移除，请同时删除对应研究记录。</p>`; }
function renderProjects() {$('#main').innerHTML=heading('PLACES TO GO','目标项目','把感兴趣的项目放在一起，逐步补全信息与判断。',button(icon('plus')+' 收藏项目','add-project','primary'))+`<div class="row between"><small>${state.projects.length} 个项目</small>${button('比较已选项目','compare-projects','',`id="compare-projects"`)}</div><div class="divider"></div><div class="project-grid">${state.projects.map(p=>`<article class="card project-card"><div class="row">${tag(p.status)}<label class="check-row"><input type="checkbox" data-project="${p.id}" ${projectSelection.has(p.id)?'checked':''}>加入比较</label></div><h3>${esc(p.name)}</h3>${safeLink(p.url,'项目主页')}<p>${esc(p.notes||'还没有研究笔记，可以记录项目特点与待核实事项。')}</p><div class="row">${button('研究这个项目','research-project','',`data-id="${p.id}"`)}${button('编辑','edit-project','subtle',`data-id="${p.id}"`)}${button('删除','delete-project','subtle',`data-id="${p.id}"`)}</div></article>`).join('')}</div>${!state.projects.length?empty('下一站，值得仔细了解','收藏具体项目，然后比较申请要求、课程与毕业去向。','projects'):''}`; }
function renderHistory() {$('#main').innerHTML=heading('A TRAIL OF THOUGHT','研究记录','回到之前的问题、调查过程和证据，也可以继续追问。')+(state.runs.length?`<div class="card">${state.runs.map(run=>`<div class="recent-row"><a href="#run/${run.id}" class="info"><strong>${esc(run.question)}</strong><small>${date(run.created_at)} · ${run.sources.length} 个来源 · ${run.skills.length} 个 Skill</small></a><div class="row">${runTag(run)}${button('删除','delete-run','subtle',`data-id="${run.id}"`)}</div></div>`).join('')}</div>`:empty('还没有研究记录','从一个与你申请相关的问题开始。','history')); }
function renderSkills() { $('#main').innerHTML=heading('METHODS & SOURCES','Skills 与信息源','主 Agent 按问题选择调查方法，通过工具读取资料，并保留执行记录。')+`<div class="section-label"><span>专项调查方法</span><small>${state.skills.length} SKILLS · 按需加载</small></div><div class="source-grid">${state.skills.map((s,i)=>`<article class="card skill-card"><span class="skill-number">0${i+1}</span>${icon('skills')}<h3>${esc(skillNames[s.name]||s.name)}</h3><p>${esc(s.description)}</p><small>${esc(s.name)}</small></article>`).join('')}</div><div class="section-label"><span>信息源与访问方式</span><small>能力状态，不代表本次采集成功</small></div><div class="source-grid">${state.sources.map(s=>`<article class="card source-card"><div class="row between"><div><h3>${esc(s.name)}</h3><div class="source-domain">${esc(s.domain)}</div></div>${tag({public:'公开采集',probe:'逐页检查',manual:'辅助导入',pending:'待确认',browser:'浏览器采集'}[s.mode],s.mode==='public'?'':'warning')}</div><p>${esc(s.description)}</p></article>`).join('')}</div><p class="help-note">网页读取执行 robots 校验、每站低频请求、公网地址检查和大小限制。搜索命中不代表正文可读，具体结果以研究过程为准。</p>`; }
async function renderRun() {
 const id=currentRun;
 try { const run=await api('/runs/'+id);if(currentRun!==id)return;
 $('#main').innerHTML=`<a class="text-link" href="#history">← 研究记录</a><h1 class="run-question">${esc(run.question)}</h1><div class="row wrap"><div id="run-tag">${runTag(run)}</div><small>${date(run.created_at)}</small>${button('停止研究','cancel-run','',`data-id="${id}" id="cancel-run"`)}${button('恢复研究','resume-run','',`data-id="${id}" id="resume-run"`)}<a class="btn" href="/api/runs/${id}/export">导出报告 ↗</a></div><div id="run-content"></div>${composer('继续追问：还有哪些信息值得进一步核实？',true)}`;
 updateRun(run);pollRun(id);
 } catch(error){toast(error.message);$('#main').innerHTML=empty('无法打开研究',error.message,'history');}
}
function updateRun(run) {
 const active=['running','queued'].includes(run.status);$('#run-tag').innerHTML=runTag(run);$('#cancel-run').hidden=!active;$('#resume-run').hidden=!['failed','interrupted','cancelled','limited'].includes(run.status);$('#resume-run').textContent=run.status==='limited'?'仅整理已有证据':'恢复研究';
 const report=run.report;let content='';
 if(report)content=`<div class="report card"><div class="eyebrow">${run.partial_report?'研究进度 · 尚未形成结论':'RESEARCH FINDINGS'}</div><p class="report-summary">${esc(report.summary)}</p>${report.findings.length?'<h3>发现与依据</h3>':''}${report.findings.map(f=>`<div class="finding"><p>${esc(f.claim)}</p>${f.evidence_ids.map(id=>{const n=run.sources.findIndex(s=>s.id===id);return `<button class="citation" data-action="evidence" data-id="${esc(id)}">来源 ${n+1} ↗</button>`}).join('')}${f.caveat?`<small>${esc(f.caveat)}</small>`:''}</div>`).join('')}${[['unknowns','仍待核实'],['next_steps','建议的下一步']].map(([k,title])=>report[k].length?`<h3>${title}</h3><ul>${report[k].map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:'').join('')}<div class="help-note">引用存在性已由程序检查；来源准确性及其是否足以支持结论，仍需结合原文判断。</div></div>`;
 else content=`<div class="card">${active?'<div class="run-status"><span class="pulse"></span> 正在沿着线索调查</div>':''}${empty(active?'正在寻找与你相关的证据':'调查进度已保存',active?'过程会持续更新，你可以离开页面，稍后回来查看。':'已有证据保留在右侧和资料库中。','research')}</div>`;
 $('#run-content').innerHTML=`<div class="stats"><span>${run.step} 轮分析</span><span>${run.search_count} 次搜索</span><span>${run.page_count} 次页面读取</span><span>${Number(run.usage?.total_tokens||0).toLocaleString()} Tokens（累计）</span></div>${run.error?`<div class="notice">${esc(run.error)}</div>`:''}<div class="skill-pills">${run.skills.map(x=>`<span class="skill-pill">${esc(skillNames[x]||x)}</span>`).join('')}</div><div class="run-layout"><section>${content}</section><aside class="stack"><section class="card activity"><h3>研究过程</h3>${run.events.slice(-14).map(e=>`<div class="activity-item ${esc(e.level)}"><span class="dot"></span><div>${esc(e.message)}<small>${date(e.time)}</small></div></div>`).join('')||'<small>等待任务开始…</small>'}</section><section class="card"><h3>证据与来源 <small>${run.sources.length}</small></h3>${run.sources.map((s,i)=>`<button class="run-source" data-action="evidence" data-id="${s.id}"><strong>${i+1}. ${esc(s.title)}</strong><small>${esc(accessNames[s.access]||s.access)} · ${esc(s.url||'本地资料')}</small></button>`).join('')||'<small>取得来源后会显示在这里。</small>'}</section></aside></div>`;
}
async function pollRun(id) { if(currentRun!==id)return;try { const run=await api('/runs/'+id);if(currentRun!==id)return;updateRun(run);if(['running','queued'].includes(run.status))poll=setTimeout(()=>pollRun(id),1500);else await refresh(); }catch(e){if(currentRun===id){toast('读取进度失败，稍后自动重试');poll=setTimeout(()=>pollRun(id),4000);}} }
async function saveSettings() {const data=Object.fromEntries(new FormData($('#settings-form')));for(const k of ['max_steps','max_searches','max_pages','max_output_tokens','max_total_tokens','timeout_seconds'])data[k]=Number(data[k]);data.profile_to_model=$('[name=profile_to_model]').checked;for(const key of ['api_key','search_key']){if(data['clear_'+key])data[key]='';else if(!data[key])delete data[key];delete data['clear_'+key];}await api('/settings',{method:'PUT',body:JSON.stringify(data)});await refresh();}
function projectDialog(project={}) {openDialog(project.id?'编辑项目':'收藏目标项目',`<form id="project-form" data-id="${project.id||''}" class="stack">${input('项目名称（包含学位与校区）','name',project.name,'text','例如：大学名 · MSCS · 主校区')}${input('项目主页','url',project.url,'url','https://…')}${input('当前状态','status',project.status||'研究中','text','研究中 / 准备申请 / 已提交')}${textarea('项目笔记与待核实事项','notes',project.notes)}<div class="form-actions"><button class="btn primary" type="submit">保存项目</button></div></form>`);}
function renderSocial() {
 const names={restorable:'登录态已保存 · 按需恢复',disconnected:'未连接',awaiting_login:'等待登录',needs_login:'需要登录',ready:'已检测到登录态',challenge:'等待手动验证',connection_error:'连接需检查'};
 $('#main').innerHTML=heading('CONNECTED SOURCES','平台连接','使用独立的本机浏览器登录，再让助手按问题搜索和读取页面。')+`<div class="notice">先打开登录窗口并完成登录，再检查状态、启用采集。登录态只保存在本机，无需粘贴密码或 Cookie。平台可能限制自动化或账号访问，尤其是 LinkedIn；遇验证码、登录失效或限流会暂停。</div><div class="stack">${(state.social||[]).map(s=>`<article class="card"><div class="row between"><h2>${esc(s.name)}</h2>${tag(names[s.status]||s.status,s.status==='ready'?'':'warning')}</div><p class="settings-info">${esc(s.message)}</p><div class="row wrap">${button('打开登录窗口','social-login','',`data-platform="${s.platform}"`)}${button('检查登录状态','social-check','',`data-platform="${s.platform}"`)}${button('关闭连接','social-disconnect','subtle',`data-platform="${s.platform}"`)}${button('清除登录态','social-forget','subtle',`data-platform="${s.platform}"`)}</div><div class="divider"></div><form class="social-config-form" data-platform="${s.platform}"><div class="form-grid">${input('请求最小间隔（秒，至少 10）','interval_seconds',s.interval_seconds,'number')}${input('每日页面请求上限（1–100）','daily_limit',s.daily_limit,'number')}<div class="wide"><label class="check-row"><input name="enabled" type="checkbox" ${s.enabled?'checked':''}>允许助手自动使用这个平台</label></div></div><div class="form-actions"><small>今天已请求 ${s.today_requests} 次 · 按 UTC 日期计数</small><button type="submit" class="btn primary">保存采集配置</button></div></form><div class="divider"></div><form class="social-search-form" data-platform="${s.platform}"><label>试搜关键词<input name="query" required maxlength="300" placeholder="${s.platform==='linkedin'?'例如：CMU MSCS software engineer':'例如：计算机硕士 申请经验'}"></label><div class="form-actions"><small>最多保存 8 条可见结果，正文需进一步读取。</small><button type="submit" class="btn">试搜并保存到资料库</button></div></form><form class="social-read-form" data-platform="${s.platform}"><label>直接读取${s.platform==='linkedin'?'职业主页':'笔记'}<input type="url" name="url" required placeholder="${s.platform==='linkedin'?'https://www.linkedin.com/in/…':'https://www.xiaohongshu.com/explore/…'}"></label><div class="form-actions"><button type="submit" class="btn">读取并保存正文</button></div></form><p class="help-note">${s.platform==='linkedin'?'仅处理职业主页中可见的简介、工作经历、教育与技能，不读取消息、联系人或联系方式。':'读取笔记文字及已经显示的少量评论；图片 OCR、视频、自动翻页尚未接入。'}</p></article>`).join('')}</div><p class="help-note">浏览器运行在启动服务的电脑上。首次登录并检查成功后自动保留会话，重启后在下次采集时恢复；平台会话过期仍需重新登录。登录窗口不要复用你的日常浏览器配置目录。</p>`;
}
function memoryDialog(memory={}) {openDialog(memory.id?'编辑记忆':'添加长期记忆',`<form id="memory-form" data-id="${memory.id||''}" class="stack">${textarea('希望助手记住的偏好或约束','text',memory.text,'例如：我更看重课程深度，倾向于两年制项目。')}<small>保存后标记为你已确认的信息。</small><div class="form-actions"><button class="btn primary" type="submit">保存记忆</button></div></form>`);}
async function fillQuestion(question) {navigate('research');await new Promise(resolve=>setTimeout(resolve,30));const area=$('#research-form textarea');if(area){area.value=question;area.focus();area.scrollIntoView({behavior:'smooth',block:'center'});}}

document.addEventListener('click',async e=>{
 const target=e.target.closest('[data-action]');if(!target)return;const action=target.dataset.action,id=target.dataset.id;
 try {
  if(action==='resume-import')resumeDialog();
  if(action==='navigate')navigate(target.dataset.page);
  if(['social-login','social-check','social-disconnect','social-forget'].includes(action)){
   if(action==='social-forget'&&!confirm('清除这个平台的独立登录态？不会删除已保存的研究资料。'))return;
   target.disabled=true;
   const operation={'social-login':'login','social-check':'check','social-disconnect':'disconnect','social-forget':'session'}[action];
   if(action==='social-login')toast('正在打开独立浏览器，请稍候…');
   const result=await api('/social/'+target.dataset.platform+'/'+operation,{method:action==='social-forget'?'DELETE':'POST'});
   await refresh();if(page==='social')renderSocial();toast(result.message);
  }
  if(action==='menu')$('#sidebar').classList.toggle('open');
  if(action==='close-dialog')$('#dialog').close();
  if(action==='prompt'){const area=$('#research-form textarea');area.value=target.dataset.prompt;area.focus();}
  if(action==='import')importDialog();
  if(action==='import-mode')importDialog(target.dataset.mode);
  if(action==='attach'){openDialog('选择本次研究的参考资料',state.evidence.length?`<div class="document-choices">${state.evidence.map(x=>`<div class="document-choice"><label class="check-row"><input type="checkbox" data-attachment="${x.id}" ${attachments.has(x.id)?'checked':''}>${esc(x.title)}</label><small>${esc(accessNames[x.access])}</small></div>`).join('')}</div><div class="form-actions">${button('完成','close-dialog','primary')}</div>`:`${empty('资料库还没有内容','先在资料库中导入文字、网页或 PDF。')}`);}
  if(action==='evidence'){target.disabled=true;const doc=await api('/evidence/'+id);openDialog(doc.title,`<div class="row wrap">${tag(accessNames[doc.access]||'资料')}${doc.truncated?tag('内容已截断','warning'):''}${safeLink(doc.url,'打开原文')}</div><p class="help-note">${doc.coverage?esc(doc.coverage)+'<br>':''}发布时间：${esc(doc.published_at||'未提供')}<br>采集 / 导入：${date(doc.fetched_at)}</p><pre>${esc(doc.content)}</pre>`);}
  if(action==='use-evidence'){attachments.add(id);await fillQuestion('请结合我选择的资料和个人档案，分析它对我的申请意味着什么，并核实其中需要确认的事实。');}
  if(action==='delete-evidence'&&confirm('删除这份资料？历史报告及上下文仍保留来源与片段，如需清理请同时删除对应研究。')){await api('/evidence/'+id,{method:'DELETE'});attachments.delete(id);await refresh();renderLibrary();toast('资料已删除');}
  if(action==='add-memory')memoryDialog();
  if(action==='edit-memory')memoryDialog(state.memories.find(x=>x.id===id));
  if(action==='confirm-memory'){const m=state.memories.find(x=>x.id===id);await api('/memories/'+id,{method:'PUT',body:JSON.stringify({text:m.text,status:'confirmed'})});await refresh();renderMemory();toast('已确认这条记忆');}
  if(action==='delete-memory'&&confirm('删除这条长期记忆？')){await api('/memories/'+id,{method:'DELETE'});await refresh();renderMemory();}
  if(action==='add-project')projectDialog();
  if(action==='edit-project')projectDialog(state.projects.find(x=>x.id===id));
  if(action==='delete-project'&&confirm('移除这个收藏项目？')){await api('/projects/'+id,{method:'DELETE'});projectSelection.delete(id);await refresh();renderProjects();}
  if(action==='research-project'){const p=state.projects.find(x=>x.id===id);await fillQuestion(`请结合我的背景调查 ${p.name}，核对申请要求、培养内容和公开毕业去向，给出有证据的建议。\n项目链接：${p.url||'待查找'}\n我的笔记：${p.notes||'无'}`);}
  if(action==='compare-projects'){const selected=state.projects.filter(x=>projectSelection.has(x.id));if(selected.length<2){toast('请至少选择两个项目');return;}await fillQuestion(`请结合我的个人背景与目标，比较以下项目的申请匹配、实际课程、毕业去向和成本，列出有来源的取舍建议和未知事项：\n${selected.map(p=>p.name+' '+p.url+'\n'+p.notes).join('\n\n')}`);}
  if(action==='test-model'||action==='test-search'){target.disabled=true;await saveSettings();const result=await api(action==='test-model'?'/settings/test':'/settings/test-search',{method:'POST'});toast(result.message);renderSettings();}
  if(action==='cancel-run'){target.disabled=true;await api('/runs/'+id+'/cancel',{method:'POST'});await renderRun();}
  if(action==='resume-run'){target.disabled=true;await api('/runs/'+id+'/resume',{method:'POST'});await new Promise(r=>setTimeout(r,100));await renderRun();}
  if(action==='delete-run'&&confirm('删除这个研究及其历史上下文？资料库中的证据会保留。')){await api('/runs/'+id,{method:'DELETE'});await refresh();renderHistory();}
 }catch(error){toast(error.message);}finally{target.disabled=false;}
});
document.addEventListener('change',e=>{const t=e.target;if(t.dataset.attachment){if(t.checked&&attachments.size>=12){t.checked=false;toast('每次最多选择 12 份资料');return;}t.checked?attachments.add(t.dataset.attachment):attachments.delete(t.dataset.attachment);const label=$('#attach-label');if(label)label.textContent=attachments.size?attachments.size+' 份已选择':'';}if(t.dataset.project)t.checked?projectSelection.add(t.dataset.project):projectSelection.delete(t.dataset.project);});
document.addEventListener('input',e=>{if(e.target.id==='library-filter')renderLibraryList(e.target.value);});
document.addEventListener('submit',async e=>{
 e.preventDefault();const form=e.target,submit=$('[type=submit]',form);const originalLabel=submit?.textContent;if(submit)submit.disabled=true;
 try {
  const data=Object.fromEntries(new FormData(form));
  if(form.id==='resume-upload'){
   const file=$('[name=file]',form).files[0];if(!file||file.size>5*1024*1024)throw new Error('请选择 5 MB 以内的 PDF');
   submit.textContent='正在提取文字…';
   const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});
   const result=await api('/profile/resume/extract',{method:'POST',body:JSON.stringify({pdf_base64:encoded})});
   openDialog('检查简历文字',`<form id="resume-analyze" class="stack"><p>已读取 ${result.pages} 页。点击下方按钮会把这里的文字发送给设置中的模型服务。可先删除姓名、邮箱、电话等不需要的信息；不会附带现有档案。</p>${result.warnings.map(x=>`<p class="help-note">${esc(x)}</p>`).join('')}${textarea('提取文字（可编辑）','text',result.text)}<p class="help-note">${state.settings.model?'模型：'+esc(state.settings.model):'尚未配置模型，请先关闭此窗口并到设置连接模型。'}</p><button type="submit" class="btn primary" ${state.settings.model?'':'disabled'}>发送给模型并解析</button></form>`);
  }
  if(form.id==='resume-analyze'){
   submit.textContent='模型正在解析，请稍候…';
   const result=await api('/profile/resume/analyze',{method:'POST',body:JSON.stringify({text:data.text})});
   resumeReview(result);
  }
  if(form.id==='resume-review'){
   let count=0;for(const key of Object.keys(resumeLabels)){if(data['select_'+key]){const field=$('#profile-form [name="'+key+'"]');if(field){field.value=data[key];count++;}}}
   if(!count)throw new Error('请先勾选要填入的字段');
   $('#dialog').close();toast('已填入 '+count+' 个字段，请检查后保存档案');
  }
  if(form.id==='profile-form'){await api('/profile',{method:'PUT',body:JSON.stringify(data)});await refresh();renderProfile();toast('个人档案已保存');}
  if(form.id==='settings-form'){await saveSettings();renderSettings();toast('设置已保存');}
  if(form.classList.contains('social-config-form')){
   await api('/social/'+form.dataset.platform,{method:'PUT',body:JSON.stringify({enabled:$('[name=enabled]',form).checked,interval_seconds:Number(data.interval_seconds),daily_limit:Number(data.daily_limit)})});
   await refresh();renderSocial();toast('平台采集配置已保存');
  }
  if(form.classList.contains('social-search-form')){
   const result=await api('/social/'+form.dataset.platform+'/search',{method:'POST',body:JSON.stringify(data)});
   await refresh();renderSocial();toast(`已保存 ${result.count} 条搜索结果，可在资料库继续查看或用于研究`);
  }
  if(form.classList.contains('social-read-form')){
   await api('/social/'+form.dataset.platform+'/read',{method:'POST',body:JSON.stringify(data)});
   await refresh();renderSocial();toast('页面可见正文已保存到资料库');
  }
  if(form.id==='research-form'){const run=await api('/runs',{method:'POST',body:JSON.stringify({question:data.question,evidence_ids:[...attachments],parent_id:currentRun})});attachments.clear();await refresh();location.hash='run/'+run.id;}
  if(form.id==='import-form'){
   if(form.dataset.mode==='url')await api('/evidence/fetch',{method:'POST',body:JSON.stringify({url:data.url})});
   else {if(form.dataset.mode==='pdf'){const file=$('[name=file]',form).files[0];if(!file||file.size>5*1024*1024)throw new Error('请选择 5 MB 以内的 PDF');data.pdf_base64=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=()=>reject(new Error('文件读取失败'));r.readAsDataURL(file);});delete data.file;}await api('/evidence',{method:'POST',body:JSON.stringify(data)});}
   $('#dialog').close();await refresh();renderLibrary();toast('资料已保存');
  }
  if(form.id==='memory-form'){await api('/memories'+(form.dataset.id?'/'+form.dataset.id:''),{method:form.dataset.id?'PUT':'POST',body:JSON.stringify({...data,status:'confirmed'})});$('#dialog').close();await refresh();renderMemory();toast('记忆已保存');}
  if(form.id==='project-form'){await api('/projects'+(form.dataset.id?'/'+form.dataset.id:''),{method:form.dataset.id?'PUT':'POST',body:JSON.stringify(data)});$('#dialog').close();await refresh();renderProjects();toast('项目已保存');}
 }catch(error){toast(error.message);}finally{if(submit){submit.disabled=false;submit.textContent=originalLabel;}}
});
$('#dialog').addEventListener('click',e=>{if(e.target===$('#dialog'))$('#dialog').close();});
window.addEventListener('hashchange',()=>{if(state)route();});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'&&e.target.closest('#research-form')){e.preventDefault();$('#research-form').requestSubmit();}});
refresh().then(route).catch(error=>{$('#main').innerHTML=empty('暂时无法连接工作空间',error.message,'settings');});
