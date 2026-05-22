# 🦀 Hàm Ninh AI Guide

> Trợ lý AI du lịch bền vững cho làng chài Hàm Ninh, Phú Quốc.

---

## 👥 Thành viên nhóm

| MSSV | Họ và tên |
|---|---|
| 26410127 | Dương Quốc Thương |
| 26410115 | Nông Nguyễn Thành |
| 26410146 | Hoàng Võ Minh Tuấn |
| 26410118 | Bùi Quốc Thịnh |
| 26410024 | Trần Tiến Dũng |

---

## 📖 Giới thiệu

Hàm Ninh AI Guide là hệ thống trợ lý AI đa tác nhân (Multi-Agent) kết hợp RAG và Ensemble Re-ranking để hỗ trợ du lịch bền vững tại làng chài Hàm Ninh, Phú Quốc, Kiên Giang.

Hệ thống giải quyết 2 vấn đề cốt lõi:
- Các nền tảng lớn ưu tiên cơ sở có ngân sách marketing → tiểu thương địa phương bị thiệt thòi
- Thiếu thông tin văn hóa, lịch sử chính xác về làng chài Hàm Ninh

---

## 🤖 Kiến trúc hệ thống

### Multi-Agent System
Hệ thống gồm 3 agent phối hợp dưới sự điều phối của Supervisor:

| Agent | Vai trò |
|---|---|
| **RAG Agent** | Trả lời câu hỏi văn hóa, lịch sử Hàm Ninh từ tài liệu thật |
| **Maps Agent** | Tìm kiếm địa điểm, nhà hàng qua Google Places API |
| **Ensemble Re-ranker** | Xếp hạng lại kết quả ưu tiên cơ sở địa phương |

### RAG Pipeline
1. Câu hỏi → chuyển thành vector (embedding)
2. Tìm tài liệu tương tự trong Qdrant
3. Ghép tài liệu vào prompt → LLM sinh câu trả lời
4. Trả về kèm citation nguồn

### Ensemble Re-ranking
Kết hợp Bagging (3 Decision Trees song song) và Boosting (hiệu chỉnh tuần tự) để xếp hạng địa điểm theo 6 tiêu chí: rating, khoảng cách, giá cả, giờ mở cửa, local_factor, độ khớp.

---

## 🔄 Data Pipeline — ELT

Hệ thống áp dụng phương pháp **ELT (Extract → Load → Transform)** để xây dựng knowledge base cho RAG.

### Extract
- Thu thập tài liệu thô về văn hóa, lịch sử Hàm Ninh từ nhiều nguồn: PDF, web, tài liệu địa phương
- Scrape thông tin địa điểm từ Google Places API

### Load
- Lưu tài liệu thô vào PostgreSQL (metadata) và Qdrant (storage tạm)
- Endpoint: `POST /admin/ingest`

### Transform — Tự động hóa hoàn toàn
Sau khi tài liệu được Load vào hệ thống, pipeline tự động xử lý mà không cần can thiệp thủ công:

1. **Auto Chunking** — Docling tự nhận dạng cấu trúc tài liệu (heading, table, paragraph) và cắt thành các đoạn nhỏ (~500 token), tự động lưu ra các file `.md` vào thư mục `data/chunks/`
2. **Auto Embedding** — Từng chunk `.md` tự động được chuyển thành vector số học bằng mô hình embedding
3. **Auto Indexing** — Vector tự động được đánh index HNSW và lưu vào Qdrant, sẵn sàng cho RAG pipeline

```
Trigger: POST /admin/ingest
        ↓
Docling tự nhận dạng cấu trúc
        ↓ (tự động)
data/chunks/*.md (file markdown đã chunk)
        ↓ (tự động)
Embedding model → vectors
        ↓ (tự động)
Qdrant Vector DB ✅ Sẵn sàng cho RAG
```

> Toàn bộ quá trình từ tài liệu thô → Qdrant chỉ cần 1 API call duy nhất.

---

## 🛠️ Tech Stack

| Lớp | Công nghệ |
|---|---|
| Frontend | Next.js 16, Tailwind CSS |
| Backend | FastAPI, Python 3.11 |
| AI Agents | LangGraph 1.1 |
| Vector DB | Qdrant v1.13.6 |
| Database | PostgreSQL 17, Redis 8.0 |
| Observability | Langfuse 4.6.1 |
| Evaluation | RAGAS 0.4.3 |
| Document Processing | Docling (IBM) |

---

## 🚀 Cài đặt & Chạy

```bash
# Clone project
git clone https://github.com/thanhnndev/citd-hk1-project.git
cd citd-hk1-project

# Tạo file .env
cp .env.example .env
# Điền các API key vào file .env

# Chạy toàn bộ hệ thống bằng Docker
docker compose up
```

## 📁 Cấu trúc project

```
citd-hk1-project/
├── frontend/    # Giao diện Next.js 16
├── backend/     # API FastAPI
├── agents/      # Multi-Agent, RAG, Ensemble Re-ranker
├── data/        # Tài liệu văn hóa Hàm Ninh
├── docs/        # Tài liệu dự án
└── scripts/     # Script tiện ích
```

## 📄 Tài liệu

- [Requirements](docs/REQUIREMENTS.md)
- [Architecture](docs/ARCHITECTURE.md)

---

*Đồ án môn học — Xây dựng ứng dụng AI có trách nhiệm cho cộng đồng địa phương.*
