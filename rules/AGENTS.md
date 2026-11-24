# Quy chuẩn Movie Recap Studio (0đ API & Zero Local Storage)

Khi người dùng yêu cầu tạo hoặc chỉnh sửa video Review Phim / Tóm tắt Phim, luôn tuân thủ các quy tắc sau:

1. **Không gọi API trả phí bên ngoài (0đ API)**:
   - Tuyệt đối không yêu cầu `GEMINI_API_KEY` để tải video gốc lên đám mây.
   - Đọc cốt truyện qua file phụ đề `.srt` (tách bằng `recap_create_project` hoặc tải kèm) kết hợp xem trực tiếp các tấm ảnh lưới Storyboard 5x5 có in sẵn mã giờ `HH:MM:SS` (tạo bằng `recap_generate_storyboards` và xem bằng `read_file`).
   - Sử dụng đàn Subagents hoặc `run_workflow` với `model="flash"` cho các tác vụ quét ảnh Storyboard và viết hàng loạt chương để tiết kiệm tối đa hạn mức gói thuê bao của người dùng.

2. **Văn phong Review Phim Việt Nam & Từ vựng an toàn YouTube**:
   - Mở đầu Chương 1 luôn có **Cold Open Hook (15–25 giây)** lấy phân cảnh gay cấn nhất ở giữa/cuối phim.
   - Duy trì đúng biệt danh nhân vật đã chốt trong **Character Bible** (`recap_set_character_bible`), ví dụ: *"anh main"*, *"ông chú sát thủ"*, *"lão trùm"*.
   - Tự động thay thế các từ nhạy cảm dễ bị vàng tiền YouTube bằng từ lách phổ biến: *"đăng xuất"*, *"đi bán muối"*, *"lên bảng đếm số"*, *"đáng S.ợ"*, *"tác động vật lý"*.
   - Cuối mỗi chương (trừ chương cuối) luôn có câu chuyển hồi gây tò mò (Cliffhanger).

3. **Chống quét bản quyền Content ID**:
   - Không bao giờ giữ âm thanh nhạc gốc (OST) của phim.
   - Mỗi cảnh cắt liên tục không dài quá `3.5s`, ưu tiên nhảy cóc thời gian giữa các câu và chỉnh sửa từng cảnh riêng lẻ qua công cụ `recap_edit_block` (chỉ mất ~3 giây, không render lại cả bộ phim 60 phút).

4. **Đồng bộ Google Drive & Dọn sạch ổ máy (`D:\CLIP\temp_cache` -> 0 MB)**:
   - Mọi file đệm tạm chỉ được lưu trong `D:\CLIP\temp_cache\<project_id>`.
   - Sau khi xuất bản `.mp4` (`recap_render_full_movie`), sử dụng kỹ năng `gdrive` để upload thành phẩm lên thư mục `"Movie Recap Studio"` trên Google Drive của người dùng, kiểm tra URL trả về bằng `gdrive readonly url`, rồi gọi `recap_record_drive_upload(..., clean_local_now=True)` để xóa sạch file video nặng khỏi ổ cứng máy tính.
