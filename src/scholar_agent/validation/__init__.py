"""Paper note validation and normalization utilities."""

from scholar_agent.validation.normalize_note import main as normalize_main
from scholar_agent.validation.validate_note import main as validate_main
from scholar_agent.validation.validate_note import validate_note

__all__ = ["normalize_main", "validate_main", "validate_note"]
