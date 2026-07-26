import os
import asyncio
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, UploadFile

from backend.app import main
from backend.app.schemas import BirthProfile, CaseCreateRequest, Fact
from backend.app.store import CaseStore
from backend.app.tribunal import agreement_score


PROFILE = {
    "display_name": "Visitor",
    "birth_date": "2000-01-02",
    "birth_time": "12:30:00",
    "birthplace_text": "Shanghai, China",
    "timezone_name": "Asia/Shanghai",
    "time_precision": "exact",
}


class CaseStoreTests(unittest.TestCase):
    def test_resume_token_is_hashed_and_required(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CaseStore(Path(directory) / "cases.db")
            payload, token = store.create(PROFILE, ["bazi"])
            self.assertIsNotNone(store.get(payload["case_id"], token))
            self.assertIsNone(store.get(payload["case_id"], "wrong-token"))
            with closing(store._connect()) as connection:
                stored_hash = connection.execute("SELECT token_hash FROM cases").fetchone()[0]
            self.assertNotEqual(stored_hash, token)
            self.assertNotIn(token, payload)


class WorkflowApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        os.environ["CASTLE_DB_PATH"] = str(Path(self.temporary.name) / "cases.db")
        main.store = CaseStore(Path(self.temporary.name) / "cases.db")

    def tearDown(self):
        main.store = None
        os.environ.pop("CASTLE_DB_PATH", None)
        self.temporary.cleanup()

    async def create_case(self):
        return await main.create_case(
            CaseCreateRequest(profile=BirthProfile.model_validate(PROFILE), systems=["bazi"])
        )

    async def test_case_can_be_created_and_restored(self):
        created = await self.create_case()
        restored = await main.restore_case(created["case_id"], created["resume_token"])
        self.assertNotIn("resume_token", restored)
        with self.assertRaises(HTTPException) as denied:
            await main.restore_case(created["case_id"], "wrong")
        self.assertEqual(denied.exception.status_code, 404)

    async def test_case_profile_fields_are_all_optional(self):
        created = await main.create_case(
            CaseCreateRequest(profile=BirthProfile(), systems=["bazi"])
        )
        self.assertEqual(
            created["profile"],
            {
                "display_name": None,
                "birth_date": None,
                "birth_time": None,
                "birthplace_text": None,
                "timezone_name": None,
                "time_precision": "unknown",
                "gender_marker": None,
            },
        )

    async def test_text_upload_only_saves_extracted_facts_not_raw_file(self):
        created = await self.create_case()
        extracted = [
            Fact(
                id="bazi.extracted-1-demo",
                label="Day Master",
                value="甲木",
                source_span="PAGE 1: 日主甲木",
                extraction_confidence=0.98,
                time_sensitive=True,
            )
        ]
        with patch("backend.app.main.extract_facts_only", new=AsyncMock(return_value=(extracted, ["excluded interpretation"], None))):
            response = await main.upload_source(
                created["case_id"],
                "bazi",
                UploadFile(
                    file=BytesIO(b"Day Master: Jia Wood. This source text is deliberately not persisted."),
                    filename="chart.txt",
                ),
                created["resume_token"],
                "request-only",
                "deepseek-v4-flash",
            )
        self.assertEqual(response["facts"][0]["value"], "甲木")
        restored = await main.restore_case(created["case_id"], created["resume_token"])
        serialized = str(restored)
        self.assertNotIn("deliberately not persisted", serialized)
        self.assertEqual(restored["extractions"]["bazi"]["facts"][0]["value"], "甲木")

    async def test_parallel_uploads_do_not_overwrite_each_other(self):
        created = await main.create_case(
            CaseCreateRequest(profile=BirthProfile.model_validate(PROFILE), systems=["bazi", "western"])
        )

        async def fake_extract(system_id, *_args, **_kwargs):
            return [Fact(id=f"{system_id}.fact-1", label="Marker", value=system_id)], [], None

        with patch("backend.app.main.extract_facts_only", new=fake_extract):
            await asyncio.gather(
                *(
                    main.upload_source(
                        created["case_id"],
                        system_id,
                        UploadFile(file=BytesIO(f"Synthetic report for {system_id}".encode()), filename=f"{system_id}.txt"),
                        created["resume_token"],
                        "request-only",
                        "deepseek-v4-flash",
                    )
                    for system_id in ("bazi", "western")
                )
            )
        restored = await main.restore_case(created["case_id"], created["resume_token"])
        self.assertEqual(set(restored["extractions"]), {"bazi", "western"})

    async def test_visitor_gemini_key_requires_explicit_data_consent(self):
        created = await self.create_case()
        with self.assertRaises(HTTPException) as denied:
            await main.upload_source(
                created["case_id"],
                "bazi",
                UploadFile(file=BytesIO(b"synthetic visual report"), filename="chart.png"),
                created["resume_token"],
                None,
                None,
                gemini_key="visitor-gemini-key",
                gemini_model="gemini-3.6-flash",
            )
        self.assertEqual(denied.exception.status_code, 428)

    async def test_gemini_visual_success_skips_local_ocr(self):
        created = await self.create_case()
        visual_fact = Fact(
            id="bazi.gemini-1-demo",
            label="Four Pillars",
            value="甲申 丙子 庚申 壬午",
            source_span="PAGE 1, center grid",
            extraction_confidence=0.94,
            time_sensitive=True,
        )
        with patch(
            "backend.app.main.extract_facts_with_gemini",
            new=AsyncMock(return_value=([visual_fact], [], None)),
        ), patch("backend.app.main.extract_bytes", new=AsyncMock(side_effect=AssertionError("OCR should not run"))):
            extraction = await main.upload_source(
                created["case_id"],
                "bazi",
                UploadFile(file=BytesIO(b"synthetic visual report"), filename="chart.png"),
                created["resume_token"],
                None,
                None,
                gemini_key="visitor-gemini-key",
                gemini_model="gemini-3.6-flash",
                gemini_consent="acknowledged",
                gemini_enabled="true",
            )
        self.assertEqual(extraction["extraction_engine"], "gemini_vision")
        self.assertEqual(extraction["facts"][0]["label"], "Four Pillars")

    async def test_server_gemini_key_is_not_used_without_visitor_opt_in(self):
        created = await self.create_case()
        gemini_call = AsyncMock()
        with patch.dict(os.environ, {"GEMINI_API_KEY": "server-key"}), patch(
            "backend.app.main.extract_facts_with_gemini", gemini_call
        ):
            extraction = await main.upload_source(
                created["case_id"],
                "bazi",
                UploadFile(file=BytesIO(b"Day Master: Jia Wood explicit chart fact"), filename="chart.txt"),
                created["resume_token"],
            )
        gemini_call.assert_not_awaited()
        self.assertNotEqual(extraction["extraction_engine"], "gemini_text")


class TribunalScoreTests(unittest.TestCase):
    def test_agreement_score_penalizes_barnum_risk(self):
        specific = [
            {"system_id": "bazi", "specificity": 0.9, "barnum_risk": 0.1},
            {"system_id": "western", "specificity": 0.9, "barnum_risk": 0.1},
        ]
        generic = [item | {"barnum_risk": 0.9} for item in specific]
        self.assertGreater(agreement_score(specific), agreement_score(generic))


if __name__ == "__main__":
    unittest.main()
