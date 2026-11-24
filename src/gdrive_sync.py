"""Google Drive helper utilities for Movie Recap Studio (Zero-Local-Storage workflow)."""

from __future__ import annotations

import re
from pathlib import Path


def extract_drive_file_id(url_or_id: str) -> str:
    """Extract a Google Drive file or folder ID from a URL or bare ID string."""
    s = url_or_id.strip()
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"/folders/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
    ]
    for pat in patterns:
        m = re.search(pat, s)
        if m:
            return m.group(1)
    return s


def build_gdrive_upload_plan(
    mp4_path: str,
    srt_path: str = "",
    kdenlive_path: str = "",
    timeline_json_path: str = "",
    folder_name: str = "Movie Recap Studio",
) -> dict[str, list[str] | str]:
    """Return exact `gdrive` CLI commands for the Antigravity agent to execute
    with the user's connected Google Drive account, followed by local cache cleanup.
    """
    files_to_upload = [p for p in (mp4_path, srt_path, kdenlive_path, timeline_json_path) if p and Path(p).exists()]
    return {
        "folder_name": folder_name,
        "files": files_to_upload,
        "instructions": (
            f"Run `gdrive readonly search --name-exact \"{folder_name}\" --type folder` first. "
            f"If missing, run `gdrive mutate mkdir \"{folder_name}\"`. "
            f"Then upload each file with `gdrive mutate upload <FILE> --parent <FOLDER_ID>`, "
            f"verify with `gdrive readonly url <FILE_ID>`, save the Drive URLs via `recap_record_drive_upload`, "
            f"and finally call `recap_clean_local_cache` so D:\\CLIP\\temp_cache returns to ~0 MB."
        ),
    }
