import { FormEvent, useEffect, useState } from 'react'

export type PaymentMode = 'byok'|'paid'|'trial'
type Account = {username:string;trial_claimed:number;balances:{paid:number;trial:number;sandbox:number};ledger:{delta:number;reason:string;bucket:string}[]}
type Billing = {hosted_available:boolean;trial_available:boolean;payment_mode:string;packs:{id:string;name:string;credits:number}[]}

class APIError extends Error {
  constructor(message:string,readonly status:number) {super(message)}
}

export async function requestJSON(path:string, init?:RequestInit) {
  const response = await fetch(`/api${path}`,init)
  const body=await response.json().catch(()=>({}))
  if(!response.ok)throw new APIError(Array.isArray(body.detail)?body.detail.map((x:{msg:string})=>x.msg).join('；'):body.detail||`HTTP ${response.status}`,response.status)
  return body
}

export default function AccessPanel({mode,setMode,apiKey,setApiKey,model,setModel,auth,setAuth,revision}:{mode:PaymentMode;setMode:(v:PaymentMode)=>void;apiKey:string;setApiKey:(v:string)=>void;model:string;setModel:(v:string)=>void;auth:string;setAuth:(v:string)=>void;revision:string}) {
  const [billing,setBilling]=useState<Billing|null>(null)
  const [account,setAccount]=useState<Account|null>(null)
  const [username,setUsername]=useState('')
  const [password,setPassword]=useState('')
  const [register,setRegister]=useState(false)
  const [error,setError]=useState('')
  const [accountError,setAccountError]=useState('')
  const [busy,setBusy]=useState(false)
  const [demo,setDemo]=useState(false)
  const headers = {'Authorization':`Bearer ${auth}`,'Content-Type':'application/json'}
  useEffect(()=>{requestJSON('/billing/config').then(setBilling).catch(()=>setError('暂时无法读取额度配置'))},[])
  useEffect(()=>{
    if(!auth){setAccount(null);return}
    let current=true
    const controller=new AbortController()
    requestJSON('/account',{headers:{Authorization:`Bearer ${auth}`},signal:controller.signal})
      .then(result=>{if(current){setAccount(result);setAccountError('')}})
      .catch(e=>{
        if(!current)return
        if(e instanceof APIError&&e.status===401){setAccount(null);setAuth('');setAccountError('登录已过期，请重新登录。案卷与已生成内容不受影响。')}
        else setAccountError('余额暂时无法刷新，请稍后重试；这里显示的可能是上一次余额。')
      })
    return ()=>{current=false;controller.abort()}
  },[auth,revision])
  async function login(e:FormEvent) {
    e.preventDefault();setError('');setBusy(true)
    try {const result=await requestJSON(register?'/account/register':'/account/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});setAuth(result.token);setAccount(result.account);setAccountError('');setPassword('')}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function claim() {setError('');try {setAccount(await requestJSON('/account/trial',{method:'POST',headers}));setMode('trial')}catch(e){setError((e as Error).message)}}
  async function buy(pack:string) {setError('');setBusy(true);try {const result=await requestJSON('/billing/checkout',{method:'POST',headers,body:JSON.stringify({pack})});window.location.assign(result.url)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function logout() {
    setAuth('');setAccount(null);setPassword('');setAccountError('');setError('')
    try{await requestJSON('/account/logout',{method:'POST',headers})}
    catch{setAccountError('本标签页已退出；服务器暂不可达，远端会话可能要到有效期结束才失效。')}
  }
  return <section className="access-panel" id="access"><p className="eyebrow">YOUR VISIT TO THE CASTLE</p><h2>Choose your invitation.</h2><p>排盘免费。AI 解读可使用自己的 Key，或使用 Castle 额度。Key 仅保存在页面内存；刷新后需重新填写。</p>
    <div className="access-options">{([['byok','自带 DeepSeek Key'],['paid','Castle 案卷额度'],['trial','两间密室体验']] as const).map(([value,label])=><button type="button" key={value} aria-pressed={mode===value} onClick={()=>setMode(value)}>{label}</button>)}<button type="button" onClick={()=>setDemo(!demo)}>免费参观示范庭审</button></div>
    {demo&&<article className="demo-hearing"><b>虚构案卷 · 预先撰写的界面示范，不调用 AI</b><p>来访者问：面对一份充满变化的工作，应该如何选择？</p><div className="demo-columns"><div><h3>守季人 · 八字</h3><p>这份虚构证词强调工作节奏与持续投入。可以先观察新岗位能否提供稳定的学习周期。</p></div><div><h3>星图制图师 · 西占</h3><p>这份虚构证词强调自主空间与探索。可以具体询问岗位允许多大程度的独立决策。</p></div></div><h3>Tribunal</h3><p>两者都关注工作环境，但稳定节奏与自主空间并不互相排斥。这属于侧重点不同，不能仅凭措辞判定为冲突。</p><h3>一次反驳与结语</h3><p>守季人认可稳定不等于重复；制图师认可自由也需要边界。可比较的行动是向雇主询问工作节奏和决策权限，而不是把两份象征解读当作就业结论。</p></article>}
    {mode==='byok'?<div className="key-panel"><label>DeepSeek API Key<input type="password" autoComplete="off" value={apiKey} onChange={e=>setApiKey(e.target.value)} placeholder="sk-..."/></label><label>模型<select value={model} onChange={e=>setModel(e.target.value)}><option value="deepseek-flash">DeepSeek Flash</option><option value="deepseek-v4-pro">DeepSeek V4 Pro</option></select></label><p>费用由 DeepSeek 向你的账户收取，Castle 不收取模型额度。调用失败不会切换到 Castle Key。</p>{!window.isSecureContext&&<p className="warning">当前连接不是 HTTPS，请勿在公共网络输入 Key。</p>}</div>:<div>
      <p>{mode==='trial'?(billing?.trial_available?'每个账户可领取一次 5 点：两份独立解读与一次 Tribunal。领取后仍受全站体验预算限制。':'免费 AI 体验尚未开放；你仍可免费排盘、查看示范或使用自己的 Key。'):(billing?.hosted_available?'Castle 额度用于 Flash 解读，无需自己申请 API Key。':'Castle 托管 AI 尚未开放，目前可使用自带 Key。')}</p>
      {!account?<form className="account-form" onSubmit={login}><label>用户名<input autoComplete="username" required minLength={3} maxLength={40} pattern="[A-Za-z0-9_-]+" value={username} onChange={e=>setUsername(e.target.value)} placeholder="英文、数字、下划线"/></label><label>密码<input type="password" autoComplete={register?'new-password':'current-password'} required minLength={10} maxLength={128} value={password} onChange={e=>setPassword(e.target.value)}/></label><button disabled={busy}>{register?'创建账户':'登录'}</button><button type="button" onClick={()=>setRegister(!register)}>{register?'已有账户':'注册新账户'}</button><small>登录凭证仅保留在当前标签页。内测版暂无自助找回密码，请妥善保存。</small></form>:<div className="wallet"><b>{account.username}</b><p>案卷额度 {account.balances.paid} 点 · 体验 {account.balances.trial} 点{account.balances.sandbox>0&&` · 测试余额 ${account.balances.sandbox} 点（不能调用真实 AI）`}</p>{!account.trial_claimed&&billing?.trial_available&&<button type="button" onClick={claim}>领取两间密室体验</button>}<button type="button" onClick={logout}>退出账户</button><details><summary>最近额度记录</summary>{account.ledger.map((row,i)=><p key={i}>{row.delta>0?'+':''}{row.delta} · {row.reason}</p>)}</details></div>}
      <div className="pack-grid">{billing?.packs.map(pack=><article key={pack.id}><b>{pack.name}</b><p>{pack.credits} 点</p><small>{pack.id==='dossier'?'可用于七份报告、Tribunal 和一轮七室追问。':'可用于一轮七室追问，或多轮较小庭审。'}</small><button type="button" disabled={!account||busy||billing.payment_mode!=='test'} onClick={()=>buy(pack.id)}>{billing.payment_mode==='test'?'测试购买 · 不收真钱':'购买尚未开放'}</button></article>)}</div><p className="note">报告 2 点／间；Tribunal 1 点；追问每间回答 1 点、反驳 1 点，总结 1 点。未完成步骤退还额度，已完成内容可反复阅读。售价尚未设定。</p>
    </div>}{accountError&&<p className="warning" role="status">{accountError}</p>}{error&&<p className="error" role="alert">{error}</p>}
  </section>
}
