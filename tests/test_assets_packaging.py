"""Tests for read-only asset loading, packaging specifications, and regression prevention."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from postbaby.assets import (
    generate_icon_assets,
    get_pacifier_ico_path,
    get_pacifier_png_path,
    load_icon_assets,
    ensure_icon_assets,
)
from postbaby.paths import resource_path


class AssetPackagingTests(unittest.TestCase):
    """Test suite ensuring bundled assets are strictly read-only and packaged properly."""

    def test_importing_and_loading_does_not_attempt_write(self) -> None:
        """Runtime icon loading must NEVER attempt to write to disk or create directories."""
        forbidden_writes: list[str] = []

        orig_write_bytes = Path.write_bytes
        orig_write_text = Path.write_text

        def tracked_write_bytes(self_path: Path, *args, **kwargs):
            forbidden_writes.append(f"write_bytes: {self_path}")
            return orig_write_bytes(self_path, *args, **kwargs)

        def tracked_write_text(self_path: Path, *args, **kwargs):
            forbidden_writes.append(f"write_text: {self_path}")
            return orig_write_text(self_path, *args, **kwargs)

        with patch.object(Path, "write_bytes", tracked_write_bytes), \
             patch.object(Path, "write_text", tracked_write_text):
            ico, png = load_icon_assets()
            self.assertEqual(forbidden_writes, [], "load_icon_assets() attempted write operations!")

            # Also ensure deprecated ensure_icon_assets does not write
            ico2, png2 = ensure_icon_assets()
            self.assertEqual(forbidden_writes, [], "ensure_icon_assets() attempted write operations!")

    def test_app_init_does_not_write_bundled_assets(self) -> None:
        """Initializing PostBabyApp must never attempt to write to bundled icon assets."""
        from postbaby.app import PostBabyApp

        forbidden_writes: list[str] = []
        orig_write_bytes = Path.write_bytes

        def tracked_write_bytes(self_path: Path, *args, **kwargs):
            if "pacifier" in str(self_path) or "postbaby" in str(self_path):
                forbidden_writes.append(str(self_path))
            return orig_write_bytes(self_path, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            test_db = Path(temp_dir) / "app_test.db"
            with patch.object(Path, "write_bytes", tracked_write_bytes):
                app = PostBabyApp(db_path=test_db)
                try:
                    self.assertEqual(forbidden_writes, [], "PostBabyApp.__init__ attempted to write bundled assets!")
                finally:
                    app.database.close()
                    app.destroy()

    def test_runtime_resource_lookup_returns_existing_readonly_assets(self) -> None:
        """Runtime lookup must resolve to pre-existing, valid assets on disk."""
        ico_path = get_pacifier_ico_path()
        png_path = get_pacifier_png_path()

        self.assertTrue(ico_path.is_file(), f"ICO asset does not exist: {ico_path}")
        self.assertTrue(png_path.is_file(), f"PNG asset does not exist: {png_path}")

        # Check PNG header magic bytes
        with open(png_path, "rb") as f:
            png_header = f.read(8)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n", "Invalid PNG header")

        # Check ICO header magic bytes
        with open(ico_path, "rb") as f:
            ico_header = f.read(4)
        self.assertEqual(ico_header, b"\x00\x00\x01\x00", "Invalid ICO header")

    def test_missing_assets_handle_gracefully_without_crashing(self) -> None:
        """If assets are missing at runtime, load_icon_assets returns None without FileNotFoundError."""
        with patch.object(Path, "is_file", return_value=False):
            ico, png = load_icon_assets()
            self.assertIsNone(ico)
            self.assertIsNone(png)

    def test_frozen_pyinstaller_resource_path_resolution(self) -> None:
        """When running under PyInstaller (sys.frozen), resource_path honors sys._MEIPASS."""
        mock_meipass = r"C:\PostBabyApp\_internal"
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", mock_meipass, create=True):
            resolved_png = resource_path("postbaby", "pacifier.png")
            resolved_ico = resource_path("postbaby", "pacifier.ico")

            expected_png = Path(mock_meipass) / "postbaby" / "pacifier.png"
            expected_ico = Path(mock_meipass) / "postbaby" / "pacifier.ico"

            self.assertEqual(resolved_png, expected_png)
            self.assertEqual(resolved_ico, expected_ico)

    def test_frozen_load_icon_assets_reads_from_meipass(self) -> None:
        """load_icon_assets in frozen environment resolves from _MEIPASS without writes."""
        with tempfile.TemporaryDirectory() as temp_bundle:
            bundle_postbaby = Path(temp_bundle) / "postbaby"
            bundle_postbaby.mkdir(parents=True)
            mock_png = bundle_postbaby / "pacifier.png"
            mock_ico = bundle_postbaby / "pacifier.ico"
            mock_png.write_bytes(b"\x89PNG\r\n\x1a\nfake_png")
            mock_ico.write_bytes(b"\x00\x00\x01\x00fake_ico")

            with patch.object(sys, "frozen", True, create=True), \
                 patch.object(sys, "_MEIPASS", temp_bundle, create=True):
                ico, png = load_icon_assets()
                self.assertEqual(ico, mock_ico)
                self.assertEqual(png, mock_png)

    def test_pregenerated_development_assets_exist(self) -> None:
        """Pre-generated development assets must exist in repo before PyInstaller build."""
        root_dir = Path(__file__).resolve().parent.parent
        root_ico = root_dir / "pacifier.ico"
        pkg_ico = root_dir / "postbaby" / "pacifier.ico"
        pkg_png = root_dir / "postbaby" / "pacifier.png"

        self.assertTrue(root_ico.is_file(), "Root pacifier.ico missing for PyInstaller icon parameter")
        self.assertTrue(pkg_ico.is_file(), "postbaby/pacifier.ico missing for runtime bundling")
        self.assertTrue(pkg_png.is_file(), "postbaby/pacifier.png missing for runtime bundling")
        self.assertGreater(root_ico.stat().st_size, 0)
        self.assertGreater(pkg_ico.stat().st_size, 0)
        self.assertGreater(pkg_png.stat().st_size, 0)

    def test_postbaby_spec_bundles_required_assets(self) -> None:
        """PostBaby.spec must include pacifier.png and pacifier.ico in datas."""
        spec_file = Path(__file__).resolve().parent.parent / "PostBaby.spec"
        self.assertTrue(spec_file.is_file(), "PostBaby.spec not found")
        content = spec_file.read_text(encoding="utf-8")

        self.assertIn('"postbaby/pacifier.png"', content)
        self.assertIn('"postbaby/pacifier.ico"', content)
        self.assertIn('icon="pacifier.ico"', content)

    def test_development_asset_generator_explicit_call(self) -> None:
        """Calling generate_icon_assets explicitly writes assets into a specified directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            ico, png = generate_icon_assets(Path(temp_dir))
            self.assertTrue(ico.is_file())
            self.assertTrue(png.is_file())
            self.assertEqual(ico.parent, Path(temp_dir))
            self.assertEqual(png.parent, Path(temp_dir))


if __name__ == "__main__":
    unittest.main()
