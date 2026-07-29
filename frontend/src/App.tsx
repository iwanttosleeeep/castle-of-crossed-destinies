import { FormEvent, ReactNode, useState } from 'react'

type Fact = { id:string; label:string; value:string; time_sensitive:boolean; source_span?:string|null; extraction_confidence?:number|null }
type Extraction = { system_id:string; display_name:string; filename:string; extracted_characters:number; source_bytes?:number; extraction_engine?:string; facts:Fact[]; source_commentary:string[]; warnings:string[]; confirmed:boolean }
type ChamberReport = { system_id:string; display_name:string; text?:string|null; free_text?:string|null; warning?:string|null }
type GuidedTestimony = { system_id:string; text:string }
type Hearing = { id:string; question:string; guided_answers?:GuidedTestimony[]; guided_rebuttals?:GuidedTestimony[]; guided_summary?:string; warnings?:string[] }
type Tribunal = { summary:string; disclaimer:string }
type CaseData = { case_id:string; systems:string[]; status:string; extractions:Record<string,Extraction>; confirmed_facts:Record<string,Fact[]>; reports:Record<string,ChamberReport>; tribunal?:Tribunal|null; debates:Hearing[]; report_warnings?:string[] }

const systems = [
  ['bazi', 'BaZi 八字', '四柱 · 五行 · 十神'],
  ['ziwei', 'Zi Wei Dou Shu', '宫位 · 星曜 · 四化'],
  ['western', 'Western Astrology', '行星 · 宫位 · 相位'],
  ['jyotish', 'Jyotish 印占', 'Lagna · Graha · Dasha'],
  ['numerology', 'Numerology 数秘', '显式数值 · 传统标注'],
  ['human_design', 'Human Design', 'Type · Authority · Centers'],
  ['dreamspell', 'Dreamspell', 'Kin · Tone · Solar Seal'],
] as const

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
    try {
      const create = await api('/api/cases', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({systems:selected})})
      setCaseToken(create.resume_token)
      const token = create.resume_token as string
      const extractions:Extraction[] = []
      for (let index=0; index<selected.length; index++) {
        const id=selected[index]
        setLoading(`读取并抽取 ${systemName(id)}（${index+1}/${selected.length}）…`)
        const body = new FormData(); body.append('file', files[id] as File)
        extractions.push(await api(`/api/cases/${create.case_id}/sources/${id}`, {method:'POST', headers:{...providerHeaders(), 'X-Case-Token':token}, body}))
      }
      setCaseData({...create, extractions:Object.fromEntries(extractions.map(item => [item.system_id,item]))})
      setStage('review'); scrollTo('review')
    } catch (caught) { setError(messageOf(caught)) } finally { setLoading('') }
  }

  async function confirmAndGenerate() {
    if (!caseData) return
    const empty = caseData.systems.filter(id => !caseData.extractions[id]?.facts.length)
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
      setStage(Object.keys(restored.reports || {}).length ? 'report' : 'review')
      scrollTo(Object.keys(restored.reports || {}).length ? 'report' : 'review')
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
    <section className="hero"><p className="eyebrow">SEVEN SEALED CHAMBERS · ONE TRIBUNAL</p><h1><em>THE CASTLE OF<br/>CROSSED DESTINIES</em></h1><p className="lede">上传你已有的七套报告。城堡先只抽取盘面事实，等你逐项确认；七间密室彼此隔离作证，最后才在宴会厅相互质询。</p><div className="rule"/><p className="note">Files are transient · API keys are never stored · Readings stay inside confirmed facts</p><div className="castle-card"><img src="/castle-card.jpg" alt="The Castle of Crossed Destinies card"/></div></section>

    <section className="entry" id="entry"><div><p className="eyebrow">I. OPEN A CASE</p><h2>Bring your seven dossiers.</h2><p>只需选择体系并上传 PDF、TXT 或图片；姓名、生日、出生时间、地点与时区都不需要填写。</p><RestoreForm id={restoreId} token={restoreToken} setId={setRestoreId} setToken={setRestoreToken} submit={restoreCase}/></div>
      <form onSubmit={startCase}>
        <div className="key-panel"><label>DeepSeek API Key<input type="password" autoComplete="off" value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="sk-...（只在页面内存）"/></label><label>模型<select value={model} onChange={e=>setModel(e.target.value)}><option value="deepseek-v4-flash">V4 Flash</option><option value="deepseek-v4-pro">V4 Pro</option></select></label>{insecureRemote&&<p className="http-key-warning">⚠ 当前页面使用 HTTP，Key 的传输没有 HTTPS 加密。请只短暂使用可撤销的测试 Key。</p>}<p>结构化 TXT/JSON 由服务器直接解析；其他文本由 DeepSeek 抽取显式事实。原文件、完整文本与 API Key 均不保存。</p></div>
        <fieldset><legend>选择密室并上传报告</legend><div className="systems upload-systems">{systems.map(([id,title,detail]) => <div className={selected.includes(id)?'system upload active':'system upload'} key={id}><button type="button" onClick={()=>setSelected(value=>value.includes(id)?value.filter(item=>item!==id):[...value,id])}><b>{title}</b><small>{detail}</small><i>{selected.includes(id)?'✓':'+'}</i></button>{selected.includes(id)&&<label className="file"><input type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={e=>setFiles({...files,[id]:e.target.files?.[0]||null})}/><span>{files[id]?.name || '选择 PDF / TXT / 图片'}</span></label>}</div>)}</div></fieldset>
        {error&&<p className="error">{error}</p>}<button className="enter" disabled={!!loading||!selected.length}>{loading||'CREATE CASE & EXTRACT FACTS'}</button>
      </form>
    </section>

    {caseData && <CasePassport data={caseData} token={caseToken}/>}
    {stage==='review' && caseData && <Review data={caseData} updateFacts={updateFacts} upload={uploadToExisting} submit={confirmAndGenerate} loading={loading} error={error}/>}
    {stage==='report' && caseData && <ReportView data={caseData} providerHeaders={providerHeaders} setData={setCaseData} review={()=>{setStage('review');scrollTo('review')}} apiKey={apiKey} setApiKey={setApiKey} loading={loading} setLoading={setLoading} error={error} setError={setError}/>}
    <section className="method" id="method"><p className="eyebrow">THE METHOD</p><h2>Castle parses. Seven chambers testify.</h2><p>报告先被整理成可核对事实；确认后，每间密室只读取自己的资料和轻量人物 Skill。Tribunal 比较独立报告，提问阶段再进行一次回答、rebuttal 与总结。</p></section><footer>THE CASTLE OF CROSSED DESTINIES <span>Symbolic interpretation—not proof, diagnosis, or professional advice.</span></footer>
  </main>
}

function RestoreForm({id,token,setId,setToken,submit}:any) { return <form className="restore" onSubmit={submit}><p className="eyebrow">RESTORE A CASE</p><input value={id} onChange={e=>setId(e.target.value)} placeholder="Case ID" required/><input type="password" value={token} onChange={e=>setToken(e.target.value)} placeholder="Resume token" required/><button>RESTORE</button></form> }

function CasePassport({data,token}:{data:CaseData;token:string}) { const [copied,setCopied]=useState(false); return <section className="passport"><div><p className="eyebrow">CASE PASSPORT</p><h3>{data.case_id}</h3><p>恢复令牌只显示在首次创建时。请现在保存；服务器只保存它的哈希。</p></div><code>{token || '令牌已在创建时发放'}</code>{token&&<button onClick={()=>navigator.clipboard.writeText(`${data.case_id}\n${token}`).then(()=>setCopied(true))}>{copied?'COPIED':'COPY ID + TOKEN'}</button>}</section> }

function Review({data,updateFacts,upload,submit,loading,error}:{data:CaseData;updateFacts:(id:string,facts:Fact[])=>void;upload:(id:string,file:File)=>void;submit:()=>void;loading:string;error:string}) { return <section className="review" id="review"><header><p className="eyebrow">II. USER CONFIRMATION</p><h2>Check every extracted fact.</h2><p>修正识别错误，删除原报告的解释性句子；需要时可手动补充报告明确写出的盘面事实。</p></header><div className="review-grid">{data.systems.map(id=>data.extractions[id]?<FactEditor key={id} extraction={data.extractions[id]} onChange={facts=>updateFacts(id,facts)} onUpload={file=>upload(id,file)}/>:<MissingUpload key={id} systemId={id} onUpload={file=>upload(id,file)}/>)}</div>{error&&<p className="error centered">{error}</p>}<button className="enter assemble" onClick={submit} disabled={!!loading}>{loading||'USER CONFIRMED · ASSEMBLE REPORTS'}</button></section> }

function FactEditor({extraction,onChange,onUpload}:{extraction:Extraction;onChange:(facts:Fact[])=>void;onUpload:(file:File)=>void}) { const add=()=>onChange([...extraction.facts,{id:`${extraction.system_id}.manual-${Date.now()}`,label:'',value:'',time_sensitive:!['numerology','dreamspell'].includes(extraction.system_id),source_span:'用户根据原报告手动补充',extraction_confidence:1}]); return <article className="fact-editor"><div className="editor-head"><div><p>{extraction.display_name}</p><small>{extraction.filename} · {engineName(extraction.extraction_engine)} · {formatSize(extraction.source_bytes||0)}</small></div><span>{extraction.facts.length} FACTS</span></div><label className="replace-file">重新上传<input type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={e=>e.target.files?.[0]&&onUpload(e.target.files[0])}/></label>{extraction.warnings.map(item=><p className="warning" key={item}>{item}</p>)}{extraction.facts.map((fact,index)=><div className="fact-row" key={fact.id}><input aria-label="事实名称" value={fact.label} onChange={e=>onChange(extraction.facts.map((item,i)=>i===index?{...item,label:e.target.value}:item))}/><textarea aria-label="事实内容" value={fact.value} onChange={e=>onChange(extraction.facts.map((item,i)=>i===index?{...item,value:e.target.value}:item))}/><button title="删除" onClick={()=>onChange(extraction.facts.filter((_,i)=>i!==index))}>×</button>{fact.source_span&&<small>{fact.source_span}</small>}</div>)}<button className="add-fact" onClick={add}>+ ADD EXPLICIT FACT</button>{extraction.source_commentary.length>0&&<details><summary>已排除的原报告解释（{extraction.source_commentary.length}）</summary>{extraction.source_commentary.map(item=><p key={item}>{item}</p>)}</details>}</article> }
function MissingUpload({systemId,onUpload}:{systemId:string;onUpload:(file:File)=>void}) { return <article className="fact-editor missing-upload"><p>{systemName(systemId)}</p><small>这份报告尚未上传，或上次上传在网络中断前没有完成。</small><label>继续上传 PDF / TXT / 图片<input type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={e=>e.target.files?.[0]&&onUpload(e.target.files[0])}/></label></article> }

function ReportView({data,providerHeaders,setData,review,apiKey,setApiKey,loading,setLoading,error,setError}:{data:CaseData;providerHeaders:()=>Record<string,string>;setData:(data:CaseData)=>void;review:()=>void;apiKey:string;setApiKey:(value:string)=>void;loading:string;setLoading:(value:string)=>void;error:string;setError:(value:string)=>void}) {
  const [question,setQuestion]=useState('')
  async function regenerate() { setError(''); setLoading('正在用已确认事实重新生成报告与 Tribunal…'); try { const assembled=await api(`/api/cases/${data.case_id}/reports`,{method:'POST',headers:providerHeaders()}); setData(assembled); scrollTo('report') } catch(caught){setError(messageOf(caught))} finally{setLoading('')} }
  async function ask(event:FormEvent) { event.preventDefault(); setError(''); setLoading('各室正在独立回答、完成一次 rebuttal，并等待主持人总结…'); try { const hearing=await api(`/api/cases/${data.case_id}/debates`,{method:'POST',headers:{...providerHeaders(),'Content-Type':'application/json'},body:JSON.stringify({question})}); setData({...data,debates:[...data.debates,hearing]}); setQuestion(''); setTimeout(()=>document.querySelector('#hearing-latest')?.scrollIntoView({behavior:'smooth'}),80) } catch(caught){setError(messageOf(caught))} finally{setLoading('')} }
  const completed=Object.values(data.reports).filter(report=>report.text||report.free_text).length
  return <section id="report" className="report"><header><div><p className="eyebrow">III. GENERAL REPORTS</p><h2>The assembled testimony</h2></div><div className="badge skills_ready">LIGHT SKILL<small>{completed} natural-language reports</small></div></header>{data.report_warnings?.map(item=><p className="warning disclosure" key={item}>{item}</p>)}
    <div className="regenerate-panel"><div><b>已确认事实会被保留</b><p>重新生成不需要再次上传或确认。</p></div>{!apiKey&&<label>DeepSeek API Key（服务器已配置时可留空）<input type="password" value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="sk-...（只在页面内存）"/></label>}<div className="regenerate-actions"><button type="button" className="secondary" onClick={review} disabled={!!loading}>返回事实确认 / 重新上传</button><button type="button" onClick={regenerate} disabled={!!loading}>{loading||'重新生成报告'}</button></div></div>
    {error&&<p className="error">{error}</p>}
    <div className="report-grid">{data.systems.map(id=><GeneralReport key={id} report={data.reports[id]}/>)}</div>
    <TribunalView tribunal={data.tribunal}/>
    <section className="hearing"><p className="eyebrow">V. CROSS-EXAMINATION</p><h2>Ask the seven chambers.</h2><p>各室先独立回答，再阅读其他第一轮证词并各作一次 rebuttal，最后由主持人总结。</p>{!apiKey&&<label>本轮 DeepSeek API Key（仍不保存）<input type="password" value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="服务器未配置时填写 sk-..."/></label>}<form onSubmit={ask}><textarea value={question} onChange={e=>setQuestion(e.target.value)} required minLength={3} placeholder="例如：面对职业选择时，各体系分别看到了什么？哪些判断真正冲突？"/><button className="enter" disabled={!!loading}>{loading||'CONVENE ONE-ROUND HEARING'}</button></form>{error&&<p className="error">{error}</p>}{data.debates.map((hearing,index)=><GuidedHearingView hearing={hearing} latest={index===data.debates.length-1} key={hearing.id}/>)}</section>
  </section>
}

function GeneralReport({report}:{report:ChamberReport|undefined}) { if(!report)return null; const text=report.text||report.free_text||''; return <article className="general-report"><div className="report-title"><p>{report.display_name}</p><span>GUIDED TEXT</span></div>{report.warning&&<p className="warning">{report.warning}</p>}{text?<MarkdownText text={text} className="report-markdown"/>:<p className="abstain">本室暂未生成正文，请稍后重新生成。</p>}</article> }

function TribunalView({tribunal}:{tribunal?:Tribunal|null}) { return <section className="tribunal-v2"><div><p className="eyebrow">IV. THE TRIBUNAL</p><h2>Consensus is not truth.</h2>{tribunal?.summary&&<MarkdownText text={tribunal.summary}/>}<small>{tribunal?.disclaimer}</small></div></section> }

function GuidedHearingView({hearing,latest}:{hearing:Hearing;latest:boolean}) { return <article className="hearing-result guided-hearing" id={latest?'hearing-latest':undefined}><p className="eyebrow">{hearing.id} · LIGHT SKILL</p><h3>“{hearing.question}”</h3>{hearing.warnings?.map(item=><p className="warning" key={item}>{item}</p>)}<h4>Independent answers</h4><div className="answers">{hearing.guided_answers?.map(answer=><div key={answer.system_id}><b>{systemName(answer.system_id)}</b><MarkdownText text={answer.text}/></div>)}</div><h4>One rebuttal each</h4><div className="guided-rebuttals">{hearing.guided_rebuttals?.map(rebuttal=><div className="rebuttal" key={rebuttal.system_id}><b>{systemName(rebuttal.system_id)} rebuttal</b><MarkdownText text={rebuttal.text}/></div>)}</div><div className="verdict guided-verdict"><h4>Moderator summary</h4>{hearing.guided_summary?<MarkdownText text={hearing.guided_summary}/>:<p>旧版质询没有轻量总结，请重新提问。</p>}</div></article> }

function MarkdownText({text,className=''}:{text:string;className?:string}) {
  const nodes:ReactNode[]=[]; let paragraph:string[]=[]; let listKind:'ul'|'ol'|null=null; let listItems:string[]=[]; let key=0
  const flushParagraph=()=>{if(!paragraph.length)return; const lines=paragraph; paragraph=[]; nodes.push(<p key={key++}>{lines.map((line,index)=><span key={index}>{inlineMarkdown(line)}{index<lines.length-1&&<br/>}</span>)}</p>)}
  const flushList=()=>{if(!listKind||!listItems.length)return; const items=listItems; const kind=listKind; listKind=null; listItems=[]; nodes.push(kind==='ul'?<ul key={key++}>{items.map((item,index)=><li key={index}>{inlineMarkdown(item)}</li>)}</ul>:<ol key={key++}>{items.map((item,index)=><li key={index}>{inlineMarkdown(item)}</li>)}</ol>)}
  for(const rawLine of text.replace(/\r/g,'').split('\n')) {
    const line=rawLine.trim()
    if(!line){flushParagraph();flushList();continue}
    const heading=line.match(/^(#{1,4})\s+(.+)$/)
    const bullet=line.match(/^[-+*]\s+(.+)$/)
    const ordered=line.match(/^\d+[.)]\s+(.+)$/)
    if(heading){flushParagraph();flushList();const level=heading[1].length;const content=inlineMarkdown(heading[2]);nodes.push(level===1?<h2 key={key++}>{content}</h2>:level===2?<h3 key={key++}>{content}</h3>:<h4 key={key++}>{content}</h4>);continue}
    if(bullet||ordered){flushParagraph();const nextKind=bullet?'ul':'ol';if(listKind&&listKind!==nextKind)flushList();listKind=nextKind;listItems.push((bullet||ordered)![1]);continue}
    if(/^(-{3,}|\*{3,})$/.test(line)){flushParagraph();flushList();nodes.push(<hr key={key++}/>);continue}
    if(line.startsWith('>')){flushParagraph();flushList();nodes.push(<blockquote key={key++}>{inlineMarkdown(line.replace(/^>\s?/,''))}</blockquote>);continue}
    flushList();paragraph.push(line)
  }
  flushParagraph();flushList()
  return <div className={`markdown-text ${className}`.trim()}>{nodes}</div>
}

function inlineMarkdown(text:string):ReactNode[] { return text.split(/(\*\*.+?\*\*|__.+?__|`.+?`|\*[^*]+?\*)/g).filter(Boolean).map((token,index)=>token.startsWith('**')&&token.endsWith('**')?<strong key={index}>{token.slice(2,-2)}</strong>:token.startsWith('__')&&token.endsWith('__')?<strong key={index}>{token.slice(2,-2)}</strong>:token.startsWith('`')&&token.endsWith('`')?<code key={index}>{token.slice(1,-1)}</code>:token.startsWith('*')&&token.endsWith('*')?<em key={index}>{token.slice(1,-1)}</em>:token) }

function systemName(id:string) { return systems.find(([system])=>system===id)?.[1] || id.replaceAll('_',' ') }
function engineName(engine?:string) { return ({structured_text:'Deterministic structured parser',deepseek_text:'Local text + DeepSeek',manual_required:'Manual review'} as Record<string,string>)[engine||'']||'Legacy extraction' }
function formatSize(bytes:number) { return bytes?`${Math.max(1,Math.round(bytes/1024)).toLocaleString()} KB`:'size unavailable' }
function scrollTo(id:string) { setTimeout(()=>document.querySelector(`#${id}`)?.scrollIntoView({behavior:'smooth'}),80) }
async function api(url:string,init?:RequestInit) { const response=await fetch(url,init); const body=await response.json().catch(()=>({})); if(!response.ok) throw new Error(body.detail||`HTTP ${response.status}`); return body }
function messageOf(caught:unknown) { return caught instanceof Error?caught.message:'无法连接到后端，请检查 FastAPI、反向代理或服务器日志。' }
