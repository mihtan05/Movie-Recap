"""MCP Server & MCP App Backend for Movie Recap Studio."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is importable when launched via stdio from any working directory
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp import types
from mcp.server.mcpserver import MCPServer

from src.gdrive_sync import build_gdrive_upload_plan, extract_drive_file_id
from src.kdenlive_exporter import export_kdenlive_project, find_kdenlive_executable, launch_kdenlive
from src.local_streamer import ensure_streamer_running, media_url_for_path
from src.media_engine import (
    extract_embedded_subtitles,
    generate_storyboard_sheets,
    has_nvenc,
    probe_video_info,
    render_block_preview,
    render_chapter,
    render_full_movie,
)
from src.project_store import (
    clean_local_media_files,
    create_project,
    get_cache_root,
    list_projects,
    load_project,
    save_project,
    timeline_path,
    update_single_block,
    upsert_chapter,
)
from src.tts_engine import SUPPORTED_VI_VOICES, synthesize_block, synthesize_project_tts

STREAMER_PORT = ensure_streamer_running()
APP_URI = "ui://recap-studio/app.html"
APP_HTML_PATH = REPO_ROOT / "mcp_server" / "ui_dist" / "app.html"

PANE_META: dict[str, Any] = {
    "ui": {
        "resourceUri": APP_URI,
        "visibility": ["model", "app"],
    },
    "com.google.antigravity/ui": {
        "entrypoints": [
            {"type": "aux_pane", "title": "🎬 Movie Recap Studio"},
            {"type": "global", "title": "🎬 Movie Recap Studio"},
        ]
    },
}

INLINE_UPDATE_META: dict[str, Any] = {
    "ui": {
        "resourceUri": APP_URI,
        "visibility": ["model", "app"],
    },
    "com.google.antigravity/ui": {
        "entrypoints": [
            {"type": "aux_pane", "title": "🎬 Movie Recap Studio"},
        ]
    },
}

APP_ONLY_META: dict[str, Any] = {
    "ui": {
        "visibility": ["app"],
    }
}

mcp = MCPServer("movie-recap-studio")


def _hydrate_project_for_ui(proj: dict[str, Any]) -> dict[str, Any]:
    """Attach localhost HTTP Range streaming URLs for video, audio, and storyboards."""
    import copy

    ui_proj = copy.deepcopy(proj)
    src = ui_proj.get("source", {})
    src["video_stream_url"] = media_url_for_path(src.get("video_path", ""))
    src["storyboard_urls"] = [
        {"path": p, "name": Path(p).name, "url": media_url_for_path(p)}
        for p in src.get("storyboard_sheets", [])
        if Path(p).exists()
    ]

    for ch in ui_proj.get("chapters", []):
        ch["chapter_video_url"] = media_url_for_path(ch.get("chapter_video_path", ""))
        for blk in ch.get("blocks", []):
            blk["audio_url"] = media_url_for_path(blk.get("audio_path", ""))
            blk["preview_clip_url"] = media_url_for_path(blk.get("preview_clip_path", ""))

    exp = ui_proj.get("exports", {})
    exp["mp4_stream_url"] = media_url_for_path(exp.get("mp4_path", ""))
    return ui_proj


def _build_studio_payload(active_project_id: str = "", notice: str = "") -> dict[str, Any]:
    projects = list_projects()
    chosen_id = active_project_id
    if not chosen_id and projects:
        chosen_id = projects[0]["project_id"]

    active_project = None
    if chosen_id:
        try:
            active_project = _hydrate_project_for_ui(load_project(chosen_id))
        except FileNotFoundError:
            active_project = None

    return {
        "streamer_port": STREAMER_PORT,
        "cache_root": str(get_cache_root()),
        "nvenc_available": has_nvenc(),
        "kdenlive_installed": bool(find_kdenlive_executable()),
        "voices": SUPPORTED_VI_VOICES,
        "projects": projects,
        "active_project": active_project,
        "notice": notice,
    }


def _tool_result(summary_text: str, payload: dict[str, Any]) -> types.CallToolResult:
    # Keep trajectory CallToolResult well under 1 MiB
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=summary_text)],
        structured_content=payload,
    )


@mcp.resource(
    APP_URI,
    name="Movie Recap Studio UI",
    description="Interactive side-pane studio for reviewing, editing, previewing, and exporting movie recaps.",
    mime_type="text/html;profile=mcp-app",
    meta={
        "ui": {
            "prefersBorder": False,
            "csp": {
                "resourceDomains": [
                    f"http://127.0.0.1:{STREAMER_PORT}",
                    "http://127.0.0.1:18920",
                    "http://127.0.0.1:18921",
                    "http://127.0.0.1:18922",
                ],
                "connectDomains": [
                    f"http://127.0.0.1:{STREAMER_PORT}",
                    "http://127.0.0.1:18920",
                    "http://127.0.0.1:18921",
                    "http://127.0.0.1:18922",
                ],
            },
        }
    },
)
def studio_app_html() -> str:
    if APP_HTML_PATH.exists():
        return APP_HTML_PATH.read_text(encoding="utf-8")
    return "<!doctype html><html><body><p>Studio UI bundle missing. Run node ui_builder/build.mjs</p></body></html>"


@mcp.tool(
    name="open_recap_studio",
    title="🎬 Movie Recap Studio",
    description="Open or refresh the Movie Recap Studio workspace in the right side pane.",
    meta=PANE_META,
)
def open_recap_studio(project_id: str = "") -> types.CallToolResult:
    payload = _build_studio_payload(project_id)
    ap = payload.get("active_project")
    if ap:
        msg = (
            f"Opened Movie Recap Studio for project '{ap['title']}' (`{ap['project_id']}`). "
            f"Chapters: {len(ap.get('chapters', []))}, Cache: {ap.get('cache_size_mb', 0)} MB, "
            f"NVENC GPU: {payload['nvenc_available']}."
        )
    else:
        msg = (
            f"Opened Movie Recap Studio (Cache root: {payload['cache_root']}, "
            f"NVENC GPU: {payload['nvenc_available']}). No active project yet."
        )
    return _tool_result(msg, payload)


@mcp.tool(
    name="recap_create_project",
    title="Create Movie Recap Project",
    description=(
        "Create a new movie recap project in D:\\CLIP\\temp_cache. Pass either a local source_video_path "
        "or a Google Drive link/ID in source_drive_url (download it first into D:\\CLIP\\temp_cache\\<id>\\source "
        "using the gdrive CLI if needed). Automatically probes video info and extracts embedded .srt if available."
    ),
    meta=INLINE_UPDATE_META,
)
def recap_create_project(
    title: str,
    source_video_path: str = "",
    source_drive_url: str = "",
    target_minutes: int = 45,
    style: str = "Hành động kịch tính, nhịp nhanh, lách từ nhạy cảm YouTube",
    voice: str = "vi-VN-NamMinhNeural",
    voice_rate: str = "+14%",
) -> types.CallToolResult:
    drive_id = extract_drive_file_id(source_drive_url) if source_drive_url else ""
    proj = create_project(
        title=title,
        source_video_path=source_video_path,
        source_drive_file_id=drive_id,
        target_minutes=target_minutes,
        style=style,
        voice=voice,
        voice_rate=voice_rate,
    )
    pid = proj["project_id"]
    extracted_srt = ""
    if source_video_path and Path(source_video_path).is_file():
        meta = probe_video_info(Path(source_video_path))
        proj["source"].update(
            {
                "duration_sec": meta["duration_sec"],
                "width": meta["width"],
                "height": meta["height"],
                "fps": meta["fps"],
            }
        )
        save_project(proj)
        extracted_srt = extract_embedded_subtitles(pid)

    payload = _build_studio_payload(pid, notice=f"Đã khởi tạo dự án '{title}'")
    summary = (
        f"Created project `{pid}` in `{get_cache_root() / pid}`.\n"
        f"- Source duration: {proj['source']['duration_sec']}s\n"
        f"- Embedded SRT extracted: {extracted_srt or 'None (provide .srt or generate storyboards)'}\n"
        f"- Drive source ID: {drive_id or 'None'}"
    )
    return _tool_result(summary, payload)


@mcp.tool(
    name="recap_generate_storyboards",
    title="Generate Storyboard Contact Sheets ($0 API)",
    description=(
        "Generate 5x5 Storyboard Contact Sheet JPEGs with burned HH:MM:SS timestamps so Antigravity "
        "models/subagents can visually inspect scenes using read_file without any paid external API."
    ),
    meta=INLINE_UPDATE_META,
)
def recap_generate_storyboards(
    project_id: str,
    start_sec: float = 0.0,
    end_sec: float = 0.0,
    interval_sec: float = 12.0,
) -> types.CallToolResult:
    sheets = generate_storyboard_sheets(
        project_id=project_id,
        start_sec=start_sec,
        end_sec=end_sec if end_sec > 0 else None,
        interval_sec=interval_sec,
    )
    payload = _build_studio_payload(project_id, notice=f"Đã tạo {len(sheets)} bảng ảnh Storyboard")
    msg = f"Generated {len(sheets)} storyboard contact sheets:\n" + "\n".join(f"- {s}" for s in sheets)
    return _tool_result(msg, payload)


@mcp.tool(
    name="recap_set_character_bible",
    title="Save Character Bible",
    description=(
        "Save the unified Character Bible (list of {original_name, alias, role, notes}) so all 8-10 "
        "chapters use consistent Vietnamese nicknames (e.g. 'Anh main sát thủ', 'Lão trùm')."
    ),
    meta=INLINE_UPDATE_META,
)
def recap_set_character_bible(
    project_id: str,
    characters: list[dict[str, str]],
) -> types.CallToolResult:
    proj = load_project(project_id)
    proj["character_bible"] = characters
    save_project(proj)
    payload = _build_studio_payload(project_id, notice="Đã lưu Từ điển Nhân vật")
    return _tool_result(f"Saved {len(characters)} characters into `{project_id}` Character Bible.", payload)


@mcp.tool(
    name="recap_upsert_chapter",
    title="Save / Update Recap Chapter",
    description=(
        "Insert or update a chapter in timeline.json. Each item in `blocks` should provide: "
        "`narration` (Vietnamese script), `start_sec` (float), `end_sec` (float), optional `flip_h` (bool), "
        "or an explicit `clips` array of `{start_sec, end_sec, flip_h, zoom_mode}`."
    ),
    meta=INLINE_UPDATE_META,
)
def recap_upsert_chapter(
    project_id: str,
    chapter_id: str,
    title: str,
    blocks: list[dict[str, Any]],
    summary: str = "",
    mood: str = "action",
) -> types.CallToolResult:
    proj = upsert_chapter(
        project_id=project_id,
        chapter_id=chapter_id,
        title=title,
        blocks=blocks,
        summary=summary,
        mood=mood,
    )
    payload = _build_studio_payload(project_id, notice=f"Đã cập nhật {title} ({len(blocks)} cảnh)")
    return _tool_result(
        f"Saved chapter `{chapter_id}` ('{title}') with {len(blocks)} blocks in `{proj['project_id']}`.",
        payload,
    )


@mcp.tool(
    name="recap_edit_block",
    title="Fast Edit Single Block (3s Re-TTS & Re-Cut)",
    description=(
        "Non-destructively update a single block's narration and/or source timestamps, immediately "
        "regenerate its Vietnamese TTS audio, and optionally render its video preview clip without "
        "re-rendering the rest of the 60-minute movie."
    ),
    meta=INLINE_UPDATE_META,
)
async def recap_edit_block(
    project_id: str,
    block_id: str,
    narration: str = "",
    start_sec: float = -1.0,
    end_sec: float = -1.0,
    flip_h: bool = False,
    render_preview: bool = True,
) -> types.CallToolResult:
    clips = None
    if start_sec >= 0:
        actual_end = end_sec if end_sec > start_sec else start_sec + 3.5
        clips = [{"start_sec": start_sec, "end_sec": actual_end, "flip_h": flip_h, "zoom_mode": "ken_burns_in"}]

    update_single_block(
        project_id=project_id,
        block_id=block_id,
        narration=narration if narration.strip() else None,
        clips=clips,
    )
    blk = await synthesize_block(project_id, block_id)
    preview_path = ""
    proj = load_project(project_id)
    if render_preview and proj["source"].get("video_path") and Path(proj["source"]["video_path"]).exists():
        preview_path = render_block_preview(project_id, block_id)

    payload = _build_studio_payload(project_id, notice=f"Đã sửa nhanh cảnh {block_id} ({blk['audio_duration_sec']}s)")
    return _tool_result(
        f"Updated block `{block_id}`: TTS duration={blk['audio_duration_sec']}s, preview={preview_path or 'audio-only'}",
        payload,
    )


@mcp.tool(
    name="recap_synthesize_tts",
    title="Synthesize Vietnamese TTS & SRT",
    description="Generate free Edge-TTS Vietnamese voiceover (.mp3) and frame-synced .srt subtitles.",
    meta=INLINE_UPDATE_META,
)
async def recap_synthesize_tts(
    project_id: str,
    chapter_id: str = "",
    force: bool = False,
) -> types.CallToolResult:
    res = await synthesize_project_tts(
        project_id=project_id,
        chapter_id=chapter_id or None,
        force=force,
    )
    payload = _build_studio_payload(
        project_id,
        notice=f"Đã tạo TTS ({res['total_duration_minutes']} phút) & file .srt",
    )
    return _tool_result(json.dumps(res, ensure_ascii=False, indent=2), payload)


@mcp.tool(
    name="recap_render_preview",
    title="Render Chapter or Block Video Preview",
    description="Render a chapter or single block preview MP4 using NVIDIA NVENC GPU & Anti-Content-ID cuts.",
    meta=INLINE_UPDATE_META,
)
def recap_render_preview(
    project_id: str,
    chapter_id: str = "",
    block_id: str = "",
) -> types.CallToolResult:
    if block_id:
        out = render_block_preview(project_id, block_id)
        label = f"block `{block_id}`"
    elif chapter_id:
        out = render_chapter(project_id, chapter_id)
        label = f"chapter `{chapter_id}`"
    else:
        proj = load_project(project_id)
        chapters = proj.get("chapters", [])
        if not chapters:
            raise ValueError("Project has no chapters yet.")
        cid = chapters[0]["chapter_id"]
        out = render_chapter(project_id, cid)
        label = f"chapter `{cid}`"

    payload = _build_studio_payload(project_id, notice=f"Đã render xem trước {label}")
    return _tool_result(f"Rendered {label} preview -> `{out}`", payload)


@mcp.tool(
    name="recap_export_kdenlive",
    title="Export Kdenlive Project (.kdenlive)",
    description="Export non-destructive MLT XML .kdenlive timeline + .srt subtitles and optionally open Kdenlive GUI.",
    meta=INLINE_UPDATE_META,
)
def recap_export_kdenlive(
    project_id: str,
    open_gui: bool = False,
) -> types.CallToolResult:
    res = export_kdenlive_project(project_id)
    launch_info = launch_kdenlive(res["kdenlive_path"]) if open_gui else {"launched": False}
    payload = _build_studio_payload(project_id, notice="Đã xuất file .kdenlive chuẩn MLT XML")
    return _tool_result(
        json.dumps({**res, "kdenlive_launch": launch_info}, ensure_ascii=False, indent=2),
        payload,
    )


@mcp.tool(
    name="recap_render_full_movie",
    title="Render Full Movie MP4 (GPU) & Prepare Drive Upload",
    description=(
        "Render the complete recap MP4 using rolling chapter rendering (NVIDIA NVENC GPU), export .srt "
        "and .kdenlive, and return the exact `gdrive` CLI upload checklist so the agent can upload to "
        "Google Drive and clean local temp files."
    ),
    meta=INLINE_UPDATE_META,
)
def recap_render_full_movie(
    project_id: str,
    burn_subtitles: bool | None = None,
) -> types.CallToolResult:
    render_res = render_full_movie(project_id=project_id, burn_subtitles=burn_subtitles)
    kd_res = export_kdenlive_project(project_id)
    proj = load_project(project_id)
    folder_name = proj.get("export_settings", {}).get("drive_folder_name", "Movie Recap Studio")
    upload_plan = build_gdrive_upload_plan(
        mp4_path=render_res["mp4_path"],
        srt_path=render_res["srt_path"],
        kdenlive_path=kd_res["kdenlive_path"],
        timeline_json_path=str(timeline_path(project_id)),
        folder_name=folder_name,
    )
    payload = _build_studio_payload(
        project_id,
        notice=f"Đã xuất MP4 ({render_res['mp4_size_mb']} MB). Sẵn sàng đẩy lên Google Drive!",
    )
    return _tool_result(
        json.dumps({"render": render_res, "kdenlive": kd_res, "gdrive_plan": upload_plan}, ensure_ascii=False, indent=2),
        payload,
    )


@mcp.tool(
    name="recap_record_drive_upload",
    title="Record Google Drive URLs & Optional Zero-Storage Wipe",
    description=(
        "Save the uploaded Google Drive web URLs into timeline.json after `gdrive mutate upload` succeeds, "
        "and optionally wipe local video/audio buffers in D:\\CLIP\\temp_cache to ~0 MB."
    ),
    meta=INLINE_UPDATE_META,
)
def recap_record_drive_upload(
    project_id: str,
    drive_mp4_url: str,
    drive_srt_url: str = "",
    drive_kdenlive_url: str = "",
    clean_local_now: bool = True,
) -> types.CallToolResult:
    proj = load_project(project_id)
    proj["exports"]["drive_mp4_url"] = drive_mp4_url
    if drive_srt_url:
        proj["exports"]["drive_srt_url"] = drive_srt_url
    if drive_kdenlive_url:
        proj["exports"]["drive_kdenlive_url"] = drive_kdenlive_url
    save_project(proj)

    clean_res = {}
    if clean_local_now:
        clean_res = clean_local_media_files(project_id, delete_entire_project=False)

    payload = _build_studio_payload(
        project_id,
        notice="Đã lưu link Google Drive & dọn sạch bộ đệm ổ D:\\CLIP về ~0 MB!",
    )
    return _tool_result(
        json.dumps(
            {"drive_mp4_url": drive_mp4_url, "clean_result": clean_res},
            ensure_ascii=False,
            indent=2,
        ),
        payload,
    )


@mcp.tool(
    name="recap_clean_local_cache",
    title="Clean Local Video Buffer (Zero Storage)",
    description="Delete temporary source/audio/clip/rendered media in D:\\CLIP\\temp_cache\\<project_id>.",
    meta=INLINE_UPDATE_META,
)
def recap_clean_local_cache(
    project_id: str,
    delete_entire_project: bool = False,
) -> types.CallToolResult:
    res = clean_local_media_files(project_id, delete_entire_project=delete_entire_project)
    payload = _build_studio_payload(
        "" if delete_entire_project else project_id,
        notice=f"Đã dọn sạch file tạm! Dung lượng còn lại: {res['remaining_mb']} MB",
    )
    return _tool_result(json.dumps(res, ensure_ascii=False, indent=2), payload)


# --- App-only tools (called directly by the right-pane UI via app.callServerTool) ---


@mcp.tool(name="app_get_state", meta=APP_ONLY_META)
def app_get_state(project_id: str = "") -> types.CallToolResult:
    payload = _build_studio_payload(project_id)
    return _tool_result("ok", payload)


@mcp.tool(name="app_save_settings", meta=APP_ONLY_META)
def app_save_settings(
    project_id: str,
    voice: str = "vi-VN-NamMinhNeural",
    rate: str = "+14%",
    aspect_ratio: str = "16:9",
    burn_subtitles: bool = False,
    use_nvenc: bool = True,
    auto_clean_local: bool = True,
    drive_folder_name: str = "Movie Recap Studio",
) -> types.CallToolResult:
    proj = load_project(project_id)
    proj["voice_settings"]["voice"] = voice
    proj["voice_settings"]["rate"] = rate
    proj["export_settings"].update(
        {
            "aspect_ratio": aspect_ratio,
            "burn_subtitles": burn_subtitles,
            "use_nvenc": use_nvenc,
            "auto_clean_local": auto_clean_local,
            "drive_folder_name": drive_folder_name,
        }
    )
    save_project(proj)
    payload = _build_studio_payload(project_id, notice="Đã lưu cài đặt dự án")
    return _tool_result("saved", payload)


if __name__ == "__main__":
    mcp.run(transport="stdio")
