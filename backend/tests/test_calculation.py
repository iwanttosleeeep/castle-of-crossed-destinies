import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from backend.app import main
from backend.app.calculation import BirthRequest, calculate_case, normalize_birth, resolve_civil, search_locations
from backend.app.schemas import FactConfirmation
from backend.app.store import CaseStore


def birth(**changes):
    return BirthRequest(**({'birth_date':'2004-12-07','birth_time':'12:26','city_id':'1816670','systems':['bazi','ziwei','western'],'gender':'female'} | changes))


class BirthValidationTests(unittest.TestCase):
    def test_chinese_search_and_timezone(self):
        self.assertEqual(search_locations('北京')[0]['geonameid'],1816670)
        normalized, metadata = normalize_birth(birth())
        self.assertEqual(normalized['utc'],'2004-12-07T04:26:00+00:00')
        self.assertEqual(metadata['location']['timezone'],'Asia/Shanghai')
        self.assertEqual(metadata['tzdata_version'],'2025.2')

    def test_invalid_or_unsupported_input_is_rejected(self):
        for changes in ({'systems':['tarot']},{'systems':['bazi','bazi']},{'systems':[]},{'birth_time':'25:00'}, {'birth_date':'1899-12-31'},{'gender':None},{'birth_time':None},{'city_id':None}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                birth(**changes)
        with self.assertRaises(HTTPException):
            normalize_birth(birth(city_id='9999999999'))
        self.assertIsNone(birth(systems=['western'],gender=None).gender)

    def test_date_only_optional_name_and_leap_conventions(self):
        request=BirthRequest(birth_date='2004-12-07',systems=['numerology','dreamspell'])
        normalized, metadata=normalize_birth(request)
        self.assertIsNone(normalized['utc'])
        self.assertIsNone(metadata['location'])
        self.assertEqual(normalized['civil'],{'year':2004,'month':12,'day':7})
        with self.assertRaises(ValidationError):
            BirthRequest(birth_date='2004-02-29',systems=['dreamspell'])
        self.assertEqual(BirthRequest(birth_date='2004-02-29',systems=['dreamspell'],dreamspell_leap_day='mar01').dreamspell_leap_day,'mar01')
        with self.assertRaises(ValidationError):
            birth(systems=['numerology'],numerology_name='张三')
        self.assertIsNone(birth(systems=['western'],numerology_name='John Doe').numerology_name)
        self.assertIsNone(birth(systems=['numerology'],numerology_name='   ').numerology_name)
        self.assertIsNone(birth(systems=['numerology']).city_id)

    def test_dst_gap_rejected_and_fold_requires_explicit_choice(self):
        with self.assertRaises(HTTPException):
            resolve_civil(datetime(2024,3,10,2,30),'America/New_York')
        with self.assertRaises(HTTPException):
            resolve_civil(datetime(2024,11,3,1,30),'America/New_York')
        early=resolve_civil(datetime(2024,11,3,1,30),'America/New_York',0).astimezone(timezone.utc)
        late=resolve_civil(datetime(2024,11,3,1,30),'America/New_York',1).astimezone(timezone.utc)
        self.assertEqual((late-early).total_seconds(),3600)

    def test_chinese_historical_dst_is_not_todays_offset(self):
        normalized, _ = normalize_birth(birth(birth_date='1990-07-01',birth_time='13:00'))
        self.assertEqual(normalized['dst_hours'],1)
        self.assertEqual(normalized['standard_offset_hours'],8)
        self.assertEqual(normalized['utc'],'1990-07-01T04:00:00+00:00')


class CalculationWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.old_store=main.store
        main.store=CaseStore(Path(self.temporary.name)/'test.db')

    def tearDown(self):
        main.store=self.old_store
        self.temporary.cleanup()

    async def test_real_engine_no_api_key_restore_confirm_and_reports(self):
        with patch('backend.app.main.extract_facts_only',new=AsyncMock()) as extractor:
            created=await main.create_calculated_case(birth(systems=['bazi','ziwei','western','jyotish','numerology','human_design','dreamspell'],numerology_name='John Doe'))
        extractor.assert_not_awaited()
        token=created['resume_token'];case_id=created['case_id']
        self.assertEqual(created['status'],'awaiting_confirmation')
        self.assertEqual(set(created['extractions']),{'bazi','ziwei','western','jyotish','numerology','human_design','dreamspell'})
        restored=await main.restore_case(case_id,token)
        self.assertEqual(restored['calculation'],created['calculation'])
        self.assertEqual(restored['confirmed_facts'],{})
        for system, extraction in created['extractions'].items():
            self.assertEqual(extraction['extraction_engine'],'local_calculation')
            self.assertFalse(extraction['confirmed'])
            await main.confirm_facts(case_id,system,FactConfirmation(facts=extraction['facts']),token)
        chamber=AsyncMock(return_value=('本命盘解读',None))
        tribunal=AsyncMock(return_value=('共识与分歧',None))
        with patch('backend.app.main.run_guided_chamber',chamber),patch('backend.app.main.run_guided_tribunal',tribunal):
            assembled=await main.create_reports(case_id,token,None,None)
        self.assertEqual(chamber.await_count,7)
        for call in chamber.call_args_list:
            self.assertTrue(all(f.id.startswith(call.args[0]+'.') for f in call.args[2]))
            if call.args[0]!='numerology':
                self.assertFalse(any('JOHN DOE' in f.value for f in call.args[2]))
        self.assertEqual(assembled['status'],'reports_ready')
        exported=(await main.export_case(case_id,token)).body.decode()
        self.assertIn('Local calculation provenance',exported)
        self.assertIn('Asia/Shanghai',exported)
        self.assertIn('本命盘解读',exported)
        self.assertNotIn(token,exported)

    async def test_date_only_real_engines_save_and_export_without_place(self):
        created=await main.create_calculated_case(BirthRequest(birth_date='2004-12-07',systems=['numerology','dreamspell']))
        self.assertIsNone(created['calculation']['location'])
        self.assertIsNone(created['calculation']['utc'])
        self.assertEqual(next(f['value'] for f in created['extractions']['dreamspell']['facts'] if f['label']=='Kin'),'133')
        exported=(await main.export_case(created['case_id'],created['resume_token'])).body.decode()
        self.assertIn('Local calculation provenance',exported)

    async def test_missing_engine_is_actionable_and_creates_no_case(self):
        with patch('backend.app.calculation.shutil.which',return_value=None),patch.dict('os.environ',{},clear=True):
            with self.assertRaises(HTTPException) as error:
                await main.create_calculated_case(birth())
        self.assertEqual(error.exception.status_code,503)
        self.assertIn('npm ci',error.exception.detail)

    async def test_concurrent_calculations_are_isolated(self):
        a,b=await asyncio.gather(calculate_case(birth(day_boundary='MIDNIGHT_00',birth_time='23:30')),calculate_case(birth(day_boundary='ZI_HOUR_23',birth_time='23:30')))
        get_day=lambda result: next(f['value'] for f in result[0]['bazi']['facts'] if f['label']=='日柱')
        self.assertNotEqual(get_day(a),get_day(b))
