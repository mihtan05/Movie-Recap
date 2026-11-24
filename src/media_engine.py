"""FFmpeg GPU Media Engine: Storyboard Contact Sheets, Subtitle Extraction,
Anti-Content-ID Smart Cutting, and Rolling Chapter Renderer.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

from .project_store import load_project, project_dir, save_project
from .tts_engine import export_project_srt

_NVENC_CACHE: bool | None = None


def has_nvenc() -> bool:
    """Detect if NVIDIA h264_nvenc is usable on this machine."""
    global _NVENC_CACHE
    if _NVENC_CACHE is not None:
        return _NVENC_CACHE
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=256x256:d=0.1",
        "-frames:v",
        "1",
        "-c:v",
        "h264_nvenc",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    _NVENC_CACHE = proc.returncode == 0
    return _NVENC_CACHE


def escape_ffmpeg_filter_path(path: Path) -> str:
    """Escape Windows drive colons and backslashes for FFmpeg filtergraphs."""
    raw = str(path.resolve()).replace("\\", "/")
    raw = raw.replace(":", r"\:")
    raw = raw.replace("'", r"\'")
    return raw


def probe_video_info(video_path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(video_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(proc.stdout)
    duration = float(info.get("format", {}).get("duration") or 0.0)
    width, height, fps = 1920, 1080, 30.0
    subtitle_streams: list[dict[str, Any]] = []

    for st in info.get("streams", []):
        codec_type = st.get("codec_type")
        if codec_type == "video" and width == 1920 and st.get("width"):
            width = int(st["width"])
            height = int(st["height"])
            r_fps = st.get("r_frame_rate", "30/1")
            if "/" in r_fps:
                num, den = r_fps.split("/", 1)
                if float(den) > 0:
                    fps = round(float(num) / float(den), 3)
        elif codec_type == "subtitle":
            subtitle_streams.append(
                {
                    "index": st.get("index"),
                    "codec_name": st.get("codec_name", ""),
                    "language": (st.get("tags") or {}).get("language", "und"),
                    "title": (st.get("tags") or {}).get("title", ""),
                }
            )
    return {
        "duration_sec": round(duration, 3),
        "width": width,
        "height": height,
        "fps": fps,
        "subtitle_streams": subtitle_streams,
    }


def extract_embedded_subtitles(project_id: str, stream_index: int | None = None) -> str:
    """Extract embedded .srt subtitle stream from an .mkv/.mp4 container in ~2 seconds."""
    proj = load_project(project_id)
    vpath = Path(proj["source"]["video_path"])
    if not vpath.exists():
        raise FileNotFoundError(f"Source video not found: {vpath}")

    meta = probe_video_info(vpath)
    subs = meta.get("subtitle_streams", [])
    if not subs:
        return ""

    chosen = subs[0]["index"]
    if stream_index is not None:
        chosen = stream_index
    else:
        for s in subs:
            if s.get("language", "").lower() in ("vie", "vi", "eng", "en"):
                chosen = s["index"]
                break

    out_srt = project_dir(project_id) / "source" / "extracted_source.srt"
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(vpath),
        "-map",
        f"0:{chosen}",
        str(out_srt),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode == 0 and out_srt.exists() and out_srt.stat().st_size > 0:
        proj["source"]["subtitle_path"] = str(out_srt)
        save_project(proj)
        return str(out_srt)
    return ""


def generate_storyboard_sheets(
    project_id: str,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    interval_sec: float = 12.0,
    cols: int = 5,
    rows: int = 5,
) -> list[str]:
    """Generate lightweight 5x5 Storyboard Contact Sheet JPEGs with HH:MM:SS burned on every tile.
    Uses OpenCV random-access frame seeking (20x faster than full stream decode, zero Fontconfig issues)
    so Antigravity models can visually inspect a 2-hour movie for $0 external API cost!
    """
    import cv2
    import numpy as np

    proj = load_project(project_id)
    vpath = Path(proj["source"]["video_path"])
    if not vpath.exists():
        raise FileNotFoundError(f"Source video not found: {vpath}")

    meta = probe_video_info(vpath)
    proj["source"].update(
        {
            "duration_sec": meta["duration_sec"],
            "width": meta["width"],
            "height": meta["height"],
            "fps": meta["fps"],
        }
    )

    total_dur = meta["duration_sec"]
    actual_end = min(total_dur, end_sec) if end_sec else total_dur
    span = max(0.5, actual_end - start_sec)

    timestamps: list[float] = []
    t = start_sec
    while t < actual_end - 0.05:
        timestamps.append(round(t, 2))
        t += interval_sec
    if not timestamps:
        timestamps = [start_sec]

    tiles_per_sheet = cols * rows
    tile_w, tile_h = 320, 180
    pad = 4
    sb_dir = project_dir(project_id) / "storyboards"
    sb_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(vpath))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video with OpenCV: {vpath}")

    generated: list[str] = []
    try:
        for s_idx in range(0, len(timestamps), tiles_per_sheet):
            batch = timestamps[s_idx : s_idx + tiles_per_sheet]
            sheet_h = rows * tile_h + (rows + 1) * pad
            sheet_w = cols * tile_w + (cols + 1) * pad
            canvas = np.full((sheet_h, sheet_w, 3), (24, 20, 20), dtype=np.uint8)

            for idx, ts in enumerate(batch):
                r = idx // cols
                c = idx % cols
                cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000.0)
                ok, frame = cap.read()
                if not ok or frame is None:
                    tile = np.zeros((tile_h, tile_w, 3), dtype=np.uint8)
                else:
                    fh, fw = frame.shape[:2]
                    scale = min(tile_w / max(1, fw), tile_h / max(1, fh))
                    nw, nh = max(1, int(fw * scale)), max(1, int(fh * scale))
                    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
                    tile = np.zeros((tile_h, tile_w, 3), dtype=np.uint8)
                    y0 = (tile_h - nh) // 2
                    x0 = (tile_w - nw) // 2
                    tile[y0 : y0 + nh, x0 : x0 + nw] = resized

                # Format HH:MM:SS (and seconds) badge on top-left corner
                hrs = int(ts // 3600)
                mins = int((ts % 3600) // 60)
                secs = ts % 60
                label = f"{hrs:02d}:{mins:02d}:{secs:04.1f} ({ts:.1f}s)"
                cv2.rectangle(tile, (4, 4), (212, 28), (12, 12, 16), -1)
                cv2.putText(
                    tile,
                    label,
                    (8, 21),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.46,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )

                py = pad + r * (tile_h + pad)
                px = pad + c * (tile_w + pad)
                canvas[py : py + tile_h, px : px + tile_w] = tile

            first_s = int(batch[0])
            last_s = int(batch[-1])
            out_jpg = sb_dir / f"storyboard_{(s_idx // tiles_per_sheet) + 1:02d}_{first_s}s_{last_s}s.jpg"
            cv2.imwrite(str(out_jpg), canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if out_jpg.exists():
                generated.append(str(out_jpg))
    finally:
        cap.release()

    proj["source"]["storyboard_sheets"] = sorted(
        set(proj["source"].get("storyboard_sheets", []) + generated)
    )
    save_project(proj)
    return generated


def plan_anti_content_id_subclips(
    clips: list[dict[str, Any]],
    target_duration_sec: float,
    source_duration_sec: float,
    max_continuous_sec: float = 3.5,
    skip_gap_sec: float = 3.2,
) -> list[dict[str, Any]]:
    """Break or adjust clip windows so:
    1) Total visual duration matches the exact TTS narration duration (`target_duration_sec`).
    2) No single shot runs longer than `max_continuous_sec` (~3.5s).
    3) Consecutive shots jump forward (`skip_gap_sec`) to avoid linear Content ID matching.
    """
    target = max(1.0, round(target_duration_sec, 3))
    src_max = max(10.0, source_duration_sec) if source_duration_sec > 0 else 999_999.0

    if not clips:
        clips = [{"start_sec": 0.0, "end_sec": min(src_max, target), "flip_h": False, "zoom_mode": "ken_burns_in"}]

    planned: list[dict[str, Any]] = []
    remaining = target
    cursor = float(clips[0].get("start_sec", 0.0))
    clip_idx = 0

    toggle_zoom = True
    while remaining > 0.08:
        seg_len = min(max_continuous_sec, remaining)
        if seg_len < 1.1 and planned:
            # Merge tiny tail (< 1.1s) into previous shot if still safe (< 4.3s)
            prev = planned[-1]
            prev_len = prev["end_sec"] - prev["start_sec"]
            if prev_len + seg_len <= 4.3 and prev["end_sec"] + seg_len <= src_max:
                prev["end_sec"] = round(prev["end_sec"] + seg_len, 3)
                remaining = 0.0
                break

        if clip_idx < len(clips):
            base = clips[clip_idx]
            c_start = float(base.get("start_sec", cursor))
            flip_h = bool(base.get("flip_h", False))
            zoom_mode = base.get("zoom_mode") or ("ken_burns_in" if toggle_zoom else "static_106")
            clip_idx += 1
        else:
            c_start = cursor
            flip_h = False
            zoom_mode = "ken_burns_in" if toggle_zoom else "static_106"

        if c_start + seg_len > src_max:
            c_start = max(0.0, src_max - seg_len - 0.5)

        c_end = round(c_start + seg_len, 3)
        planned.append(
            {
                "start_sec": round(c_start, 3),
                "end_sec": c_end,
                "flip_h": flip_h,
                "zoom_mode": zoom_mode,
            }
        )
        remaining = round(remaining - seg_len, 3)
        cursor = c_end + skip_gap_sec
        if cursor >= src_max - 4.0:
            cursor = max(0.0, (c_start * 0.5) % max(5.0, src_max - 6.0))
        toggle_zoom = not toggle_zoom

    return planned


def _video_encode_args(use_nvenc: bool, crf: int = 23) -> list[str]:
    if use_nvenc and has_nvenc():
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", str(crf), "-b:v", "0"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]


def _render_single_block_mp4(
    source_video: Path,
    audio_path: Path,
    subclips: list[dict[str, Any]],
    out_mp4: Path,
    aspect_ratio: str = "16:9",
    use_nvenc: bool = True,
    crf: int = 23,
) -> Path:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    out_w, out_h = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
    scale_w, scale_h = int(out_w * 1.07), int(out_h * 1.07)

    cmd: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    filter_parts: list[str] = []

    for i, sc in enumerate(subclips):
        dur = max(0.2, round(sc["end_sec"] - sc["start_sec"], 3))
        cmd.extend(["-ss", f"{sc['start_sec']:.3f}", "-t", f"{dur:.3f}", "-i", str(source_video)])
        hflip_str = ",hflip" if sc.get("flip_h") else ""
        # Subtle anti-Content-ID crop/zoom + 30fps normalization + slight contrast grade
        chain = (
            f"[{i}:v]fps=30,"
            f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},"
            f"eq=contrast=1.04:saturation=1.04"
            f"{hflip_str},setsar=1,format=yuv420p[v{i}]"
        )
        filter_parts.append(chain)

    audio_idx = len(subclips)
    cmd.extend(["-i", str(audio_path)])

    if len(subclips) == 1:
        v_concat = "[v0]copy[vout]"
    else:
        inputs_str = "".join(f"[v{i}]" for i in range(len(subclips)))
        v_concat = f"{inputs_str}concat=n={len(subclips)}:v=1:a=0[vout]"
    filter_parts.append(v_concat)

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
            "-map",
            f"{audio_idx}:a:0",
            *_video_encode_args(use_nvenc, crf),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-shortest",
            str(out_mp4),
        ]
    )
    subprocess.run(cmd, check=True, capture_output=True)
    return out_mp4


def render_block_preview(project_id: str, block_id: str) -> str:
    """Render/re-render ONLY a single block (~2-4s) so prompt edits preview in ~2 seconds."""
    proj = load_project(project_id)
    src_video = Path(proj["source"]["video_path"])
    if not src_video.exists():
        raise FileNotFoundError(f"Source video missing: {src_video}")
    src_dur = float(proj["source"].get("duration_sec") or probe_video_info(src_video)["duration_sec"])
    ecfg = proj.get("export_settings", {})
    pdir = project_dir(project_id)

    for ch in proj.get("chapters", []):
        for blk in ch.get("blocks", []):
            if blk.get("block_id") == block_id:
                apath = Path(blk.get("audio_path", ""))
                if not apath.exists():
                    raise FileNotFoundError(f"TTS audio missing for block '{block_id}'. Synthesize TTS first.")
                adur = float(blk.get("audio_duration_sec") or 3.5)
                planned = plan_anti_content_id_subclips(blk.get("clips", []), adur, src_dur)
                blk["clips"] = planned
                out_clip = pdir / "clips" / f"{block_id}.mp4"
                _render_single_block_mp4(
                    src_video,
                    apath,
                    planned,
                    out_clip,
                    aspect_ratio=ecfg.get("aspect_ratio", "16:9"),
                    use_nvenc=bool(ecfg.get("use_nvenc", True)),
                    crf=int(ecfg.get("crf", 23)),
                )
                blk["preview_clip_path"] = str(out_clip)
                blk["status"] = "rendered"
                save_project(proj)
                return str(out_clip)
    raise KeyError(f"Block '{block_id}' not found.")


def render_chapter(project_id: str, chapter_id: str, force_blocks: bool = False) -> str:
    """Render all blocks in a chapter and concatenate them cleanly with -c copy."""
    proj = load_project(project_id)
    src_video = Path(proj["source"]["video_path"])
    if not src_video.exists():
        raise FileNotFoundError(f"Source video missing: {src_video}")
    src_dur = float(proj["source"].get("duration_sec") or probe_video_info(src_video)["duration_sec"])
    ecfg = proj.get("export_settings", {})
    pdir = project_dir(project_id)

    target_ch = None
    for ch in proj.get("chapters", []):
        if ch.get("chapter_id") == chapter_id:
            target_ch = ch
            break
    if target_ch is None:
        raise KeyError(f"Chapter '{chapter_id}' not found.")

    block_files: list[Path] = []
    for blk in target_ch.get("blocks", []):
        prev_str = (blk.get("preview_clip_path") or "").strip()
        existing = Path(prev_str) if prev_str else None
        if not force_blocks and existing and existing.is_file() and existing.stat().st_size > 0:
            block_files.append(existing)
            continue
        aud_str = (blk.get("audio_path") or "").strip()
        apath = Path(aud_str) if aud_str else None
        if not apath or not apath.is_file():
            raise FileNotFoundError(f"Block '{blk['block_id']}' has no TTS audio yet.")
        adur = float(blk.get("audio_duration_sec") or 3.5)
        planned = plan_anti_content_id_subclips(blk.get("clips", []), adur, src_dur)
        blk["clips"] = planned
        out_clip = pdir / "clips" / f"{blk['block_id']}.mp4"
        _render_single_block_mp4(
            src_video,
            apath,
            planned,
            out_clip,
            aspect_ratio=ecfg.get("aspect_ratio", "16:9"),
            use_nvenc=bool(ecfg.get("use_nvenc", True)),
            crf=int(ecfg.get("crf", 23)),
        )
        blk["preview_clip_path"] = str(out_clip)
        blk["status"] = "rendered"
        block_files.append(out_clip)

    if not block_files:
        raise ValueError(f"Chapter '{chapter_id}' has no blocks to render.")

    concat_list = pdir / "chapters" / f"{chapter_id}_concat.txt"
    concat_lines = [f"file '{str(bf.resolve()).replace(chr(92), '/')}'" for bf in block_files]
    concat_list.write_text("\n".join(concat_lines), encoding="utf-8")

    out_ch_mp4 = pdir / "chapters" / f"{chapter_id}.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c",
        "copy",
        str(out_ch_mp4),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    target_ch["chapter_video_path"] = str(out_ch_mp4)
    save_project(proj)
    return str(out_ch_mp4)


def render_full_movie(
    project_id: str,
    burn_subtitles: bool | None = None,
    clean_block_clips_immediately: bool = True,
) -> dict[str, Any]:
    """Rolling chapter-by-chapter render for 45-60m recaps with optional BGM & Hardsub."""
    proj = load_project(project_id)
    ecfg = proj.get("export_settings", {})
    vcfg = proj.get("voice_settings", {})
    do_burn = ecfg.get("burn_subtitles", False) if burn_subtitles is None else burn_subtitles
    use_nvenc = bool(ecfg.get("use_nvenc", True))
    crf = int(ecfg.get("crf", 23))
    pdir = project_dir(project_id)

    chapter_mp4s: list[Path] = []
    for ch in proj.get("chapters", []):
        cid = ch["chapter_id"]
        ch_mp4 = Path(render_chapter(project_id, cid))
        chapter_mp4s.append(ch_mp4)
        if clean_block_clips_immediately:
            # Free intermediate block clips right after each chapter finishes!
            for blk in ch.get("blocks", []):
                bclip_str = (blk.get("preview_clip_path") or "").strip()
                if bclip_str:
                    bclip = Path(bclip_str)
                    if bclip.is_file():
                        bclip.unlink(missing_ok=True)
                blk["preview_clip_path"] = ""

    proj = load_project(project_id)
    srt_path = export_project_srt(project_id)

    concat_txt = pdir / "exports" / "full_chapters_concat.txt"
    concat_txt.write_text(
        "\n".join(f"file '{str(p.resolve()).replace(chr(92), '/')}'" for p in chapter_mp4s),
        encoding="utf-8",
    )

    stitched_mp4 = pdir / "exports" / f"{project_id}_stitched.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-c",
            "copy",
            str(stitched_mp4),
        ],
        check=True,
        capture_output=True,
    )

    final_mp4 = pdir / "exports" / f"{project_id}_final.mp4"
    bgm_str = (vcfg.get("bgm_path") or "").strip()
    bgm_path = Path(bgm_str) if bgm_str else None
    has_bgm = bool(bgm_path and bgm_path.is_file())

    if not do_burn and not has_bgm:
        if final_mp4.exists():
            final_mp4.unlink()
        stitched_mp4.rename(final_mp4)
    else:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(stitched_mp4)]
        if has_bgm:
            bgm_vol = float(vcfg.get("bgm_volume", 0.12))
            cmd.extend(["-stream_loop", "-1", "-i", str(bgm_path)])
            a_filter = f"[1:a]volume={bgm_vol}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        else:
            a_filter = ""

        if do_burn:
            esc_srt = escape_ffmpeg_filter_path(srt_path)
            v_filter = (
                f"subtitles='{esc_srt}':force_style="
                f"'FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=1,MarginV=28'"
            )
            cmd.extend(["-vf", v_filter, *_video_encode_args(use_nvenc, crf)])
        else:
            cmd.extend(["-c:v", "copy"])

        if a_filter:
            cmd.extend(["-filter_complex", a_filter, "-map", "0:v:0", "-map", "[aout]", "-c:a", "aac", "-b:a", "192k"])
        else:
            cmd.extend(["-c:a", "copy"])

        cmd.append(str(final_mp4))
        subprocess.run(cmd, check=True, capture_output=True)
        stitched_mp4.unlink(missing_ok=True)

    proj["exports"]["mp4_path"] = str(final_mp4)
    proj["exports"]["srt_path"] = str(srt_path)
    proj["exports"]["local_cache_cleaned"] = False
    saved = save_project(proj)
    size_mb = round(final_mp4.stat().st_size / (1024 * 1024), 2)
    return {
        "project_id": project_id,
        "mp4_path": str(final_mp4),
        "srt_path": str(srt_path),
        "mp4_size_mb": size_mb,
        "used_nvenc": use_nvenc and has_nvenc(),
        "cache_size_mb": saved.get("cache_size_mb", 0.0),
    }
