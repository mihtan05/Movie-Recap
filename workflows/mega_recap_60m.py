"""Dynamic Antigravity Workflow for 45-60 Minute Movie Recaps (8-10 Chapters in Parallel).

Usage via `run_workflow`:
  run_workflow(
      ScriptPath="D:/CLIP/movie-recap-studio/workflows/mega_recap_60m.py",
      Args={
          "project_id": "ten-du-an",
          "chapters_plan": [
              {"chapter_id": "ch01", "title": "Chương 1: Sát thủ quy ẩn", "start_sec": 0, "end_sec": 900, "plot_notes": "..."},
              ...
          ]
      },
      Description="Viết song song 8-10 chương kịch bản Review Phim bằng model Flash tiết kiệm quota"
  )
"""

import json

project_id = args.get("project_id", "")
chapters_plan = args.get("chapters_plan", [])
style = args.get("style", "Hành động kịch tính, nhịp nhanh, đặt biệt danh hài hước, từ vựng lách kiểm duyệt YouTube")

if not project_id or not chapters_plan:
    raise ValueError("Cần truyền 'project_id' và danh sách 'chapters_plan' trong Args.")

BLOCK_LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "chapter_id": {"type": "string"},
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "narration": {"type": "string"},
                    "start_sec": {"type": "number"},
                    "end_sec": {"type": "number"},
                    "flip_h": {"type": "boolean"},
                },
                "required": ["narration", "start_sec", "end_sec"],
            },
        },
    },
    "required": ["chapter_id", "title", "blocks"],
}

phase("Viết song song kịch bản các chương (Model Flash tiết kiệm quota)")


def make_chapter_writer(ch):
    cid = ch["chapter_id"]
    title = ch["title"]
    s_sec = ch.get("start_sec", 0)
    e_sec = ch.get("end_sec", s_sec + 900)
    notes = ch.get("plot_notes", "")
    is_first = cid.endswith("01") or cid == "ch1"
    hook_rule = (
        "3 block đầu tiên PHẢI là Cold Open Hook lấy cảnh cao trào kịch tính nhất phim!"
        if is_first
        else "Mở đầu nối mượt từ chương trước và kết thúc bằng 1 câu Cliffhanger gây tò mò!"
    )

    prompt = f"""Viết kịch bản chi tiết cho {title} (`{cid}`) của dự án `{project_id}` lưu tại `D:\\CLIP\\temp_cache\\{project_id}\\timeline.json`.
1. Đọc file `D:\\CLIP\\temp_cache\\{project_id}\\timeline.json` để lấy `character_bible` (dùng đúng 100% biệt danh nhân vật) và đọc đoạn phụ đề gốc/storyboard tương ứng khoảng giây `{s_sec}s` -> `{e_sec}s`.
2. Phong cách: {style}.
3. {hook_rule}
4. Viết khoảng 40 - 55 blocks (mỗi block 18-24 từ tiếng Việt, tổng ~950-1.100 từ cho ~5.5-6.5 phút thuyết minh).
5. Tuyệt đối dùng từ an toàn YouTube ("đăng xuất", "đi bán muối", "tác động vật lý", "đáng S.ợ").
6. Ghi chú diễn biến chương này: {notes}
Trả về đúng cấu trúc JSON yêu cầu."""

    return agent(
        prompt=prompt,
        schema=BLOCK_LIST_SCHEMA,
        role=f"Biên kịch {cid}",
        model="flash",
    )


results = await parallel(chapters_plan, make_chapter_writer)
log(f"Đã viết xong {len(results)} chương kịch bản!")
print(json.dumps(results, ensure_ascii=False))
