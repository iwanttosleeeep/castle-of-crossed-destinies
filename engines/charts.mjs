import bazi from '@openfate/bazi-engine';
import iztro from 'iztro';
import * as A from 'astronomy-engine';
import {calculateHumanDesign, calculateJyotish, calculateNumerology, calculateDreamspell} from './additional-charts.mjs';

export const VERSIONS = {adapter:'castle-3', bazi:'@openfate/bazi-engine@1.1.3', ziwei:'iztro@2.6.1', western:'astronomy-engine@2.1.19',jyotish:'natalengine@1.6.0 + hd-chart-engine@0.1.1 + Castle',human_design:'hd-chart-engine@0.1.1 + natalengine@1.6.0 tables + Castle',numerology:'castle-pythagorean-1',dreamspell:'castle-dreamspell-1'};
const SIGNS = ['白羊座','金牛座','双子座','巨蟹座','狮子座','处女座','天秤座','天蝎座','射手座','摩羯座','水瓶座','双鱼座'];
const PLANETS = {Sun:'太阳',Moon:'月亮',Mercury:'水星',Venus:'金星',Mars:'火星',Jupiter:'木星',Saturn:'土星',Uranus:'天王星',Neptune:'海王星',Pluto:'冥王星'};
const ELEMENTS = {wood:'木',fire:'火',earth:'土',metal:'金',water:'水'};
const mod = n => (n % 360 + 360) % 360;
const delta = (a,b) => mod(a-b+180)-180;
const radians = d => d*Math.PI/180;
const position = lon => `${SIGNS[Math.floor(mod(lon)/30)]} ${(mod(lon)%30).toFixed(3)}°`;
const dot = (a,b) => a.reduce((s,x,i)=>s+x*b[i],0);
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];

function factsFor(system, rows) {
  return rows.map(([label,value],i)=>({id:`${system}.calculated-${i+1}`,label,value:String(value),time_sensitive:!['numerology','dreamspell'].includes(system),source_span:`本地计算 · ${VERSIONS[system]} · ${VERSIONS.adapter}`}));
}

function chineseClock(input) {
  // The engine supplies the explicitly selected local standard/apparent-solar clock.
  // Its year/month pillars are NOT used: solar-term instants use the UTC+8 calendar.
  return bazi.calculateBaziChart({...input.civil, gender:input.gender || 'female',
    longitude:input.longitude, timezone:input.standard_offset_hours,
    dstOffset:input.dst_hours, enableTrueSolarTime:input.true_solar_time,
    dayBoundaryMode:input.day_boundary});
}

export function calculateBazi(input, clock=chineseClock(input)) {
  const bj = new Date(new Date(input.utc).getTime()+8*3600000);
  const term = bazi.generatePillarsFromSolar(bj.getUTCFullYear(),bj.getUTCMonth()+1,bj.getUTCDate(),bj.getUTCHours(),bj.getUTCMinutes(),bj.getUTCSeconds(),input.day_boundary);
  const dayStem = clock.pillars.day.stem;
  const pillars = {year:term.pillars.year,month:term.pillars.month,day:clock.pillars.day,hour:clock.pillars.hour};
  const rows = [['排盘约定',`公历；年柱立春、月柱按节；节气以绝对时刻比较；日时按${input.true_solar_time?'真太阳时':'当地标准时（已去夏令时）'}；${input.day_boundary==='ZI_HOUR_23'?'23:00':'00:00'}换日`],
    ['计算用日时',JSON.stringify(clock.calendar.calculationSolar)],['日主',`${dayStem}（${ELEMENTS[clock.dayMaster.element]}）`]];
  for (const [key,label] of [['year','年柱'],['month','月柱'],['day','日柱'],['hour','时柱']]) {
    const p = pillars[key];
    rows.push([label,`${p.ganZhi}；天干${ELEMENTS[p.element]}、地支${ELEMENTS[p.branchElement]}；天干十神：${key==='day'?'日主':bazi.calculateTenGod(dayStem,p.stem)}；藏干：${p.hiddenStems.map(h=>`${h.stem}${ELEMENTS[h.element]}（${bazi.calculateTenGod(dayStem,h.stem)}${h.isMain?'，本气':''}）`).join('、')}`]);
  }
  rows.push(['分析边界','仅本命四柱、藏干与十神；未计算大运、起运日期、流年、格局或喜用神。不得把未计算的项目当成已知盘面。']);
  return {facts:factsFor('bazi',rows), chart:{pillars:Object.fromEntries(Object.entries(pillars).map(([k,p])=>[k,p.ganZhi]))},warnings:['首版不提供大运与起运时间；节气或时辰边界附近请与原盘核对。']};
}

export function calculateZiwei(input, clock=chineseClock(input)) {
  const c = clock.calendar.calculationSolar;
  const hourIndex = c.hour===23?12:Math.floor((c.hour+1)/2);
  iztro.astro.config({yearDivide:'normal',horoscopeDivide:'normal',ageDivide:'normal',dayDivide:input.day_boundary==='ZI_HOUR_23'?'forward':'current',algorithm:'default'});
  const chart = iztro.astro.bySolar(`${c.year}-${c.month}-${c.day}`,hourIndex,input.gender==='male'?'男':'女',true,'zh-CN');
  const rows = [['排盘约定',`iztro default；农历正月初一换年；闰月按 fixLeap=true；${input.day_boundary==='ZI_HOUR_23'?'晚子进一日':'晚子不进日'}；${input.true_solar_time?'真太阳时':'当地标准时（已去夏令时）'}。不是八字节气月。`],
    ['农历日期',chart.lunarDate],['五行局',chart.fiveElementsClass],['命主',chart.soul],['身主',chart.body],['排盘性别参数',input.gender==='male'?'男':'女']];
  const star = s => `${s.name}${s.brightness?`（${s.brightness}）`:''}${s.mutagen?`化${s.mutagen}`:''}`;
  const palaces = chart.palaces.map(p=>({name:p.name,ganZhi:p.heavenlyStem+p.earthlyBranch,isBodyPalace:p.isBodyPalace,majorStars:p.majorStars.map(star),minorStars:p.minorStars.map(star),adjectiveStars:p.adjectiveStars.map(star)}));
  for (const p of palaces) rows.push([p.name.endsWith('宫')?p.name:`${p.name}宫`,`${p.ganZhi}${p.isBodyPalace?'；身宫所在':''}；主星：${p.majorStars.join('、')||'空宫（未借星）'}；辅星：${p.minorStars.join('、')||'无'}；杂曜：${p.adjectiveStars.join('、')||'无'}`]);
  rows.push(['分析边界','仅本命十二宫与生年四化；未计算流年、大限、宫干飞化或自化。四化表按 iztro default，不混用其他派别。']);
  return {facts:factsFor('ziwei',rows),chart:{palaces},warnings:['采用 iztro 默认流派。闰月、晚子时与不同四化表可能使其他网站的结果不同。']};
}

export function angles(date, latitude, longitude) {
  const rot = A.Rotation_ECT_EQD(date);
  const vec = (x,y,z) => {const v=A.RotateVector(rot,new A.Vector(x,y,z,date));return [v.x,v.y,v.z]};
  const x=vec(1,0,0), y=vec(0,1,0), normal=cross(x,y);
  const theta=radians(A.SiderealTime(date)*15+longitude), phi=radians(latitude);
  const east=[-Math.sin(theta),Math.cos(theta),0];
  const zenith=[Math.cos(phi)*Math.cos(theta),Math.cos(phi)*Math.sin(theta),Math.sin(phi)];
  let asc=cross(zenith,normal);
  if(dot(asc,east)<0) asc=asc.map(v=>-v);
  let mc=cross(east,normal);
  if(dot(mc,[Math.cos(theta),Math.sin(theta),0])<0) mc=mc.map(v=>-v);
  return {asc:mod(Math.atan2(dot(asc,y),dot(asc,x))*180/Math.PI),mc:mod(Math.atan2(dot(mc,y),dot(mc,x))*180/Math.PI)};
}

export function calculateWestern(input) {
  const date=new Date(input.utc);
  const longitude = (body,at) => A.Ecliptic(A.GeoVector(body,at,true)).elon;
  const positions=Object.fromEntries(Object.keys(PLANETS).map(body=>[body,longitude(body,date)]));
  // Polar horizon/ecliptic intersections need separate convention validation.
  const axes=Math.abs(input.latitude)<66?angles(date,input.latitude,input.longitude):null;
  const rows=[['排盘约定','地心、热带黄道、日期真黄道；整宫制 Whole Sign（非 Placidus）；十颗主要天体；西占使用出生 UTC 瞬间，不套用真太阳时或八字换日。'],['UTC 瞬间',input.utc],['位置精度','天文算法目标约 1 角分；这里的小数位只是显示，不代表测量精度。']];
  if(axes) rows.push(['上升 ASC',position(axes.asc)],['天顶 MC',position(axes.mc)]);
  for(const [body,lon] of Object.entries(positions)) {
    const speed=delta(longitude(body,new Date(+date+3600000)),longitude(body,new Date(+date-3600000)))*12;
    const house=axes?((Math.floor(lon/30)-Math.floor(axes.asc/30)+12)%12)+1:null;
    rows.push([PLANETS[body],`${position(lon)}${house?`；整宫第${house}宫`:''}；${Math.abs(speed)<0.005?'近停滞':speed<0?'逆行':'顺行'}`]);
  }
  const aspects=[];
  const bodies=Object.keys(PLANETS);
  for(let i=0;i<bodies.length;i++) for(let j=i+1;j<bodies.length;j++) {
    const separation=Math.abs(delta(positions[bodies[i]],positions[bodies[j]]));
    for(const [angle,label,orb] of [[0,'合',6],[60,'六合',4],[90,'刑',6],[120,'拱',6],[180,'冲',6]]) {
      if(Math.abs(separation-angle)<=orb) aspects.push(`${PLANETS[bodies[i]]}—${PLANETS[bodies[j]]}：${label}（偏离 ${Math.abs(separation-angle).toFixed(2)}°）`);
    }
  }
  rows.push(['主要相位',aspects.join('；')||'在所选容许度内无主要相位'],['相位容许度','合/刑/拱/冲 6°，六合 4°；未区分入相出相。'],['分析边界','未计算月交点、小行星、推运或行运；整宫宫头不等于 ASC 度数，MC 不一定在第十宫。']);
  return {facts:factsFor('western',rows),chart:{positions,angles:axes,house_system:'whole_sign'},warnings:axes?['首版仅整宫制；与 Placidus 报告的宫位不同是预期差异。']:['高纬度首版仅提供行星与相位，不输出上升、天顶或宫位。']};
}

export function calculate(input) {
  const clock=input.systems.some(s=>['bazi','ziwei'].includes(s))?chineseClock(input):null;
  const result={};
  for(const system of input.systems) {
    if(system==='bazi') result[system]=calculateBazi(input,clock);
    else if(system==='ziwei') result[system]=calculateZiwei(input,clock);
    else if(system==='western') result[system]=calculateWestern(input);
    else if(system==='human_design') result[system]=calculateHumanDesign(input);
    else if(system==='jyotish') result[system]=calculateJyotish(input,Math.abs(input.latitude)<66?angles(new Date(input.utc),input.latitude,input.longitude):null);
    else if(system==='numerology') result[system]=calculateNumerology(input);
    else if(system==='dreamspell') result[system]=calculateDreamspell(input);
    else throw new Error('Unsupported system');
    if(result[system].rows){result[system].facts=factsFor(system,result[system].rows);delete result[system].rows}
  }
  return {systems:result,versions:VERSIONS,chinese_clock:clock?{calculation:clock.calendar.calculationSolar,solar_time:clock.solarTimeInfo}:null};
}
