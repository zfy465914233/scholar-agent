from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KnowledgeScaffoldTest(unittest.TestCase):
    def test_knowledge_directories_templates_and_seed_cards_exist(self) -> None:
        expected_paths = [
            ROOT / "indexes" / "local",
            ROOT / "knowledge" / "cards" / "definitions",
            ROOT / "knowledge" / "cards" / "methods",
            ROOT / "knowledge" / "cards" / "theorems",
            ROOT / "knowledge" / "cards" / "derivations",
            ROOT / "knowledge" / "cards" / "comparisons",
            ROOT / "knowledge" / "cards" / "decision_records",
            ROOT / "knowledge" / "notes" / "raw_distillations",
            ROOT / "knowledge" / "sources",
            ROOT / "knowledge" / "templates" / "definition-card.md",
            ROOT / "knowledge" / "templates" / "method-card.md",
            ROOT / "knowledge" / "templates" / "theorem-card.md",
            ROOT / "knowledge" / "templates" / "derivation-card.md",
            ROOT / "knowledge" / "templates" / "comparison-card.md",
            ROOT / "knowledge" / "templates" / "decision-record.md",
            ROOT / "knowledge" / "cards" / "definitions" / "markov-chain-definition.md",
            ROOT / "knowledge" / "cards" / "derivations" / "stationary-distribution-derivation.md",
        ]

        missing = [str(path.relative_to(ROOT)) for path in expected_paths if not path.exists()]
        self.assertEqual([], missing, f"Missing expected scaffold paths: {missing}")


if __name__ == "__main__":
    unittest.main()
