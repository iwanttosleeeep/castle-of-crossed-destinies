import test from 'node:test';
import assert from 'node:assert/strict';
import {calculate,calculateWestern,angles} from '../charts.mjs';

const input={systems:['bazi','ziwei','western'],civil:{year:2004,month:12,day:7,hour:12,minute:26},utc:'2004-12-07T04:26:00Z',latitude:39.9,longitude:116.4,standard_offset_hours:8,dst_hours:0,gender:'female',true_solar_time:false,day_boundary:'MIDNIGHT_00'};
test('four pillars and Ziwei palace regression against supplied chart',()=>{
  const r=calculate(input).systems;
  assert.deepEqual(r.bazi.chart.pillars,{year:'甲申',month:'丙子',day:'庚申',hour:'壬午'});
  const soul=r.ziwei.chart.palaces.find(p=>p.name==='命宫');
  assert.equal(soul.ganZhi,'己巳');assert.equal(soul.isBodyPalace,true);
  assert.deepEqual(soul.majorStars,['武曲（平）化科','破军（平）化权']);
  assert.deepEqual(r.ziwei.chart.palaces.find(p=>p.name==='父母').majorStars,['太阳（旺）化忌']);
  assert.equal(r.ziwei.chart.palaces.length,12);
  assert.ok(r.ziwei.facts.some(f=>f.label==='五行局'&&f.value==='木三局'));
  assert.ok(!r.ziwei.facts.some(f=>f.label==='命宫宫'));
});
test('J2000 tropical longitudes and axes match published Swiss-Ephemeris reference',()=>{
  // Source: https://openfate.ai/en/editorial-methodology/calculation-validation
  // A cross-engine regression fixture, not certification of all dates/locations.
  const r=calculateWestern({utc:'2000-01-01T12:00:00Z',latitude:0,longitude:0}).chart;
  const expected={Sun:280.368919,Moon:223.323751,Mercury:271.889277,Venus:241.565788,Mars:327.963302,Jupiter:25.253076,Saturn:40.395639,Uranus:314.809224,Neptune:303.192981,Pluto:251.454708};
  for(const [body,lon] of Object.entries(expected))assert.ok(Math.abs(r.positions[body]-lon)<0.02,body);
  assert.ok(Math.abs(r.angles.asc-11.3739)<0.002);
  assert.ok(Math.abs(r.angles.mc-279.6111)<0.002);
});
test('same absolute instant has same term pillars overseas, on both sides of LiChun',()=>{
  for(const minute of [20,40]) {
    const east=calculate({...input,systems:['bazi'],civil:{year:2024,month:2,day:4,hour:16,minute},utc:`2024-02-04T08:${minute}:00Z`}).systems.bazi.chart.pillars;
    const west=calculate({...input,systems:['bazi'],civil:{year:2024,month:2,day:4,hour:3,minute},utc:`2024-02-04T08:${minute}:00Z`,longitude:-74,latitude:40.7,standard_offset_hours:-5}).systems.bazi.chart.pillars;
    assert.equal(east.year,west.year);assert.equal(east.month,west.month);
    assert.equal(east.year,minute===20?'癸卯':'甲辰');
    assert.equal(east.month,minute===20?'乙丑':'丙寅');
  }
});
test('true solar time can roll back a date but never changes western positions',()=>{
  const local={...input,civil:{...input.civil,hour:0,minute:10},utc:'2004-12-06T16:10:00Z',longitude:87.6};
  const standard=calculate(local), solar=calculate({...local,true_solar_time:true});
  assert.equal(solar.chinese_clock.calculation.day,6);
  assert.notEqual(standard.systems.bazi.chart.pillars.day,solar.systems.bazi.chart.pillars.day);
  assert.deepEqual(standard.systems.western,solar.systems.western);
});
test('late Zi day convention is explicit and deterministic',()=>{
  const local={...input,civil:{...input.civil,hour:23,minute:30},utc:'2004-12-07T15:30:00Z'};
  const midnight=calculate(local),zi=calculate({...local,day_boundary:'ZI_HOUR_23'});
  assert.notEqual(midnight.systems.bazi.chart.pillars.day,zi.systems.bazi.chart.pillars.day);
  assert.notDeepEqual(midnight.systems.ziwei.chart,zi.systems.ziwei.chart);
  assert.deepEqual(midnight.systems.western,zi.systems.western);
});
test('western-only needs no Chinese convention/gender and polar houses abstain',()=>{
  const r=calculate({...input,systems:['western'],gender:null,latitude:70});
  assert.equal(r.chinese_clock,null);assert.equal(r.systems.western.chart.angles,null);
  assert.equal(Object.keys(r.systems.western.chart.positions).length,10);
  assert.ok(!r.systems.western.facts.some(f=>f.label==='上升 ASC'));
});
test('DST clock normalization happens once, preserving western UTC',()=>{
  const dst={...input,civil:{year:1990,month:7,day:1,hour:13,minute:0},utc:'1990-07-01T04:00:00Z',dst_hours:1};
  const standard={...dst,civil:{...dst.civil,hour:12},dst_hours:0};
  assert.deepEqual(calculate(dst).systems,calculate(standard).systems);
});
test('ASC/MC move with longitude; facts are finite, unique and bounded',()=>{
  const date=new Date('2000-01-01T12:00:00Z');
  assert.notEqual(angles(date,40,0).asc,angles(date,40,120).asc);
  for(const system of Object.values(calculate(input).systems)) {
    assert.ok(system.facts.length>0&&system.facts.length<=120);
    assert.equal(new Set(system.facts.map(f=>f.id)).size,system.facts.length);
    assert.ok(system.facts.every(f=>f.value&&!f.value.includes('undefined')&&!f.value.includes('NaN')));
  }
});
