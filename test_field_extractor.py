import sys
sys.path.insert(0, r'D:\Code\AI-extract\src')

from ollama import Client
from field_extractor import extract_fields
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
    "Thực hiện Kế hoạch số 128-KH/HU ngày 10/7/2019 của Huyện ủy Cô Tô "
    '"Về tổ chức đại hội đảng bộ các cấp tiến tới Đại hội Đại biểu Đảng bộ '
    'huyện Cô Tô lần thứ VI, nhiệm kỳ 2020 - 2025".\n\n'
    "Yêu cầu các chi, Đảng bộ cơ sở gửi lịch Đại hội về Cơ quan Tổ chức - "
    "Nội vụ huyện trước ngày 18/3/2020.\n\n"
    "K/T THỦ TRƯỞNG\n"
    "PHÓ THỦ TRƯỞNG\n\n"
    "Trương Thị Phương"
)

print("Calling Ollama field extractor...")
result = extract_fields(text, client)

# Write to file first (avoids Windows cp1252 console encoding issues)
out_path = r'D:\Code\AI-extract\field_extractor_result.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"Result written to {out_path}")

# Print ASCII-escaped version safe for any console
print(json.dumps(result, ensure_ascii=True, indent=2))
