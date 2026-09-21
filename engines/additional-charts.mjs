import * as A from 'astronomy-engine';
import {createAstronomyEngine, findDesignJD, longitudeToActivation} from 'hd-chart-engine';
import {CHANNELS, GATES, calculateLahiriAyanamsa, getNakshatra, getRashi, DASHA_ORDER, DASHA_YEARS} from 'natalengine';

const mod = (n,m=360) => (n%m+m)%m;
const JD_UNIX=2440587.5, DAY_MS=86400000;
const ephemeris=createAstronomyEngine();
const planetNames={sun:'太阳',earth:'地球',moon:'月亮',north_node:'北交点',south_node:'南交点',mercury:'水星',venus:'金星',mars:'火星',jupiter:'木星',saturn:'土星',uranus:'天王星',neptune:'海王星',pluto:'冥王星'};
const centerNames={head:'头顶中心',ajna:'阿基那中心',throat:'喉中心',g:'G 中心',heart:'意志力中心',sacral:'荐骨中心',spleen:'脾中心',solar:'情绪中心',root:'根部中心'};
const instantJD = utc => Date.parse(utc)/DAY_MS+JD_UNIX;

// NatalEngine supplies the canonical channel/gate table. Derivation is kept
// separate from its prose, biological claims and sub-line interpretations.
export function deriveBodygraph(gates) {
  const active=new Set(gates);
  const channels=CHANNELS.filter(c=>c.gates.every(g=>active.has(g)));
  const graph=new Map();
  for(const {centers:[a,b]} of channels) {
    if(!graph.has(a))graph.set(a,new Set());
    if(!graph.has(b))graph.set(b,new Set());
    graph.get(a).add(b);graph.get(b).add(a);
  }
  const groups=[],visited=new Set();
  for(const start of graph.keys()) {
    if(visited.has(start))continue;
    const group=[],queue=[start];visited.add(start);
    while(queue.length) {
      const current=queue.pop();group.push(current);
      for(const next of graph.get(current))if(!visited.has(next)){visited.add(next);queue.push(next)}
    }
    groups.push(group);
  }
  const throatGroup=groups.find(g=>g.includes('throat'))||[];
  const motorToThroat=['sacral','solar','heart','root'].some(c=>throatGroup.includes(c));
  const defined=c=>graph.has(c);
  const type=!graph.size?'Reflector':defined('sacral')?(motorToThroat?'Manifesting Generator':'Generator'):(motorToThroat?'Manifestor':'Projector');
  const authority=defined('solar')?'Emotional':defined('sacral')?'Sacral':defined('spleen')?'Splenic':defined('heart')?(throatGroup.includes('heart')?'Ego Manifested':'Ego Projected'):defined('g')?'Self Projected':graph.size?'Mental / Environmental':'Lunar';
  const centers=Object.keys(centerNames).map(key=>({key,status:defined(key)?'defined':Object.entries(GATES).some(([g,v])=>v.center===key&&active.has(Number(g)))?'undefined':'open'}));
  return {type,authority,groups,centers,channels:channels.map(c=>({gates:c.gates,centers:c.centers}))};
}

export function humanDesignAt(utc) {
  const jd=instantJD(utc),designJD=findDesignJD(jd,ephemeris.sunLongitude.bind(ephemeris));
  const raw={personality:ephemeris.bodyLongitudes(jd),design:ephemeris.bodyLongitudes(designJD)};
  const activations=Object.fromEntries(Object.entries(raw).map(([side,bodies])=>[side,Object.fromEntries(Object.entries(bodies).map(([body,longitude])=>{
    const {g,l}=longitudeToActivation(longitude);
    return [body,{gate:g,line:l,longitude}];
  }))]));
  const active=Object.values(activations).flatMap(side=>Object.values(side).map(a=>a.gate));
  const p=activations.personality,d=activations.design;
  return {...deriveBodygraph(active),activations,profile:`${p.sun.line}/${d.sun.line}`,cross:[p.sun.gate,p.earth.gate,d.sun.gate,d.earth.gate],design_utc:new Date((designJD-JD_UNIX)*DAY_MS).toISOString(),solar_arc:mod(raw.personality.sun-raw.design.sun)};
}

export function calculateHumanDesign(input) {
  const chart=humanDesignAt(input.utc);
  const typeNames={Generator:'生产者', 'Manifesting Generator':'显示生产者',Manifestor:'显示者',Projector:'投射者',Reflector:'反映者'};
  const authorityNames={Emotional:'情绪权威',Sacral:'荐骨权威',Splenic:'脾权威','Ego Manifested':'意志力显示权威','Ego Projected':'意志力投射权威','Self Projected':'自我投射权威','Mental / Environmental':'无内在权威／环境与表达过程',Lunar:'月亮权威'};
  const strategy={Generator:'等待回应', 'Manifesting Generator':'等待回应；行动涉及他人时告知',Manifestor:'告知',Projector:'等待邀请',Reflector:'等待一个月亮周期'};
  const signature={Generator:'满足／挫败', 'Manifesting Generator':'满足／挫败',Manifestor:'平和／愤怒',Projector:'成功／苦涩',Reflector:'惊喜／失望'};
  const definitions=['无定义','一分人','二分人','三分人','四分人'];
  const rows=[['计算约定','热带黄道、地心视位置；真月交点（轨道法近似）；Design 为太阳弧回溯 88°，不是减 88 天。仅输出 gate/line，不输出 color/tone/base 或四箭头。'],
    ['类型',`${typeNames[chart.type]} / ${chart.type}`],['内在权威',`${authorityNames[chart.authority]} / ${chart.authority}`],['策略（体系术语）',strategy[chart.type]],['标志／非自己主题（体系术语）',signature[chart.type]],
    ['人生角色 Profile',chart.profile],['定义 Definition',`${definitions[chart.groups.length]}；${chart.groups.length} 个连通分组`],['Design UTC',chart.design_utc],['太阳弧回溯',`${chart.solar_arc.toFixed(5)}°`],
    ['轮回交叉四闸门',`${chart.cross[0]}/${chart.cross[1]} | ${chart.cross[2]}/${chart.cross[3]}（仅计算四闸门，未核验交叉名称，不自行补名）`]];
  for(const [side,label] of [['personality','人格／黑'],['design','设计／红']]) {
    for(const [body,a] of Object.entries(chart.activations[side])) rows.push([`${label} · ${planetNames[body]}`,`${a.gate}.${a.line}`]);
  }
  rows.push(['完整通道',chart.channels.map(c=>c.gates.join('–')).join('、')||'无完整通道']);
  for(const status of ['defined','undefined','open']) rows.push([{defined:'已定义中心',undefined:'未定义但有激活闸门的中心',open:'完全开放中心（无激活闸门）'}[status],chart.centers.filter(c=>c.status===status).map(c=>centerNames[c.key]).join('、')||'无']);
  rows.push(['定义连通分组',chart.groups.map(g=>g.map(c=>centerNames[c]).join('—')).join('；')||'无']);
  const warnings=['这是现代象征系统的计算，不是生物学结论；分钟误差或天体落在闸门/爻线边界可能改变结果。'];
  // A one-arcminute uncertainty band, independent of the upstream precision label.
  const nearBoundary=Object.entries(chart.activations).flatMap(([side,values])=>Object.entries(values).filter(([,a])=>{
    const offset=mod(a.longitude-223.25,0.9375);return Math.min(offset,0.9375-offset)<1/60;
  }).map(([body])=>`${side}/${body}`));
  if(nearBoundary.length)warnings.push(`以下激活接近爻线边界（1′内），需要更精确出生记录或外部盘复核：${nearBoundary.join('、')}`);
  return {rows,chart,warnings};
}

export function vimshottari(moonLongitude,utc) {
  const fraction=mod(moonLongitude,360/27)/(360/27);
  const index=Math.floor(mod(moonLongitude)/(360/27))%9;
  const yearMs=365.25*DAY_MS;
  let start=Date.parse(utc)-fraction*DASHA_YEARS[DASHA_ORDER[index]]*yearMs;
  const periods=[];
  for(let i=0;i<9;i++) {
    const lord=DASHA_ORDER[(index+i)%9],years=DASHA_YEARS[lord],end=start+years*yearMs;
    periods.push({lord,years,start_utc:new Date(start).toISOString(),end_utc:new Date(end).toISOString()});start=end;
  }
  return {birth_lord:DASHA_ORDER[index],balance_years:(1-fraction)*DASHA_YEARS[DASHA_ORDER[index]],year_days:365.25,periods};
}

export function calculateJyotish(input,axes) {
  const jd=instantJD(input.utc),ayanamsa=calculateLahiriAyanamsa(jd);
  const raw=ephemeris.bodyLongitudes(jd);
  const nodeType=input.jyotish_node_type||'mean';
  const t=(jd-2451545)/36525;
  const rahu=nodeType==='true'?raw.north_node:mod(125.0445479-1934.1362891*t+0.0020754*t*t+t*t*t/467441-t*t*t*t/60616000);
  const names={sun:'太阳 Surya',moon:'月亮 Chandra',mars:'火星 Mangala',mercury:'水星 Budha',jupiter:'木星 Guru',venus:'金星 Shukra',saturn:'土星 Shani',rahu:'罗睺 Rahu',ketu:'计都 Ketu'};
  const positions={};
  for(const key of Object.keys(names)) {
    const lon=mod((key==='rahu'?rahu:key==='ketu'?rahu+180:raw[key])-ayanamsa);
    const nak=getNakshatra(lon),rashi=getRashi(lon),navamsa=getRashi(mod(lon*9));
    positions[key]={longitude:lon,rashi:rashi.name,nakshatra:nak.name,pada:nak.pada,navamsa:navamsa.name};
  }
  const lagna=axes?mod(axes.asc-ayanamsa):null;
  const degree=lon=>`${getRashi(lon).name} ${mod(lon,30).toFixed(3)}°`;
  const rows=[['排盘约定',`恒星黄道；Lahiri（NatalEngine 近似式），ayanamsa=${ayanamsa.toFixed(6)}°；整宫；${nodeType==='mean'?'平均':'真'}月交点；D1 与 D9 分开记录。`],['精度与流派边界','该近似岁差式并非 Swiss Ephemeris 的逐位等同实现；不同 ayanamsa、月交点、宫制、岁长会导致差异。临近分盘/宿/爻分界请复核。']];
  if(lagna!==null)rows.push(['D1 Lagna',degree(lagna)],['D9 Lagna',getRashi(mod(lagna*9)).name]);
  for(const [key,p] of Object.entries(positions)) {
    const house=lagna===null?null:mod(Math.floor(p.longitude/30)-Math.floor(lagna/30),12)+1;
    rows.push([`D1 ${names[key]}`,`${degree(p.longitude)}；${p.nakshatra} 第${p.pada}足${house?`；整宫第${house}宫`:''}`],[`D9 ${names[key]}`,p.navamsa]);
  }
  // Planet motion is astronomical, not inferred from zodiac placement.
  for(const key of ['mercury','venus','mars','jupiter','saturn']) {
    const body=key[0].toUpperCase()+key.slice(1),date=new Date(input.utc);
    const lon=offset=>A.Ecliptic(A.GeoVector(body,new Date(+date+offset),true)).elon;
    const speed=(mod(lon(3600000)-lon(-3600000)+180)-180)*12;
    rows.push([`${names[key]} 运动`,Math.abs(speed)<0.005?'近停滞':speed<0?'逆行':'顺行']);
  }
  const dasha=vimshottari(positions.moon.longitude,input.utc);
  rows.push(['Vimshottari 出生大运余额',`${dasha.birth_lord}；余 ${dasha.balance_years.toFixed(4)} 年；固定岁长 365.25 日，仅 Mahadasha，不含 Antardasha。`]);
  dasha.periods.forEach((p,i)=>rows.push([`Mahadasha ${i+1} · ${p.lord}`,`${p.start_utc} 至 ${p.end_utc}${i===0?'（出生时已在此周期内）':''}`]));
  rows.push(['分析边界','D9 的宫位未输出；未计算其他分盘、瑜伽、Shadbala、Ashtakavarga、行运或下级大运，不得把它们当成已知盘面。']);
  const boundaryBodies=Object.entries(positions).filter(([,p])=>{const offset=mod(p.longitude,10/3);return Math.min(offset,10/3-offset)<0.05}).map(([key])=>names[key]);
  return {rows,chart:{positions,lagna,ayanamsa,node_type:nodeType,dasha},warnings:[`采用 Lahiri 近似式与${nodeType==='mean'?'平均':'真'}月交点；不能保证与未注明设置的 Jagannatha Hora 报告逐项相同。`, '大运日期是所选算法的计算值，不代表实际精确到毫秒；月亮位置的小偏差也可能造成数日差异。',...(boundaryBodies.length?[`以下天体距 D9 / 宿足边界小于 0.05°，请复核：${boundaryBodies.join('、')}`]:[]),...(axes?[]:['高纬度暂不输出 Lagna 与宫位。'])]};
}

export function reduceNumber(number,masters=true) {
  const steps=[number];
  while(number>9&&!(masters&&[11,22,33].includes(number))) {
    number=String(number).split('').reduce((n,d)=>n+Number(d),0);steps.push(number);
  }
  return {value:number,steps};
}

export function calculateNumerology(input) {
  const {year,month,day}=input.civil;
  const components=[month,day,year].map(n=>reduceNumber(n));
  const life=reduceNumber(components.reduce((s,c)=>s+c.value,0));
  const birthday=reduceNumber(day);
  const rows=[['算法约定','毕达哥拉斯体系：年月日分别缩减，再相加缩减；各阶段保留 11/22/33。姓名 A–Z 按 1–9 循环赋值，全名各字母直接求和后缩减（不先缩减每个词）。'],
    ['生命路径数 Life Path',`${life.value}；月/日/年：${components.map(c=>c.steps.join('→')).join(' / ')}；合计 ${life.steps.join('→')}`],['生日数 Birthday',`${birthday.value}；原生日 ${day}；${birthday.steps.join('→')}`]];
  const chart={life_path:life,birthday};
  const name=(input.numerology_name||'').trim().toUpperCase();
  if(name) {
    // Input is validated at both boundaries; never silently transliterate/drop Hanzi.
    if(!/^[A-Z][A-Z '\-]*$/.test(name))throw new Error('Unsupported name alphabet');
    const letters=name.replace(/[^A-Z]/g,'');
    const vowelSet=input.numerology_y_vowel?'AEIOUY':'AEIOU';
    const sum=chars=>chars.split('').reduce((s,c)=>s+(c.charCodeAt(0)-65)%9+1,0);
    const vowels=letters.split('').filter(c=>vowelSet.includes(c)).join('');
    const consonants=letters.split('').filter(c=>!vowelSet.includes(c)).join('');
    rows.push(['姓名拼写约定',`${name}；空格/连字符/撇号不计分；Y 视为${input.numerology_y_vowel?'元音':'辅音'}；不自动音译。`]);
    for(const [key,label,chars] of [['expression','表达数 Expression',letters],['soul_urge','灵魂渴望数 Soul Urge',vowels],['personality','人格数 Personality',consonants]]) {
      if(chars.length) {const value=reduceNumber(sum(chars));chart[key]=value;rows.push([label,`${value.value}；${chars} 合计 ${value.steps.join('→')}`]);}
      else rows.push([label,'没有符合所选规则的字母，因此未计算（不是数值 0）。']);
    }
  }
  rows.push(['分析边界',name?'仅输出已列出的核心数；未计算个人年、挑战数、巅峰数或业力结论。':'未提供姓名：只计算日期数，未计算表达数、灵魂渴望数、人格数；不要补造。']);
  return {rows,chart,warnings:[name?'姓名数取决于拼写、缩减法及 Y 的约定；其他计算器不同约定可能得出不同主数。':'姓名可选；本次只提供日期数。']};
}

const SEALS=['Red Dragon','White Wind','Blue Night','Yellow Seed','Red Serpent','White Worldbridger','Blue Hand','Yellow Star','Red Moon','White Dog','Blue Monkey','Yellow Human','Red Skywalker','White Wizard','Blue Eagle','Yellow Warrior','Red Earth','White Mirror','Blue Storm','Yellow Sun'];
const SEALS_ZH=['红龙','白风','蓝夜','黄种子','红蛇','白世界桥','蓝手','黄星星','红月','白狗','蓝猴','黄人','红天行者','白巫师','蓝鹰','黄战士','红地球','白镜','蓝风暴','黄太阳'];
const TONES=['Magnetic','Lunar','Electric','Self-Existing','Overtone','Rhythmic','Resonant','Galactic','Solar','Planetary','Spectral','Crystal','Cosmic'];
const TONES_ZH=['磁性','月亮','电力','自我存在','超频','韵律','共振','银河','太阳','行星','光谱','水晶','宇宙'];
const MONTH_OFFSETS=[0,31,59,90,120,151,181,212,243,273,304,334];

export function calculateDreamspell(input) {
  let {year,month,day}=input.civil;
  const leap=month===2&&day===29;
  if(leap) {
    if(!['feb28','mar01'].includes(input.dreamspell_leap_day))throw new Error('Explicit leap-day convention required');
    [month,day]=input.dreamspell_leap_day==='feb28'?[2,28]:[3,1];
  }
  // Foundation for the Law of Time's published year/month/day table:
  // 2004 year number=52, regular year progression=365; February 29 is outside count.
  const kin=mod(52+(year-2004)*365+MONTH_OFFSETS[month-1]+day-1,260)+1;
  const tone=mod(kin-1,13)+1,seal=mod(kin-1,20)+1;
  const wavespellStart=kin-tone+1;
  const chart={kin,tone_number:tone,tone:TONES[tone-1],seal_number:seal,seal:SEALS[seal-1],wavespell_start_kin:wavespellStart,effective_date:`${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`};
  const rows=[['历法约定','现代 Dreamspell／13 月亮体系，非传统 Maya Tzolk’in 的连续历法换算。使用当地出生公历日期，不使用 UTC 日期或真太阳时；2 月 29 日不进入普通 260 日计数。'],
    ['Kin',String(kin)],['银河调性',`${tone} · ${TONES_ZH[tone-1]} / ${chart.tone}`],['太阳图腾',`${seal} · ${SEALS_ZH[seal-1]} / ${chart.seal}`],['波符位置',`起始 Kin ${wavespellStart}（${SEALS[mod(wavespellStart-1,20)]}）；第 ${tone}/13 天`],
    ['实际换算日期',chart.effective_date+(leap?'（闰日按用户明确选择映射）':'')],['分析边界','未计算五大神谕、城堡、PSI、合盘或流年；不宣称这是历史玛雅历法或已验证的人格预测。']];
  return {rows,chart,warnings:leap?['2 月 29 日是特殊日：官方解码说明建议午前用 2/28、午后用 3/1；这里使用你明确选择的日期。']:['Dreamspell 是现代象征系统，不等同于传统 Maya 历法。']};
}
