# Theo dõi chứng khoán tự động

Chương trình gửi bản tin về Telegram mỗi ngày:

- **07:05 sáng (thứ 3 → thứ 7):** chứng khoán Mỹ, Nhật, Trung Quốc, DXY, tỷ giá, vàng, Bitcoin, lợi suất trái phiếu 10 năm Mỹ / Nhật / Việt Nam.
- **Mỗi phút** trong phiên VN (file lịch `lien-tuc.yml`): cảnh báo dòng tiền bất thường gửi ngay — khối lượng đột biến, mua/bán chủ động áp đảo, lệnh lớn, khối ngoại. Phiên Mỹ (20:00–4:00): biến động chỉ số thế giới 15 phút/lần. Mỗi giờ thêm tóm tắt ngắn.
- **15:20 chiều (thứ 2 → thứ 6):** dòng tiền các mã VN100 (KL bất thường, khối ngoại, mua/bán chủ động, lệnh lớn), báo cáo tài chính quý (khi có báo cáo mới), cảnh báo danh mục, vĩ mô trong nước (tỷ giá Vietcombank, vàng SJC).

## Các file

| File | Việc |
|---|---|
| `config.yaml` | **File duy nhất bạn cần sửa**: danh sách mã, ngưỡng tín hiệu, danh mục đang nắm giữ |
| `main.py` | Chương trình chính |
| `src/` | Các phần xử lý: lấy dữ liệu, kỹ thuật, BCTC, vĩ mô, soạn và gửi tin |
| `.github/workflows/theo-doi.yml` | Lịch chạy tự động trên GitHub |
| `workflow-dan-vao-github.txt` | Bản sao file lịch `theo-doi.yml`, để dán vào GitHub |
| `lien-tuc-dan-vao-github.txt` | Bản sao file lịch `lien-tuc.yml` (quét mỗi phút) |
| `data/` | Chương trình tự ghi: `lich_su_dong_tien.csv` (số liệu dòng tiền mỗi ngày, mở bằng Excel) và trạng thái |

## Chạy tay

Trên GitHub: tab **Actions** → **Theo doi chung khoan** → **Run workflow** → chọn:
- `chieu`: bản tin dòng tiền VN100 + vĩ mô
- `sang`: bản tin thế giới
- `nhanh`: cập nhật 15 phút (chạy tay luôn kèm tóm tắt)
- `kiem-tra`: kiểm tra từng nguồn dữ liệu (dùng khi có lỗi)

Lưu ý: đây là công cụ hỗ trợ theo dõi, không phải khuyến nghị đầu tư.
