"""Non-destructive block-based project store for Movie Recap Studio.

All heavy media and temporary buffers live inside D:\\CLIP\\temp_cache\\<project_id>
so the GitHub repository stays ~1-2 MB and local video caches can be wiped to 0 MB
after uploading finished videos to Google Drive.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_CACHE_ROOT = Path(os.environ.get("RECAP_CACHE_ROOT", r"D:\CLIP\temp_cache"))


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9_-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or f"recap-{uuid.uuid4().hex[:6]}"


def get_cache_root() -> Path:
    DEFAULT_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    return DEFAULT_CACHE_ROOT


def project_dir(project_id: str) -> Path:
    p = get_cache_root() / project_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def timeline_path(project_id: str) -> Path:
    return project_dir(project_id) / "timeline.json"


def compute_dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return round(total / (1024 * 1024), 2)


def create_project(
    title: str,
    source_video_path: str = "",
    source_drive_file_id: str = "",
    target_minutes: int = 45,
    style: str = "Hành động kịch tính, nhịp nhanh, lách từ nhạy cảm YouTube",
    voice: str = "vi-VN-NamMinhNeural",
    voice_rate: str = "+14%",
    project_id: str | None = None,
) -> dict[str, Any]:
    pid = slugify(project_id or title)
    pdir = project_dir(pid)
    for sub in ("source", "storyboards", "audio", "clips", "chapters", "exports"):
        (pdir / sub).mkdir(parents=True, exist_ok=True)

    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    data: dict[str, Any] = {
        "project_id": pid,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "style": style,
        "target_minutes": target_minutes,
        "source": {
            "video_path": source_video_path,
            "drive_file_id": source_drive_file_id,
            "subtitle_path": "",
            "duration_sec": 0.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "storyboard_sheets": [],
        },
        "voice_settings": {
            "voice": voice,
            "rate": voice_rate,
            "bgm_path": "",
            "bgm_volume": 0.12,
        },
        "export_settings": {
            "aspect_ratio": "16:9",
            "burn_subtitles": False,
            "use_nvenc": True,
            "crf": 23,
            "drive_folder_name": "Movie Recap Studio",
            "drive_folder_id": "",
            "auto_clean_local": True,
        },
        "character_bible": [],
        "chapters": [],
        "exports": {
            "mp4_path": "",
            "srt_path": "",
            "kdenlive_path": "",
            "drive_mp4_id": "",
            "drive_mp4_url": "",
            "drive_srt_url": "",
            "drive_kdenlive_url": "",
            "local_cache_cleaned": False,
        },
    }
    save_project(data)
    return data


def load_project(project_id: str) -> dict[str, Any]:
    tpath = timeline_path(project_id)
    if not tpath.exists():
        raise FileNotFoundError(f"Project '{project_id}' not found at {tpath}")
    with tpath.open("r", encoding="utf-8") as f:
        data = json.load(f)
    data["cache_size_mb"] = compute_dir_size_mb(project_dir(project_id))
    return data


def save_project(data: dict[str, Any]) -> dict[str, Any]:
    pid = data["project_id"]
    pdir = project_dir(pid)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    tpath = pdir / "timeline.json"
    tmp_path = pdir / "timeline.json.tmp"
    clean_copy = {k: v for k, v in data.items() if k != "cache_size_mb"}
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(clean_copy, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, tpath)
    data["cache_size_mb"] = compute_dir_size_mb(pdir)
    return data


def list_projects() -> list[dict[str, Any]]:
    root = get_cache_root()
    items: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        tpath = child / "timeline.json"
        if child.is_dir() and tpath.exists():
            try:
                proj = load_project(child.name)
                total_blocks = sum(len(ch.get("blocks", [])) for ch in proj.get("chapters", []))
                total_dur = sum(
                    float(b.get("audio_duration_sec") or 0.0)
                    for ch in proj.get("chapters", [])
                    for b in ch.get("blocks", [])
                )
                items.append(
                    {
                        "project_id": proj["project_id"],
                        "title": proj.get("title", child.name),
                        "updated_at": proj.get("updated_at", ""),
                        "chapters_count": len(proj.get("chapters", [])),
                        "blocks_count": total_blocks,
                        "estimated_duration_sec": round(total_dur, 1),
                        "cache_size_mb": proj.get("cache_size_mb", 0.0),
                        "drive_mp4_url": proj.get("exports", {}).get("drive_mp4_url", ""),
                        "local_cache_cleaned": proj.get("exports", {}).get("local_cache_cleaned", False),
                    }
                )
            except Exception:
                continue
    return items


def upsert_chapter(
    project_id: str,
    chapter_id: str,
    title: str,
    blocks: list[dict[str, Any]],
    summary: str = "",
    mood: str = "action",
) -> dict[str, Any]:
    proj = load_project(project_id)
    normalized_blocks: list[dict[str, Any]] = []
    for idx, b in enumerate(blocks, start=1):
        bid = b.get("block_id") or f"{chapter_id}_b{idx:02d}"
        clips = b.get("clips") or []
        if not clips and ("start_sec" in b or "end_sec" in b):
            clips = [
                {
                    "start_sec": float(b.get("start_sec", 0.0)),
                    "end_sec": float(b.get("end_sec", 3.5)),
                    "flip_h": bool(b.get("flip_h", False)),
                    "zoom_mode": b.get("zoom_mode", "ken_burns_in"),
                }
            ]
        normalized_blocks.append(
            {
                "block_id": bid,
                "narration": str(b.get("narration", "")).strip(),
                "clips": clips,
                "audio_path": b.get("audio_path", ""),
                "audio_duration_sec": float(b.get("audio_duration_sec") or 0.0),
                "preview_clip_path": b.get("preview_clip_path", ""),
                "status": b.get("status", "draft"),
            }
        )

    chapter_obj = {
        "chapter_id": chapter_id,
        "title": title,
        "summary": summary,
        "mood": mood,
        "chapter_video_path": "",
        "blocks": normalized_blocks,
    }
    chapters = proj.get("chapters", [])
    replaced = False
    for i, existing in enumerate(chapters):
        if existing.get("chapter_id") == chapter_id:
            chapter_obj["chapter_video_path"] = existing.get("chapter_video_path", "")
            chapters[i] = chapter_obj
            replaced = True
            break
    if not replaced:
        chapters.append(chapter_obj)
    chapters.sort(key=lambda c: c.get("chapter_id", ""))
    proj["chapters"] = chapters
    return save_project(proj)


def update_single_block(
    project_id: str,
    block_id: str,
    narration: str | None = None,
    clips: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Update a single block non-destructively without touching other blocks."""
    proj = load_project(project_id)
    for ch in proj.get("chapters", []):
        for blk in ch.get("blocks", []):
            if blk.get("block_id") == block_id:
                if narration is not None:
                    blk["narration"] = narration.strip()
                    blk["status"] = "draft"
                if clips is not None:
                    blk["clips"] = clips
                    blk["preview_clip_path"] = ""
                ch["chapter_video_path"] = ""
                save_project(proj)
                return proj, ch, blk
    raise KeyError(f"Block '{block_id}' not found in project '{project_id}'")


def clean_local_media_files(project_id: str, delete_entire_project: bool = False) -> dict[str, Any]:
    """Wipe heavy video/audio/storyboard files from D:\\CLIP\\temp_cache so disk usage drops to ~0 MB."""
    pdir = project_dir(project_id)
    if delete_entire_project:
        shutil.rmtree(pdir, ignore_errors=True)
        return {"project_id": project_id, "deleted_entirely": True, "remaining_mb": 0.0}

    proj = load_project(project_id)
    for sub in ("source", "storyboards", "audio", "clips", "chapters", "exports"):
        subdir = pdir / sub
        if subdir.exists():
            shutil.rmtree(subdir, ignore_errors=True)
            subdir.mkdir(parents=True, exist_ok=True)

    proj["source"]["video_path"] = ""
    proj["source"]["storyboard_sheets"] = []
    for ch in proj.get("chapters", []):
        ch["chapter_video_path"] = ""
        for blk in ch.get("blocks", []):
            blk["audio_path"] = ""
            blk["preview_clip_path"] = ""
    proj["exports"]["mp4_path"] = ""
    proj["exports"]["local_cache_cleaned"] = True
    saved = save_project(proj)
    return {
        "project_id": project_id,
        "deleted_entirely": False,
        "remaining_mb": saved.get("cache_size_mb", 0.0),
    }
