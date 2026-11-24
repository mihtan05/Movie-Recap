"""Kdenlive (.kdenlive / MLT XML) Non-Destructive Timeline Exporter."""

from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .media_engine import plan_anti_content_id_subclips, probe_video_info
from .project_store import load_project, project_dir, save_project
from .tts_engine import export_project_srt


def _sec_to_frames(sec: float, fps: float = 30.0) -> int:
    return max(0, int(round(sec * fps)))


def export_kdenlive_project(project_id: str) -> dict[str, Any]:
    """Generate a valid MLT / Kdenlive .kdenlive XML timeline with synced V1 video cuts,
    A1 TTS narration, optional A2 BGM, and automatic .kdenlive.srt subtitle track.
    """
    proj = load_project(project_id)
    pdir = project_dir(project_id)
    src_video = Path(proj["source"]["video_path"])
    src_dur = float(proj["source"].get("duration_sec") or 0.0)
    if src_dur <= 0 and src_video.exists():
        src_dur = probe_video_info(src_video)["duration_sec"]

    fps = 30.0
    ecfg = proj.get("export_settings", {})
    width, height = (1080, 1920) if ecfg.get("aspect_ratio") == "9:16" else (1920, 1080)

    out_kdenlive = pdir / "exports" / f"{project_id}.kdenlive"
    out_kdenlive.parent.mkdir(parents=True, exist_ok=True)

    # Also place matching <project>.kdenlive.srt next to .kdenlive so Kdenlive auto-loads subtitles
    srt_path = export_project_srt(project_id)
    kdenlive_srt = out_kdenlive.with_suffix(".kdenlive.srt")
    shutil.copyfile(srt_path, kdenlive_srt)

    mlt = ET.Element(
        "mlt",
        {
            "LC_NUMERIC": "C",
            "producer": "main_bin",
            "version": "7.22.0",
            "root": str(pdir.resolve()).replace("\\", "/"),
        },
    )
    ET.SubElement(
        mlt,
        "profile",
        {
            "description": f"Recap {width}x{height} 30fps",
            "width": str(width),
            "height": str(height),
            "progressive": "1",
            "sample_aspect_num": "1",
            "sample_aspect_den": "1",
            "display_aspect_num": "9" if width < height else "16",
            "display_aspect_den": "16" if width < height else "9",
            "frame_rate_num": "30",
            "frame_rate_den": "1",
            "colorspace": "709",
        },
    )

    # Source movie producer
    src_prod = ET.SubElement(
        mlt,
        "producer",
        {"id": "source_movie", "in": "0", "out": str(_sec_to_frames(max(10.0, src_dur), fps))},
    )
    prop_res = ET.SubElement(src_prod, "property", {"name": "resource"})
    prop_res.text = str(src_video.resolve()).replace("\\", "/") if str(src_video) else ""
    prop_aud = ET.SubElement(src_prod, "property", {"name": "audio_index"})
    prop_aud.text = "-1"  # Mute original copyrighted audio on V1

    # Audio producers for each block
    audio_entries: list[tuple[str, int]] = []
    video_entries: list[tuple[int, int]] = []

    for ch in proj.get("chapters", []):
        for blk in ch.get("blocks", []):
            bid = blk["block_id"]
            adur = float(blk.get("audio_duration_sec") or 3.5)
            aframes = max(1, _sec_to_frames(adur, fps))
            apath = blk.get("audio_path") or ""

            aprod_id = f"tts_{bid}"
            aprod = ET.SubElement(mlt, "producer", {"id": aprod_id, "in": "0", "out": str(aframes - 1)})
            p = ET.SubElement(aprod, "property", {"name": "resource"})
            p.text = str(Path(apath).resolve()).replace("\\", "/") if apath else ""
            audio_entries.append((aprod_id, aframes))

            planned = plan_anti_content_id_subclips(blk.get("clips", []), adur, src_dur or 3600.0)
            allocated_frames = 0
            for idx, sc in enumerate(planned):
                in_f = _sec_to_frames(sc["start_sec"], fps)
                if idx == len(planned) - 1:
                    seg_f = max(1, aframes - allocated_frames)
                else:
                    seg_f = max(1, _sec_to_frames(sc["end_sec"] - sc["start_sec"], fps))
                out_f = in_f + seg_f - 1
                video_entries.append((in_f, out_f))
                allocated_frames += seg_f

    main_bin = ET.SubElement(mlt, "playlist", {"id": "main_bin"})
    bprop = ET.SubElement(main_bin, "property", {"name": "kdenlive:docproperties.subtitleFile"})
    bprop.text = kdenlive_srt.name
    ET.SubElement(main_bin, "entry", {"producer": "source_movie"})
    for aprod_id, _ in audio_entries:
        ET.SubElement(main_bin, "entry", {"producer": aprod_id})

    # Video playlist V1
    v_playlist = ET.SubElement(mlt, "playlist", {"id": "playlist_v1"})
    for in_f, out_f in video_entries:
        ET.SubElement(
            v_playlist,
            "entry",
            {"producer": "source_movie", "in": str(in_f), "out": str(out_f)},
        )

    # Audio playlist A1 (Voiceover)
    a_playlist = ET.SubElement(mlt, "playlist", {"id": "playlist_a1"})
    for aprod_id, aframes in audio_entries:
        ET.SubElement(
            a_playlist,
            "entry",
            {"producer": aprod_id, "in": "0", "out": str(aframes - 1)},
        )

    tractor = ET.SubElement(mlt, "tractor", {"id": "maintractor"})
    t_multitrack = ET.SubElement(tractor, "multitrack")
    ET.SubElement(t_multitrack, "track", {"producer": "playlist_v1"})
    ET.SubElement(t_multitrack, "track", {"producer": "playlist_a1"})

    tree = ET.ElementTree(mlt)
    ET.indent(tree, space="  ")
    tree.write(out_kdenlive, encoding="utf-8", xml_declaration=True)

    proj["exports"]["kdenlive_path"] = str(out_kdenlive)
    save_project(proj)
    return {
        "kdenlive_path": str(out_kdenlive),
        "subtitle_path": str(kdenlive_srt),
        "video_cuts_count": len(video_entries),
        "audio_blocks_count": len(audio_entries),
    }


def find_kdenlive_executable() -> str | None:
    on_path = shutil.which("kdenlive")
    if on_path:
        return on_path
    candidates = [
        r"C:\Program Files\kdenlive\bin\kdenlive.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\kdenlive\bin\kdenlive.exe"),
    ]
    for c in candidates:
        if Path(c).is_file():
            return c
    return None


def launch_kdenlive(kdenlive_file: str) -> dict[str, Any]:
    exe = find_kdenlive_executable()
    if not exe:
        return {
            "launched": False,
            "message": "Kdenlive chưa được cài trên máy. File .kdenlive đã được tạo sẵn; bạn có thể cài Kdenlive miễn phí (winget install KDE.Kdenlive) để mở bất cứ lúc nào.",
            "kdenlive_file": kdenlive_file,
        }
    subprocess.Popen([exe, kdenlive_file], close_fds=True)
    return {
        "launched": True,
        "executable": exe,
        "kdenlive_file": kdenlive_file,
    }
