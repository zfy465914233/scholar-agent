from pathlib import Path
import unittest

_ROOT = Path(__file__).resolve().parents[1]




class KnowledgeScaffoldTest(unittest.TestCase):
    def test_knowledge_scaffold_structure_exists(self) -> None:
        expected_paths = [
            _ROOT / "templates" / "knowledge.md",
            _ROOT / "templates" / "method.md",
            _ROOT / "tests" / "fixtures" / "example-markov-chain.md",
        ]

        missing = [str(path.relative_to(_ROOT)) for path in expected_paths if not path.exists()]
        self.assertEqual([], missing, f"Missing expected scaffold paths: {missing}")


if __name__ == "__main__":
    unittest.main()
