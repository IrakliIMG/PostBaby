# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for a reliable Windows one-folder PostBaby build."""

from PyInstaller.building.build_main import Analysis, COLLECT, EXE, PYZ

analysis = Analysis(
    ["postbaby_launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("postbaby/pacifier.png", "postbaby"),
        ("postbaby/pacifier.ico", "postbaby"),
    ],
    hiddenimports=[
        "postbaby.bundled_stdlib",
        "uuid",
        "base64",
        "hashlib",
        "hmac",
        "secrets",
        "json",
        "re",
        "time",
        "datetime",
        "calendar",
        "math",
        "random",
        "decimal",
        "fractions",
        "urllib",
        "urllib.parse",
        "urllib.request",
        "urllib.error",
        "http",
        "http.client",
        "string",
        "collections",
        "itertools",
        "functools",
        "copy",
        "dataclasses",
        "typing",
        "csv",
        "gzip",
        "zlib",
        "binascii",
        "struct",
        "ipaddress",
        "pathlib",
        "xml",
        "xml.etree.ElementTree",
        "zoneinfo",
        "_hashlib",
        "_uuid",
    ],
    hookspath=[],
    excludes=[],
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True, name="PostBaby", console=False, icon="pacifier.ico",
)
coll = COLLECT(exe, analysis.binaries, analysis.zipfiles, analysis.datas, name="PostBaby")
