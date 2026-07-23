import { FormEvent, useState } from 'react'

type Report = { case_id:string; mode:string; time_sensitivity:string; chambers:any[]; claims:any[]; consensus:any[]; conflicts:any[]; questions:any[]; audit:any }
const systems = [
  ['bazi', 'BaZi 八字', '四柱 · 五行 · 十神'], ['ziwei', 'Zi Wei Dou Shu', '宫位 · 星曜 · 四化'], ['western', 'Western Astrology', '行星 · 宫位 · 相位'], ['jyotish', 'Jyotish 印占', 'Lagna · Graha · Dasha'], ['numerology', 'Numerology 数秘', '显式数值 · 传统标注'], ['human_design', 'Human Design', 'Type · Authority · Centers'], ['dreamspell', 'Dreamspell', 'Kin · Tone · Solar Seal']
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
      const response = await fetch('/api/reports', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ systems:selected, facts_text:form.get('facts'), profile:{ display_name:form.get('name'), birth_date:form.get('date'), birth_time:form.get('time') || null, birthplace_text:form.get('place'), timezone_name:form.get('timezone'), time_precision:form.get('precision') } }) })
      if (!response.ok) throw new Error('The gatekeeper could not create this case.')
      setReport(await response.json())
      setTimeout(() => document.querySelector('#report')?.scrollIntoView({behavior:'smooth'}), 80)
    } catch { setError('无法连接到后端。请先启动 FastAPI（见 README）。') } finally { setLoading(false) }
  }
  return <main>
    <nav><span className="monogram">✦ CCD</span><span>THE CASTLE OF CROSSED DESTINIES</span><a href="#method">Method</a></nav>
    <section className="hero"><p className="eyebrow">SEVEN LOCAL SKILLS · AUDITABLE BY DESIGN</p><h1>Let the systems<br/><em>cross-examine</em> each other.</h1><p className="lede">一份出生资料，七套独立 Skill 证词。它们只解释你提供的盘面事实；每个结论都必须接受证据、矛盾与宽泛性审计。</p><div className="rule"/><p className="note">No external APIs. No hidden chart calculation. Zi Wei is back in the castle.</p></section>
    <section className="entry" id="entry"><div><p className="eyebrow">I. CONDITIONS OF ENTRY</p><h2>Enter the castle</h2><p>Skill 不会自行排盘。请提供你已有的、可核验的盘面事实；时间精度会被带入每个敏感结论。</p></div><form onSubmit={submit}>
      <label>姓名或昵称<input name="name" required placeholder="The visitor"/></label><div className="twocol"><label>出生日期<input name="date" type="date" required defaultValue="1994-04-18"/></label><label>出生时间<input name="time" type="time" defaultValue="08:30"/></label></div>
      <label>出生地点<input name="place" required placeholder="Shanghai, China" defaultValue="Shanghai, China"/></label><div className="twocol"><label>IANA 时区<input name="timezone" required defaultValue="Asia/Shanghai"/></label><label>时间精度<select name="precision" defaultValue="exact"><option value="exact">精确</option><option value="approximate">约略</option><option value="unknown">未知</option></select></label></div>
      <fieldset><legend>Open chambers</legend><div className="systems">{systems.map(([id,title,detail]) => <button type="button" className={selected.includes(id) ? 'system active':'system'} key={id} onClick={() => setSelected(v => v.includes(id) ? v.filter(x => x !== id) : [...v,id])}><b>{title}</b><small>{detail}</small><i>{selected.includes(id) ? '✓' : '+'}</i></button>)}</div></fieldset>
      <label>可核验事实档案 <small>每行：system | label | value</small><textarea name="facts" placeholder={'bazi | Day Master | 甲木\nziwei | 命宫主星 | 紫微、天府\nwestern | Mercury | 9th house\njyotish | Lagna | Sagittarius\nnumerology | Pythagorean Life Path | 7\nhuman_design | Authority | Sacral\ndreamspell | Kin | 104'} /></label>
      {error && <p className="error">{error}</p>}<button className="enter" disabled={loading || !selected.length}>{loading ? 'ASSEMBLING DOSSIERS…' : 'ENTER THE CASTLE  →'}</button>
    </form></section>
    {report && <ReportView report={report}/>}<section className="method" id="method"><p className="eyebrow">THE METHOD</p><h2>Facts first. Skills second.</h2><p>不调用 API，也不在后台偷算盘。每间 chamber 只读取事实档案中属于自己的条目；Skill 的每条 claim 必须回指事实 ID。Tribunal 再比较这些可追溯证词。</p></section><footer>CCD / CASEWORK FOR SYMBOLIC SYSTEMS <span>Not advice. Not proof. A traceable conversation.</span></footer>
  </main>
}

function ReportView({report}:{report:Report}) { return <section id="report" className="report"><header><div><p className="eyebrow">CASE FILE {report.case_id}</p><h2>The assembled testimony</h2></div><div className="badge skills_ready">SKILLS READY<small>Time sensitivity: {report.time_sensitivity}</small></div></header><div className="disclosure">本案仅接纳访客手动提供的事实档案。没有事实的 chamber 会保持沉默，不会生成命理结论。</div>
  <div className="chambers">{report.chambers.map(c => <article className="chamber" key={c.system_id}><p>{c.display_name}</p><span>{c.source_type === 'user_dossier' ? 'DOSSIER VERIFIED' : 'AWAITING FACTS'}</span>{c.facts.map((f:any) => <div className="fact" key={f.id}><small>{f.label}</small><b>{f.value}</b></div>)}<em>{c.warning || `Skill: ${c.skill_path}`}</em></article>)}</div>
  {report.claims.length > 0 && <section className="testimonies"><p className="eyebrow">III. CHAMBER TESTIMONY</p><h3>Evidence-linked claims</h3>{report.claims.map((claim:any) => <article key={claim.id}><span>{claim.system_id.replace('_',' ')}</span><p>{claim.statement}</p><small>Evidence: {claim.evidence_ids.join(' · ')} · confidence {Math.round(claim.confidence * 100)}%</small></article>)}</section>}
  <div className="tribunal"><div><p className="eyebrow">IV. THE BANQUET HALL</p><h3>Shared motifs</h3>{report.consensus.map(c=><div className="motif" key={c.theme}><div><b>{c.theme.replace('_',' ')}</b><small>{c.support.join(' · ')} · {c.independence}</small></div><strong>{c.score}<small>/100</small></strong><div className="bar"><i style={{width:`${c.score}%`}}/></div></div>)}</div><aside><p className="eyebrow">VI. COURTROOM</p><h3>Cross-examination</h3><b>{report.questions[0]?.target}</b><p>“{report.questions[0]?.question}”</p><small>Only evidence-linked challenges are admitted.</small></aside></div>
  <div className="audit"><div><p className="eyebrow">VIII. AUDITOR’S NOTES</p><h3>What survives scrutiny?</h3><p><b>Barnum risk: </b>{report.audit.barnum_risk}</p><p><b>Traceability: </b>{report.audit.traceability}</p><p>{report.audit.limitation}</p></div><div><p className="eyebrow">TOWER OF CONTRADICTIONS</p><h3>{report.conflicts[0]?.topic}</h3><p>{report.conflicts[0]?.positions}</p><span className="pill">{report.conflicts[0]?.severity} disagreement</span></div></div></section> }
