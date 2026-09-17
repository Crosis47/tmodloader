import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "overview", Path(__file__).resolve().parents[1] / ".github/scripts/dockerhub-overview.py")
overview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overview)


class OverviewTests(unittest.TestCase):
    def release(self, **values):
        return dict(body="## 3.2.0\n### Fixed\n- Published fix\n<details>build evidence</details>",
                    isDraft=False, isPrerelease=False, **values)

    def test_complete_readme_and_published_changes(self):
        text = overview.render("# Project\nIntroduction\n## Setup\nInstructions\n",
                               self.release(), "owner/repo")
        self.assertIn("Published fix", text)
        self.assertIn("## Setup\nInstructions", text)
        self.assertNotIn("build evidence", text)
        self.assertLess(text.index("Latest release changes"), text.index("## Setup"))
        self.assertIn("/blob/master/CHANGELOG.md", text)

    def test_gallery_links_and_document_links(self):
        text = overview.absolute_links(
            "[![Overview](docs/images/view.png)](docs/images/view.png)\n"
            "[Config](.env.example) [Docs](docs/setup.md) [Local](#setup) "
            "[External](https://example.com)", "owner/repo")
        self.assertEqual(text.count("https://raw.githubusercontent.com/owner/repo/master/docs/images/view.png"), 2)
        self.assertIn("https://github.com/owner/repo/blob/master/.env.example", text)
        self.assertIn("[Local](#setup)", text)
        self.assertIn("[External](https://example.com)", text)

    def test_code_fences_unchanged(self):
        text = "```markdown\n[Example](relative.md)\n```\n"
        self.assertEqual(overview.absolute_links(text, "owner/repo"), text)

    def test_preview_or_draft_rejected(self):
        for field in ("isDraft", "isPrerelease"):
            release = self.release()
            release[field] = True
            with self.assertRaises(ValueError):
                overview.render("# Readme", release, "owner/repo")

    def test_size_limit_counts_utf8_bytes(self):
        with self.assertRaisesRegex(ValueError, "25,000"):
            overview.render("é" * 13000, self.release(), "owner/repo")

    def test_empty_notes_fail(self):
        release = self.release()
        release["body"] = ""
        with self.assertRaises(ValueError):
            overview.render("# Readme", release, "owner/repo")


if __name__ == "__main__":
    unittest.main()
