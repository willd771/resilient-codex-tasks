import unittest
from pathlib import Path

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = REPOSITORY_ROOT / "skills" / "resilient-codex-tasks"


class PublicationPackageTests(unittest.TestCase):
    def test_contains_a_complete_installable_skill(self):
        required_files = (
            SKILL_ROOT / "SKILL.md",
            SKILL_ROOT / "agents" / "openai.yaml",
            SKILL_ROOT / "scripts" / "codex_retry.py",
            SKILL_ROOT / "scripts" / "global_proxy.py",
            SKILL_ROOT / "scripts" / "install_global.py",
        )

        for required_file in required_files:
            self.assertTrue(required_file.is_file(), f"Missing {required_file.relative_to(REPOSITORY_ROOT)}")

    def test_skill_metadata_is_discoverable(self):
        skill_text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = yaml.safe_load(skill_text.split("---", 2)[1])

        self.assertEqual(frontmatter["name"], "resilient-codex-tasks")
        self.assertTrue(frontmatter["description"].startswith("Use when"))

    def test_repository_includes_publication_files(self):
        required_files = (
            REPOSITORY_ROOT / "README.md",
            REPOSITORY_ROOT / "LICENSE",
            REPOSITORY_ROOT / "requirements-dev.txt",
            REPOSITORY_ROOT / ".github" / "workflows" / "validate.yml",
        )

        for required_file in required_files:
            self.assertTrue(required_file.is_file(), f"Missing {required_file.relative_to(REPOSITORY_ROOT)}")


if __name__ == "__main__":
    unittest.main()
