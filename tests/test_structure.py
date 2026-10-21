import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StructureTests(unittest.TestCase):
    def test_preserved_baseline_and_raw_inputs(self):
        manifest = json.loads((ROOT / 'artifacts/baseline/legacy/migration_manifest.json').read_text())
        for item in manifest['files']:
            if not item['destination'].startswith(('data/', 'artifacts/baseline/legacy/')):
                continue
            with self.subTest(path=item['destination']):
                with (ROOT / item['destination']).open('rb') as stream:
                    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
                self.assertEqual(actual, item['sha256'])

    def test_dashboard_from_another_working_directory_without_network(self):
        script = (
            'import sys; from unittest.mock import patch; '
            f'sys.path.insert(0, {str(ROOT)!r}); '
            'guard=patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")); '
            'mock=guard.start(); from app import app; '
            'client=app.test_client(); response=client.get("/"); '
            'assert response.status_code == 200; '
            'assert client.get("/static/js/app.js").status_code == 200; '
            'assert client.get("/static/css/styles.css").status_code == 200; '
            'assert not mock.called, "Import or rendering attempted network access"'
        )
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script], cwd=directory,
                                    capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
