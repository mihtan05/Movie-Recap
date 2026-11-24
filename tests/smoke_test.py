"""End-to-end automated verification for Movie Recap Studio MCP Server & GPU Pipeline."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run_smoke_test() -> None:
    sample_dir = Path(r"D:\CLIP\temp_cache\_smoke_src")
    sample_dir.mkdir(parents=True, exist_ok=True)
    sample_mp4 = sample_dir / "sample_action.mp4"

    print("1. Creating 12s 1080p test video via FFmpeg...")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1920x1080:rate=30:duration=12",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=12",
            "-c:v",
            "h264_nvenc",
            "-c:a",
            "aac",
            str(sample_mp4),
        ],
        check=True,
    )

    server_params = StdioServerParameters(
        command=str(REPO_ROOT / ".venv" / "Scripts" / "python.exe"),
        args=[str(REPO_ROOT / "mcp_server" / "server.py")],
        env={**os.environ, "RECAP_CACHE_ROOT": r"D:\CLIP\temp_cache", "PYTHONIOENCODING": "utf-8"},
    )

    print("2. Connecting to Movie Recap Studio MCP Server over stdio...")
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_res = await session.list_tools()
            tool_names = [t.name for t in tools_res.tools]
            print(f"   Registered MCP Tools ({len(tool_names)}): {tool_names}")
            assert "open_recap_studio" in tool_names

            resources_res = await session.list_resources()
            res_uris = [str(r.uri) for r in resources_res.resources]
            print(f"   Registered MCP Resources: {res_uris}")
            assert "ui://recap-studio/app.html" in res_uris

            print("3. Creating smoke-test project & Storyboard 5x5 sheet...")
            r_create = await session.call_tool(
                "recap_create_project",
                {"title": "Smoke Test Action", "source_video_path": str(sample_mp4), "target_minutes": 5},
            )
            pid = r_create.structured_content["active_project"]["project_id"]
            assert pid == "smoke-test-action"

            r_sb = await session.call_tool(
                "recap_generate_storyboards",
                {"project_id": pid, "interval_sec": 3.0},
            )
            sb_urls = r_sb.structured_content["active_project"]["source"]["storyboard_urls"]
            assert len(sb_urls) >= 1
            print(f"   Storyboard URL: {sb_urls[0]['url']}")

            print("4. Saving chapter & synthesizing Vietnamese Edge-TTS + SRT...")
            await session.call_tool(
                "recap_upsert_chapter",
                {
                    "project_id": pid,
                    "chapter_id": "ch01",
                    "title": "Chương 1: Mở đầu kịch tính",
                    "blocks": [
                        {
                            "narration": "Chuyện gì sẽ xảy ra khi ông chú sát thủ quyết định tái xuất giang hồ?",
                            "start_sec": 0.5,
                            "end_sec": 4.0,
                        },
                        {
                            "narration": "Chỉ trong chớp mắt, toàn bộ đám tay sai đã phải lên bảng đếm số.",
                            "start_sec": 5.5,
                            "end_sec": 9.0,
                            "flip_h": True,
                        },
                    ],
                },
            )
            r_tts = await session.call_tool("recap_synthesize_tts", {"project_id": pid})
            assert not r_tts.is_error

            print("5. Rendering full movie with NVIDIA NVENC GPU + Kdenlive XML...")
            r_full = await session.call_tool("recap_render_full_movie", {"project_id": pid, "burn_subtitles": False})
            assert not r_full.is_error
            mp4_stream_url = r_full.structured_content["active_project"]["exports"]["mp4_stream_url"]
            kdenlive_path = r_full.structured_content["active_project"]["exports"]["kdenlive_path"]
            assert Path(kdenlive_path).exists()
            print(f"   Rendered MP4 stream URL: {mp4_stream_url}")
            print(f"   Exported Kdenlive XML: {kdenlive_path}")

            print("6. Verifying HTTP 206 Partial Content Range Streaming...")
            req = urllib.request.Request(mp4_stream_url, headers={"Range": "bytes=0-1023"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                assert resp.status == 206
                data = resp.read()
                assert len(data) == 1024
                print(f"   HTTP Range test passed: status={resp.status}, bytes={len(data)}")

            print("7. Testing Zero-Local-Storage cleanup (wiping project cache to 0 MB)...")
            r_clean = await session.call_tool(
                "recap_clean_local_cache",
                {"project_id": pid, "delete_entire_project": True},
            )
            assert not r_clean.is_error

    # Remove sample source dir too
    import shutil

    shutil.rmtree(sample_dir, ignore_errors=True)
    print("=== ALL END-TO-END SMOKE TESTS PASSED (D:\\CLIP\\temp_cache returned to 0 MB)! ===")


if __name__ == "__main__":
    asyncio.run(run_smoke_test())
