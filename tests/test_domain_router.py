#!/usr/bin/env python3
"""Tests for _propose_new_major_domain and infer_domain_decision domain_override."""

import os
import tempfile
import shutil
from pathlib import Path


from scholar_agent.engine.domain_router import _propose_new_major_domain, infer_domain_decision


class TestProposeNewMajorDomain:
    def test_pure_chinese_short(self):
        result = _propose_new_major_domain("量化回测")
        assert result == "量化回测"

    def test_pure_chinese_with_punctuation(self):
        result = _propose_new_major_domain("回测-训练闭环架构：量化交易中从回测结果到特征工程")
        assert "回测" in result
        assert "-" in result

    def test_pure_chinese_no_delimiters(self):
        """No delimiters → treated as single meaningful segment, no truncation."""
        result = _propose_new_major_domain("量化交易回测系统")
        assert result == "量化交易回测系统"

    def test_chinese_comma_delimited(self):
        result = _propose_new_major_domain("数据源选型、存储架构、复权处理")
        assert "-" in result

    def test_mixed_a_share(self):
        result = _propose_new_major_domain("A股量化回测系统行情数据管理方案")
        assert result != "a"
        assert len(result) > 1

    def test_mixed_with_english_terms(self):
        result = _propose_new_major_domain("Python+Rust混合栈量化回测实践")
        assert result
        assert len(result) <= 48

    def test_english_simple(self):
        result = _propose_new_major_domain("machine learning optimization")
        assert "machine" in result

    def test_english_short_words_filtered(self):
        result = _propose_new_major_domain("a vs an the big data")
        parts = result.split("-")
        assert "a" not in parts

    def test_empty_query(self):
        result = _propose_new_major_domain("")
        assert result == "general"

    def test_only_punctuation(self):
        result = _propose_new_major_domain("：，、！？")
        assert result == "general"

    def test_long_query_truncation(self):
        result = _propose_new_major_domain("一" * 100)
        assert len(result) <= 48

    def test_regression_a_share_not_just_a(self):
        result = _propose_new_major_domain("A股量化回测系统行情数据管理方案")
        assert result != "a"

    def test_regression_long_chinese_title(self):
        result = _propose_new_major_domain("回测-训练闭环架构：量化交易中从回测结果到特征工程")
        assert len(result) <= 48


class TestDomainOverride:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self.knowledge_root = Path(self._tmpdir) / "knowledge"
        self.knowledge_root.mkdir(parents=True)

    def teardown_method(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_override_skips_routing(self):
        result = infer_domain_decision(
            "some query", self.knowledge_root, use_ai_fallback=False,
            domain_override="quant-backtest",
        )
        assert result["major_domain"] == "quant-backtest"
        assert result["decision_mode"] == "domain_override"

    def test_override_empty_falls_through(self):
        result = infer_domain_decision(
            "machine learning", self.knowledge_root, use_ai_fallback=False,
            domain_override="",
        )
        assert result["decision_mode"] != "domain_override"

    def test_override_none_falls_through(self):
        result = infer_domain_decision(
            "machine learning", self.knowledge_root, use_ai_fallback=False,
            domain_override=None,
        )
        assert result["decision_mode"] != "domain_override"

    def test_override_creates_directory(self):
        infer_domain_decision(
            "test query", self.knowledge_root, use_ai_fallback=False,
            domain_override="new-domain",
        )
        assert (self.knowledge_root / "new-domain").is_dir()

    def test_override_whitespace_trimmed(self):
        result = infer_domain_decision(
            "test query", self.knowledge_root, use_ai_fallback=False,
            domain_override="  my-domain  ",
        )
        assert result["major_domain"] == "my-domain"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
