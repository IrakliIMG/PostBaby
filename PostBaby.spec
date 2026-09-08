# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for a reliable Windows one-folder PostBaby build."""

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ

analysis = Analysis(
    ["postbaby_launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[("samples/example_api_tests.py", "samples")],
    hiddenimports=[],
    hookspath=[],
    excludes=[],
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True, name="PostBaby", console=False,
)
coll = COLLECT(exe, analysis.binaries, analysis.zipfiles, analysis.datas, name="PostBaby")
