"""Unit tests for orchestrate_research.classify_route — pattern injection.

classify_route's intent keywords are parameterised (decision: they are intent
cues, not retrieval synonyms). Defaults stay unchanged; callers can inject
custom patterns (testing, new languages) without editing the module.
"""

import unittest

from scholar_agent.engine.orchestrate_research import (
    _DEFAULT_ROUTING_PATTERNS,
    classify_route,
)


class TestClassifyRoutePatterns(unittest.TestCase):
    """classify_route honours injected patterns; defaults unchanged."""

    def test_default_patterns_route_as_before(self) -> None:
        self.assertEqual(classify_route("latest SOTA results"), "web-led")
        self.assertEqual(classify_route("what is a markov chain"), "local-led")
        self.assertEqual(classify_route("debug this failing test"), "context-led")

    def test_custom_patterns_override(self) -> None:
        custom = {"latest": ("alpha",), "definition": ("beta",), "code": ("gamma",)}
        self.assertEqual(classify_route("alpha something", patterns=custom), "web-led")
        self.assertEqual(classify_route("beta something", patterns=custom), "local-led")
        self.assertEqual(classify_route("gamma something", patterns=custom), "context-led")

    def test_custom_patterns_replace_not_merge(self) -> None:
        # "latest" is a default latest-cue; custom patterns fully replace, so a
        # default cue no longer triggers. No index_path → probe None → "mixed".
        custom = {"latest": ("alpha",), "definition": (), "code": ()}
        self.assertEqual(classify_route("latest news", patterns=custom), "mixed")

    def test_default_patterns_grouped(self) -> None:
        self.assertEqual(set(_DEFAULT_ROUTING_PATTERNS), {"latest", "definition", "code"})


if __name__ == "__main__":
    unittest.main()
