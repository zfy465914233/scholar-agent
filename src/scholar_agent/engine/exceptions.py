"""Unified exception hierarchy for Scholar Agent.

All modules should raise these instead of generic RuntimeError/ValueError
so callers can handle errors uniformly.
"""

from __future__ import annotations


class ScholarError(Exception):
    """Base exception for all Scholar Agent errors."""


class IndexNotFoundError(ScholarError):
    """The knowledge index file does not exist or is unreadable."""


class ResearchError(ScholarError):
    """Error during web research or evidence gathering."""


class SynthesisError(ScholarError):
    """Error during answer synthesis (LLM call, response parsing)."""


class ValidationError(ScholarError):
    """Schema or input validation failure."""


class ConfigurationError(ScholarError):
    """Configuration file is missing, malformed, or inconsistent."""
