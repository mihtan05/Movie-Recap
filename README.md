# 🎬 Movie Recap Studio (Antigravity Plugin & Zero-Storage Pipeline)

Bộ công cụ **Subagents + MCP App Giao diện Khung phải + Workflow 45–60 phút** dành cho **Google Antigravity**, chuyên làm video **Review / Tóm tắt Phim** theo phong cách Việt Nam:

- **Tốn 0đ API bên ngoài**: Tận dụng 100% gói thuê bao Antigravity hiện tại (kết hợp tách phụ đề `.srt` + bảng ảnh **Storyboard 5x5 có mã giờ** để AI nhìn cảnh phim + giọng đọc **Edge-TTS** tiếng Việt miễn phí không giới hạn).
- **Giao diện Studio ngay bên phải Khung Chat (`MCP App Side Pane`)**: Xem trước video từng chương/từng cảnh, sửa Từ điển nhân vật, nghe thử thoại, bấm 1 nút gửi cảnh sang khung Chat để prompt chỉnh sửa trong **3 giây**.
- **Chống quét bản quyền Content ID & Render siêu tốc bằng NVIDIA NVENC GPU**: Tự động chia cú cắt `<= 3.5s`, nhảy cóc không liền mạch, zoom nhẹ `107%`, tắt nhạc gốc OST, xuất đồng thời cả **`.mp4`** và project **`.kdenlive`** (MLT XML).
- **Zero Local Storage (`D:\CLIP\temp_cache` -> Google Drive -> 0 MB ổ máy)**: Xuất xong tự đẩy `.mp4` + `.srt` + `.kdenlive` lên **Google Drive** của tài khoản hiện tại và tự dọn sạch bộ đệm tạm trên ổ cứng về `~0 MB`.

---

## Cấu trúc Repository (~1.5 MB)

```text
movie-recap-studio/
├── plugin.json                        # Manifest định danh Plugin Antigravity
├── mcp_config.json                    # Cấu hình MCP Server + MCP App UI
├── setup_windows.ps1                  # Script cài đặt 1 chạm khi clone qua máy mới
├── requirements.txt                   # Thư viện Python gọn nhẹ (mcp, edge-tts, scenedetect...)
├── rules/
│   └── AGENTS.md                      # Quy chuẩn văn phong Review Phim VN & chống Content ID
├── agents/                            # Bộ 4 Subagents chuyên biệt
│   ├── recap-scene-analyst.md         # Quét phụ đề .srt & bảng ảnh Storyboard 5x5
│   ├── recap-scriptwriter.md          # Viết kịch bản 900-1.200 từ/chương (Cold Open + Cliffhanger)
│   ├── recap-voice-sub.md             # Tổng hợp giọng đọc Edge-TTS & phụ đề .srt
│   └── recap-kdenlive-editor.md       # Dựng GPU NVENC, xuất Kdenlive & đồng bộ Google Drive
├── skills/
│   └── movie-recap-pipeline/
│       └── SKILL.md                   # Quy trình điều phối End-to-End (5 phút -> 60 phút)
├── workflows/
│   └── mega_recap_60m.py              # Chạy song song 8-10 chương bằng model Flash tiết kiệm quota
├── src/                               # Lõi xử lý Media & Kdenlive
│   ├── project_store.py               # Quản lý timeline.json theo từng Block không phá hủy
│   ├── tts_engine.py                  # Edge-TTS (Nam Minh / Hoài My) & xuất .srt chuẩn khung hình
│   ├── media_engine.py                # FFmpeg NVENC, Storyboard 5x5, cắt cảnh chống Content ID
│   ├── kdenlive_exporter.py           # Bộ sinh file .kdenlive chuẩn MLT XML
│   ├── local_streamer.py              # HTTP Range Streamer (127.0.0.1) tua mượt video 60 phút
│   └── gdrive_sync.py                 # Trợ lý đồng bộ Google Drive & dọn ổ máy 0 MB
└── mcp_server/
    ├── server.py                      # MCP Server & các công cụ điều khiển Studio
    └── ui_dist/app.html               # Giao diện đơn file Movie Recap Studio (Side Pane)
```

---

## Cài đặt trên máy khác từ GitHub

```powershell
git clone https://github.com/mihtan05/Movie-Recap.git D:\CLIP\movie-recap-studio
cd D:\CLIP\movie-recap-studio
.\setup_windows.ps1
```
