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
from backend.app.schemas import CaseCreateRequest, DebateRequest, Fact
from backend.app.store import CaseStore


class CaseStoreTests(unittest.TestCase):
    def test_resume_token_is_hashed_and_required(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CaseStore(Path(directory) / "cases.db")
            payload, token = store.create(["bazi"])
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
        return await main.create_case(CaseCreateRequest(systems=["bazi"]))

    async def test_case_can_be_created_and_restored(self):
        created = await self.create_case()
        restored = await main.restore_case(created["case_id"], created["resume_token"])
        self.assertNotIn("resume_token", restored)
        with self.assertRaises(HTTPException) as denied:
            await main.restore_case(created["case_id"], "wrong")
        self.assertEqual(denied.exception.status_code, 404)

    async def test_case_has_no_personal_profile(self):
        created = await main.create_case(CaseCreateRequest(systems=["bazi"]))
        self.assertNotIn("profile", created)

    async def test_case_export_contains_all_persisted_results_without_secrets(self):
        created = await self.create_case()
        payload = main.get_store().get(created["case_id"], created["resume_token"])
        payload["confirmed_facts"] = {
            "bazi": [
                {
                    "id": "bazi.fact-1",
                    "label": "日主",
                    "value": "<script>甲木</script>",
                    "time_sensitive": False,
                    "source_span": "PAGE 1: 日主甲木",
                }
            ]
        }
        payload["reports"] = {
            "bazi": {"system_id": "bazi", "display_name": "BaZi 八字", "text": "## 八字报告\n\n**正文**"}
        }
        payload["tribunal"] = {"summary": "## 共识\n\n审议正文", "disclaimer": "不是事实证明"}
        payload["debates"] = [
            {
                "id": "hearing-1",
                "question": "如何选择？",
                "guided_answers": [{"system_id": "bazi", "text": "独立回答"}],
                "guided_rebuttals": [{"system_id": "bazi", "text": "一次反驳"}],
                "guided_summary": "主持人总结",
                "warnings": [],
            }
        ]
        main.get_store().save(payload)

        response = await main.export_case(created["case_id"], created["resume_token"])
        markdown = response.body.decode("utf-8")

        self.assertIn("## I. Confirmed dossier", markdown)
        self.assertIn("## 八字报告", markdown)
        self.assertIn("审议正文", markdown)
        self.assertIn("独立回答", markdown)
        self.assertIn("一次反驳", markdown)
        self.assertIn("主持人总结", markdown)
        self.assertIn("&lt;script&gt;甲木&lt;/script&gt;", markdown)
        self.assertNotIn(created["resume_token"], markdown)
        self.assertEqual(response.headers["content-disposition"], f'attachment; filename="{created["case_id"]}.md"')

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

    async def test_ai_readable_text_uses_deterministic_parser_without_api_call(self):
        created = await main.create_case(CaseCreateRequest(systems=["western"]))
        source = b"""[PLANET_POSITIONS]\nobject | sign | longitude | house | motion\nSun | Sagittarius | 15 degrees | 10 | direct\n"""
        mocked_extract = AsyncMock()
        with patch("backend.app.main.extract_facts_only", mocked_extract):
            response = await main.upload_source(
                created["case_id"],
                "western",
                UploadFile(file=BytesIO(source), filename="astro_ai_readable.txt"),
                created["resume_token"],
                None,
                "deepseek-v4-flash",
            )

        mocked_extract.assert_not_awaited()
        self.assertEqual(response["extraction_engine"], "structured_text")
        self.assertEqual(response["facts"][0]["label"], "PLANET_POSITIONS · Sun")

    async def test_parallel_uploads_do_not_overwrite_each_other(self):
        created = await main.create_case(CaseCreateRequest(systems=["bazi", "western"]))

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

    async def test_pdf_text_is_passed_to_deepseek_fact_extraction(self):
        created = await self.create_case()
        pdf_fact = Fact(
            id="bazi.extracted-1-demo",
            label="四柱",
            value="甲申 丙子 庚申 壬午",
            source_span="PAGE 1: 甲申 丙子 庚申 壬午",
            extraction_confidence=0.94,
            time_sensitive=True,
        )
        local_text = "[PAGE 1]\n四柱：甲申 丙子 庚申 壬午"
        with patch("backend.app.main.extract_bytes", new=AsyncMock(return_value=(local_text, []))), patch(
            "backend.app.main.extract_facts_only", new=AsyncMock(return_value=([pdf_fact], [], None))
        ) as deepseek_extract:
            extraction = await main.upload_source(
                created["case_id"],
                "bazi",
                UploadFile(file=BytesIO(b"synthetic pdf bytes"), filename="chart.pdf"),
                created["resume_token"],
                "request-only",
                "deepseek-v4-flash",
            )
        self.assertEqual(extraction["extraction_engine"], "deepseek_text")
        self.assertEqual(extraction["facts"][0]["label"], "四柱")
        self.assertEqual(deepseek_extract.await_args.args[1], local_text)

    async def test_guided_reports_and_hearing_are_the_only_active_path(self):
        created = await main.create_case(CaseCreateRequest(systems=["bazi", "ziwei"]))
        for system_id in ("bazi", "ziwei"):
            await main.confirm_facts(
                created["case_id"],
                system_id,
                main.FactConfirmation(
                    facts=[Fact(id=f"{system_id}.fact-1", label="盘面", value=f"{system_id} 已确认资料")]
                ),
                created["resume_token"],
            )

        guided = AsyncMock(return_value=("有人格约束的报告", None))
        with patch("backend.app.main.run_guided_chamber", guided), patch(
            "backend.app.main.run_guided_tribunal",
            new=AsyncMock(return_value=("轻量 Tribunal", None)),
        ):
            assembled = await main.create_reports(
                created["case_id"],
                created["resume_token"],
                "request-key",
                "deepseek-v4-flash",
            )

        self.assertEqual(guided.await_count, 2)
        self.assertEqual(assembled["reports"]["bazi"]["text"], "有人格约束的报告")
        self.assertNotIn("claims", assembled["reports"]["bazi"])
        self.assertEqual(assembled["tribunal"]["summary"], "轻量 Tribunal")

        guided_hearing = {
            "mode": "guided",
            "question": "职业选择怎么看？",
            "answers": [],
            "challenges": [],
            "rebuttals": [],
            "summary": {"closing": "总结"},
            "guided_answers": [],
            "guided_rebuttals": [],
            "guided_summary": "总结",
        }
        with patch(
            "backend.app.main.run_guided_debate",
            new=AsyncMock(return_value=(guided_hearing, None)),
        ) as guided_debate:
            hearing = await main.create_debate(
                created["case_id"],
                DebateRequest(question="职业选择怎么看？"),
                created["resume_token"],
                "request-key",
                "deepseek-v4-flash",
            )

        guided_debate.assert_awaited_once()
        self.assertEqual(hearing["mode"], "guided")
        self.assertEqual(hearing["id"], "hearing-1")


if __name__ == "__main__":
    unittest.main()
