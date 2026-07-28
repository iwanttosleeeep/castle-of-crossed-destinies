import { FormEvent, useMemo, useState } from 'react'

type Fact = { id:string; label:string; value:string; time_sensitive:boolean; source_span?:string|null; extraction_confidence?:number|null }
type Extraction = { system_id:string; display_name:string; filename:string; extracted_characters:number; source_bytes?:number; extraction_engine?:string; facts:Fact[]; source_commentary:string[]; warnings:string[]; confirmed:boolean }
type Claim = { id:string; system_id:string; neutral_statement:string; statement:string; themes:string[]; evidence_ids:string[]; rule_ids:string[]; caveat:string; counter_reading:string; confidence:number; specificity:number; barnum_risk:number }
type ChamberReport = { system_id:string; display_name:string; claims:Claim[]; sections:Record<string,string[]>; abstentions:string[]; warning?:string|null }
type Finding = { id:string; title:string; type:string; theme:string; claim_ids:string[]; systems:string[]; agreement_strength?:number|null; explanation:string; open_question:string }
type Hearing = { id:string; question:string; answers:any[]; challenges:any[]; rebuttals:any[]; summary:any }
type CaseData = { case_id:string; profile:any; systems:string[]; status:string; extractions:Record<string,Extraction>; confirmed_facts:Record<string,Fact[]>; reports:Record<string,ChamberReport>; tribunal?:{findings:Finding[];summary:string;counts:Record<string,number>;disclaimer:string}|null; debates:Hearing[]; report_warnings?:string[] }

const systems = [
  ['bazi', 'BaZi 八字', '四柱 · 五行 · 十神'],
  ['ziwei', 'Zi Wei Dou Shu', '宫位 · 星曜 · 四化'],
  ['western', 'Western Astrology', '行星 · 宫位 · 相位'],
  ['jyotish', 'Jyotish 印占', 'Lagna · Graha · Dasha'],
  ['numerology', 'Numerology 数秘', '显式数值 · 传统标注'],
  ['human_design', 'Human Design', 'Type · Authority · Centers'],
  ['dreamspell', 'Dreamspell', 'Kin · Tone · Solar Seal'],
] as const

const themeNames:Record<string,string> = {
  identity_orientation:'核心结构', decision_style:'决策方式', thinking_communication:'思考与沟通',
  relationships_boundaries:'关系与边界', work_creation:'工作与创造', resources_stewardship:'资源与管理',
  stress_adaptation:'压力与适应', change_timing:'变化与时机', meaning_imagination:'意义与想象',
}

export default function App() {
  const [stage, setStage] = useState<'entry'|'review'|'report'>('entry')
  const [selected, setSelected] = useState<string[]>(systems.map(([id]) => id))
  const [files, setFiles] = useState<Record<string,File|null>>({})
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('deepseek-v4-flash')
  const [caseData, setCaseData] = useState<CaseData|null>(null)
  const [caseToken, setCaseToken] = useState('')
  const [restoreId, setRestoreId] = useState('')
  const [restoreToken, setRestoreToken] = useState('')
  const [loading, setLoading] = useState('')
  const [error, setError] = useState('')
  const insecureRemote = !window.isSecureContext && !['localhost','127.0.0.1'].includes(window.location.hostname)

  const providerHeaders = () => {
    const headers:Record<string,string> = {'X-DeepSeek-Model':model}
    if (apiKey) headers['X-DeepSeek-Key'] = apiKey
    if (caseToken) headers['X-Case-Token'] = caseToken
    return headers
  }

  async function startCase(event:FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('')
    const missing = selected.filter(id => !files[id])
    if (missing.length) return setError(`请为每个已开启的体系上传报告：${missing.map(systemName).join('、')}`)
    setLoading('正在建立案件…')
    const form = new FormData(event.currentTarget)
    try {
      const create = await api('/api/cases', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({systems:selected, profile:{display_name:optionalFormValue(form,'name'),birth_date:optionalFormValue(form,'date'),birth_time:optionalFormValue(form,'time'),birthplace_text:optionalFormValue(form,'place'),timezone_name:optionalFormValue(form,'timezone'),time_precision:form.get('precision')||'unknown'}})})
      setCaseToken(create.resume_token)
      const token = create.resume_token as string
      const extractions:Extraction[] = []
      for (let index=0; index<selected.length; index++) {
        const id=selected[index]
        setLoading(`读取并抽取 ${systemName(id)}（${index+1}/${selected.length}）…`)
        const body = new FormData(); body.append('file', files[id] as File)
        extractions.push(await api(`/api/cases/${create.case_id}/sources/${id}`, {method:'POST', headers:{...providerHeaders(), 'X-Case-Token':token}, body}))
      }
      const next = {...create, extractions:Object.fromEntries(extractions.map((item:Extraction) => [item.system_id,item]))}
      setCaseData(next); setStage('review'); scrollTo('review')
    } catch (caught) { setError(messageOf(caught)) } finally { setLoading('') }
  }

  async function confirmAndGenerate() {
    if (!caseData) return
    const empty = caseData.systems.filter(id => !(caseData.extractions[id]?.facts.length))
    if (empty.length) return setError(`这些报告没有可确认事实：${empty.map(systemName).join('、')}。请添加事实或重新上传。`)
    setError(''); setLoading('正在封存用户确认的事实…')
    try {
      await Promise.all(caseData.systems.map(id => api(`/api/cases/${caseData.case_id}/facts/${id}`, {method:'PUT',headers:{...providerHeaders(),'Content-Type':'application/json'},body:JSON.stringify({facts:caseData.extractions[id].facts})})))
      setLoading('七间密室正在独立撰写报告；随后召开 Tribunal…')
      const assembled = await api(`/api/cases/${caseData.case_id}/reports`, {method:'POST',headers:providerHeaders()})
      setCaseData(assembled); setStage('report'); scrollTo('report')
    } catch (caught) { setError(messageOf(caught)) } finally { setLoading('') }
  }

  async function restoreCase(event:FormEvent) {
    event.preventDefault(); setError(''); setLoading('正在恢复案件…')
    try {
      const restored = await api(`/api/cases/${restoreId.trim()}`, {headers:{'X-Case-Token':restoreToken.trim()}})
      setCaseToken(restoreToken.trim()); setCaseData(restored); setSelected(restored.systems)
      setStage(Object.keys(restored.reports || {}).length ? 'report' : 'review'); scrollTo(Object.keys(restored.reports || {}).length ? 'report' : 'review')
    } catch (caught) { setError(messageOf(caught)) } finally { setLoading('') }
  }

  function updateFacts(systemId:string, facts:Fact[]) {
    if (!caseData) return
    setCaseData({...caseData,extractions:{...caseData.extractions,[systemId]:{...caseData.extractions[systemId],facts}}})
  }

  async function uploadToExisting(systemId:string, file:File) {
    if (!caseData) return
    setError(''); setLoading(`正在读取 ${systemName(systemId)}…`)
    try {
      const body=new FormData(); body.append('file',file)
      const extraction=await api(`/api/cases/${caseData.case_id}/sources/${systemId}`,{method:'POST',headers:providerHeaders(),body})
      setCaseData({...caseData,extractions:{...caseData.extractions,[systemId]:extraction},reports:{},tribunal:null})
    } catch(caught){setError(messageOf(caught))} finally{setLoading('')}
  }

  return <main>
    <nav><span className="site-title">THE CASTLE OF CROSSED DESTINIES</span><a href="#method">Method</a></nav>
    <section className="hero"><p className="eyebrow">SEVEN SEALED CHAMBERS · ONE TRIBUNAL</p><h1><em>THE CASTLE OF<br/>CROSSED DESTINIES</em></h1><p className="lede">上传你已有的七套报告。城堡先只抽取盘面事实，等你逐项确认；七间密室彼此隔离作证，最后才在宴会厅相互质询。</p><div className="rule"/><p className="note">Files are transient · API keys are never stored · Every claim must cite evidence</p><div className="castle-card"><img src="/castle-card.jpg" alt="The Castle of Crossed Destinies card"/></div></section>

    <section className="entry" id="entry"><div><p className="eyebrow">I. OPEN A CASE</p><h2>Bring your seven dossiers.</h2><p>每个体系分别上传 PDF、TXT 或图片。上传阶段只做文字识别与事实抽取，不生成性格、命运或建议。</p><RestoreForm id={restoreId} token={restoreToken} setId={setRestoreId} setToken={setRestoreToken} submit={restoreCase}/></div>
      <form onSubmit={startCase}><p className="optional-profile-note">基础资料均为可选项。报告里已有的信息不必重复填写；留空不会影响文件抽取。</p><label>姓名或昵称 <small>可选</small><input name="name" placeholder="可留空"/></label><div className="twocol"><label>出生日期 <small>可选</small><input name="date" type="date"/></label><label>出生时间 <small>可选</small><input name="time" type="time"/></label></div><label>出生地点 <small>可选</small><input name="place" placeholder="可留空"/></label><div className="twocol"><label>IANA 时区 <small>可选</small><input name="timezone" placeholder="例如 Asia/Shanghai；可留空"/></label><label>时间精度 <small>可选</small><select name="precision" defaultValue="unknown"><option value="unknown">未知 / 未填写</option><option value="exact">精确</option><option value="approximate">约略</option></select></label></div>
        <div className="key-panel"><label>DeepSeek API Key · 抽取、分析与辩论<input type="password" autoComplete="off" value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="sk-...（只在页面内存）"/></label><label>模型<select value={model} onChange={e=>setModel(e.target.value)}><option value="deepseek-v4-flash">V4 Flash</option><option value="deepseek-v4-pro">V4 Pro</option></select></label>{insecureRemote&&<p className="http-key-warning">⚠ 当前页面使用 HTTP。为了方便测试，Castle 仍允许填写并发送 Key，但传输过程不受 HTTPS 加密保护。请只短暂使用测试 Key，并尽快配置 HTTPS。</p>}<p>上传阶段，DeepSeek 会读取从 TXT 或文本 PDF 临时取得的文字，只抽取显式盘面事实；原文件与完整文本均不保存。用户确认后，报告、Tribunal 与辩论只读取确认事实。服务器已配置 Key 时可留空。</p></div>
        <fieldset><legend>Open chambers & attach reports</legend><div className="systems upload-systems">{systems.map(([id,title,detail]) => <div className={selected.includes(id)?'system upload active':'system upload'} key={id}><button type="button" onClick={()=>setSelected(v=>v.includes(id)?v.filter(x=>x!==id):[...v,id])}><b>{title}</b><small>{detail}</small><i>{selected.includes(id)?'✓':'+'}</i></button>{selected.includes(id)&&<label className="file"><input type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={e=>setFiles({...files,[id]:e.target.files?.[0]||null})}/><span>{files[id]?.name || '选择 PDF / TXT / 图片'}</span></label>}</div>)}</div></fieldset>
        {error&&<p className="error">{error}</p>}<button className="enter" disabled={!!loading||!selected.length}>{loading||'CREATE CASE & EXTRACT FACTS'}</button>
      </form>
    </section>

    {caseData && <CasePassport data={caseData} token={caseToken}/>}
    {stage==='review' && caseData && <Review data={caseData} updateFacts={updateFacts} upload={uploadToExisting} submit={confirmAndGenerate} loading={loading} error={error}/>}
    {stage==='report' && caseData && <ReportView data={caseData} token={caseToken} providerHeaders={providerHeaders} setData={setCaseData} apiKey={apiKey} setApiKey={setApiKey} loading={loading} setLoading={setLoading} error={error} setError={setError}/>}
    <section className="method" id="method"><p className="eyebrow">THE METHOD</p><h2>DeepSeek extracts. Seven chambers testify.</h2><p>DeepSeek 在上传阶段只从本地解析出的文字中抽取事实；七间 chamber 随后只看你确认后的事实。角色口吻在独立的第二遍添加，Tribunal 和最终主持人永远只读取中性证词。</p></section><footer>THE CASTLE OF CROSSED DESTINIES <span>Symbolic interpretation—not proof, diagnosis, or professional advice.</span></footer>
  </main>
}

function RestoreForm({id,token,setId,setToken,submit}:any) { return <form className="restore" onSubmit={submit}><p className="eyebrow">RESTORE A CASE</p><input value={id} onChange={e=>setId(e.target.value)} placeholder="Case ID" required/><input type="password" value={token} onChange={e=>setToken(e.target.value)} placeholder="Resume token" required/><button>RESTORE</button></form> }

function CasePassport({data,token}:{data:CaseData;token:string}) { const [copied,setCopied]=useState(false); return <section className="passport"><div><p className="eyebrow">CASE PASSPORT</p><h3>{data.case_id}</h3><p>恢复令牌只显示在首次创建时。请现在保存；服务器只保存它的哈希。</p></div><code>{token || '令牌已在创建时发放'}</code>{token&&<button onClick={()=>navigator.clipboard.writeText(`${data.case_id}\n${token}`).then(()=>setCopied(true))}>{copied?'COPIED':'COPY ID + TOKEN'}</button>}</section> }

function Review({data,updateFacts,upload,submit,loading,error}:{data:CaseData;updateFacts:(id:string,facts:Fact[])=>void;upload:(id:string,file:File)=>void;submit:()=>void;loading:string;error:string}) { return <section className="review" id="review"><header><p className="eyebrow">II. USER CONFIRMATION</p><h2>Check every extracted fact.</h2><p>这一步决定后续所有证词的证据边界。修正 OCR 错字，删除“你很敏感”一类解释文字；需要时可手动补充报告中明确写出的事实。</p></header><div className="review-grid">{data.systems.map(id=>data.extractions[id]?<FactEditor key={id} extraction={data.extractions[id]} onChange={facts=>updateFacts(id,facts)} onUpload={file=>upload(id,file)}/>:<MissingUpload key={id} systemId={id} onUpload={file=>upload(id,file)}/>)}</div>{error&&<p className="error centered">{error}</p>}<button className="enter assemble" onClick={submit} disabled={!!loading}>{loading||'USER CONFIRMED · ASSEMBLE SEVEN REPORTS'}</button></section> }

function FactEditor({extraction,onChange,onUpload}:{extraction:Extraction;onChange:(facts:Fact[])=>void;onUpload:(file:File)=>void}) { const add=()=>onChange([...extraction.facts,{id:`${extraction.system_id}.manual-${Date.now()}`,label:'',value:'',time_sensitive:!['numerology','dreamspell'].includes(extraction.system_id),source_span:'用户根据原报告手动补充',extraction_confidence:1}]); return <article className="fact-editor"><div className="editor-head"><div><p>{extraction.display_name}</p><small>{extraction.filename} · {engineName(extraction.extraction_engine)} · {formatSize(extraction.source_bytes||0)}</small></div><span>{extraction.facts.length} FACTS</span></div><label className="replace-file">重新上传<input type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={e=>e.target.files?.[0]&&onUpload(e.target.files[0])}/></label>{extraction.warnings.map(item=><p className="warning" key={item}>{item}</p>)}{extraction.facts.map((fact,index)=><div className="fact-row" key={fact.id}><input aria-label="事实名称" value={fact.label} onChange={e=>onChange(extraction.facts.map((x,i)=>i===index?{...x,label:e.target.value}:x))}/><textarea aria-label="事实内容" value={fact.value} onChange={e=>onChange(extraction.facts.map((x,i)=>i===index?{...x,value:e.target.value}:x))}/><button title="删除" onClick={()=>onChange(extraction.facts.filter((_,i)=>i!==index))}>×</button>{fact.source_span&&<small>{fact.source_span}</small>}</div>)}<button className="add-fact" onClick={add}>+ ADD EXPLICIT FACT</button>{extraction.source_commentary.length>0&&<details><summary>已排除的原报告解释（{extraction.source_commentary.length}）</summary>{extraction.source_commentary.map(item=><p key={item}>{item}</p>)}</details>}</article> }
function MissingUpload({systemId,onUpload}:{systemId:string;onUpload:(file:File)=>void}) { return <article className="fact-editor missing-upload"><p>{systemName(systemId)}</p><small>这份报告尚未上传，或上次上传在网络中断前没有完成。</small><label>继续上传 PDF / TXT / 图片<input type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={e=>e.target.files?.[0]&&onUpload(e.target.files[0])}/></label></article> }

function ReportView({data,providerHeaders,setData,apiKey,setApiKey,loading,setLoading,error,setError}:{data:CaseData;token:string;providerHeaders:()=>Record<string,string>;setData:(d:CaseData)=>void;apiKey:string;setApiKey:(v:string)=>void;loading:string;setLoading:(v:string)=>void;error:string;setError:(v:string)=>void}) {
  const claims = useMemo(()=>Object.values(data.reports).flatMap(report=>report.claims),[data.reports]); const claimMap=useMemo(()=>Object.fromEntries(claims.map(c=>[c.id,c])),[claims]); const [question,setQuestion]=useState('')
  async function regenerate() { setError(''); setLoading('正在用已确认事实重新生成七份报告与 Tribunal…'); try { const assembled=await api(`/api/cases/${data.case_id}/reports`,{method:'POST',headers:providerHeaders()}); setData(assembled); scrollTo('report') } catch(caught){setError(messageOf(caught))} finally{setLoading('')} }
  async function ask(event:FormEvent) { event.preventDefault(); setError(''); setLoading('七间密室独立回答；主持人正在提出一次质询…'); try { const hearing=await api(`/api/cases/${data.case_id}/debates`,{method:'POST',headers:{...providerHeaders(),'Content-Type':'application/json'},body:JSON.stringify({question})}); setData({...data,debates:[...data.debates,hearing]}); setQuestion(''); setTimeout(()=>document.querySelector('#hearing-latest')?.scrollIntoView({behavior:'smooth'}),80) } catch(caught){setError(messageOf(caught))} finally{setLoading('')} }
  return <section id="report" className="report"><header><div><p className="eyebrow">III. SEVEN GENERAL REPORTS</p><h2>The assembled testimony</h2></div><div className="badge skills_ready">USER CONFIRMED<small>{claims.length} admissible claims</small></div></header>{data.report_warnings?.map(item=><p className="warning disclosure" key={item}>{item}</p>)}
    <div className="regenerate-panel"><div><b>已确认事实会被保留</b><p>重新生成会使用当前版本的七套 Skills，并替换旧报告与 Tribunal；不需要重新上传原文件。</p></div>{!apiKey&&<label>DeepSeek API Key（服务器已配置时可留空）<input type="password" value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="sk-...（只在页面内存）"/></label>}<button type="button" onClick={regenerate} disabled={!!loading}>{loading||'重新生成七份报告'}</button></div>
    {error&&<p className="error">{error}</p>}
    <div className="report-grid">{data.systems.map(id=><GeneralReport key={id} report={data.reports[id]}/>)}</div>
    <Tribunal tribunal={data.tribunal} claimMap={claimMap}/>
    <section className="hearing"><p className="eyebrow">V. CROSS-EXAMINATION</p><h2>Ask the seven chambers.</h2><p>每间 chamber 先独立回答；主持人只针对真实矛盾提出一次 challenge；被质询方各有一次 rebuttal，随后结案总结。</p>{!apiKey&&<label>本轮 DeepSeek API Key（仍不保存）<input type="password" value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="服务器未配置时填写 sk-..."/></label>}<form onSubmit={ask}><textarea value={question} onChange={e=>setQuestion(e.target.value)} required minLength={3} placeholder="例如：面对职业选择时，七套体系分别看到了什么？哪些判断真正冲突？"/><button className="enter" disabled={!!loading}>{loading||'CONVENE ONE-ROUND HEARING'}</button></form>{error&&<p className="error">{error}</p>}{data.debates.map((hearing,index)=><HearingView hearing={hearing} latest={index===data.debates.length-1} key={hearing.id}/>)}</section>
  </section>
}

function GeneralReport({report}:{report:ChamberReport}) { if(!report)return null; const map=Object.fromEntries(report.claims.map(c=>[c.id,c])); return <article className="general-report"><div className="report-title"><p>{report.display_name}</p><span>{report.claims.length} CLAIMS</span></div>{report.warning&&<p className="warning">{report.warning}</p>}{Object.entries(report.sections).map(([theme,ids])=><section key={theme}><h4>{themeNames[theme]||theme}</h4>{ids.map(id=><ClaimCard claim={map[id]} key={id}/>)}</section>)}{report.claims.length===0&&<p className="abstain">本室暂未形成通过引用校验的解读，请重新生成或检查已确认事实。</p>}{report.abstentions.length>0&&report.claims.length>0&&<details className="abstention-summary"><summary>本室未覆盖的主题（{report.abstentions.length}）</summary><p>{report.abstentions.map(theme=>themeNames[theme]||theme).join(' · ')}</p></details>}</article> }
function ClaimCard({claim}:{claim:Claim}) { return <div className="claim"><p>{claim.statement}</p>{claim.statement!==claim.neutral_statement&&<details><summary>中性原证词</summary><p>{claim.neutral_statement}</p></details>}<small>Evidence {claim.evidence_ids.join(' · ')}<br/>Rules {claim.rule_ids.join(' · ')}</small><div className="claim-meta"><span>confidence {Math.round(claim.confidence*100)}%</span><span>Barnum {Math.round(claim.barnum_risk*100)}%</span></div><details><summary>限制与反向解读</summary><p>{claim.caveat}</p><p>{claim.counter_reading}</p></details></div> }

function Tribunal({tribunal,claimMap}:{tribunal:CaseData['tribunal'];claimMap:Record<string,Claim>}) { return <section className="tribunal-v2"><div><p className="eyebrow">IV. THE TRIBUNAL</p><h2>Consensus is not truth.</h2><p>{tribunal?.summary}</p><small>{tribunal?.disclaimer}</small></div><div className="findings">{tribunal?.findings.map(f=><article className={`finding ${f.type}`} key={f.id}><div><span>{f.type.replaceAll('_',' ')}</span><h3>{f.title}</h3></div>{f.agreement_strength!=null&&<strong>{f.agreement_strength}<small>/100 narrative agreement</small></strong>}<p>{f.explanation}</p><small>{f.systems.map(systemName).join(' × ')}</small><details><summary>查看参与证词</summary>{f.claim_ids.map(id=><p key={id}>{claimMap[id]?.neutral_statement}</p>)}</details>{f.open_question&&<blockquote>{f.open_question}</blockquote>}</article>)}</div></section> }

function HearingView({hearing,latest}:{hearing:Hearing;latest:boolean}) { return <article className="hearing-result" id={latest?'hearing-latest':undefined}><p className="eyebrow">{hearing.id}</p><h3>“{hearing.question}”</h3><div className="answers">{hearing.answers.map(a=><div key={a.system_id}><b>{systemName(a.system_id)}</b><p>{a.statement}</p><small>{a.abstained?'ABSTAINED':`Evidence ${a.evidence_ids.join(' · ')}`}</small></div>)}</div>{hearing.challenges.length>0&&<div className="challenges"><h4>Moderator challenges</h4>{hearing.challenges.map((c,i)=><p key={i}><b>{systemName(c.target_system)}:</b> {c.question}</p>)}</div>}{hearing.rebuttals.map(r=><div className="rebuttal" key={r.system_id}><span>{r.disposition}</span><b>{systemName(r.system_id)} rebuttal</b><p>{r.statement}</p></div>)}<div className="verdict"><h4>One-round summary</h4><SummaryList title="仍然一致" items={hearing.summary.aligned}/><SummaryList title="仍有冲突" items={hearing.summary.still_conflicted}/><SummaryList title="已收窄或让步" items={hearing.summary.resolved_or_narrowed}/><SummaryList title="无法回答" items={hearing.summary.unanswerable}/><p>{hearing.summary.closing}</p></div></article> }
function SummaryList({title,items}:{title:string;items:string[]}) { return items?.length?<div><b>{title}</b><ul>{items.map(item=><li key={item}>{item}</li>)}</ul></div>:null }

function systemName(id:string) { return systems.find(([system])=>system===id)?.[1] || id.replaceAll('_',' ') }
function engineName(engine?:string) { return ({deepseek_text:'Local text + DeepSeek',manual_required:'Manual review'} as Record<string,string>)[engine||'']||'Legacy extraction' }
function formatSize(bytes:number) { return bytes?`${Math.max(1,Math.round(bytes/1024)).toLocaleString()} KB`:'size unavailable' }
function optionalFormValue(form:FormData,name:string) { const value=String(form.get(name)||'').trim(); return value||null }
function scrollTo(id:string) { setTimeout(()=>document.querySelector(`#${id}`)?.scrollIntoView({behavior:'smooth'}),80) }
async function api(url:string,init?:RequestInit) { const response=await fetch(url,init); const body=await response.json().catch(()=>({})); if(!response.ok) throw new Error(body.detail||`HTTP ${response.status}`); return body }
function messageOf(caught:unknown) { return caught instanceof Error?caught.message:'无法连接到后端，请检查 FastAPI、反向代理或服务器日志。' }
