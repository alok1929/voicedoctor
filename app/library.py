"""Per-org sound library: manifest + MP3 storage on disk.

Keyed by org_id (a team's shared library), not by individual user — everyone in
the same org sees and can use the same uploaded sounds.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, UploadFile

from app import config

LIBRARY_ROOT = os.path.join(config._ASSETS, "library", "users")
VALID_CATEGORIES = frozenset({"ambient", "barge_in", "other"})
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_LABEL_LEN = 64
_LIB_ID_RE = re.compile(r"^lib_[a-f0-9]{12}$")


def org_key(org_id: str) -> str:
    normalized = (org_id or "").strip().lower()
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


def _user_dir(key: str) -> str:
    return os.path.join(LIBRARY_ROOT, key)


def _manifest_path(key: str) -> str:
    return os.path.join(_user_dir(key), "manifest.json")


def _load_manifest(key: str) -> list[dict]:
    path = _manifest_path(key)
    if not os.path.isfile(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        items = data.get("items") if isinstance(data, dict) else data
        return list(items) if isinstance(items, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_manifest(key: str, items: list[dict]) -> None:
    root = _user_dir(key)
    os.makedirs(root, exist_ok=True)
    path = _manifest_path(key)
    tmp = f"{path}.tmp"
    payload = {"items": items}
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def _sanitize_label(label: str) -> str:
    cleaned = (label or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Label is required")
    if len(cleaned) > MAX_LABEL_LEN:
        raise HTTPException(status_code=400, detail=f"Label must be at most {MAX_LABEL_LEN} characters")
    return cleaned


def _validate_category(category: str) -> str:
    cat = (category or "").strip().lower()
    if cat not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category!r}")
    return cat


def _item_path(key: str, category: str, filename: str) -> str:
    return os.path.join(_user_dir(key), category, filename)


def list_all(key: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {c: [] for c in VALID_CATEGORIES}
    for item in _load_manifest(key):
        cat = item.get("category")
        if cat in grouped:
            grouped[cat].append(_public_item(item))
    return grouped


def list_by_category(key: str, category: str) -> list[dict]:
    cat = _validate_category(category)
    return [
        _public_item(item)
        for item in _load_manifest(key)
        if item.get("category") == cat
    ]


def _public_item(item: dict) -> dict:
    return {
        "id": item["id"],
        "category": item["category"],
        "label": item["label"],
        "created_at": item.get("created_at"),
    }


def resolve_path(key: str, item_id: str) -> str | None:
    if not item_id or not _LIB_ID_RE.match(item_id):
        return None
    for item in _load_manifest(key):
        if item.get("id") == item_id:
            path = _item_path(key, item["category"], item["filename"])
            if os.path.isfile(path):
                return path
            return None
    return None


async def add_item(key: str, category: str, label: str, file: UploadFile) -> dict:
    cat = _validate_category(category)
    clean_label = _sanitize_label(label)
    filename_orig = (file.filename or "").lower()
    if not filename_orig.endswith(".mp3"):
        raise HTTPException(status_code=400, detail="Only MP3 files are supported")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds 10 MB limit")

    item_id = f"lib_{uuid.uuid4().hex[:12]}"
    mp3_name = f"{item_id}.mp3"
    dest = _item_path(key, cat, mp3_name)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as out:
        out.write(content)

    entry = {
        "id": item_id,
        "category": cat,
        "label": clean_label,
        "filename": mp3_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    items = _load_manifest(key)
    items.append(entry)
    _save_manifest(key, items)
    return _public_item(entry)


def delete_item(key: str, item_id: str) -> None:
    if not _LIB_ID_RE.match(item_id or ""):
        raise HTTPException(status_code=404, detail="Sound not found")
    items = _load_manifest(key)
    kept: list[dict] = []
    removed: dict | None = None
    for item in items:
        if item.get("id") == item_id:
            removed = item
        else:
            kept.append(item)
    if not removed:
        raise HTTPException(status_code=404, detail="Sound not found")
    path = _item_path(key, removed["category"], removed["filename"])
    if os.path.isfile(path):
        os.remove(path)
    _save_manifest(key, kept)


def merge_presets(
    builtin: list[dict],
    key: str | None,
    category: str,
) -> list[dict]:
    if not key:
        return list(builtin)
    custom = list_by_category(key, category)
    return [*builtin, *custom]


def resolve_preview_path(
    preset_id: str,
    builtin_map: dict[str, str],
    key: str | None,
) -> str | None:
    pid = (preset_id or "").strip().lower()
    if pid in builtin_map:
        path = builtin_map[pid]
        return path if path and os.path.isfile(path) else None
    if key and pid.startswith("lib_"):
        return resolve_path(key, pid)
    return None


def collect_library_ids_from_simulations(sims: dict) -> set[str]:
    ids: set[str] = set()
    noise = sims.get("ambient_noise") or {}
    if noise.get("enabled"):
        t = (noise.get("type") or "").strip().lower()
        if t.startswith("lib_"):
            ids.add(t)
    barge = sims.get("barge_in") or {}
    if barge.get("enabled"):
        st = (barge.get("sound_type") or "").strip().lower()
        if st.startswith("lib_"):
            ids.add(st)
        for rid in barge.get("enabled_custom_reactions") or []:
            r = (rid or "").strip().lower()
            if r.startswith("lib_"):
                ids.add(r)
    return ids


def resolve_library_paths_for_org(org_id: str, ids: set[str]) -> dict[str, str]:
    if not org_id or not ids:
        return {}
    key = org_key(org_id)
    resolved: dict[str, str] = {}
    for item_id in ids:
        path = resolve_path(key, item_id)
        if path:
            resolved[item_id] = path
    return resolved
