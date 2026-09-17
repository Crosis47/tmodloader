import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "mirror", Path(__file__).resolve().parents[1] / ".github/scripts/mirror-dockerhub.py")
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)
DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
SOURCE = "ghcr.io/crosis47/tmodloader"
TARGET = "crosis47/tmodloader"
INDEX = {"manifests": [{"platform": {"os": "linux", "architecture": arch}}
                       for arch in ["amd64", "arm64"]]}


class MirrorTests(unittest.TestCase):
    def exercise(self, target_digest=None, source_digest=DIGEST, alias_digest=DIGEST,
                 index=INDEX, verified_digest=DIGEST, channel="stable", marker=False):
        tag = "3.2.0" + ("-preview" if channel == "preview" else "")
        notes = f"Original notes `{SOURCE}@{DIGEST}`"
        if marker:
            notes += f"<!-- dockerhub:{TARGET}:{tag} -->"
        calls = []
        copied = False

        def run(*args):
            nonlocal copied
            calls.append(args)
            if args[:3] == ("gh", "release", "view"):
                return json.dumps({"body": notes, "isDraft": False}).encode()
            if args[:4] == ("docker", "buildx", "imagetools", "create"):
                copied = True
            if args[:3] == ("gh", "release", "edit"):
                content = Path(args[-1]).read_text()
                self.assertTrue(content.startswith(notes))
                self.assertIn(f"docker pull {TARGET}:{tag}", content)
            return b""

        def manifest(reference, missing_ok=False):
            if reference == f"{SOURCE}:{tag}":
                return source_digest, index
            if reference.startswith(SOURCE):
                return alias_digest, INDEX
            digest = verified_digest if copied else target_digest
            return (digest, INDEX) if digest else None

        with patch.object(mirror, "run", side_effect=run), patch.object(
                mirror, "manifest", side_effect=manifest):
            mirror.mirror("Crosis47/tmodloader", SOURCE, TARGET, tag, channel)
        return calls

    def test_first_copy_and_notes(self):
        calls = self.exercise()
        command = next(c for c in calls if c[0] == "docker")
        self.assertIn(f"{TARGET}:latest", command)
        self.assertNotIn(f"{TARGET}:stable", command)
        self.assertEqual(command[-1], f"{SOURCE}@{DIGEST}")
        self.assertTrue(any(c[:3] == ("gh", "release", "edit") for c in calls))

    def test_retry_is_idempotent(self):
        calls = self.exercise(target_digest=DIGEST, marker=True)
        self.assertFalse(any(c[:3] == ("gh", "release", "edit") for c in calls))

    def test_numbered_collision_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Refusing to replace"):
            self.exercise(target_digest=OTHER)

    def test_changed_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "differs"):
            self.exercise(source_digest=OTHER)

    def test_missing_architecture_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing AMD64 or ARM64"):
            self.exercise(index={"manifests": []})

    def test_verification_failure(self):
        with self.assertRaisesRegex(ValueError, "verification failed"):
            self.exercise(verified_digest=OTHER)

    def test_old_release_does_not_move_aliases(self):
        calls = self.exercise(alias_digest=OTHER)
        command = next(c for c in calls if c[0] == "docker")
        self.assertNotIn(f"{TARGET}:latest", command)
        self.assertNotIn(f"{TARGET}:stable", command)

    def test_preview_alias(self):
        calls = self.exercise(channel="preview")
        command = next(c for c in calls if c[0] == "docker")
        self.assertIn(f"{TARGET}:preview", command)
        self.assertNotIn(f"{TARGET}:latest", command)

    def test_registry_errors_are_not_absence(self):
        for message in [b"unauthorized", b"429 Too Many Requests", b"timeout"]:
            with self.subTest(message=message), patch.object(mirror, "run", side_effect=
                    subprocess.CalledProcessError(1, "docker", stderr=message)):
                with self.assertRaises(subprocess.CalledProcessError):
                    mirror.manifest("example/image:tag", missing_ok=True)

    def test_missing_manifest(self):
        with patch.object(mirror, "run", side_effect=subprocess.CalledProcessError(
                1, "docker", stderr=b"manifest unknown")):
            self.assertIsNone(mirror.manifest("example/image:tag", missing_ok=True))


if __name__ == "__main__":
    unittest.main()
