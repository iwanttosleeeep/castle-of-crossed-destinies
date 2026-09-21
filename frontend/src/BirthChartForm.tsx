import { FormEvent, useEffect, useState } from 'react'

type City = { geonameid:number; name:string; countrycode:string; admin1code:string; latitude:number; longitude:number; timezone:string }
export type BirthInput = { birth_date:string; birth_time:string|null; city_id:string|null; systems:string[]; gender:string|null; true_solar_time:boolean; day_boundary:string; fold:number|null; numerology_name?:string|null; numerology_y_vowel?:boolean; jyotish_node_type?:string; dreamspell_leap_day?:string|null }
const CHARTS=[['bazi','八字'],['ziwei','紫微'],['western','西占'],['jyotish','印占'],['numerology','数秘'],['human_design','Human Design'],['dreamspell','Dreamspell']]

export default function BirthChartForm({submit,loading,error}:{submit:(input:BirthInput)=>Promise<void>;loading:string;error:string}) {
  const [date,setDate]=useState('')
  const [time,setTime]=useState('')
  const [query,setQuery]=useState('')
  const [city,setCity]=useState<City|null>(null)
  const [results,setResults]=useState<City[]>([])
  const [searchStatus,setSearchStatus]=useState('')
  const [selected,setSelected]=useState(CHARTS.map(([id])=>id))
  const [gender,setGender]=useState('')
  const [solar,setSolar]=useState(false)
  const [boundary,setBoundary]=useState('MIDNIGHT_00')
  const [fold,setFold]=useState('')
  const [name,setName]=useState('')
  const [yVowel,setYVowel]=useState(false)
  const [nodeType,setNodeType]=useState('mean')
  const [leapDay,setLeapDay]=useState('')
  const needsTime=selected.some(id=>!['numerology','dreamspell'].includes(id))
  useEffect(()=>{
    if(city || query.trim().length<2) {setResults([]);setSearchStatus('');return}
    const abort=new AbortController()
    const timer=setTimeout(async()=>{
      setSearchStatus('正在搜索城市…')
      try {
        const response=await fetch(`/api/locations?q=${encodeURIComponent(query.trim())}`,{signal:abort.signal})
        if(!response.ok)throw new Error('城市搜索暂时不可用，请检查后端。')
        const data=await response.json()
        if(!abort.signal.aborted){setResults(data.locations);setSearchStatus(data.locations.length?'':'未找到城市，可试英文名或最近的大城市。')}
      }catch(error){if(!abort.signal.aborted)setSearchStatus(error instanceof Error?error.message:'搜索失败')}
    },250)
    return ()=>{clearTimeout(timer);abort.abort()}
  },[query,city])

  function calculate(event:FormEvent) {
    event.preventDefault()
    if(needsTime&&!city)return
    void submit({birth_date:date,birth_time:needsTime?time:null,city_id:needsTime&&city?String(city.geonameid):null,systems:selected,gender:selected.includes('ziwei')?gender||null:null,true_solar_time:solar,day_boundary:boundary,fold:fold===''?null:Number(fold),numerology_name:selected.includes('numerology')?name.trim()||null:null,numerology_y_vowel:yVowel,jyotish_node_type:nodeType,dreamspell_leap_day:leapDay||null})
  }
  return <form className="birth-form" onSubmit={calculate}>
    <p className="eyebrow">ONE ORIGIN · SEVEN CHAMBERS</p>
    <h3>No dossiers needed.</h3>
    <p>填一次出生资料，由本地引擎排盘。无需排盘 API Key，也不会让 AI 猜星位。</p>
    <fieldset><legend>这次开启的密室</legend><div className="chart-choices">{CHARTS.map(([id,title])=><label key={id}><input type="checkbox" checked={selected.includes(id)} onChange={()=>setSelected(v=>v.includes(id)?v.filter(s=>s!==id):[...v,id])}/>{title}</label>)}</div></fieldset>
    <div className="birth-grid">
      <label>公历出生日期<input type="date" min="1900-01-01" max="2099-12-31" required value={date} onChange={e=>setDate(e.target.value)}/></label>
      {needsTime&&<label>出生证明上的当地钟表时间<input type="time" required value={time} onChange={e=>setTime(e.target.value)}/></label>}
    </div>
    {needsTime&&<><label>出生城市<input type="search" value={query} maxLength={80} autoComplete="off" placeholder="输入中文或英文，例如 北京 / London" onChange={e=>{setQuery(e.target.value);setCity(null)}} aria-describedby="city-note"/></label>
    {searchStatus&&<p role="status" className="search-status">{searchStatus}</p>}
    {results.length>0&&<ul className="city-results" aria-label="城市搜索结果">{results.map(c=><li key={c.geonameid}><button type="button" onClick={()=>{setCity(c);setQuery(`${c.name} · ${c.countrycode} / ${c.admin1code}`);setResults([])}}><b>{c.name}</b><span>{c.countrycode} / {c.admin1code} · {c.timezone}</span></button></li>)}</ul>}
    {city&&<div className="city-confirmed"><span>✓ {city.timezone}</span><small>纬度 {city.latitude.toFixed(4)} · 经度 {city.longitude.toFixed(4)} · 历史夏令时自动处理</small></div>}
    <p id="city-note" className="form-hint">城市中心坐标来自 <a href="https://www.geonames.org/" target="_blank" rel="noreferrer">GeoNames</a>（CC BY 4.0）。时间不详可只选数秘 / Dreamspell 或使用文档上传，不要随意填 12:00。</p></>}
    {selected.includes('ziwei')&&<label>紫微传统排盘性别参数<select required value={gender} onChange={e=>setGender(e.target.value)}><option value="">请选择</option><option value="female">女</option><option value="male">男</option></select><small className="form-hint">仅用于传统算法，不作身份判断；不愿提供可取消紫微。</small></label>}
    {selected.includes('numerology')&&<><label>数秘姓名拼写（可选）<input type="text" maxLength={120} pattern="[A-Za-z][A-Za-z '\-]*" placeholder="留空只计算日期数；或填写自行确认的 A–Z 拼写" value={name} onChange={e=>setName(e.target.value)}/><small className="form-hint">不会自动猜拼音。按全名直接求和，保留 11/22/33；填写的姓名会随数秘事实保存并交给解读模型。</small></label><label className="inline-choice"><input type="checkbox" checked={yVowel} onChange={e=>setYVowel(e.target.checked)}/> 姓名中的 Y 作为元音（默认作为辅音）</label></>}
    {selected.includes('dreamspell')&&date.endsWith('-02-29')&&<label>Dreamspell 闰日换算<select required value={leapDay} onChange={e=>setLeapDay(e.target.value)}><option value="">2 月 29 日是特殊日，请明确选择</option><option value="feb28">按 2 月 28 日（官方建议午前）</option><option value="mar01">按 3 月 1 日（官方建议午后）</option></select></label>}
    <details className="birth-conventions"><summary>排盘约定与高级设置</summary>
      {selected.some(id=>['bazi','ziwei'].includes(id))&&<><label>八字 / 紫微的日时基准<select value={solar?'solar':'standard'} onChange={e=>setSolar(e.target.value==='solar')}><option value="standard">当地标准时（自动去除夏令时）</option><option value="solar">真太阳时（经度与均时差校正）</option></select></label>
      <label>八字 / 紫微换日<select value={boundary} onChange={e=>setBoundary(e.target.value)}><option value="MIDNIGHT_00">午夜 00:00 换日</option><option value="ZI_HOUR_23">子初 23:00 换日</option></select></label></>}
      {needsTime&&<label>若钟表时间因夏令时回拨出现两次<select value={fold} onChange={e=>setFold(e.target.value)}><option value="">自动检查；有歧义时提示</option><option value="0">较早的一次</option><option value="1">较晚的一次</option></select></label>}
      {selected.includes('jyotish')&&<label>印占月交点<select value={nodeType} onChange={e=>setNodeType(e.target.value)}><option value="mean">平均交点（默认）</option><option value="true">真交点（轨道法近似）</option></select></label>}
      <p>西占：热带黄道、地心、整宫制（非 Placidus）。紫微：iztro 默认流派、农历年界。八字不输出大运。印占：Lahiri 近似式，D1 / D9 星座与 Vimshottari 大运（365.25 日年），不含下级大运。Human Design：太阳弧回溯 88°，只算闸门 / 爻线，不含四箭头。Dreamspell：现代 13 月亮体系，非传统 Maya 历法。</p>
    </details>
    <p className="form-hint">七套均可本地计算，也保留文档上传。不同流派与边界时刻可能产生不同盘面，请先核对。资料与排盘约定会保存在案卷中；确认后才发送盘面事实给 DeepSeek 解读。</p>
    {error&&<p className="error" role="alert">{error}</p>}
    <button className="enter" disabled={!!loading||(needsTime&&!city)||!selected.length}>{loading||'CALCULATE · 生成盘面'}</button>
  </form>
}
