# Theo dõi chứng khoán tự động

Chương trình gửi bản tin về Telegram mỗi ngày:

- **07:05 sáng (thứ 3 → thứ 7):** chứng khoán Mỹ, Nhật, Trung Quốc, DXY, tỷ giá, vàng, Bitcoin, lợi suất trái phiếu 10 năm Mỹ / Nhật / Việt Nam.
- **15 phút/lần** trong phiên VN (9:00–15:00) và phiên Mỹ (20:00–4:00): chỉ nhắn cảnh báo mới, mỗi giờ thêm tóm tắt ngắn.
- **15:20 chiều (thứ 2 → thứ 6):** tín hiệu kỹ thuật cho các mã VN100, báo cáo tài chính quý (khi có báo cáo mới), cảnh báo danh mục, vĩ mô trong nước (tỷ giá Vietcombank, vàng SJC).

## Các file

| File | Việc |
|---|---|
| `config.yaml` | **File duy nhất bạn cần sửa**: danh sách mã, ngưỡng tín hiệu, danh mục đang nắm giữ |
| `main.py` | Chương trình chính |
| `src/` | Các phần xử lý: lấy dữ liệu, kỹ thuật, BCTC, vĩ mô, soạn và gửi tin |
| `.github/workflows/theo-doi.yml` | Lịch chạy tự động trên GitHub |
| `workflow-dan-vao-github.txt` | Bản sao file lịch chạy, để dán vào GitHub nếu thư mục `.github` bị ẩn |
| `data/` | Chương trình tự ghi lịch sử tín hiệu |

## Chạy tay

Trên GitHub: tab **Actions** → **Theo doi chung khoan** → **Run workflow** → chọn:
- `chieu`: bản tin VN30 + vĩ mô
- `sang`: bản tin thế giới
- `nhanh`: cập nhật 15 phút (chạy tay luôn kèm tóm tắt)
- `kiem-tra`: kiểm tra từng nguồn dữ liệu (dùng khi có lỗi)

Lưu ý: đây là công cụ hỗ trợ theo dõi, không phải khuyến nghị đầu tư.
