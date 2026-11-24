---
name: movie-recap-pipeline
description: Quy trình khép kín tạo video Review & Tóm tắt phim (từ ngắn 3-5 phút đến Mega-Recap 45-60 phút) ngay trong Antigravity bằng gói thuê bao hiện tại (0đ API), hiển thị giao diện Studio bên phải, xuất Kdenlive & MP4 bằng GPU và tự động đẩy lên Google Drive (dọn sạch ổ máy 0 MB).
---

# Quy trình Movie Recap Studio (End-to-End 0đ API)

Kích hoạt kỹ năng này bất cứ khi nào người dùng muốn làm video Review Phim / Tóm tắt Phim, mở giao diện **Movie Recap Studio**, chỉnh sửa cảnh bằng prompt, xuất Kdenlive hoặc đẩy video lên Google Drive.

---

## Bước 0: Mở Khung Studio Bên Phải & Chuẩn bị Nguồn Phim

1. Gọi công cụ MCP `open_recap_studio` (thuộc server `movie-recap-studio_recap-studio`) để bật giao diện **🎬 Movie Recap Studio** ở khung bên phải (`aux_pane`).
2. Xác định nguồn phim người dùng đưa:
   - **Nếu là link Google Drive**: Đọc kỹ năng `gdrive`, chạy `gdrive readonly download <FILE_ID> --out "D:\CLIP\temp_cache\<slug>\source\source_movie.mp4"` để tải tạm vào bộ đệm `D:\CLIP\temp_cache`.
   - **Nếu là file trên máy**: Truyền trực tiếp đường dẫn vào `recap_create_project`.

---

## Bước 1: Khởi tạo Dự án, Tách `.SRT` & Tạo Bảng ảnh Storyboard (0đ API)

1. Gọi `recap_create_project(title=..., source_video_path=..., target_minutes=...)`.
   - Nếu file `.mkv` / `.mp4` có sẵn luồng phụ đề, hệ thống tự động tách ra `extracted_source.srt` trong 2 giây.
   - Nếu người dùng có file `.srt` ngoài, lưu đường dẫn vào dự án.
2. Gọi `recap_generate_storyboards(project_id=..., interval_sec=15.0)` để tạo các bảng ảnh lưới **5x5 (`HH:MM:SS` in trên góc mỗi ô ảnh)**.
3. Dùng `read_file` xem các bảng ảnh Storyboard + đọc `.srt` để nắm 100% cốt truyện và mặt nhân vật mà **không tốn bất kỳ API trả phí nào**.

---

## Bước 2: Chốt "Từ điển Nhân vật" & Duyệt Chương 1 trước khi chạy hàng loạt

1. Gọi `recap_set_character_bible(project_id=..., characters=[...])` để khóa biệt danh thống nhất (VD: `Sato` -> `"Anh main sát thủ"`).
2. **Với video dài 45–60 phút (8–10 chương)**:
   - Luôn viết và dựng thử **Chương 1 (`ch01` ~5–6 phút, gồm Cold Open Hook)** trước bằng `recap_upsert_chapter` -> `recap_synthesize_tts(chapter_id="ch01")` -> `recap_render_preview(chapter_id="ch01")`.
   - Mời người dùng xem thử ngay trên **Khung Studio bên phải**!
   - Sau khi người dùng chốt phong cách Chương 1 (hoặc nếu người dùng yêu cầu chạy một mạch toàn bộ ngay từ đầu), gọi `run_workflow` chạy script `D:\CLIP\movie-recap-studio\workflows\mega_recap_60m.py` (sử dụng `model="flash"` chạy song song tất cả các chương còn lại để nhanh gấp 8 lần và tiết kiệm hạn mức gói thuê bao).

---

## Bước 3: Chỉnh sửa tức thì theo Prompt (3 giây / cảnh)

Khi người dùng nhắn chỉnh sửa một câu hoặc một phân cảnh cụ thể (ví dụ: *"Câu 4 chương 2 viết gắt hơn và đổi sang cảnh đánh nhau ở 34:15"*):
- **TUYỆT ĐỐI KHÔNG render lại cả bộ phim 60 phút!**
- Chỉ gọi duy nhất công cụ `recap_edit_block(project_id=..., block_id=..., narration=..., start_sec=..., render_preview=True)`. Công cụ này chỉ đọc lại TTS và cắt lại đúng 1 cảnh đó trong ~3 giây rồi làm mới ngay Khung Studio bên phải!

---

## Bước 4: Xuất Thành phẩm GPU -> Tải lên Google Drive -> Dọn sạch ổ máy (0 MB)

Khi người dùng bấm xuất bản hoặc yêu cầu xuất video lên Google Drive:
1. Gọi `recap_synthesize_tts(project_id=...)` (đảm bảo 100% câu thoại đã có audio & `.srt`).
2. Gọi `recap_render_full_movie(project_id=...)`:
   - Hệ thống tự động render cuốn chiếu từng chương bằng **NVIDIA NVENC GPU (`h264_nvenc`)**, áp dụng cắt nhảy cóc `<= 3.5s` + zoom nhẹ `107%` chống Content ID, xuất cả `.mp4`, `.srt` và `.kdenlive`.
3. Thực hiện đẩy lên Google Drive bằng CLI `gdrive` (đọc hướng dẫn trong kỹ năng `gdrive` nếu cần đăng nhập lần đầu):
   ```powershell
   gdrive readonly search --name-exact "Movie Recap Studio" --type folder --json
   # Nếu chưa có thư mục, tạo mới:
   gdrive mutate mkdir "Movie Recap Studio"
   # Upload thành phẩm:
   gdrive mutate upload "<mp4_path>" --parent <FOLDER_ID>
   gdrive mutate upload "<srt_path>" --parent <FOLDER_ID>
   gdrive mutate upload "<kdenlive_path>" --parent <FOLDER_ID>
   gdrive readonly url <MP4_FILE_ID>
   ```
4. **Chỉ sau khi đã lấy được link Google Drive hợp lệ**, gọi `recap_record_drive_upload(project_id=..., drive_mp4_url=..., clean_local_now=True)` để lưu link Drive vào giao diện và **xóa sạch toàn bộ file video/audio tạm trong `D:\CLIP\temp_cache` về ~0 MB**!
