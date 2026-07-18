"""Unified exception hierarchy for Scholar Agent.

All modules should raise these instead of generic RuntimeError/ValueError
so callers can handle errors uniformly.
"""

from __future__ import annotations


class ScholarError(Exception):
    """Base exception for all Scholar Agent errors."""


class ResearchError(ScholarError):
    """Error during web research or evidence gathering."""


class SynthesisError(ScholarError):
    """Error during answer synthesis (LLM call, response parsing)."""
