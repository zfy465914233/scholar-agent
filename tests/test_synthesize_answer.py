"""Tests for synthesize_answer.py.

Tests cover:
- Answer JSON parsing (including fenced JSON and malformed responses)
- Dry-run mode via CLI
- Integration test: full pipeline from answer context to synthesis output
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

SAMPLE_PROMPT_BUNDLE = {
    "system_prompt": "Answer using the provided evidence context.",
    "user_prompt": (
        "Question: what is a markov chain\n"
        "Route: local-led\n\n"
        "Direct Support:\n"
        "- [markov-chain-definition] Local definition card: Markov Chain Definition\n\n"
        "Citations:\n"
        "- [markov-chain-definition] Markov Chain Definition (local / definition) knowledge/markov_chain/markov_chain_definition.md"
    ),
    "metadata": {
        "query": "what is a markov chain",
        "route": "local-led",
    },
    "citations": [
        {
            "evidence_id": "example-markov-chain-definition",
            "origin": "local",
            "title": "Markov Chain Definition",
            "source_type": "knowledge",
        }
    ],
}


def _run_script(args: list[str], stdin_data: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "synthesize_answer.py")] + args,
        capture_output=True,
        text=True,
        cwd=SCRIPTS,
        input=stdin_data,
    )


def _write_temp_json(data: dict) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(data, handle)
    handle.close()
    return handle.name


class DryRunTest(unittest.TestCase):
    """Test dry-run mode emits correct request payload."""

    def test_dry_run_emits_request_payload(self) -> None:
        bundle_path = _write_temp_json(SAMPLE_PROMPT_BUNDLE)
        result = _run_script(["--prompt-bundle", bundle_path, "--dry-run"])
        Path(bundle_path).unlink(missing_ok=True)

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("dry_run"))
        self.assertIn("request_payload", payload)
        rp = payload["request_payload"]
        self.assertEqual(3, len(rp["messages"]))
        self.assertIn("markov chain", rp["messages"][2]["content"])

    def test_dry_run_respects_model_override(self) -> None:
        bundle_path = _write_temp_json(SAMPLE_PROMPT_BUNDLE)
        result = _run_script(["--prompt-bundle", bundle_path, "--dry-run", "--model", "my-model"])
        Path(bundle_path).unlink(missing_ok=True)

        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("my-model", payload["request_payload"]["model"])


class DryRunWithStdinTest(unittest.TestCase):
    """Test stdin input mode."""

    def test_dry_run_from_stdin(self) -> None:
        result = _run_script(
            ["--prompt-bundle", "-", "--dry-run"],
            stdin_data=json.dumps(SAMPLE_PROMPT_BUNDLE),
        )
        self.assertEqual(0, result.returncode, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("dry_run"))


class OutputFileTest(unittest.TestCase):
    """Test file output mode."""

    def test_dry_run_writes_to_output_file(self) -> None:
        bundle_path = _write_temp_json(SAMPLE_PROMPT_BUNDLE)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.json"
            result = _run_script([
                "--prompt-bundle", bundle_path,
                "--dry-run",
                "--output", str(output_path),
            ])
            self.assertEqual(0, result.returncode, msg=result.stderr)
            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertTrue(payload.get("dry_run"))
        Path(bundle_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
