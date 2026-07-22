import { FormEvent, useState } from 'react'

type Report = { case_id:string; mode:string; time_sensitivity:string; chambers:any[]; claims:any[]; consensus:any[]; conflicts:any[]; questions:any[]; audit:any }
const systems = [
  ['western', 'Western Astrology', '本命盘 · 行星 · 宫位'], ['jyotish', 'Jyotish', '印度占星 API'], ['bazi', 'BaZi 八字', '四柱与五行 API'], ['human_design', 'Human Design', '类型 · 权威 · 中心']
]

export default function App() {
  const [selected, setSelected] = useState(systems.map(([id]) => id))
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setLoading(true); setError('')
    const form = new FormData(e.currentTarget)
    try {
      const response = await fetch('/api/reports', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ systems:selected, profile:{ display_name:form.get('name'), birth_date:form.get('date'), birth_time:form.get('time') || null, birthplace_text:form.get('place'), timezone_name:form.get('timezone'), time_precision:form.get('precision') } }) })
      if (!response.ok) throw new Error('The gatekeeper could not create this case.')
      setReport(await response.json())
      setTimeout(() => document.querySelector('#report')?.scrollIntoView({behavior:'smooth'}), 80)
    } catch { setError('无法连接到后端。请先启动 FastAPI（见 README）。') } finally { setLoading(false) }
  }
  return <main>
    <nav><span className="monogram">✦ CCD</span><span>THE CASTLE OF CROSSED DESTINIES</span><a href="#method">Method</a></nav>
    <section className="hero"><p className="eyebrow">MULTI-SYSTEM INTERPRETATION · AUDITABLE BY DESIGN</p><h1>Let the systems<br/><em>cross-examine</em> each other.</h1><p className="lede">一份出生资料，多个独立 API 证词；所有结论都要接受证据、矛盾与宽泛性审计。</p><div className="rule"/><p className="note">紫微斗数报告与上传功能不在本版本范围内。</p></section>
    <section className="entry" id="entry"><div><p className="eyebrow">I. CONDITIONS OF ENTRY</p><h2>Enter the castle</h2><p>只收集生成盘面所需的信息。时间精度会被带入每个敏感结论。</p></div><form onSubmit={submit}>
      <label>姓名或昵称<input name="name" required placeholder="The visitor"/></label><div className="twocol"><label>出生日期<input name="date" type="date" required defaultValue="1994-04-18"/></label><label>出生时间<input name="time" type="time" defaultValue="08:30"/></label></div>
      <label>出生地点<input name="place" required placeholder="Shanghai, China" defaultValue="Shanghai, China"/></label><div className="twocol"><label>IANA 时区<input name="timezone" required defaultValue="Asia/Shanghai"/></label><label>时间精度<select name="precision" defaultValue="exact"><option value="exact">精确</option><option value="approximate">约略</option><option value="unknown">未知</option></select></label></div>
      <fieldset><legend>Open chambers</legend><div className="systems">{systems.map(([id,title,detail]) => <button type="button" className={selected.includes(id) ? 'system active':'system'} key={id} onClick={() => setSelected(v => v.includes(id) ? v.filter(x => x !== id) : [...v,id])}><b>{title}</b><small>{detail}</small><i>{selected.includes(id) ? '✓' : '+'}</i></button>)}</div></fieldset>
      {error && <p className="error">{error}</p>}<button className="enter" disabled={loading || !selected.length}>{loading ? 'SUMMONING WITNESSES…' : 'ENTER THE CASTLE  →'}</button>
    </form></section>
    {report && <ReportView report={report}/>}<section className="method" id="method"><p className="eyebrow">THE METHOD</p><h2>Calculation is not interpretation.</h2><p>盘面由可替换的 API provider 生成并标准化；chamber 只能引用自己的事实。Tribunal 只比较结构化 claims，并扣除相互依赖体系的重复票数。</p></section><footer>CCD / CASEWORK FOR SYMBOLIC SYSTEMS <span>Not advice. Not proof. A traceable conversation.</span></footer>
  </main>
}

function ReportView({report}:{report:Report}) { return <section id="report" className="report"><header><div><p className="eyebrow">CASE FILE {report.case_id}</p><h2>The assembled testimony</h2></div><div className={'badge '+report.mode}>{report.mode === 'demo' ? 'DEMO DATA' : 'LIVE API'}<small>Time sensitivity: {report.time_sensitivity}</small></div></header>{report.mode === 'demo' && <div className="disclosure">演示模式：至少一间 chamber 未配置 provider 密钥。卡片内容用于检验流程，不是实际命盘。</div>}
  <div className="chambers">{report.chambers.map(c => <article className="chamber" key={c.system_id}><p>{c.display_name}</p><span>{c.source_type === 'api' ? 'API VERIFIED' : 'DEMO ADAPTER'}</span>{c.facts.map((f:any) => <div className="fact" key={f.id}><small>{f.label}</small><b>{f.value}</b></div>)}<em>{c.warning || `Provider: ${c.provider}`}</em></article>)}</div>
  <div className="tribunal"><div><p className="eyebrow">IV. THE BANQUET HALL</p><h3>Shared motifs</h3>{report.consensus.map(c=><div className="motif" key={c.theme}><div><b>{c.theme.replace('_',' ')}</b><small>{c.support.join(' · ')} · {c.independence}</small></div><strong>{c.score}<small>/100</small></strong><div className="bar"><i style={{width:`${c.score}%`}}/></div></div>)}</div><aside><p className="eyebrow">VI. COURTROOM</p><h3>Cross-examination</h3><b>{report.questions[0]?.target}</b><p>“{report.questions[0]?.question}”</p><small>Only evidence-linked challenges are admitted.</small></aside></div>
  <div className="audit"><div><p className="eyebrow">VIII. AUDITOR’S NOTES</p><h3>What survives scrutiny?</h3><p><b>Barnum risk: </b>{report.audit.barnum_risk}</p><p><b>Traceability: </b>{report.audit.traceability}</p><p>{report.audit.limitation}</p></div><div><p className="eyebrow">TOWER OF CONTRADICTIONS</p><h3>{report.conflicts[0]?.topic}</h3><p>{report.conflicts[0]?.positions}</p><span className="pill">{report.conflicts[0]?.severity} disagreement</span></div></div></section> }
