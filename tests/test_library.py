"""Tests for per-user sound library manifest and preset merge.

Run:  .venv/bin/python tests/test_library.py
"""

import asyncio
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import UploadFile

from app import config
from app.library import (
    add_item,
    delete_item,
    list_all,
    list_by_category,
    merge_presets,
    resolve_library_paths_for_user,
    collect_library_ids_from_simulations,
    user_key,
)


def _fake_mp3() -> bytes:
    return b"\xff\xfb" + b"\x00" * 128


async def _upload(key: str, category: str, label: str) -> dict:
    upload = UploadFile(filename="test.mp3", file=io.BytesIO(_fake_mp3()))
    return await add_item(key, category, label, upload)


def test_manifest_crud():
    root = tempfile.mkdtemp()
    try:
        import app.library as lib

        old_root = lib.LIBRARY_ROOT
        lib.LIBRARY_ROOT = os.path.join(root, "users")
        key = user_key("alice@example.com")

        item = asyncio.run(_upload(key, "ambient", "Rain"))
        assert item["id"].startswith("lib_")
        assert item["label"] == "Rain"
        assert item["category"] == "ambient"

        grouped = list_all(key)
        assert len(grouped["ambient"]) == 1
        assert grouped["barge_in"] == []
        assert list_by_category(key, "barge_in") == []

        delete_item(key, item["id"])
        assert list_all(key)["ambient"] == []
    finally:
        shutil.rmtree(root, ignore_errors=True)
        lib.LIBRARY_ROOT = old_root


def test_merge_presets_scoped_to_user():
    root = tempfile.mkdtemp()
    try:
        import app.library as lib

        old_root = lib.LIBRARY_ROOT
        lib.LIBRARY_ROOT = os.path.join(root, "users")

        alice = user_key("alice@example.com")
        bob = user_key("bob@example.com")
        asyncio.run(_upload(alice, "ambient", "Alice Rain"))
        asyncio.run(_upload(bob, "ambient", "Bob Wind"))

        builtin = [{"id": "cafe", "label": "Café"}]
        alice_presets = merge_presets(builtin, alice, "ambient")
        bob_presets = merge_presets(builtin, bob, "ambient")
        assert len(alice_presets) == 2
        assert len(bob_presets) == 2
        assert alice_presets[-1]["label"] == "Alice Rain"
        assert bob_presets[-1]["label"] == "Bob Wind"
        assert merge_presets(builtin, None, "ambient") == builtin
    finally:
        shutil.rmtree(root, ignore_errors=True)
        lib.LIBRARY_ROOT = old_root


def test_normalize_custom_reactions():
    sims = config.normalize_simulations({
        "barge_in": {
            "enabled": True,
            "enabled_custom_reactions": ["lib_abc123", "invalid", "lib_def456"],
        },
    })
    assert sims["barge_in"]["enabled_custom_reactions"] == ["lib_abc123", "lib_def456"]


def test_collect_and_resolve_library_paths():
    root = tempfile.mkdtemp()
    try:
        import app.library as lib

        old_root = lib.LIBRARY_ROOT
        lib.LIBRARY_ROOT = os.path.join(root, "users")

        email = "caller@example.com"
        key = user_key(email)
        item = asyncio.run(_upload(key, "barge_in", "Honk"))
        sims = config.normalize_simulations({
            "ambient_noise": {"enabled": False},
            "barge_in": {
                "enabled": True,
                "sound_type": item["id"],
                "enabled_custom_reactions": [],
            },
        })
        ids = collect_library_ids_from_simulations(sims)
        assert item["id"] in ids
        paths = resolve_library_paths_for_user(email, ids)
        assert item["id"] in paths
        assert os.path.isfile(paths[item["id"]])
    finally:
        shutil.rmtree(root, ignore_errors=True)
        lib.LIBRARY_ROOT = old_root


if __name__ == "__main__":
    test_manifest_crud()
    test_merge_presets_scoped_to_user()
    test_normalize_custom_reactions()
    test_collect_and_resolve_library_paths()
    print("All library tests passed.")
