import sys
sys.path.insert(0, r'D:\Code\AI-extract\src')

from ollama import Client
import json

client = Client(host='http://127.0.0.1:11435')

text = (
    "HUYỆN ỦY CÔ TÔ\n"
    "CƠ QUAN TỔ CHỨC – NỘI VỤ\n\n"
    "Số 29-CV/TC-NV\n"
    "V/v báo cáo lịch Đại hội chi, đảng bộ cơ sở, nhiệm kỳ 2020 - 2025\n\n"
    "ĐẢNG CỘNG SẢN VIỆT NAM\n"
    "Cô Tô, ngày 16 tháng 3 năm 2020\n\n"
    "Kính gửi: Các chi, đảng bộ cơ sở\n\n"
    "Thực hiện Kế hoạch số 128-KH/HU ngày 10/7/2019 của Huyện ủy Cô Tô.\n\n"
    "Yêu cầu gửi lịch Đại hội trước ngày 18/3/2020.\n\n"
    "K/T THỦ TRƯỞNG\nPHÓ THỦ TRƯỞNG\n\nTrương Thị Phương"
)

prompt = (
    "Đọc văn bản hành chính Việt Nam sau và trích xuất các trường dữ liệu.\n"
    "Chỉ trả về JSON hợp lệ, không giải thích thêm, không markdown, không dấu ```json.\n\n"
    "Văn bản:\n" + text + "\n\n"
    "Trả về JSON với đúng các trường sau (để trống \"\" nếu không tìm thấy):\n"
    '{\n'
    '  "tac_gia": "tên cơ quan hoặc tác giả ban hành văn bản",\n'
    '  "the_loai": "thể loại văn bản (Công văn, Quyết định, Thông báo, v.v.)",\n'
    '  "ngay_thang_nam": "ngày tháng năm theo định dạng DD/MM/YYYY",\n'
    '  "trich_yeu": "trích yếu nội dung văn bản",\n'
    '  "do_mat": "độ mật (Tuyệt mật / Tối mật / Mật) hoặc để trống nếu không có",\n'
    '  "nguoi_ky": "họ tên người ký văn bản",\n'
    '  "loai_ban": "unknown"\n'
    '}\n'
)

out_path = r'D:\Code\AI-extract\debug_raw_response.txt'

# Test: chat() with think=False
response = client.chat(
    model="qwen3:4b",
    messages=[{"role": "user", "content": prompt}],
    options={"temperature": 0},
    think=False,
)

msg = response.message
content = msg.content if hasattr(msg, 'content') else ''
thinking = getattr(msg, 'thinking', None) or ''

with open(out_path, 'w', encoding='utf-8') as f:
    f.write(f"content length: {len(content)}\n")
    f.write(f"thinking length: {len(thinking)}\n\n")
    f.write("--- content ---\n")
    f.write(content)
    f.write("\n\n--- thinking (first 300) ---\n")
    f.write(str(thinking)[:300])

print(f"content length={len(content)}, thinking length={len(thinking)}")
