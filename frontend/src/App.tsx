import { FormEvent, ReactNode, useEffect, useState } from 'react'
import BirthChartForm, { BirthInput } from './BirthChartForm'
import AccessPanel, { PaymentMode } from './AccessPanel'

type Fact = { id:string; label:string; value:string; time_sensitive:boolean; source_span?:string|null; extraction_confidence?:number|null }
type Extraction = { system_id:string; display_name:string; filename:string; extracted_characters:number; source_bytes?:number; extraction_engine?:string; facts:Fact[]; source_commentary:string[]; warnings:string[]; confirmed:boolean }
type ChamberReport = { system_id:string; display_name:string; text?:string|null; free_text?:string|null; warning?:string|null }
type GuidedTestimony = { system_id:string; text:string }
type Hearing = { id:string; question:string; guided_answers?:GuidedTestimony[]; guided_rebuttals?:GuidedTestimony[]; guided_summary?:string; warnings?:string[] }
type Tribunal = { summary:string; disclaimer:string }
type Calculation = { input:BirthInput; location:{name:string;countrycode:string;timezone:string}|null; utc:string|null; utc_offset_hours:number|null; dst_hours:number|null; versions:Record<string,string> }
type Job = {id:string;kind:string;state:string;mode:PaymentMode;facts_revision:number;steps:Record<string,{state:string;text:string;error?:string}>}
type CaseData = { case_id:string; systems:string[]; status:string; extractions:Record<string,Extraction>; confirmed_facts:Record<string,Fact[]>; reports:Record<string,ChamberReport>; tribunal?:Tribunal|null; debates:Hearing[]; report_warnings?:string[]; calculation?:Calculation; jobs?:Job[];facts_revision?:number }

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
  const [entryMode, setEntryMode] = useState<'calculate'|'upload'>('calculate')
  const [selected, setSelected] = useState<string[]>(systems.map(([id]) => id))
  const [files, setFiles] = useState<Record<string,File|null>>({})
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('deepseek-flash')
  const [mode,setMode]=useState<PaymentMode>('byok')
  const [auth,setAuthState]=useState(()=>sessionStorage.getItem('castle-session')||'')
  const [invited,setInvited]=useState<string[]>([])
  const [caseData, setCaseData] = useState<CaseData|null>(null)
  const [caseToken, setCaseToken] = useState('')
  const [restoreId, setRestoreId] = useState('')
  const [restoreToken, setRestoreToken] = useState('')
  const [loading, setLoading] = useState('')
  const [error, setError] = useState('')
  const [connectionError, setConnectionError] = useState('')
  const active=caseData?.jobs?.some(job=>['queued','running','stopping'].includes(job.state))||false
  const busy=loading||(active?'正在生成，可离开后凭案卷令牌恢复进度':'')
  const setAuth=(value:string)=>{setAuthState(value);if(value)sessionStorage.setItem('castle-session',value);else sessionStorage.removeItem('castle-session')}
  function remember(data:CaseData,token:string) {sessionStorage.setItem('castle-passport',JSON.stringify({id:data.case_id,token}));setCaseData(data);setCaseToken(token);setInvited(data.systems.slice(0,2))}
  useEffect(()=>{
    const saved=sessionStorage.getItem('castle-passport')
    if(!saved)return
    try{const {id,token}=JSON.parse(saved);api(`/api/cases/${id}`,{headers:{'X-Case-Token':token}}).then(data=>{remember(data,token);setStage(data.jobs?.length||Object.keys(data.reports).length?'report':'review')}).catch(()=>setError('自动恢复未完成，可以使用案卷凭证手动恢复。'))}catch{sessionStorage.removeItem('castle-passport')}
  },[])
  useEffect(()=>{
    setConnectionError('')
    if(!active||!caseData)return
    let cancelled=false
    let failures=0
    let timer:ReturnType<typeof setTimeout>
    let controller:AbortController|undefined
    async function poll() {
      controller=new AbortController()
      const deadline=setTimeout(()=>controller?.abort(),15000)
      try {
        const data=await api(`/api/cases/${caseData!.case_id}`,{headers:{'X-Case-Token':caseToken},signal:controller.signal})
        if(!cancelled){setCaseData(data);setConnectionError('');failures=0}
      } catch {
        if(!cancelled){failures++;setConnectionError('进度连接暂时中断，任务可能仍在后台执行；正在自动重连。请勿重复提交。')}
      } finally {
        clearTimeout(deadline)
        // No overlapping requests; back off when offline or the server is unavailable.
        if(!cancelled)timer=setTimeout(poll,Math.min(30000,2500*2**Math.min(failures,4)))
      }
    }
    timer=setTimeout(poll,2500)
    return ()=>{cancelled=true;clearTimeout(timer);controller?.abort()}
  },[active,caseData?.case_id,caseToken])

  const providerHeaders = () => {
    const headers:Record<string,string> = {'X-DeepSeek-Model':model,'X-Payment-Mode':mode}
    if (apiKey&&mode==='byok') headers['X-DeepSeek-Key'] = apiKey
    if(auth)headers.Authorization=`Bearer ${auth}`
    if (caseToken) headers['X-Case-Token'] = caseToken
    return headers
  }

  async function calculateBirth(input:BirthInput) {
    setError('');setLoading('本地引擎正在计算盘面…')
    try {
      const created=await api('/api/cases/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input)})
      remember(created,created.resume_token);setStage('review');scrollTo('review')
    }catch(caught){setError(messageOf(caught))}finally{setLoading('')}
  }

  async function startCase(event:FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError('')
    const missing = selected.filter(id => !files[id])
    if (missing.length) return setError(`请为每个已开启的体系上传报告：${missing.map(systemName).join('、')}`)
    setLoading('正在建立案件…')
    try {
      const create = await api('/api/cases', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({systems:selected})})
      remember(create,create.resume_token);setStage('review');scrollTo('review')
      const token = create.resume_token as string
      const extractions:Extraction[] = []
      for (let index=0; index<selected.length; index++) {
        const id=selected[index]
        setLoading(`读取并抽取 ${systemName(id)}（${index+1}/${selected.length}）…`)
        const body = new FormData(); body.append('file', files[id] as File)
        extractions.push(await api(`/api/cases/${create.case_id}/sources/${id}`, {method:'POST', headers:{...providerHeaders(), 'X-Case-Token':token}, body}))
        setCaseData({...create,extractions:Object.fromEntries(extractions.map(item=>[item.system_id,item]))})
      }
      setCaseData({...create, extractions:Object.fromEntries(extractions.map(item => [item.system_id,item]))})
      setStage('review'); scrollTo('review')
    } catch (caught) { setError(messageOf(caught)) } finally { setLoading('') }
  }

  async function confirmAndGenerate() {
    if (!caseData) return
    if(!invited.length)return setError('请至少邀请一间密室。免费体验需选择两间。')
    const empty = caseData.systems.filter(id => !caseData.extractions[id]?.facts.length)
    if (empty.length) return setError(`这些报告没有可确认事实：${empty.map(systemName).join('、')}。请添加事实或重新上传。`)
    setError(''); setLoading('正在封存用户确认的事实…')
    try {
      await Promise.all(caseData.systems.map(id => api(`/api/cases/${caseData.case_id}/facts/${id}`, {method:'PUT',headers:{...providerHeaders(),'Content-Type':'application/json'},body:JSON.stringify({facts:caseData.extractions[id].facts})})))
      await api(`/api/cases/${caseData.case_id}/reports`, {method:'POST',headers:{...providerHeaders(),'Content-Type':'application/json'},body:JSON.stringify({systems:invited})})
      setCaseData(await api(`/api/cases/${caseData.case_id}`,{headers:providerHeaders()})); setStage('report'); scrollTo('report')
    } catch (caught) { setError(messageOf(caught)) } finally { setLoading('') }
  }

  async function restoreCase(event:FormEvent) {
    event.preventDefault(); setError(''); setLoading('正在恢复案件…')
    try {
      const restored = await api(`/api/cases/${restoreId.trim()}`, {headers:{'X-Case-Token':restoreToken.trim()}})
      remember(restored,restoreToken.trim());setSelected(restored.systems)
      setStage(restored.jobs?.length||Object.keys(restored.reports || {}).length ? 'report' : 'review')
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
      await api(`/api/cases/${caseData.case_id}/sources/${systemId}`,{method:'POST',headers:providerHeaders(),body})
      setCaseData(await api(`/api/cases/${caseData.case_id}`,{headers:providerHeaders()}))
    } catch(caught){setError(messageOf(caught))} finally{setLoading('')}
  }

  function endCase() {
    if (!caseData) return
    const confirmed = window.confirm(`结束 ${caseData.case_id} 的本次浏览并重新开始？\n\n旧案仍保存在服务器；请确认你已经保存 Case ID 与恢复令牌。${active?'\n\n后台任务仍会继续。若想停止后续 AI 调用，请先点击「停止后续生成」。':''}`)
    if (!confirmed) return
    setStage('entry'); setSelected(systems.map(([id])=>id)); setFiles({}); setApiKey(''); setModel('deepseek-flash')
    sessionStorage.removeItem('castle-passport')
    setCaseData(null); setCaseToken(''); setRestoreId(''); setRestoreToken(''); setLoading(''); setError('')
    setTimeout(()=>document.querySelector('#entry')?.scrollIntoView({behavior:'smooth'}),50)
  }

  async function retry(job:Job) {if(!caseData)return;setLoading('正在继续未完成步骤…');setError('');try{await api(`/api/cases/${caseData.case_id}/jobs/${job.id}/retry`,{method:'POST',headers:providerHeaders()});setCaseData(await api(`/api/cases/${caseData.case_id}`,{headers:providerHeaders()}))}catch(e){setError(messageOf(e))}finally{setLoading('')}}
  async function stop(job:Job) {
    if(!caseData||!window.confirm('停止尚未发出的 AI 请求？已发出的请求会继续完成并正常计费，成功内容会保留。之后可以继续未完成步骤。'))return
    setLoading('正在停止后续生成…');setError('')
    try {
      const stopped=await api(`/api/cases/${caseData.case_id}/jobs/${job.id}/stop`,{method:'POST',headers:{'X-Case-Token':caseToken}})
      setCaseData(current=>current?{...current,jobs:current.jobs?.map(item=>item.id===stopped.id?stopped:item)}:current)
    }catch(e){setError(messageOf(e))}finally{setLoading('')}
  }
  async function deleteCase() {if(!caseData||!window.confirm('永久删除本案全部盘面、报告和庭审？此操作不可恢复。'))return;try{await api(`/api/cases/${caseData.case_id}`,{method:'DELETE',headers:providerHeaders()});sessionStorage.removeItem('castle-passport');setCaseData(null);setCaseToken('');setApiKey('');setStage('entry')}catch(e){setError(messageOf(e))}}

  return <main>
    <nav><span className="site-title">THE CASTLE OF CROSSED DESTINIES</span><a href="#method">Method</a></nav>
    <section className="hero"><p className="eyebrow">SEVEN SEALED CHAMBERS · ONE TRIBUNAL</p><h1><em>THE CASTLE OF<br/>CROSSED DESTINIES</em></h1><p className="lede">从一个出生时刻开始，让不同的象征体系彼此作证。城堡在本地计算盘面，密室独立撰写解读，最后在宴会厅相互质询。也可带着已有报告入场。</p><div className="rule"/><p className="note">Local chart engines · Independent readings · One shared question</p><div className="castle-card"><img src="/castle-card.jpg" alt="The Castle of Crossed Destinies card"/></div></section>
    <AccessPanel mode={mode} setMode={setMode} apiKey={apiKey} setApiKey={setApiKey} model={model} setModel={setModel} auth={auth} setAuth={setAuth} revision={JSON.stringify(caseData?.jobs?.map(j=>[j.id,j.state,j.steps]))||''}/>

    {!caseData&&<section className="entry" id="entry"><div><p className="eyebrow">I. OPEN A CASE</p><h2>One moment.<br/>Many readings.</h2><p>不必先去其他网站找报告。七间密室都可自动排盘；只选数秘和 Dreamspell 时，填出生日期就够了。</p><div className="entry-modes" role="group" aria-label="入场方式"><button type="button" aria-pressed={entryMode==='calculate'} onClick={()=>{setEntryMode('calculate');setError('')}}>自动排盘</button><button type="button" aria-pressed={entryMode==='upload'} onClick={()=>{setEntryMode('upload');setError('')}}>文档上传 · 七体系</button></div><RestoreForm id={restoreId} token={restoreToken} setId={setRestoreId} setToken={setRestoreToken} submit={restoreCase}/></div>
      {entryMode==='calculate'?<BirthChartForm submit={calculateBirth} loading={loading} error={error}/>:<form onSubmit={startCase}>
        <div className="key-panel"><p>结构化 TXT/JSON 直接解析；其他文本的 AI 抽取使用上方所选方式，每次成功抽取消耗 2 点 Castle 额度或你的 Key。免费体验请使用自动排盘。原文件、完整文本与 API Key 均不保存。</p></div>
        <fieldset><legend>选择密室并上传报告</legend><div className="systems upload-systems">{systems.map(([id,title,detail]) => <div className={selected.includes(id)?'system upload active':'system upload'} key={id}><button type="button" onClick={()=>setSelected(value=>value.includes(id)?value.filter(item=>item!==id):[...value,id])}><b>{title}</b><small>{detail}</small><i>{selected.includes(id)?'✓':'+'}</i></button>{selected.includes(id)&&<label className="file"><input type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={e=>setFiles({...files,[id]:e.target.files?.[0]||null})}/><span>{files[id]?.name || '选择 PDF / TXT / 图片'}</span></label>}</div>)}</div></fieldset>
        {error&&<p className="error">{error}</p>}<button className="enter" disabled={!!loading||!selected.length}>{loading||'CREATE CASE & EXTRACT FACTS'}</button>
      </form>}
    </section>}

    {caseData && <><CasePassport data={caseData} token={caseToken}/><p className="centered">案卷凭证暂存在当前标签页；API Key 不会保存。</p>{connectionError&&<p className="warning centered" role="status">{connectionError}</p>}<JobsView data={caseData} retry={retry} stop={stop} busy={!!busy} acting={!!loading}/><button className="delete-case" onClick={deleteCase} disabled={!!busy}>永久删除本案</button></>}
    {stage==='review' && caseData && <Review data={caseData} updateFacts={updateFacts} upload={uploadToExisting} submit={confirmAndGenerate} loading={busy} error={error} access={<section className="review-access"><b>邀请哪些密室解读？</b><ParticipantPicker systems={caseData.systems} selected={invited} setSelected={setInvited}/><p>{mode==='byok'?'使用自己的 Key，费用由 DeepSeek 结算。':`本次最多 ${invited.length*2+(invited.length>1?1:0)} 点；已完成且配置相同的报告可复用。`}{mode==='trial'&&' 免费体验请选择两间。'}</p><button type="button" onClick={endCase} disabled={!!loading}>退出本案 · 重新开始</button></section>}/>}
    {stage==='report' && caseData && <ReportView data={caseData} providerHeaders={providerHeaders} setData={setCaseData} review={()=>{setStage('review');scrollTo('review')}} endCase={endCase} loading={busy} acting={!!loading} setLoading={setLoading} error={error} setError={setError} mode={mode}/>}
    <section className="method" id="method"><p className="eyebrow">THE METHOD</p><h2>Calculate. Contemplate. Cross-examine.</h2><p>本地引擎计算，或从报告抽取事实。确认后，每间密室只读取自己的资料和轻量人物 Skill。Tribunal 比较独立报告，提问阶段再进行一次回答、rebuttal 与总结。计算可重复，不等于象征性解释获得科学验证。</p><p className="engine-credits">Local libraries (MIT): <a href="https://github.com/openfate-ai/bazi-engine">OpenFate BaZi</a> · <a href="https://github.com/SylarLong/iztro">iztro</a> · <a href="https://github.com/cosinekitty/astronomy">Astronomy Engine</a> · <a href="https://github.com/domalhambra/hd-chart-engine">hd-chart-engine</a> · <a href="https://github.com/Unforced-Dev/natalengine">NatalEngine</a></p></section><footer>THE CASTLE OF CROSSED DESTINIES <span>Symbolic interpretation—not proof, diagnosis, or professional advice.</span></footer>
  </main>
}

function RestoreForm({id,token,setId,setToken,submit}:any) { return <form className="restore" onSubmit={submit}><p className="eyebrow">RESTORE A CASE</p><input value={id} onChange={e=>setId(e.target.value)} placeholder="Case ID" required/><input type="password" value={token} onChange={e=>setToken(e.target.value)} placeholder="Resume token" required/><button>RESTORE</button></form> }

function ParticipantPicker({systems:available,selected,setSelected}:{systems:string[];selected:string[];setSelected:(v:string[])=>void}) {return <div className="participant-picker" role="group" aria-label="选择参与密室">{available.map(id=><button type="button" key={id} aria-pressed={selected.includes(id)} onClick={()=>setSelected(selected.includes(id)?selected.filter(s=>s!==id):[...selected,id])}>{selected.includes(id)?'✓ ':''}{systemName(id)}</button>)}</div>}

function JobsView({data,retry,stop,busy,acting}:{data:CaseData;retry:(job:Job)=>void;stop:(job:Job)=>void;busy:boolean;acting:boolean}) {
  const jobs=(data.jobs||[]).filter(job=>job.facts_revision===(data.facts_revision||0))
  const labels:Record<string,string>={queued:'等待中',running:'生成中',stopping:'正在停止后续生成',cancelled:'已停止',completed:'已完成',failed:'未完成',partial:'部分完成',interrupted:'已中断',report:'报告',answer:'独立回答',rebuttal:'一次反驳',tribunal:'Tribunal',summary:'主持人总结'}
  return <>{jobs.slice(0,3).map(job=><section className="job-panel" key={job.id} aria-live="polite">
    <b>{job.kind==='reports'?'密室解读':'一轮庭审'} · {labels[job.state]||job.state}</b>
    <p>完成 {Object.values(job.steps).filter(s=>s.state==='completed').length} / {Object.keys(job.steps).length}；完成内容已保存。</p>
    <progress aria-label="任务完成进度" max={Object.keys(job.steps).length} value={Object.values(job.steps).filter(s=>s.state==='completed').length}/>
    <ul>{Object.entries(job.steps).map(([id,step])=>{const [phase,system]=id.split(':');return <li key={id}>{system?`${systemName(system)} · `:''}{labels[phase]||phase}：{labels[step.state]||step.state}{step.error&&<small>{step.error}</small>}</li>})}</ul>
    {['queued','running'].includes(job.state)&&<button type="button" disabled={acting} onClick={()=>stop(job)}>停止后续生成 · 保留已完成内容</button>}
    {job.state==='stopping'&&<p role="status">已停止派发新请求，正在等待已发出的请求完成和结算。关闭页面不会撤销它们。</p>}
    {['partial','interrupted','cancelled'].includes(job.state)&&<button type="button" disabled={busy} onClick={()=>retry(job)}>仅继续未完成步骤 · 使用原付费方式</button>}
  </section>)}</>
}

function CasePassport({data,token}:{data:CaseData;token:string}) { const [copied,setCopied]=useState(false); return <section className="passport"><div><p className="eyebrow">CASE PASSPORT</p><h3>{data.case_id}</h3><p>请妥善保存恢复令牌，不要公开分享；持有它即可访问和删除本案。服务器只保存令牌哈希。</p></div><code>{token || '令牌已在创建时发放'}</code>{token&&<button onClick={()=>navigator.clipboard.writeText(`${data.case_id}\n${token}`).then(()=>setCopied(true)).catch(()=>setCopied(false))}>{copied?'COPIED':'COPY ID + TOKEN'}</button>}</section> }

function Review({data,updateFacts,upload,submit,loading,error,access}:{data:CaseData;updateFacts:(id:string,facts:Fact[])=>void;upload:(id:string,file:File)=>void;submit:()=>void;loading:string;error:string;access:ReactNode}) {
  return <section className="review" id="review"><header><p className="eyebrow">II. USER CONFIRMATION</p><h2>{data.calculation?'Your charts are ready.':'Check every extracted fact.'}</h2><p>{data.calculation?'请核对出生资料与排盘约定。盘面已由本地引擎生成，无需再上传报告；你仍可展开查看和修改。':'修正识别错误，删除原报告的解释性句子；需要时可手动补充报告明确写出的盘面事实。'}</p></header>
    {data.calculation&&<div className="calculation-summary"><b>{data.calculation.input.birth_date}{data.calculation.input.birth_time&&` · ${data.calculation.input.birth_time}`}</b>{data.calculation.location&&<p>{data.calculation.location.name} / {data.calculation.location.countrycode} · {data.calculation.location.timezone}</p>}{data.calculation.utc&&<p>UTC {data.calculation.utc} · 夏令时偏移 {data.calculation.dst_hours} 小时</p>}<p>已生成 {data.systems.length} 套盘面。各体系的流派、算法及未计算项目见下方「计算约定 / 分析边界」。</p><small>资料填错时请使用「退出本案 · 重新开始」。修改下方事实不会反向改变原始排盘记录。</small></div>}
    <div className="review-grid">{data.systems.map(id=>{
      const extraction=data.extractions[id]
      if(!extraction)return <MissingUpload key={id} systemId={id} onUpload={file=>upload(id,file)}/>
      const editor=<FactEditor extraction={extraction} onChange={facts=>updateFacts(id,facts)} onUpload={file=>upload(id,file)}/>
      return extraction.extraction_engine==='local_calculation'?<details className="calculated-dossier" key={id}><summary><b>{systemName(id)}</b><span>{extraction.facts.length} 项盘面数据 · 展开核对</span></summary>{editor}</details>:<div key={id}>{editor}</div>
    })}</div>{access}{error&&<p className="error centered">{error}</p>}<button className="enter assemble" onClick={submit} disabled={!!loading}>{loading||'确认资料 · 开始独立解读'}</button></section>
}

function FactEditor({extraction,onChange,onUpload}:{extraction:Extraction;onChange:(facts:Fact[])=>void;onUpload:(file:File)=>void}) { const add=()=>onChange([...extraction.facts,{id:`${extraction.system_id}.manual-${Date.now()}`,label:'',value:'',time_sensitive:!['numerology','dreamspell'].includes(extraction.system_id),source_span:'用户根据原报告手动补充',extraction_confidence:1}]); return <article className="fact-editor"><div className="editor-head"><div><p>{extraction.display_name}</p><small>{extraction.filename} · {engineName(extraction.extraction_engine)} · {formatSize(extraction.source_bytes||0)}</small></div><span>{extraction.facts.length} FACTS</span></div><label className="replace-file">重新上传<input type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={e=>e.target.files?.[0]&&onUpload(e.target.files[0])}/></label>{extraction.warnings.map(item=><p className="warning" key={item}>{item}</p>)}{extraction.facts.map((fact,index)=><div className="fact-row" key={fact.id}><input aria-label="事实名称" value={fact.label} onChange={e=>onChange(extraction.facts.map((item,i)=>i===index?{...item,label:e.target.value}:item))}/><textarea aria-label="事实内容" value={fact.value} onChange={e=>onChange(extraction.facts.map((item,i)=>i===index?{...item,value:e.target.value}:item))}/><button title="删除" onClick={()=>onChange(extraction.facts.filter((_,i)=>i!==index))}>×</button>{fact.source_span&&<small>{fact.source_span}</small>}</div>)}<button className="add-fact" onClick={add}>+ ADD EXPLICIT FACT</button>{extraction.source_commentary.length>0&&<details><summary>已排除的原报告解释（{extraction.source_commentary.length}）</summary>{extraction.source_commentary.map(item=><p key={item}>{item}</p>)}</details>}</article> }
function MissingUpload({systemId,onUpload}:{systemId:string;onUpload:(file:File)=>void}) { return <article className="fact-editor missing-upload"><p>{systemName(systemId)}</p><small>这份报告尚未上传，或上次上传在网络中断前没有完成。</small><label>继续上传 PDF / TXT / 图片<input type="file" accept=".pdf,.txt,.md,.png,.jpg,.jpeg,.webp,.tif,.tiff" onChange={e=>e.target.files?.[0]&&onUpload(e.target.files[0])}/></label></article> }

function ReportView({data,providerHeaders,setData,review,endCase,loading,acting,setLoading,error,setError,mode}:{data:CaseData;providerHeaders:()=>Record<string,string>;setData:(data:CaseData)=>void;review:()=>void;endCase:()=>void;loading:string;acting:boolean;setLoading:(value:string)=>void;error:string;setError:(value:string)=>void;mode:PaymentMode}) {
  const [question,setQuestion]=useState('')
  const [participants,setParticipants]=useState(data.systems.slice(0,2))
  async function ask(event:FormEvent) { event.preventDefault(); setError(''); setLoading('正在建立庭审任务…'); try { await api(`/api/cases/${data.case_id}/debates`,{method:'POST',headers:{...providerHeaders(),'Content-Type':'application/json'},body:JSON.stringify({question,systems:participants})}); setData(await api(`/api/cases/${data.case_id}`,{headers:providerHeaders()})); setQuestion('') } catch(caught){setError(messageOf(caught))} finally{setLoading('')} }
  async function exportMarkdown() { setError(''); setLoading('正在整理完整 Markdown 案卷…'); try { const token=providerHeaders()['X-Case-Token']||''; const response=await fetch(`/api/cases/${data.case_id}/export.md`,{headers:{'X-Case-Token':token}}); if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||`HTTP ${response.status}`)} const blob=await response.blob(); const url=URL.createObjectURL(blob); const link=document.createElement('a'); link.href=url; link.download=`${data.case_id}.md`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url) } catch(caught){setError(messageOf(caught))} finally{setLoading('')} }
  const completed=Object.values(data.reports).filter(report=>report.text||report.free_text).length
  return <section id="report" className="report"><header><div><p className="eyebrow">III. GENERAL REPORTS</p><h2>The assembled testimony</h2></div><div className="badge skills_ready">LIGHT SKILL<small>{completed} natural-language reports</small></div></header>{data.report_warnings?.map(item=><p className="warning disclosure" key={item}>{item}</p>)}
    <div className="regenerate-panel"><div><b>每篇报告完成后立即保存</b><p>未完成步骤可在上方继续。相同配置的已完成任务直接复用，不重复扣费。</p></div><div className="regenerate-actions"><button type="button" className="secondary" onClick={review} disabled={!!loading}>核对事实 / 邀请更多密室</button></div></div>
    {error&&<p className="error">{error}</p>}
    <div className="report-grid">{data.systems.map(id=><GeneralReport key={id} report={data.reports[id]}/>)}</div>
    <TribunalView tribunal={data.tribunal}/>
    <section className="hearing"><p className="eyebrow">V. CROSS-EXAMINATION</p><h2>Invite your witnesses.</h2><p>所选密室先独立回答，再各作一次反驳，最后由主持人总结。</p><ParticipantPicker systems={data.systems.filter(s=>data.confirmed_facts[s]?.length)} selected={participants} setSelected={setParticipants}/><p>{mode==='byok'?`本轮最多 ${participants.length*2+1} 次模型调用，由你的 Key 结算。`:`本轮最多 ${participants.length*2+1} 点。免费体验不包含追加庭审。`}</p><form onSubmit={ask}><textarea value={question} onChange={e=>setQuestion(e.target.value)} required minLength={3} maxLength={1200} placeholder="例如：面对职业选择时，各体系分别看到了什么？哪些判断真正冲突？"/><button className="enter" disabled={!!loading||!participants.length||mode==='trial'}>{loading||'CONVENE ONE-ROUND HEARING'}</button></form>{error&&<p className="error">{error}</p>}{data.debates.map((hearing,index)=><GuidedHearingView hearing={hearing} latest={index===data.debates.length-1} key={hearing.id}/>)}</section>
    <section className="case-closure"><p className="eyebrow">VI. CLOSE THE CASE</p><h2>Seal the record.</h2><p>下载当前已保存的 Markdown 案卷，或结束本次浏览并回到一份全新的空白案件。旧案不会从服务器删除；退出不会停止后台任务。生成中导出的文件仅包含当时已完成的内容。</p><div><button type="button" className="export-case" onClick={exportMarkdown} disabled={acting}>EXPORT DOSSIER · .MD</button><button type="button" className="end-case" onClick={endCase} disabled={acting}>结束庭审 · 重新开始</button></div></section>
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
function engineName(engine?:string) { return ({local_calculation:'本地确定性排盘',structured_text:'Deterministic structured parser',deepseek_text:'Local text + DeepSeek',manual_required:'Manual review'} as Record<string,string>)[engine||'']||'Legacy extraction' }
function formatSize(bytes:number) { return bytes?`${Math.max(1,Math.round(bytes/1024)).toLocaleString()} KB`:'size unavailable' }
function scrollTo(id:string) { setTimeout(()=>document.querySelector(`#${id}`)?.scrollIntoView({behavior:'smooth'}),80) }
async function api(url:string,init?:RequestInit) { const response=await fetch(url,init); const body=await response.json().catch(()=>({})); if(!response.ok) throw new Error(Array.isArray(body.detail)?body.detail.map((item:{msg:string})=>item.msg).join('；'):body.detail||`HTTP ${response.status}`); return body }
function messageOf(caught:unknown) { return caught instanceof Error?caught.message:'无法连接到后端，请检查 FastAPI、反向代理或服务器日志。' }
