import test from 'node:test';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {calculate,angles} from '../charts.mjs';
import {humanDesignAt,deriveBodygraph,calculateJyotish,vimshottari,calculateNumerology,calculateDreamspell,reduceNumber} from '../additional-charts.mjs';

const input={civil:{year:2004,month:12,day:7,hour:12,minute:26},utc:'2004-12-07T04:26:00Z',latitude:26.266667,longitude:104.016667,standard_offset_hours:8,dst_hours:0,gender:'female',true_solar_time:false,day_boundary:'MIDNIGHT_00'};
const dateInput=(year,month,day)=>({civil:{year,month,day}});

test('HD reference: 26 activations and core classification, without copying report prose',()=>{
  // Anonymized local reference from a Maia Mechanics / Jovian Archive export.
  const h=humanDesignAt(input.utc);
  assert.equal(h.type,'Generator');assert.equal(h.authority,'Sacral');assert.equal(h.profile,'5/1');
  assert.equal(h.groups.length,2);assert.deepEqual(h.cross,[5,35,47,22]);
  const expected={personality:{sun:'5.5',earth:'35.5',moon:'48.2',north_node:'3.6',south_node:'50.6',mercury:'11.1',venus:'1.6',mars:'1.5',jupiter:'48.6',saturn:'56.1',uranus:'55.4',neptune:'19.6',pluto:'26.6'},design:{sun:'47.1',earth:'22.1',moon:'62.2',north_node:'27.2',south_node:'28.2',mercury:'29.6',venus:'31.2',mars:'47.3',jupiter:'6.5',saturn:'62.4',uranus:'55.5',neptune:'19.6',pluto:'26.3'}};
  for(const [side,bodies] of Object.entries(expected))for(const [body,value] of Object.entries(bodies)) {
    const a=h.activations[side][body];assert.equal(`${a.gate}.${a.line}`,value,`${side}/${body}`);
  }
});

test('HD derives types/authority from connected complete channels, not hanging gates',()=>{
  const fixtures=[ [[], 'Reflector','Lunar'], [[27,50],'Generator','Sacral'], [[20,34],'Manifesting Generator','Sacral'], [[21,45],'Manifestor','Ego Manifested'], [[11,56],'Projector','Mental / Environmental'], [[37,40],'Projector','Emotional'], [[1,8],'Projector','Self Projected'], [[25,51],'Projector','Ego Projected'], [[57,20],'Projector','Splenic'] ];
  for(const [gates,type,authority] of fixtures){const h=deriveBodygraph(gates);assert.equal(h.type,type);assert.equal(h.authority,authority)}
  const hanging=deriveBodygraph([5]);
  assert.equal(hanging.type,'Reflector');assert.equal(hanging.centers.find(c=>c.key==='sacral').status,'undefined');
  assert.equal(hanging.centers.find(c=>c.key==='head').status,'open');
  // A motor in an unrelated connected component does not make a Manifestor.
  assert.equal(deriveBodygraph([11,56,27,50]).type,'Generator');
});

test('HD Design solves a solar arc, including seasonal / 0-degree wrap cases',()=>{
  for(const year of [1900,1950,2000,2050,2099])for(const month of ['01','04','07','10']) {
    const utc=`${year}-${month}-01T00:00:00Z`,h=humanDesignAt(utc);
    assert.ok(Math.abs(h.solar_arc-88)<0.0001,utc);
    const days=(Date.parse(utc)-Date.parse(h.design_utc))/86400000;
    assert.ok(days>80&&days<100);
    for(const side of Object.values(h.activations))for(const a of Object.values(side)) {
      assert.ok(a.gate>=1&&a.gate<=64);assert.ok(a.line>=1&&a.line<=6);
    }
  }
});

test('Jyotish chart layers and reference placements are separated',()=>{
  const j=calculateJyotish(input,angles(new Date(input.utc),input.latitude,input.longitude)).chart;
  assert.equal(j.positions.sun.rashi,'Vrishchika');assert.equal(j.positions.sun.nakshatra,'Jyeshtha');assert.equal(j.positions.sun.pada,2);assert.equal(j.positions.sun.navamsa,'Makara');
  assert.equal(j.positions.moon.rashi,'Kanya');assert.equal(j.positions.moon.nakshatra,'Hasta');assert.equal(j.positions.moon.pada,3);
  assert.equal(Math.floor(j.lagna/30),10);
  assert.ok(Math.abs(Math.abs(j.positions.rahu.longitude-j.positions.ketu.longitude)-180)<1e-9);
  assert.equal(j.dasha.birth_lord,'Moon');
  // Source report does not specify ayanamsa: compare angular placement within
  // 0.03 degrees, not exact dasha dates (small lunar offsets amplify to days).
  assert.ok(Math.abs(j.positions.moon.longitude-(150+16+45/60+48.06/3600))<0.03);
  const truth=calculateJyotish({...input,jyotish_node_type:'true'},null);
  assert.notEqual(truth.chart.positions.rahu.longitude,j.positions.rahu.longitude);
  assert.equal(truth.chart.lagna,null);assert.ok(!truth.rows.some(([label])=>label==='D1 Lagna'));
});

test('Jyotish J2000 positions derive from the documented sidereal convention',()=>{
  const j=calculateJyotish({utc:'2000-01-01T12:00:00Z'},null).chart;
  assert.equal(j.ayanamsa,23.856944);
  assert.ok(Math.abs(j.positions.sun.longitude-(280.368919-23.856944))<0.02);
  assert.ok(Math.abs(j.positions.rahu.longitude-(125.0445479-23.856944))<1e-9);
});

test('Vimshottari uses fractional nakshatra balance and continuous 120-year cycles',()=>{
  const at='2000-01-01T12:00:00Z';
  for(const moon of [0,6.6666666667,13.3333333334,179.99,359.99]) {
    const d=vimshottari(moon,at),first=d.periods[0];
    assert.ok(Date.parse(first.start_utc)<=Date.parse(at));assert.ok(Date.parse(first.end_utc)>Date.parse(at));
    assert.equal(d.periods.reduce((n,p)=>n+p.years,0),120);
    for(let i=1;i<9;i++)assert.equal(d.periods[i].start_utc,d.periods[i-1].end_utc);
  }
  assert.equal(vimshottari(0,at).balance_years,7);
  assert.ok(Math.abs(vimshottari(6.6666666667,at).balance_years-3.5)<1e-8);
});

test('Numerology uses disclosed reduction, optional name and explicit Y rule',()=>{
  assert.equal(calculateNumerology(dateInput(1980,10,22)).chart.life_path.value,5);
  assert.deepEqual(reduceNumber(29),{value:11,steps:[29,11]});
  const n=calculateNumerology({...dateInput(1980,10,22),numerology_name:'John Doe'}).chart;
  assert.equal(n.expression.value,8);assert.equal(n.soul_urge.value,8);assert.equal(n.personality.value,9);
  assert.equal(calculateNumerology(dateInput(1980,10,22)).chart.expression,undefined);
  const a=calculateNumerology({...dateInput(1980,10,22),numerology_name:'Y',numerology_y_vowel:false}).chart;
  const b=calculateNumerology({...dateInput(1980,10,22),numerology_name:'Y',numerology_y_vowel:true}).chart;
  assert.equal(a.soul_urge,undefined);assert.equal(b.personality,undefined);assert.equal(a.expression.value,b.expression.value);
  assert.throws(()=>calculateNumerology({...input,numerology_name:'张三'}));
});

test('Dreamspell agrees with published Law of Time date examples and reference Kin',()=>{
  // https://www.lawoftime.org/pdfs/OvertoneMoon.pdf, year/month tables and examples.
  for(const [year,month,day,kin] of [[1940,10,9,114],[2001,9,11,251],[2004,6,8,211],[1987,8,16,55],[2004,12,7,133]])assert.equal(calculateDreamspell(dateInput(year,month,day)).chart.kin,kin);
  const d=calculateDreamspell(dateInput(2004,12,7)).chart;
  assert.equal(d.tone,'Electric');assert.equal(d.seal,'Red Skywalker');
  assert.throws(()=>calculateDreamspell(dateInput(2004,2,29)));
  for(const [choice,month,day] of [['feb28',2,28],['mar01',3,1]])assert.equal(calculateDreamspell({...dateInput(2004,2,29),dreamspell_leap_day:choice}).chart.kin,calculateDreamspell(dateInput(2004,month,day)).chart.kin);
  assert.equal(calculateDreamspell(dateInput(2004,3,1)).chart.kin,calculateDreamspell(dateInput(2004,2,28)).chart.kin+1);
});

test('all seven yield bounded facts with no missing values; name stays in its chamber',()=>{
  const systems=['bazi','ziwei','western','jyotish','numerology','human_design','dreamspell'];
  const r=calculate({...input,systems,numerology_name:'John Doe'});
  assert.deepEqual(Object.keys(r.systems),systems);
  for(const [id,s] of Object.entries(r.systems)) {
    assert.ok(s.facts.length>0&&s.facts.length<=120);
    assert.equal(new Set(s.facts.map(f=>f.id)).size,s.facts.length);
    assert.ok(s.facts.every(f=>f.value&&!/undefined|NaN/.test(f.value)));
    assert.ok(s.facts.every(f=>f.id.startsWith(`${id}.`)));
    if(id!=='numerology')assert.ok(!JSON.stringify(s).includes('JOHN DOE'));
  }
  const dates=calculate({systems:['numerology','dreamspell'],...dateInput(2004,12,7)});
  assert.equal(dates.chinese_clock,null);
  assert.ok(Object.values(dates.systems).every(s=>s.facts.every(f=>!f.time_sensitive)));
});

test('remaining engines are independent of the server timezone',()=>{
  const runner=new URL('../runner.mjs',import.meta.url);
  const payload=JSON.stringify({...input,systems:['human_design','jyotish','numerology','dreamspell']});
  const run=TZ=>execFileSync(process.execPath,[fileURLToPath(runner)],{input:payload,env:{...process.env,TZ},encoding:'utf8'});
  assert.equal(run('UTC'),run('America/Los_Angeles'));
});
