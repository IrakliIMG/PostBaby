import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from postbaby.paths import app_data_dir, default_database_path, resource_path


class PathTests(unittest.TestCase):
    def test_non_windows_data_directory_honors_xdg_data_home(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"XDG_DATA_HOME": temporary}, clear=False):
            with patch("postbaby.paths.os.name", "posix"):
                result = app_data_dir()
                expected = Path(os.path.join(temporary, "PostBaby"))
                self.assertEqual(expected, result)
            self.assertTrue(result.is_dir())

    def test_legacy_database_is_preserved_when_new_location_is_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); legacy = root / "postbaby.db"; legacy.touch()
            with patch("postbaby.paths.app_data_dir", return_value=root / "user-data"), patch("postbaby.paths.Path.cwd", return_value=root):
                self.assertEqual(legacy, default_database_path())

    def test_bundled_sample_resource_resolves_from_project_root(self):
        self.assertTrue(resource_path("samples", "example_api_tests.py").is_file())
