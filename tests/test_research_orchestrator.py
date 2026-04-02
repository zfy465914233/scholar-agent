import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "indexes" / "local" / "index.json"
FAKE_HARNESS = ROOT / "tests" / "fake_research_harness.py"


class ResearchOrchestratorTest(unittest.TestCase):
    def setUp(self) -> None:
        build_index = subprocess.run(
            [sys.executable, "scripts/local_index.py", "--knowledge-root", str(ROOT / "tests" / "fixtures"), "--output", str(INDEX_PATH)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if build_index.returncode != 0:
            self.fail(
                f"failed to build local index for orchestrator test: "
                f"stdout={build_index.stdout!r} stderr={build_index.stderr!r}"
            )

    def test_auto_mode_prefers_web_led_for_latest_queries(self) -> None:
        command = [
            sys.executable,
            "scripts/orchestrate_research.py",
            "latest markov chain tutorial",
            "--index",
            str(INDEX_PATH),
            "--research-script",
            str(FAKE_HARNESS),
        ]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("web-led", payload["route"])
        self.assertEqual("web", payload["decision"]["primary_source"])
        self.assertEqual(1, payload["evidence_pack"]["web_count"])

    def test_auto_mode_prefers_local_led_for_definition_queries(self) -> None:
        command = [
            sys.executable,
            "scripts/orchestrate_research.py",
            "what is a markov chain",
            "--index",
            str(INDEX_PATH),
        ]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("local-led", payload["route"])
        self.assertEqual("local", payload["decision"]["primary_source"])
        self.assertGreaterEqual(payload["evidence_pack"]["local_count"], 1)

    def test_local_led_can_still_merge_explicit_web_bundle_when_provided(self) -> None:
        web_payload = {
            "query": "what is a markov chain",
            "depth": "quick",
            "generated_at": "2026-04-01T00:00:00+00:00",
            "summary": {"total_evidence": 1},
            "validation": {"ok": True, "errors": []},
            "evidence": [
                {
                    "query": "what is a markov chain",
                    "source_type": "docs",
                    "url": "https://example.com/local-led-bundle",
                    "title": "Local-Led Bundle",
                    "summary": "Supplementary web bundle.",
                    "retrieved_at": "2026-04-01T00:00:00+00:00",
                    "retrieval_status": "succeeded",
                }
            ],
        }

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(web_payload, handle)
            web_path = Path(handle.name)

        command = [
            sys.executable,
            "scripts/orchestrate_research.py",
            "what is a markov chain",
            "--mode",
            "local-led",
            "--index",
            str(INDEX_PATH),
            "--web-evidence",
            str(web_path),
        ]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        web_path.unlink(missing_ok=True)

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("local-led", payload["route"])
        self.assertEqual(1, payload["evidence_pack"]["web_count"])
        self.assertTrue(any(item["origin"] == "web" for item in payload["evidence_pack"]["items"]))
        self.assertTrue(payload["decision"]["web_available"])

    def test_mixed_mode_can_merge_local_and_web_evidence(self) -> None:
        web_payload = {
            "query": "markov chain overview",
            "depth": "quick",
            "generated_at": "2026-04-01T00:00:00+00:00",
            "summary": {"total_evidence": 1},
            "validation": {"ok": True, "errors": []},
            "evidence": [
                {
                    "query": "markov chain overview",
                    "source_type": "docs",
                    "url": "https://example.com/overview",
                    "title": "Overview",
                    "summary": "Overview article.",
                    "retrieved_at": "2026-04-01T00:00:00+00:00",
                    "retrieval_status": "succeeded",
                }
            ],
        }

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(web_payload, handle)
            web_path = Path(handle.name)

        command = [
            sys.executable,
            "scripts/orchestrate_research.py",
            "markov chain overview",
            "--mode",
            "mixed",
            "--index",
            str(INDEX_PATH),
            "--web-evidence",
            str(web_path),
        ]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        web_path.unlink(missing_ok=True)

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("mixed", payload["route"])
        self.assertGreaterEqual(payload["evidence_pack"]["local_count"], 1)
        self.assertEqual(1, payload["evidence_pack"]["web_count"])

    def test_web_led_can_generate_web_evidence_via_harness_script(self) -> None:
        command = [
            sys.executable,
            "scripts/orchestrate_research.py",
            "latest markov chain tutorial",
            "--index",
            str(INDEX_PATH),
            "--research-script",
            str(FAKE_HARNESS),
        ]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("web-led", payload["route"])
        self.assertEqual(1, payload["evidence_pack"]["web_count"])
        web_item = next(item for item in payload["evidence_pack"]["items"] if item["origin"] == "web")
        self.assertEqual("Fake Harness Result", web_item["title"])
        self.assertEqual("https://example.com/fake-harness", web_item["url"])


if __name__ == "__main__":
    unittest.main()
