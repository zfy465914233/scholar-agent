"""Unit tests for synonym-based query expansion."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scholar_agent.engine import synonyms as syn_mod
from scholar_agent.engine.synonyms import (
    add_user_group,
    clear_cache,
    expand_query,
    load_synonyms,
    remove_user_group,
)


def _make_project_dict(tmp: Path, groups: list[dict]) -> Path:
    p = tmp / "synonyms.json"
    p.write_text(json.dumps({"groups": groups}, ensure_ascii=False), encoding="utf-8")
    return p


class TestLoadSynonyms(unittest.TestCase):
    def setUp(self) -> None:
        clear_cache()

    def tearDown(self) -> None:
        clear_cache()

    def test_load_project_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            project = _make_project_dict(
                tmp,
                [{"canonical": "diffusion model", "aliases": ["DDPM", "SDE"]}],
            )
            with patch.object(syn_mod, "_user_dict_path", return_value=tmp / "missing.json"):
                result = load_synonyms(project_path=project)
            self.assertIn("diffusion model", result)
            self.assertEqual(set(result["diffusion model"]), {"ddpm", "sde"})

    def test_user_overrides_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            project = _make_project_dict(
                tmp,
                [{"canonical": "attention", "aliases": ["MHA"]}],
            )
            user = tmp / "user.json"
            user.write_text(
                json.dumps({"groups": [{"canonical": "attention", "aliases": ["self-attention"]}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            with patch.object(syn_mod, "_user_dict_path", return_value=user):
                result = load_synonyms(project_path=project)
            self.assertEqual(result["attention"], ["self-attention"])

    def test_missing_files_return_empty(self) -> None:
        with patch.object(syn_mod, "_user_dict_path", return_value=Path("/nonexistent/user.json")):
            result = load_synonyms(project_path=Path("/nonexistent/project.json"))
        self.assertEqual(result, {})

    def test_corrupt_json_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            project = tmp / "synonyms.json"
            project.write_text("not json {{{", encoding="utf-8")
            with patch.object(syn_mod, "_user_dict_path", return_value=tmp / "missing.json"):
                result = load_synonyms(project_path=project)
            self.assertEqual(result, {})


class TestExpandQuery(unittest.TestCase):
    def test_no_synonyms_returns_original(self) -> None:
        out = expand_query("hello world", synonyms={})
        self.assertEqual(out, ["hello world"])

    def test_empty_query(self) -> None:
        self.assertEqual(expand_query("", synonyms={}), [])

    def test_canonical_in_query_returns_all_aliases(self) -> None:
        syn = {"diffusion model": ["ddpm", "sde", "ncsn"]}
        out = expand_query("diffusion model for image gen", synonyms=syn)
        self.assertEqual(out[0], "diffusion model for image gen")
        for alias in ("ddpm", "sde", "ncsn", "diffusion model"):
            self.assertIn(alias, out)

    def test_alias_in_query_returns_canonical_and_other_aliases(self) -> None:
        syn = {"diffusion model": ["ddpm", "sde"]}
        out = expand_query("DDPM sampling speedup", synonyms=syn)
        self.assertIn("DDPM sampling speedup", out)
        self.assertIn("diffusion model", out)
        self.assertIn("sde", out)
        self.assertIn("ddpm", out)

    def test_case_insensitive_match(self) -> None:
        syn = {"ppo": ["proximal policy optimization"]}
        out = expand_query("Using PPO here", synonyms=syn)
        self.assertIn("proximal policy optimization", out)

    def test_multiple_groups_hit(self) -> None:
        syn = {
            "diffusion model": ["ddpm"],
            "attention mechanism": ["mha", "self-attention"],
        }
        # Query must contain an exact phrase from each group to hit it
        out = expand_query("DDPM with MHA", synonyms=syn)
        self.assertIn("diffusion model", out)
        self.assertIn("ddpm", out)
        self.assertIn("attention mechanism", out)
        self.assertIn("self-attention", out)

    def test_no_duplicates(self) -> None:
        syn = {"diffusion model": ["ddpm", "diffusion"]}
        out = expand_query("diffusion model ddpm", synonyms=syn)
        self.assertEqual(len(out), len(set(out)))


class TestUserDictMutations(unittest.TestCase):
    def setUp(self) -> None:
        clear_cache()

    def tearDown(self) -> None:
        clear_cache()

    def test_add_and_remove_user_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            user_path = tmp / "synonyms.json"
            with patch.object(syn_mod, "_user_dict_path", return_value=user_path):
                added = add_user_group("test canonical", ["alias1", "alias2"])
                self.assertEqual(added, user_path)
                self.assertTrue(user_path.exists())

                # Reload and confirm
                data = json.loads(user_path.read_text(encoding="utf-8"))
                groups = data["groups"]
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]["canonical"], "test canonical")

                # Overwrite same canonical
                add_user_group("Test Canonical", ["new alias"])
                data = json.loads(user_path.read_text(encoding="utf-8"))
                self.assertEqual(len(data["groups"]), 1)
                self.assertEqual(data["groups"][0]["aliases"], ["new alias"])

                # Remove
                removed = remove_user_group("test canonical")
                self.assertTrue(removed)
                data = json.loads(user_path.read_text(encoding="utf-8"))
                self.assertEqual(data["groups"], [])

    def test_remove_nonexistent_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            user_path = tmp / "synonyms.json"
            user_path.write_text(json.dumps({"groups": []}), encoding="utf-8")
            with patch.object(syn_mod, "_user_dict_path", return_value=user_path):
                self.assertFalse(remove_user_group("ghost"))

    def test_remove_when_file_missing_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with patch.object(syn_mod, "_user_dict_path", return_value=tmp / "missing.json"):
                self.assertFalse(remove_user_group("anything"))

    def test_remove_corrupt_json_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            user_path = tmp / "synonyms.json"
            user_path.write_text("not valid json {{{", encoding="utf-8")
            with patch.object(syn_mod, "_user_dict_path", return_value=user_path):
                self.assertFalse(remove_user_group("x"))

    def test_add_when_existing_file_corrupt(self) -> None:
        """add_user_group should overwrite a corrupt user dict rather than crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            user_path = tmp / "synonyms.json"
            user_path.write_text("garbage", encoding="utf-8")
            with patch.object(syn_mod, "_user_dict_path", return_value=user_path):
                path = add_user_group("fresh", ["a1"])
            self.assertEqual(path, user_path)
            data = json.loads(user_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["groups"]), 1)
            self.assertEqual(data["groups"][0]["canonical"], "fresh")


class TestExpandQueryErrorPaths(unittest.TestCase):
    """expand_query must degrade gracefully when load_synonyms fails."""

    def setUp(self) -> None:
        clear_cache()

    def tearDown(self) -> None:
        clear_cache()

    def test_load_synonyms_exception_returns_original_query(self) -> None:
        with patch.object(syn_mod, "load_synonyms", side_effect=RuntimeError("boom")):
            out = expand_query("diffusion model")
        self.assertEqual(out, ["diffusion model"])


class TestChineseSynonymExpansion(unittest.TestCase):
    """Chinese aliases in the shipped synonyms.json trigger expansion."""

    def setUp(self) -> None:
        syn_mod.clear_cache()

    def test_chinese_diffusion_expands(self) -> None:
        merged = syn_mod.load_synonyms()
        out = expand_query("扩散模型原理", synonyms=merged)
        self.assertIn("diffusion model", out)

    def test_chinese_reinforcement_learning_expands(self) -> None:
        merged = syn_mod.load_synonyms()
        out = expand_query("强化学习", synonyms=merged)
        self.assertIn("reinforcement learning", out)


if __name__ == "__main__":
    unittest.main()
