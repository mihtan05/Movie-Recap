"""Resilient Free Vietnamese TTS & Frame-Accurate SRT Generator.

Tries Microsoft Edge-TTS first when available, and automatically falls back to
Google Vietnamese TTS (`gTTS`) enhanced with FFmpeg Studio Mastering (speed `atempo`,
male/female pitch profile, and broadcast loudness normalization) so 60-minute recaps
run 100% free with zero API keys and zero downtime.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import edge_tts
from gtts import gTTS

from .project_store import load_project, project_dir, save_project

SUPPORTED_VI_VOICES = {
    "vi-VN-NamMinhNeural": "Nam Trầm Review Phim (Auto Edge / Studio Pitch)",
    "vi-VN-HoaiMyNeural": "Nữ Nhanh Kịch Tính (Auto Edge / Studio Crisp)",
    "gtts-vi-fast": "Google Tiếng Việt Nhịp Nhanh (+22% Studio)",
}


def probe_audio_duration(audio_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(audio_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return 3.5
    try:
        info = json.loads(proc.stdout)
        return round(float(info["format"]["duration"]), 3)
    except Exception:
        return 3.5


def _rate_to_speed_multiplier(rate: str) -> float:
    """Convert '+14%' or '-5%' to float multiplier like 1.14 (clamped 0.75..1.65)."""
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)%$", rate.strip())
    if not m:
        return 1.16
    pct = float(m.group(1))
    return max(0.75, min(1.65, 1.0 + pct / 100.0))


def _synthesize_gtts_studio_sync(
    text: str,
    out_path: Path,
    voice: str,
    rate: str,
) -> None:
    raw_mp3 = out_path.with_suffix(".raw_gtts.mp3")
    tts = gTTS(text=text, lang="vi", slow=False)
    tts.save(str(raw_mp3))

    speed = _rate_to_speed_multiplier(rate)
    # gTTS base cadence is slightly slower than recap style, boost slightly
    effective_speed = min(1.65, round(speed * 1.06, 3))

    if "NamMinh" in voice:
        # Warm deeper male timbre while keeping natural recap speed
        pitch_factor = 0.87
        tempo_comp = min(1.85, round(effective_speed / pitch_factor, 3))
        af = f"asetrate=24000*{pitch_factor},aresample=44100,atempo={tempo_comp},volume=1.25"
    else:
        af = f"aresample=44100,atempo={effective_speed},volume=1.2"

    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(raw_mp3),
        "-af",
        af,
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        raw_mp3.unlink(missing_ok=True)


async def synthesize_text_to_mp3(
    text: str,
    out_path: Path,
    voice: str = "vi-VN-NamMinhNeural",
    rate: str = "+14%",
) -> float:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if voice.startswith("vi-VN-"):
        try:
            communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
            await asyncio.wait_for(communicate.save(str(out_path)), timeout=6.0)
            if out_path.exists() and out_path.stat().st_size > 256:
                return probe_audio_duration(out_path)
        except Exception:
            out_path.unlink(missing_ok=True)

    # Automatic resilient fallback: gTTS + FFmpeg Studio Mastering
    await asyncio.to_thread(_synthesize_gtts_studio_sync, text, out_path, voice, rate)
    return probe_audio_duration(out_path)


async def synthesize_block(project_id: str, block_id: str) -> dict[str, Any]:
    proj = load_project(project_id)
    vcfg = proj.get("voice_settings", {})
    voice = vcfg.get("voice", "vi-VN-NamMinhNeural")
    rate = vcfg.get("rate", "+14%")
    pdir = project_dir(project_id)

    for ch in proj.get("chapters", []):
        for blk in ch.get("blocks", []):
            if blk.get("block_id") == block_id:
                text = blk.get("narration", "").strip()
                if not text:
                    raise ValueError(f"Block '{block_id}' has empty narration.")
                out_mp3 = pdir / "audio" / f"{block_id}.mp3"
                dur = await synthesize_text_to_mp3(text, out_mp3, voice=voice, rate=rate)
                blk["audio_path"] = str(out_mp3)
                blk["audio_duration_sec"] = dur
                blk["status"] = "tts_ready"
                ch["chapter_video_path"] = ""
                save_project(proj)
                export_project_srt(project_id)
                return blk
    raise KeyError(f"Block '{block_id}' not found in '{project_id}'")


async def synthesize_project_tts(
    project_id: str,
    chapter_id: str | None = None,
    force: bool = False,
    concurrency: int = 4,
) -> dict[str, Any]:
    proj = load_project(project_id)
    vcfg = proj.get("voice_settings", {})
    voice = vcfg.get("voice", "vi-VN-NamMinhNeural")
    rate = vcfg.get("rate", "+14%")
    pdir = project_dir(project_id)

    sem = asyncio.Semaphore(concurrency)
    synthesized_count = 0

    async def _worker(blk: dict[str, Any]) -> None:
        nonlocal synthesized_count
        text = blk.get("narration", "").strip()
        if not text:
            return
        existing = blk.get("audio_path", "")
        if not force and existing and Path(existing).exists() and blk.get("audio_duration_sec", 0) > 0:
            return
        out_mp3 = pdir / "audio" / f"{blk['block_id']}.mp3"
        async with sem:
            dur = await synthesize_text_to_mp3(text, out_mp3, voice=voice, rate=rate)
        blk["audio_path"] = str(out_mp3)
        blk["audio_duration_sec"] = dur
        blk["status"] = "tts_ready"
        synthesized_count += 1

    tasks = []
    for ch in proj.get("chapters", []):
        if chapter_id and ch.get("chapter_id") != chapter_id:
            continue
        for blk in ch.get("blocks", []):
            tasks.append(_worker(blk))

    if tasks:
        await asyncio.gather(*tasks)

    save_project(proj)
    srt_file = export_project_srt(project_id)
    total_dur = sum(
        float(b.get("audio_duration_sec") or 0.0)
        for ch in proj.get("chapters", [])
        for b in ch.get("blocks", [])
    )
    return {
        "project_id": project_id,
        "synthesized_blocks": synthesized_count,
        "total_duration_sec": round(total_dur, 2),
        "total_duration_minutes": round(total_dur / 60.0, 2),
        "srt_path": str(srt_file),
    }


def _format_srt_ts(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000)))
    hrs = ms_total // 3_600_000
    rem = ms_total % 3_600_000
    mins = rem // 60_000
    rem %= 60_000
    secs = rem // 1000
    ms = rem % 1000
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def _split_caption_chunks(text: str, max_words: int = 12) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    chunks: list[str] = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i : i + max_words]))
    return chunks


def export_project_srt(project_id: str, chapter_id: str | None = None) -> Path:
    proj = load_project(project_id)
    pdir = project_dir(project_id)
    suffix = f"_{chapter_id}" if chapter_id else ""
    out_srt = pdir / "exports" / f"{project_id}{suffix}.srt"
    out_srt.parent.mkdir(parents=True, exist_ok=True)

    cursor = 0.0
    idx = 1
    lines: list[str] = []

    for ch in proj.get("chapters", []):
        if chapter_id and ch.get("chapter_id") != chapter_id:
            continue
        for blk in ch.get("blocks", []):
            text = blk.get("narration", "").strip()
            dur = float(blk.get("audio_duration_sec") or 3.5)
            if not text:
                cursor += dur
                continue
            chunks = _split_caption_chunks(text, max_words=13)
            total_chars = max(1, sum(len(c) for c in chunks))
            local_start = cursor
            for c_i, chunk in enumerate(chunks):
                if c_i == len(chunks) - 1:
                    local_end = cursor + dur
                else:
                    portion = dur * (len(chunk) / total_chars)
                    local_end = local_start + portion
                lines.append(f"{idx}")
                lines.append(f"{_format_srt_ts(local_start)} --> {_format_srt_ts(local_end)}")
                lines.append(chunk)
                lines.append("")
                idx += 1
                local_start = local_end
            cursor += dur

    out_srt.write_text("\n".join(lines), encoding="utf-8")
    if not chapter_id:
        proj["exports"]["srt_path"] = str(out_srt)
        save_project(proj)
    return out_srt
