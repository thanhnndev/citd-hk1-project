# Nhật ký Phát triển & Kế hoạch Công việc (VERSION)

## 📌 Trạng thái Hiện tại
*   **Nhánh Git đang làm việc**: `Thuong` (Đã push lên GitHub, làm việc độc lập không ảnh hưởng đến `main`).
*   **Trạng thái Code**: Sạch lỗi compile và lint. Thư mục làm việc hiện tại sạch sẽ (`working tree clean`).
*   **Máy chủ chạy thử nghiệm**: 
    *   Frontend: Chạy ở cổng `3000` (`npm run dev`).
    *   Backend: Cổng `48721` (hoặc cấu hình local).

---

## 🛠️ Các công việc Đã hoàn thành (07/06/2026)

### 1. Sửa lỗi Chatbox & Hội thoại (Agents)
*   **Nhớ ngữ cảnh hội thoại**: Cập nhật [followup.py](file:///c:/Users/Admin/Desktop/Project01/citd-hk1-project-main/agents/graph/followup.py) lọc bỏ các từ khóa địa lý chung để giữ hội thoại liên tiếp không bị đứt đoạn.
*   **Định tuyến ý định chỉ đường**: Sửa logic trong [state.py](file:///c:/Users/Admin/Desktop/Project01/citd-hk1-project-main/agents/graph/state.py) để các câu hỏi kết hợp chỉ đường truyền thẳng vào RAG (`search_knowledge`) thay vì Places.
*   **Đồng nhất Persona**: Khống chế câu trả lời ngoài phạm vi (off-topic) giữ nguyên giọng điệu *"Trợ lý Hàm Ninh"*.

### 2. Thiết kế Giao diện Kiến trúc hệ thống Tương tác (Frontend)
*   Tạo trang kiến trúc tương tác chuyên nghiệp tại `/vi/architecture` (Component [interactive-architecture.tsx](file:///c:/Users/Admin/Desktop/Project01/citd-hk1-project-main/frontend/src/components/architecture/interactive-architecture.tsx)):
    *   **Tab 1 - Tổng quan**: Sơ đồ SVG tương tác thể hiện luồng đi từ Client -> Next.js -> FastAPI -> LangGraph -> CSDL & APIs.
    *   **Tab 2 - Luồng Agent**: Đồ thị node phân tích chi tiết Input/Output và logic hoạt động của từng agent trong LangGraph.
    *   **Tab 3 - RAG Pipeline**: Chi tiết 4 bước xử lý RAG và cấu trúc các Collection trong Qdrant.
    *   **Tab 4 - Giả lập Re-ranker**: Trình mô phỏng toán học Bagging & Boosting theo thời gian thực (được xác minh hoạt động hoàn hảo khi tương tác thay đổi các tham số).
    *   **Tab 5 - 5 Trục Responsible AI**: Thống kê chỉ số đo lường cho tính tin cậy, công bằng, chịu lỗi, tác động xã hội và minh bạch.

### 3. Sửa lỗi Chất lượng Code (Typecheck & Lint)
*   Sửa lỗi kiểu dữ liệu ReactMarkdown trong [message-bubble.tsx](file:///c:/Users/Admin/Desktop/Project01/citd-hk1-project-main/frontend/src/components/chat/message-bubble.tsx).
*   Khắc phục toàn bộ lỗi biến/tham số chưa sử dụng trong các file kiểm thử `tests/s04-explainability-contract.test.mjs` và `tests/s06-integrated-chat-ux.test.mjs`. Lệnh `npm run lint` và `npm run type-check` hiện tại đã **PASSED 100%**.

---

## 📅 Kế hoạch Công việc ngày mai (08/06/2026)

### 1. Đồng bộ & Kiểm thử tích hợp
*   [ ] Kiểm tra log kết nối thực tế giữa Frontend và Backend khi hỏi đáp về các địa điểm Hàm Ninh xem các dữ liệu điểm số `score_breakdown` có được map chuẩn xác vào giao diện chat hay không.
*   [ ] Chạy thử bộ kiểm thử tự động của dự án: `npm run test` hoặc chạy Playwright (`npx playwright test`) để kiểm tra độ ổn định của giao diện chat.

### 2. Tinh chỉnh Bộ mô phỏng Re-ranking
*   [ ] Xem xét thêm thắt các địa điểm mockup thực tế của làng chài Hàm Ninh (ví dụ: Nhà bè Tình Biển, Quán ăn Kim Cương) vào danh sách giả lập để bài thuyết minh thêm sinh động.
*   [ ] Cập nhật tệp thuyết minh `THUYET_MINH_RAG_KICH_TRUOC.md` ở thư mục gốc nếu giáo viên hoặc hội đồng yêu cầu tài liệu bản in.

### 3. Hướng dẫn Lệnh hữu ích khi code tiếp:
*   Khởi chạy Dev Frontend:
    ```bash
    cd frontend
    npm run dev
    ```
*   Kiểm tra lỗi TypeScript:
    ```bash
    npm run type-check
    ```
*   Kiểm tra lỗi cú pháp/tiêu chuẩn code:
    ```bash
    npm run lint
    ```
