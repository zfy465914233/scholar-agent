from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class KnowledgeScaffoldTest(unittest.TestCase):
    def test_knowledge_scaffold_structure_exists(self) -> None:
        expected_paths = [
            ROOT / "indexes" / "local",
            ROOT / "knowledge" / "examples" / "example-markov-chain.md",
            ROOT / "knowledge" / "templates" / "definition-card.md",
            ROOT / "knowledge" / "templates" / "method-card.md",
            ROOT / "knowledge" / "templates" / "theorem-card.md",
            ROOT / "knowledge" / "templates" / "derivation-card.md",
            ROOT / "knowledge" / "templates" / "comparison-card.md",
            ROOT / "knowledge" / "templates" / "decision-record.md",
            ROOT / "knowledge" / "templates" / "research-note.md",
        ]

        missing = [str(path.relative_to(ROOT)) for path in expected_paths if not path.exists()]
        self.assertEqual([], missing, f"Missing expected scaffold paths: {missing}")


if __name__ == "__main__":
    unittest.main()
