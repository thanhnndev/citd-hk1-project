# Hàm Ninh AI Guide 🦀

Trợ lý AI du lịch bền vững cho làng chài Hàm Ninh, Phú Quốc.

## Giới thiệu

Hàm Ninh AI Guide là hệ thống multi-agent AI kết hợp:
- **RAG Agent** — Trả lời câu hỏi văn hóa, lịch sử Hàm Ninh dựa trên tài liệu thật
- **Maps Agent** — Tìm kiếm địa điểm, nhà hàng, dịch vụ gần người dùng
- **Ensemble Re-ranker** — Xếp hạng ưu tiên cơ sở kinh doanh địa phương

## Mục tiêu

- Bảo tồn văn hóa làng chài Hàm Ninh
- Hỗ trợ tiểu thương, ngư dân địa phương
- Cung cấp thông tin du lịch chính xác, có kiểm chứng

## Tech Stack

| Lớp | Công nghệ |
|---|---|
| Frontend | Next.js 16, Tailwind CSS |
| Backend | FastAPI, Python 3.11 |
| AI Agents | LangGraph 1.1 |
| Vector DB | Qdrant v1.13.6 |
| Database | PostgreSQL 17, Redis 8.0 |
| ML | scikit-learn 1.8.0 |

## Cài đặt

```bash
# Clone project
git clone https://github.com/thanhnndev/citd-hk1-project.git
cd citd-hk1-project

# Chạy toàn bộ hệ thống
cp .env.example .env
docker compose up
```

## Cấu trúc project