// Synthetic boundary fixtures: structural/metamorphic regression, not a claim
// that every astrological convention has been independently certified.
import test from 'node:test';
import assert from 'node:assert/strict';
import {calculate} from '../charts.mjs';
import {vimshottari,calculateNumerology,calculateDreamspell} from '../additional-charts.mjs';
import {longitudeToActivation} from 'hd-chart-engine';

const systems=['bazi','ziwei','western','jyotish','numerology','human_design','dreamspell'];
const base={systems,latitude:0,longitude:0,standard_offset_hours:0,dst_hours:0,
  gender:'female',true_solar_time:false,day_boundary:'MIDNIGHT_00',dreamspell_leap_day:'feb28'};
function input(iso,extra={}) {
  const d=new Date(iso);
  return {...base,civil:{year:d.getUTCFullYear(),month:d.getUTCMonth()+1,day:d.getUTCDate(),hour:d.getUTCHours(),minute:d.getUTCMinutes()},utc:iso,...extra};
}
function finite(value) {
  if(typeof value==='number')assert.ok(Number.isFinite(value));
  else if(value&&typeof value==='object')Object.values(value).forEach(finite);
}
for(const [label,iso,extra] of [
  ['lower supported date','1900-01-01T00:00:00Z',{}],
  ['upper supported date','2099-12-31T23:59:00Z',{}],
  ['century leap day','2000-02-29T12:00:00Z',{}],
  ['lunar leap month first day','2023-03-22T12:00:00Z',{}],
  ['lunar leap month second half','2023-04-06T12:00:00Z',{}],
  ['north supported latitude edge','2024-06-21T12:00:00Z',{latitude:65.999}],
  ['north polar exclusion','2024-06-21T12:00:00Z',{latitude:66}],
  ['south polar exclusion','2024-12-21T12:00:00Z',{latitude:-66}],
  ['east longitude edge','2024-01-01T00:00:00Z',{longitude:179.999}],
  ['west longitude edge','2024-01-01T00:00:00Z',{longitude:-179.999}],
])test(`seven-chamber boundary: ${label}`,()=>{
  const r=calculate(input(iso,extra));
  assert.deepEqual(Object.keys(r.systems),systems);
  finite(r);
  for(const [id,s] of Object.entries(r.systems)) {
    assert.ok(s.facts.length>0&&s.facts.length<=120,id);
    assert.equal(new Set(s.facts.map(f=>f.id)).size,s.facts.length,id);
    assert.ok(s.facts.every(f=>f.value.length<=2500&&!/NaN|undefined|Infinity/.test(f.value)),id);
  }
  assert.equal(r.systems.ziwei.chart.palaces.length,12);
  assert.equal(r.systems.ziwei.chart.palaces.filter(p=>p.isBodyPalace).length,1);
  assert.ok(r.systems.dreamspell.chart.kin>=1&&r.systems.dreamspell.chart.kin<=260);
  const hd=r.systems.human_design.chart;
  assert.ok(Math.abs(hd.solar_arc-88)<0.0001);
  if(Math.abs(extra.latitude||0)>=66){
    assert.equal(r.systems.western.chart.angles,null);
    assert.equal(r.systems.jyotish.chart.lagna,null);
    assert.ok(!r.systems.jyotish.facts.some(f=>f.label==='D1 Lagna'));
  }
});

test('late Zi crosses December/January once; convention switches do not leak',()=>{
  const a=input('2024-12-31T23:00:00Z',{day_boundary:'ZI_HOUR_23'});
  const b=input('2025-01-01T00:00:00Z',{day_boundary:'ZI_HOUR_23'});
  const first=calculate(a),next=calculate(b);
  assert.deepEqual(first.systems.bazi.chart,next.systems.bazi.chart);
  assert.deepEqual(first.systems.ziwei.chart,next.systems.ziwei.chart);
  const midnight=calculate({...a,day_boundary:'MIDNIGHT_00'});
  assert.notEqual(first.systems.bazi.chart.pillars.day,midnight.systems.bazi.chart.pillars.day);
  for(const id of systems.filter(s=>!['bazi','ziwei'].includes(s)))assert.deepEqual(first.systems[id],midnight.systems[id],id);
  assert.deepEqual(calculate(a),first); // iztro's global config must be reset on each calculation
});

test('Vimshottari all 27 exact boundaries share lord and full period balance',()=>{
  const at='2000-01-01T12:00:00Z';
  const lords=['Ketu','Venus','Sun','Moon','Mars','Rahu','Jupiter','Saturn','Mercury'];
  const years=[7,20,6,10,7,18,16,19,17];
  for(let i=0;i<27;i++) {
    const lon=i*360/27;
    const d=vimshottari(lon,at);
    assert.equal(d.birth_lord,lords[i%9],`sector ${i}`);
    assert.equal(d.balance_years,years[i%9],`balance ${i}`);
    assert.equal(d.periods[0].start_utc,at.replace('Z','.000Z'));
    assert.equal(vimshottari(lon-1e-7,at).birth_lord,lords[(i+26)%9]);
    assert.equal(vimshottari(lon+1e-7,at).birth_lord,lords[i%9]);
  }
  for(const lon of [-720,-360,360,720])assert.deepEqual(vimshottari(lon,at),vimshottari(0,at));
});

test('HD wheel has 384 distinct gate/line cells and wraps without losing a cell',()=>{
  const cells=new Set();
  for(let i=0;i<384;i++) {
    const a=longitudeToActivation((223.25+(i+0.5)*0.9375)%360);
    assert.ok(a.g>=1&&a.g<=64);assert.ok(a.l>=1&&a.l<=6);
    cells.add(`${a.g}.${a.l}`);
    const before=longitudeToActivation((223.25+i*0.9375-1e-7+360)%360);
    const after=longitudeToActivation((223.25+i*0.9375+1e-7)%360);
    assert.notDeepEqual([before.g,before.l],[after.g,after.l]);
  }
  assert.equal(cells.size,384);
});

test('Dreamspell progresses on ordinary civil dates, including year/260-cycle wraps',()=>{
  let previous=null;
  for(let day=0;day<800;day++) {
    const d=new Date(Date.UTC(1999,0,1+day));
    if(d.getUTCMonth()===1&&d.getUTCDate()===29)continue;
    const civil={year:d.getUTCFullYear(),month:d.getUTCMonth()+1,day:d.getUTCDate()};
    const c=calculateDreamspell({civil}).chart;
    if(previous!==null)assert.equal(c.kin,previous%260+1);
    assert.equal(c.tone_number,(c.kin-1)%13+1);
    assert.equal(c.seal_number,(c.kin-1)%20+1);
    previous=c.kin;
  }
});

test('Numerology ignores separator spelling, but never fabricates empty name numbers',()=>{
  const date={civil:{year:2000,month:2,day:29}};
  assert.deepEqual(calculateNumerology({...date,numerology_name:"A-B C'D"}).chart,calculateNumerology({...date,numerology_name:'abcd'}).chart);
  const vowels=calculateNumerology({...date,numerology_name:'AEIOU'}).chart;
  assert.equal(vowels.personality,undefined);
  const consonants=calculateNumerology({...date,numerology_name:'BCDFG'}).chart;
  assert.equal(consonants.soul_urge,undefined);
  assert.deepEqual(vowels.life_path,consonants.life_path);
});
