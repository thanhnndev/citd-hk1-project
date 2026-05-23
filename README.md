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
Hệ thống gồm 3 agent phối hợp qua LangGraph StateGraph:

| Agent | Vai trò | File |
|---|---|---|
| **AgentService** | LangGraph orchestration (retrieve → answer) | `agents/graph/agent_service.py` |
| **GroundedAnswer** | Intent detection + grounded answers | `agents/guardrails/grounded_answer.py` |
| **EnsembleReranker** | 3-tree Bagging + 2-step Boosting fairness | `agents/ml/ensemble_reranker.py` |

### RAG Pipeline
1. Câu hỏi → embedding (OpenAI text-embedding-3-small)
2. Tìm tài liệu tương tự trong Qdrant (BM25 + dense hybrid)
3. LLM sinh câu trả lời với strict grounding (gpt-4o-mini)
4. Trả về kèm citation nguồn

### Ensemble Re-ranking
Kết hợp Bagging (3 Decision Trees song song) và Boosting (hiệu chỉnh tuần tự) để xếp hạng địa điểm theo 6 tiêu chí: rating, khoảng cách, giá cả, giờ mở cửa, local_factor, độ khớp.

---

## 🔄 Data Pipeline

```
data/cleaned/documents/*.md + data/entities/*.json
        ↓ (PropositionChunker)
data/tourism_documents.jsonl
        ↓ (corpus_loader.py)
Retriever (keyword) / Qdrant (hybrid dense+sparse)
        ↓ (RAG via LLMAnswerService)
Grounded answer with citations
```

---

## 🛠️ Tech Stack

| Lớp | Công nghệ |
|---|---|
| Frontend | Next.js 16, Tailwind CSS v4, next-intl |
| Backend API | FastAPI 0.136, Python 3.12 |
| AI Agents | LangGraph 1.2 (trong `agents/` package) |
| LLM | OpenAI gpt-4o-mini, text-embedding-3-small |
| Vector DB | Qdrant v1.13.6 (HNSW index) |
| Database | PostgreSQL 17, Redis 8.0 |
| Places | Google Places API (New) v1 |
| Observability | Langfuse 4.6.1 |

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
├── agents/                    # LangGraph Multi-Agent Orchestration
│   ├── graph/
│   │   └── agent_service.py   # LangGraph StateGraph (retrieve → answer)
│   ├── tools/
│   │   ├── hybrid_retriever.py  # BM25 + Qdrant dense + keyword fallback
│   │   ├── retriever.py         # In-memory keyword search
│   │   ├── qdrant_service.py    # Qdrant vector DB
│   │   ├── embedding_service.py # OpenAI embeddings
│   │   ├── places_service.py    # Google Places API (New)
│   │   ├── routes_service.py    # Google Routes API
│   │   ├── corpus_loader.py     # JSONL document ingestion
│   │   └── proposition_chunker.py
│   ├── guardrails/
│   │   └── grounded_answer.py   # Intent detection + grounded answers
│   ├── ml/
│   │   ├── ensemble_reranker.py # 3-tree Bagging + Boosting
│   │   └── feature_extractor.py # Feature engineering (6 features)
│   ├── services/
│   │   ├── llm_answer_service.py       # OpenAI LLM answers
│   │   └── place_recommendation_service.py  # Places → Ensemble → rank
│   └── requirements.txt
│
├── backend/                     # FastAPI API Gateway (thin wrapper)
│   ├── app/
│   │   ├── main.py              # Lifespan, router wiring, service init
│   │   ├── routers/             # chat, health, admin, auth
│   │   ├── models/              # Pydantic schemas
│   │   ├── services/            # Backend-only: langfuse, jwt, email, user
│   │   ├── middleware/          # auth, cors, rate_limiter, correlation
│   │   └── core/                # config, logging
│   ├── tests/
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/                    # Next.js 16 UI
│   ├── src/
│   │   ├── app/                 # App Router (landing, chat, map, auth)
│   │   ├── components/          # landing, chat, map, ui
│   │   ├── lib/                 # api clients, auth store
│   │   └── i18n/                # next-intl (vi, en)
│   └── tests/
│
├── data/                        # Knowledge base
│   ├── cleaned/documents/       # Source markdown files
│   ├── tourism_documents.jsonl  # Ingested corpus
│   └── reports/
│
├── docs/                        # Project documentation
├── scripts/                     # Verification and ingestion scripts
└── compose.yaml                 # Docker Compose (postgres, redis, qdrant, backend)
```

## 📄 Tài liệu

- [Requirements](docs/REQUIREMENTS.md)

---

*Đồ án môn học — Xây dựng ứng dụng AI có trách nhiệm cho cộng đồng địa phương.*
