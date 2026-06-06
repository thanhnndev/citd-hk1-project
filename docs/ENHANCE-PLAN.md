# UX Enhancement Plan — Hàm Ninh AI Guide

**Date:** 2026-05-31
**Context:** End-user testing revealed critical UX gaps — agent fallbacks, meaningless scores, invisible reasoning, legacy data provider, bare-bones UI.
**Goal:** Transform from technical demo into real end-user AI travel companion app.

---

## Vấn đề thực tế (từ trải nghiệm user)

| # | Vấn đề | Ví dụ | Root cause |
|---|--------|-------|------------|
| 1 | **Agent fallback máy móc** | "điểm số đó là gì?" → "Bạn nói rõ hơn..." | `_is_followup()` không match tham chiếu context; system prompt không dạy agent trả lời câu hỏi về nội dung vừa đề cập |
| 2 | **Điểm số vô nghĩa** | "Điểm số: 0.53" — không giải thích | ScoreBreakdown có 5 trục nhưng UI chỉ hiện 1 con số raw, không có label tiếng Việt, không có visual breakdown |
| 3 | **Agent "thinking" vô hình** | User không biết agent đang làm gì | SSE `[STATUS]` events đã có nhưng UI chỉ hiện khi `loading=true`, không có post-response summary |
| 4 | **Place card thiếu chiều sâu** | Chỉ tên + rating + điểm số | `PlaceExplanation` đã có sẵn (M013/S05) nhưng UI không dùng — không có "tại sao gợi ý" |
| 5 | **Dùng Goong cũ thay vì Google Places API New** | Data cũ, ít thông tin | `GooglePlacesService` đã có sẵn nhưng chưa được wire làm primary provider |
| 6 | **UI như bản demo kỹ thuật** | Grid overlay, layout cứng, không phải messaging app feel | Design ưu tiên chứng minh kỹ thuật thay vì trải nghiệm người dùng |

---

## Phase 1: Fix Agent + Explainability (Ưu tiên cao nhất)

### 1A — Fix Agent Follow-up Intelligence

**Vấn đề:** Câu hỏi follow-up như "điểm số đó là gì?", "tìm đường đi được không?" bị fallback sang "Bạn nói rõ hơn..."

**Root cause:**
- `_is_followup()` patterns quá hẹp — chỉ match `{"?", "??"}` và vài term tiếng Việt
- System prompt không dạy agent trả lời câu hỏi tham chiếu đến nội dung vừa đề cập
- Khi LLM có history, nó vẫn không hiểu "điểm số đó" = điểm số trong place results vừa trả về

**Fix:**

1. **Mở rộng `_is_followup()` patterns** (`agents/graph/agent_service.py`):
   ```python
   # Thêm patterns tham chiếu context
   followup_refs = (
       "đó là gì", "là sao", "là gì", "sao", "tại sao", "thế nào",
       "giải thích", "nói rõ", "là cái gì", "nghĩa là",
       "điểm số", "score", "xếp hạng", "rank",
       "tìm đường", "đường đi", "chỉ đường", "route", "direction",
       "được không", "có được không", "có thể", "có ... không",
   )
   ```

2. **System prompt enhancement** — thêm policy:
   ```
   - Nếu user hỏi về điều vừa được đề cập trong conversation (điểm số, địa điểm, tính năng),
     trả lời trực tiếp dựa trên context — KHÔNG hỏi lại.
   - "điểm số đó là gì?" → giải thích 5-axis scoring
   - "tìm đường đi được không?" → trả lời về tính năng tìm đường
   - Chỉ hỏi lại khi câu hỏi thực sự mơ hồ, không có context.
   ```

3. **Thêm `can_answer_from_context()`**: kiểm tra nếu last assistant message có place results hoặc citations, trả lời từ context đó trước khi fallback.

**Files:**
- `agents/graph/agent_service.py` — `_is_followup()`, `_SYSTEM_PROMPT`, `_direct_answer()`
- `agents/graph/test_agent_service.py` — tests cho follow-up patterns

**Done khi:**
- "điểm số đó là gì?" → giải thích 5-axis scoring
- "tìm đường đi được không?" → trả lời về tính năng tìm đường
- "có quán cf ngon ngon không" → vẫn hoạt động (không regression)
- ≥10 test cases follow-up pass

---

### 1B — 5-Axis Score Display

**Vấn đề:** "Điểm số: 0.53" hiện ra vô nghĩa, user không hiểu dựa trên gì.

**Fix:**
- Thay thế single number bằng **horizontal bar chart** với 5 nhãn tiếng Việt:

| Trục | Label VI | Source |
|------|----------|--------|
| `tree1_locality` | 🏠 Địa phương | local_factor, locality score |
| `tree2_proximity` | 📍 Khoảng cách | distance từ user location |
| `tree3_quality` | ⭐ Chất lượng | rating, review count |
| `delta1_fairness` | ⚖️ Công bằng | fairness adjustment |
| `delta2_access` | ♿ Tiếp cận | accessibility score |

- Visual: mỗi trục là bar 0-100%, màu khác nhau, có tooltip hover
- Dưới chart: "Tổng điểm: 0.53 / 1.00 — Xếp hạng #1 trong 10 kết quả"

**Frontend components mới:**
- `ScoreBreakdownChart` — horizontal bar chart 5 trục
- `ScoreTooltip` — giải thích mỗi trục bằng tiếng Việt

**Files:**
- `frontend/src/components/chat/score-breakdown-chart.tsx` — NEW
- `frontend/src/components/chat/place-card.tsx` — MODIFY (thay single number bằng chart)

**Done khi:**
- Place card hiện 5-axis bar chart thay vì "0.53"
- Tooltip hiện giải thích tiếng Việt khi hover
- Responsive: mobile hiện compact view, desktop hiện full view

---

### 1C — "Why This Place" Explanation Panel

**Vấn đề:** Place card không giải thích tại sao quán này được gợi ý cho user.

**Fix:**
- `PlaceExplanation` model đã có sẵn (M013/S05):
  - `primary_reason` — lý do chính
  - `matched_preferences` — preference signals (budget, accessibility)
  - `local_context` — locality/fairness context
  - `fairness_note` — fairness/locality note
  - `accessibility_note` — accessibility note
  - `provider_source` — nguồn data (google_places / goong_places)
- Thêm expandable panel "💡 Tại sao gợi ý?" trên mỗi place card
- Content format:
  ```
  💡 Tại sao gợi ý?
  • Quán cà phê địa phương (local_factor: 0.8)
  • Giá vừa phải, phù hợp ngân sách
  • Đánh giá 4.9★ từ 200+ người dùng
  • Nguồn: Google Places
  ```

**Files:**
- `frontend/src/components/chat/place-card.tsx` — MODIFY (thêm explanation panel)
- `frontend/src/lib/chat-api.ts` — MODIFY (thêm PlaceExplanation type)

**Done khi:**
- Mỗi place card có expandable "Tại sao gợi ý?" section
- Content lấy từ `PlaceExplanation` model, không hardcode
- Mobile: tap để mở rộng, Desktop: hover + click

---

### 1D — Agent "Thinking" Visible

**Vấn đề:** User không biết agent đang làm gì trong lúc xử lý.

**Fix:**
- Backend đã emit `[STATUS]` events qua SSE: `understanding`, `searching_knowledge`, `checking_places`, `composing`
- Frontend `streamStatus` đã nhận — nhưng chỉ hiện khi `loading = true`
- Hiển thị rõ hơn:
  - **Trong lúc loading:** Animated dots + text chi tiết:
    - "Đang hiểu câu hỏi..." → "Đang tìm quán cà phê quanh Hàm Ninh..." → "Đang tính điểm phù hợp..." → "Đang tổng hợp câu trả lời..."
  - **Sau khi response xong:** Subtle summary thu gọn:
    - "✨ Gợi ý từ 10 quán cà phê, xếp hạng theo 5 tiêu chí"
    - Hoặc "✨ Trả lời từ 3 nguồn kiến thức" nếu là cultural query

**Files:**
- `frontend/src/components/chat/message-bubble.tsx` — MODIFY (thêm post-response summary)
- `frontend/src/components/chat/chat-interface.tsx` — MODIFY (enhance status labels)

**Done khi:**
- Loading: visible status với text chi tiết + animation
- Post-response: subtle summary thu gọn dưới message
- Status text tiếng Việt + tiếng Anh (i18n)

---

## Phase 2: Google Places API New + Rich Data

### 2A — Switch Primary Provider

**Vấn đề:** Đang dùng Goong Places API V2 (data cũ, ít thông tin). Google Places API New đã có sẵn nhưng chưa dùng làm primary.

**Fix:**
- `GooglePlacesService` đã có sẵn (`agents/tools/places_service.py`)
- `.env` đã có `GOOGLE_PLACES_API_KEY`
- Wire Google Places làm primary provider trong `PlaceRecommendationService`
- Fallback → Goong nếu Google unavailable
- Cập nhật `PlaceToolSource` enum: ưu tiên `google_places`

**Files:**
- `agents/services/place_recommendation_service.py` — MODIFY (provider priority)
- `agents/tools/places_service.py` — VERIFY (Google Places contract)
- `backend/app/models/places.py` — VERIFY (PlaceToolSource)

**Done khi:**
- Place results có `provider_source: "google_places"` khi key hợp lệ
- Fallback → Goong khi Google unavailable
- Test: Google available → google_places; Google blocked → credential_blocked + goong fallback

---

### 2B — Rich Place Data

**Vấn đề:** Place card thiếu thông tin — không có photo, giờ mở cửa, price indicator.

**Fix:**
- Google Places API New có: photos, opening hours, price level, reviews summary, accessibility options
- Place card hiện:
  - Photo thumbnail (nếu có)
  - Open/Closed badge (🟢 Mở / 🔴 Đóng)
  - Price indicator (💰 / 💰💰 / 💰💰💰 / 💰💰💰💰)
  - Review count + rating
  - Types badge (Café • Local • Outdoor seating)

**Files:**
- `frontend/src/components/chat/place-card.tsx` — MODIFY (thêm photo, badges)
- `backend/app/models/places.py` — VERIFY (PlaceCandidate có đủ fields)
- `agents/services/place_recommendation_service.py` — MODIFY (pass through rich data)

**Done khi:**
- Place card hiện photo thumbnail
- Open/Closed badge chính xác
- Price indicator hiển thị symbolic
- Types badge present

---

## Phase 3: Redesign UX (Messenger-Style)

### 3A — Messaging App Feel

**Vấn đề:** UI hiện tại như bản demo kỹ thuật — grid overlay, layout cứng, không phải trải nghiệm messaging app thật.

**Fix:**
- Layout như iMessage/WhatsApp:
  - User bubble: bên phải, màu xanh dương đậm
  - Assistant bubble: bên trái, màu trắng/xám nhạt
  - Avatar assistant: icon Hàm Ninh Guide
  - Timestamp: subtle dưới mỗi bubble
- Background: clean, không grid overlay kỹ thuật
- Typing indicator: 3 dots animation khi agent đang xử lý
- Input area: floating bar, rounded, shadow

**Files:**
- `frontend/src/components/chat/chat-interface.tsx` — REDESIGN
- `frontend/src/components/chat/message-bubble.tsx` — REDESIGN
- `frontend/src/app/globals.css` — MODIFY (animation, styling)

**Done khi:**
- Layout như messaging app (bubble left/right)
- Typing indicator animation (3 dots)
- Background clean, không grid
- Responsive mobile/desktop

---

### 3B — Rich Place Cards v2

**Vấn đề:** Place card hiện tại đơn giản, không hấp dẫn.

**Fix:**
- Photo carousel/thumbnail (từ Google Places)
- Header: Name + rating + price + open/closed
- Body: Address, types, "Why recommended" expandable
- Footer: 5-axis score bar chart + "Xem trên bản đồ"
- Map overlay: click "Xem trên bản đồ" → mở map overlay trong chat (không chuyển trang)

**Files:**
- `frontend/src/components/chat/place-card.tsx` — REDESIGN
- `frontend/src/components/map/` — MODIFY (overlay mode)

**Done khi:**
- Photo thumbnail present
- Rich header với badges
- Expandable "Why recommended"
- Map overlay trong chat

---

### 3C — Context-Aware Conversation

**Vấn đề:** Agent không nhớ preference, không suggest follow-up.

**Fix:**
- Agent nhớ preference từ conversation history:
  - "Lần trước bạn hỏi cà phê, giờ bạn muốn gì?"
- Suggest follow-up chips dưới mỗi response:
  - Sau place results: ["Xem bản đồ", "Lọc theo giá", "Quán gần bờ biển"]
  - Sau cultural answer: ["Đọc thêm", "Địa điểm liên quan"]
- Quick reply chips: clickable, gửi message ngay

**Files:**
- `agents/graph/agent_service.py` — MODIFY (follow-up suggestion generation)
- `frontend/src/components/chat/chat-interface.tsx` — MODIFY (quick reply chips)
- `frontend/src/components/chat/message-bubble.tsx` — MODIFY (suggestion chips)

**Done khi:**
- Quick reply chips hiện dưới assistant message
- Click chip → gửi message ngay
- Agent nhận diện preference từ history

---

## Execution Order & Dependencies

```
Phase 1 (Agent + Explainability)
├── 1A: Fix agent follow-up ← ĐỘC LẬP, làm trước
├── 1B: 5-axis score display ← ĐỘC LẬP, song song 1A
├── 1C: "Why this place" panel ← PHỤ THUỘC 1B (cùng place card)
└── 1D: Thinking indicator ← ĐỘC LẬP, làm sau cùng Phase 1

Phase 2 (Google Places + Rich Data)
├── 2A: Switch primary provider ← ĐỘC LẬP
└── 2B: Rich place data ← PHỤ THUỘC 2A

Phase 3 (UX Redesign)
├── 3A: Messenger-style UI ← ĐỘC LẬP
├── 3B: Rich cards v2 ← PHỤ THUỘC 2B + 1B/1C
└── 3C: Context-aware ← PHỤ THUỘC 1A
```

## Risk & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Google Places API quota hết | 2A/2B blocked | Fallback → Goong, verifier báo credential_blocked |
| LLM follow-up vẫn fail edge cases | 1A incomplete | Thêm test cases, refine patterns iteratively |
| Redesign UX tốn thời gian hơn dự kiến | Phase 3 delay | Phase 1+2 ship trước, Phase 3 là nice-to-have |
| PlaceExplanation data thiếu | 1C incomplete | Fallback: generate từ score breakdown + provider data |

---

## Success Criteria

| Metric | Before | Target |
|--------|--------|--------|
| Follow-up success rate | ~30% (fallback) | ≥90% (direct answer) |
| Score comprehension | 0% (con số vô nghĩa) | ≥80% (5-axis visual) |
| "Why this place" visibility | 0% | 100% (expandable panel) |
| Agent thinking visibility | Partial (loading only) | Full (detailed + post-response) |
| Data freshness | Goong (cũ) | Google Places API New |
| UI feel | Technical demo | Messenger-style app |
