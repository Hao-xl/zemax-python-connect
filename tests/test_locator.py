from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from zemax_connection import root_kind  # noqa: E402


def test_root_kind_unknown_for_empty_temp(tmp_path):
    assert root_kind(tmp_path) == "unknown"


def test_root_kind_data_directory(tmp_path):
    lib = tmp_path / "ZOS-API" / "Libraries"
    lib.mkdir(parents=True)
    (lib / "ZOSAPI_NetHelper.dll").write_text("stub")
    assert root_kind(tmp_path) == "data"


def test_root_kind_install_directory(tmp_path):
    for name in ["ZOSAPI_NetHelper.dll", "ZOSAPI.dll", "ZOSAPI_Interfaces.dll"]:
        (tmp_path / name).write_text("stub")
    assert root_kind(tmp_path) == "install"
