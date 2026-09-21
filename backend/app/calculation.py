"""Offline birth-data normalization and isolated deterministic chart adapter."""
import asyncio
import hashlib
import json
import os
import re
import shutil
from datetime import date, datetime, time, timezone
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import geonamescache
import tzdata
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .providers import SYSTEMS
from .schemas import Fact

RUNNER = Path(__file__).resolve().parents[2] / 'engines' / 'runner.mjs'
calculation_slots = asyncio.Semaphore(2)


class BirthRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    birth_date: date
    birth_time: str | None = Field(default=None, pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    city_id: str | None = Field(default=None, pattern=r'^\d{1,10}$')
    systems: list[Literal['bazi', 'ziwei', 'western', 'jyotish', 'numerology', 'human_design', 'dreamspell']] = Field(min_length=1, max_length=7)
    gender: Literal['male', 'female'] | None = None
    true_solar_time: bool = False
    day_boundary: Literal['MIDNIGHT_00', 'ZI_HOUR_23'] = 'MIDNIGHT_00'
    fold: Literal[0, 1] | None = None
    numerology_name: str | None = Field(default=None, max_length=120)
    numerology_y_vowel: bool = False
    jyotish_node_type: Literal['mean', 'true'] = 'mean'
    dreamspell_leap_day: Literal['feb28', 'mar01'] | None = None

    @model_validator(mode='after')
    def conventions(self):
        if not 1900 <= self.birth_date.year <= 2099:
            raise ValueError('首版支持 1900–2099 年公历日期')
        if len(set(self.systems)) != len(self.systems):
            raise ValueError('体系不可重复')
        if 'ziwei' in self.systems and self.gender is None:
            raise ValueError('紫微引擎需要传统排盘性别参数；不愿提供可取消紫微')
        if set(self.systems) - {'numerology', 'dreamspell'}:
            if self.birth_time is None or self.city_id is None:
                raise ValueError('所选体系需要出生时间与城市；时间不详可只选数秘 / Dreamspell，或使用文档上传')
        else:
            self.birth_time = self.city_id = None
            self.fold = None
        if 'numerology' not in self.systems:
            self.numerology_name = None
            self.numerology_y_vowel = False
        elif self.numerology_name:
            self.numerology_name = self.numerology_name.strip() or None
            if self.numerology_name and not re.fullmatch(r"[A-Za-z][A-Za-z '\-]*", self.numerology_name):
                raise ValueError('姓名数仅支持自行确认的 A–Z 拼写（可含空格、连字符和撇号），不自动音译；也可留空只算日期数')
        if 'dreamspell' in self.systems and self.birth_date.month == 2 and self.birth_date.day == 29 and not self.dreamspell_leap_day:
            raise ValueError('Dreamspell 的 2 月 29 日需要明确选择按 2/28 或 3/1 换算')
        return self


@lru_cache(maxsize=1)
def cities():
    return geonamescache.GeonamesCache().get_cities()


def city_public(city):
    return {key: city[key] for key in ('geonameid', 'name', 'countrycode', 'admin1code', 'latitude', 'longitude', 'timezone')}


@lru_cache(maxsize=1)
def city_index():
    return [(c, {c['name'].casefold(), *(n.casefold() for n in c['alternatenames'])}) for c in cities().values()]


def search_locations(query: str):
    query = query.strip().casefold()
    if len(query) < 2:
        return []
    matches = [(query not in names, -c['population'], c) for c, names in city_index() if any(query in n for n in names)]
    matches.sort(key=lambda x: (x[0], x[1], x[2]['geonameid']))
    return [city_public(c) for _, _, c in matches[:12]]


@lru_cache(maxsize=128)
def pinned_zone(name: str):
    # Do not let host OS tzdb and container tzdb silently disagree.
    resource = files('tzdata.zoneinfo').joinpath(*name.split('/'))
    with resource.open('rb') as handle:
        return ZoneInfo.from_file(handle, key=name)


def resolve_civil(naive: datetime, zone_name: str, fold: int | None = None):
    zone = pinned_zone(zone_name)
    valid = {}
    for candidate in (0, 1):
        aware = naive.replace(tzinfo=zone, fold=candidate)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == naive:
            valid[candidate] = aware
    if not valid:
        raise HTTPException(422, '该钟表时间位于夏令时跳跃造成的不存在时段，请核对出生记录。')
    if len({a.utcoffset() for a in valid.values()}) > 1 and fold is None:
        raise HTTPException(422, '该钟表时间因夏令时回拨出现两次。请在高级设置选择较早或较晚的一次。')
    return valid.get(fold if fold is not None else 0, next(iter(valid.values())))


def normalize_birth(request: BirthRequest):
    city = aware = offset = dst = None
    civil = {'year':request.birth_date.year, 'month':request.birth_date.month, 'day':request.birth_date.day}
    if request.birth_time is not None:
        city = cities().get(request.city_id)
        if not city:
            raise HTTPException(422, '请从搜索结果中选择出生城市；目前使用城市中心坐标。')
        naive = datetime.combine(request.birth_date, time.fromisoformat(request.birth_time))
        aware = resolve_civil(naive, city['timezone'], request.fold)
        offset = aware.utcoffset().total_seconds()/3600
        dst = aware.dst().total_seconds()/3600
        civil.update(hour=naive.hour, minute=naive.minute)
    normalized = {
        'civil': civil,
        'utc': aware.astimezone(timezone.utc).isoformat() if aware else None,
        'latitude': city['latitude'] if city else None, 'longitude': city['longitude'] if city else None,
        'standard_offset_hours':offset-dst if aware else None, 'dst_hours':dst,
        'gender':request.gender, 'systems':request.systems,
        'true_solar_time':request.true_solar_time, 'day_boundary':request.day_boundary,
        'numerology_name':request.numerology_name, 'numerology_y_vowel':request.numerology_y_vowel,
        'jyotish_node_type':request.jyotish_node_type, 'dreamspell_leap_day':request.dreamspell_leap_day,
    }
    metadata = {
        'input': request.model_dump(mode='json'), 'location':city_public(city) if city else None,
        'utc':normalized['utc'], 'utc_offset_hours':offset, 'dst_hours':dst,
        'tzdata_version':tzdata.__version__, 'geonamescache_version':'3.0.1',
        'notice':'需要地点的体系使用 GeoNames 城市中心坐标。输入资料及计算约定随案卷保存；姓名可选，仅用于数秘，确认后也会作为数秘事实发送给解读模型。',
    }
    return normalized, metadata


async def calculate_case(request: BirthRequest):
    normalized, metadata = normalize_birth(request)
    node = os.getenv('CASTLE_NODE_BIN') or shutil.which('node')
    if not node or not RUNNER.is_file():
        raise HTTPException(503, '本地排盘引擎未安装：需要 Node.js，并在 engines 目录运行 npm ci。')
    # Bound both running and waiting work: no unbounded queue of subprocesses.
    try:
        await asyncio.wait_for(calculation_slots.acquire(), timeout=2)
    except TimeoutError:
        raise HTTPException(503, '排盘正在处理其他请求，请稍后重试。') from None
    process = None
    try:
        process = await asyncio.create_subprocess_exec(node, str(RUNNER), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(process.communicate(json.dumps(normalized).encode()), timeout=20)
        if process.returncode:
            raise HTTPException(503, '本地排盘失败，请检查 engines 依赖是否已安装；也可改用文档上传。')
        output = json.loads(stdout)
        metadata.update({k:output[k] for k in ('versions', 'chinese_clock')})
        metadata['engine_lock_sha256'] = hashlib.sha256(RUNNER.with_name('package-lock.json').read_bytes()).hexdigest()
        extractions = {}
        for system in request.systems:
            calculated = output['systems'][system]
            facts = [Fact.model_validate(item).model_dump(mode='json') for item in calculated['facts']]
            if not 1 <= len(facts) <= 120:
                raise ValueError('Unexpected fact count')
            extractions[system] = {
                'system_id':system, 'display_name':SYSTEMS[system],
                'filename':f'自动排盘 · {request.birth_date}', 'extracted_characters':0,
                'extraction_engine':'local_calculation', 'facts':facts,
                'source_commentary':[], 'warnings':calculated['warnings'], 'confirmed':False,
            }
        return extractions, metadata
    except TimeoutError:
        raise HTTPException(504, '本地排盘超时；没有创建不完整案卷，请稍后重试。') from None
    except (OSError, ValueError, KeyError):
        raise HTTPException(503, '本地排盘返回异常；请检查引擎依赖与版本。') from None
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        calculation_slots.release()
