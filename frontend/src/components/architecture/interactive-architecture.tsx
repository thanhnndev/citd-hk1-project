"use client";

import { useState } from "react";
import {
  Cpu,
  Database,
  Activity,
  Layers,
  ArrowRight,
  ShieldCheck,
  Zap,
  Sliders,
  Scale,
  Building,
  CheckCircle2,
  AlertTriangle,
  FileText,
  Search,
  BookOpen,
  Settings,
  HelpCircle
} from "lucide-react";

type InteractiveArchitectureProps = Readonly<{
  locale: string;
}>;

// Dictionary for content
const dict = {
  vi: {
    tabs: {
      overview: "Tổng quan Hệ thống",
      agentFlow: "Luồng Agent (LangGraph)",
      rag: "RAG Pipeline",
      rerank: "Trình mô phỏng Re-ranker",
      responsible: "5 Trục Responsible AI",
    },
    overview: {
      title: "Kiến trúc Tổng quan Hệ thống",
      desc: "Mô tả cách các thành phần trong hệ thống kết nối với nhau, từ trải nghiệm người dùng đến các API bản đồ và cơ sở dữ liệu.",
      clickPrompt: "Click vào các thành phần trong sơ đồ để xem vai trò và đặc tả kỹ thuật.",
      techDetails: "Đặc tả kỹ thuật",
      responsibility: "Nhiệm vụ chính",
      protocol: "Giao thức kết nối",
      nodes: {
        user: {
          name: "👤 Trình duyệt (User)",
          desc: "Giao diện tương tác người dùng, bản đồ Goong Map Tiles, ô chat streaming SSE.",
          tech: "React 19 / Mapbox GL",
          resp: "Nhận yêu cầu người dùng, hiển thị bản đồ, vẽ ghim (pins), stream câu trả lời và hiển thị citation/reasoning log.",
          proto: "HTTPS / Server-Sent Events (SSE)",
        },
        nextjs: {
          name: "Frontend Next.js 16",
          desc: "Ứng dụng máy chủ frontend, định tuyến đa ngôn ngữ, proxy cuộc gọi API và quản lý cache explicit.",
          tech: "Next.js 16.2.6 LTS / next-intl / proxy.ts",
          resp: "Phục vụ giao diện tĩnh qua Cache Components, định nghĩa ranh giới mạng (network boundary) qua proxy.ts, bảo vệ API key.",
          proto: "REST API / SSE (Proxy to Backend)",
        },
        fastapi: {
          name: "Backend FastAPI",
          desc: "API Gateway hiệu năng cao, quản lý xác thực người dùng và tích hợp luồng observability.",
          tech: "FastAPI 0.136.1 / Pydantic v2",
          resp: "Xử lý xác thực người dùng (JWT, OTP), phân tích schema request/response, đo lường correlation ID, rate limit.",
          proto: "REST API / SSE (to Frontend), LangGraph invoke",
        },
        langgraph: {
          name: "Agent Orchestrator",
          desc: "Môi trường điều phối các Agent chuyên biệt dưới dạng đồ thị trạng thái bền vững (StateGraph).",
          tech: "LangGraph 1.1.10 / LangChain Core",
          resp: "Quản lý Supervisor Agent định tuyến intent, gọi RAG Agent và Maps Agent song song hoặc tuần tự, duy trì session memory.",
          proto: "Python Service Calls, PostgresSaver state",
        },
        qdrant: {
          name: "Qdrant Vector DB",
          desc: "Cơ sở dữ liệu vector lưu trữ tri thức văn hóa, ẩm thực Hàm Ninh.",
          tech: "Qdrant v1.13.6 / HNSW Index / Gridstore",
          resp: "Tìm kiếm tương đồng (similarity search) dựa trên dense embeddings với ngưỡng cosine similarity >= 0.70.",
          proto: "gRPC (giao tiếp hiệu năng cao) / REST",
        },
        goong: {
          name: "Goong Maps API V2",
          desc: "Dịch vụ cung cấp tìm kiếm địa điểm và tính toán ma trận khoảng cách tại Việt Nam.",
          tech: "Goong Places & Routes REST API",
          resp: "Tìm kiếm địa điểm (Text / Nearby Search), chi tiết địa điểm, và tính toán khoảng cách thực tế qua Routes Matrix.",
          proto: "REST API (Server-only key)",
        },
        langfuse: {
          name: "Langfuse 4.6.1",
          desc: "Nền tảng Observability chuyên sâu cho các ứng dụng LLM.",
          tech: "Langfuse SDK v4 (Rewrite)",
          resp: "Ghi nhận trace chi tiết của từng bước suy luận, giám sát độ trễ (latency), chi phí token và điểm đánh giá RAGAS.",
          proto: "HTTPS Async Tracing (Background task)",
        },
        redis: {
          name: "Redis 8.0 Cache",
          desc: "Bộ nhớ đệm ngữ nghĩa (Semantic Cache) và quản lý session.",
          tech: "Redis Search / JSON native",
          resp: "Lưu trữ cache ngữ nghĩa cho các câu hỏi tương tự (cosine sim >= 0.95), giới hạn rate limit và session ngắn hạn.",
          proto: "TCP (Redis protocol)",
        },
        postgres: {
          name: "PostgreSQL 17",
          desc: "Cơ sở dữ liệu quan hệ lưu trữ thông tin tài khoản và checkpoint lưu vết hội thoại.",
          tech: "PostgreSQL 17 / Alembic / PostgresSaver",
          resp: "Lưu trữ metadata người dùng, bảng điểm local_factor của tiểu thương, và lưu giữ trạng thái LangGraph để khôi phục sau sự cố.",
          proto: "TCP / asyncpg connection pool",
        },
      },
    },
    agentFlow: {
      title: "Luồng Xử lý Multi-Agent",
      desc: "LangGraph điều khiển luồng công việc thông qua kiến trúc Supervisor/Worker. Bấm vào từng node để khám phá chi tiết hành vi.",
      nodeDetails: "Chi tiết Node",
      status: "Trạng thái",
      input: "Input nhận vào",
      output: "Output trả ra",
      nodes: {
        guardrails_in: {
          name: "1. Input Guardrails",
          desc: "Hàng rào bảo mật đầu vào sử dụng NeMo Guardrails để phát hiện Prompt Injection và lọc chủ đề.",
          status: "Hoạt động (Active)",
          input: "Raw user query",
          output: "Cleaned query hoặc Chặn & Từ chối an toàn",
          rule: "Chặn 99% tấn công dạng 'Ignore instructions', roleplay. Lọc câu hỏi ngoài phạm vi Hàm Ninh.",
        },
        router: {
          name: "2. Semantic Router",
          desc: "Phân loại intent nhanh dựa trên cosine similarity của embedding truy vấn với tập mẫu.",
          status: "Hoạt động (Active)",
          input: "Cleaned query",
          output: "Intent (CULTURE_HISTORY, FOOD_CULTURE, NEARBY_SEARCH, ROUTE_NAVIGATION, OFF_TOPIC)",
          rule: "Ngưỡng CULTURE/FOOD >= 0.82; NEARBY/ROUTE >= 0.80. Dưới ngưỡng sẽ chuyển Supervisor quyết định.",
        },
        supervisor: {
          name: "3. Supervisor Agent",
          desc: "Bộ não trung tâm điều phối. Sử dụng LLM reasoning để đưa ra quyết định gọi worker agents tương ứng.",
          status: "Hoạt động (Active)",
          input: "Query + Intent + History",
          output: "Routing decision (RAG, Maps, hoặc cả hai song song)",
          rule: "Định tuyến câu hỏi văn hóa sang RAG Agent, câu hỏi địa điểm/đường đi sang Maps Agent. Hỗ trợ chạy song song trong câu hỏi hỗn hợp (HYBRID).",
        },
        rag_agent: {
          name: "4a. RAG Agent (Local Guide)",
          desc: "Agent chịu trách nhiệm truy xuất tri thức và trả lời các câu hỏi về văn hóa, lịch sử và ẩm thực Hàm Ninh.",
          status: "Hoạt động (Active)",
          input: "Sub-query văn hóa",
          output: "Văn bản trả lời có trích dẫn nguồn (citations)",
          rule: "Strict Grounding: Chỉ trả lời dựa trên tài liệu được cung cấp trong Qdrant. Không bịa đặt thông tin.",
        },
        maps_agent: {
          name: "4b. Maps Agent (Concierge)",
          desc: "Agent phụ trách tìm kiếm địa điểm, tính toán khoảng cách và thời gian di chuyển thực tế.",
          status: "Hoạt động (Active)",
          input: "Địa điểm tìm kiếm, tọa độ người dùng, bộ lọc giá/tiếp cận",
          output: "Danh sách địa điểm thô từ Goong API",
          rule: "Per-node timeout = 10s. Nếu Goong API lỗi 3 lần liên tiếp, kích hoạt Circuit Breaker chuyển sang SQLite cục bộ.",
        },
        reranker: {
          name: "5. Ensemble Re-ranker",
          desc: "Thuật toán sắp xếp lại địa điểm dựa trên toán học Bagging và Boosting định sẵn để đảm bảo công bằng.",
          status: "Hoạt động (Active)",
          input: "Raw places list + user preferences",
          output: "Xếp hạng top-5 địa điểm kèm score_breakdown",
          rule: "Kết hợp 3 Decision Trees (Locality, Proximity, Quality) và 2 Boosting stumps (chain penalty, accessibility bonus).",
        },
        guardrails_out: {
          name: "6. Output Guardrails",
          desc: "Hàng rào bảo mật đầu ra, xác minh tính xác thực và an toàn nội dung trước khi gửi trả người dùng.",
          status: "Hoạt động (Active)",
          input: "Merged response + places list",
          output: "Final ChatResponse + Citations + Places",
          rule: "Grounding Check: Loại bỏ bất kỳ địa danh nào được LLM nhắc tới trong câu trả lời nếu không tồn tại trong danh sách của Places API.",
        },
      },
    },
    rag: {
      title: "RAG Pipeline - Hỏi đáp có Căn cứ",
      desc: "Trực quan hóa luồng dữ liệu của hệ thống Retrieval-Augmented Generation giúp loại bỏ hallucination và đảm bảo tính minh bạch.",
      steps: [
        {
          title: "1. Nhận truy vấn & Embedding",
          desc: "Câu hỏi của người dùng được chuẩn hóa và chuyển đổi thành vector 768 chiều sử dụng mô hình Gemini Embedding.",
        },
        {
          title: "2. Tìm kiếm Vector Qdrant",
          desc: "Tìm kiếm tương đồng cosine trong các collection của Qdrant. Sử dụng HNSW index với ngưỡng tìm kiếm similarity >= 0.70 để lấy ra top-5 chunk liên quan nhất.",
        },
        {
          title: "3. Bộ lọc Strict Grounding",
          desc: "Hệ thống áp dụng prompt ràng buộc cực kỳ nghiêm ngặt: LLM chỉ được phép tổng hợp từ thông tin trong các chunk vừa tìm thấy. Nếu không đủ dữ liệu, hệ thống bắt buộc phải trả lời 'Tôi chưa tìm thấy dữ liệu' thay vì tự suy đoán.",
        },
        {
          title: "4. Sinh câu trả lời & Trích xuất Citation",
          desc: "Hệ thống phân tích nguồn và tạo thẻ Citation chứa tên tài liệu và vị trí chunk. Người dùng có thể click trực tiếp vào citation để kiểm chứng tri thức.",
        },
      ],
      collections: {
        title: "Cấu trúc Qdrant Collections",
        desc: "Dữ liệu tri thức được lưu trữ trong 3 collection riêng biệt để tối ưu hóa tìm kiếm:",
        items: [
          {
            name: "hamninh_culture",
            desc: "Lịch sử làng chài, các di tích cổ, các giai thoại, lễ hội cầu ngư.",
            dim: "768 vector - Cosine distance",
          },
          {
            name: "hamninh_food",
            desc: "Ẩm thực truyền thống, công thức chế biến đặc trưng (ghẹ Hàm Ninh, mắm tôm, hải sản).",
            dim: "768 vector - Cosine distance",
          },
          {
            name: "hamninh_businesses",
            desc: "Thông tin cơ sở kinh doanh, hộ gia đình bản địa phục vụ cho việc liên kết gợi ý.",
            dim: "768 vector - Cosine distance",
          },
        ],
      },
    },
    rerank: {
      title: "Trình mô phỏng Ensemble Re-ranking",
      desc: "Mô phỏng cách hệ thống xếp hạng địa điểm thực tế sử dụng Bagging và Boosting dựa trên quy tắc định sẵn (Rule-based) để hỗ trợ sinh kế tiểu thương địa phương.",
      inputs: "Cấu hình Địa điểm Ứng viên",
      metrics: "Kết quả chấm điểm thuật toán",
      localFactorTitle: "Nhân tố công bằng địa phương (local_factor)",
      localFactorDesc: "Được tính dựa trên các tiêu chí bản địa (cộng dồn, tối đa 1.0):",
      criteria: {
        business: "Đăng ký hộ kinh doanh cá thể tại Hàm Ninh (+0.4)",
        fishing: "Chủ sở hữu là gia đình ngư dân Hàm Ninh (+0.25)",
        traditional: "Chứng nhận nghề truyền thống địa phương (+0.2)",
        elderly: "Sử dụng lao động người cao tuổi/khuyết tật địa phương (+0.15)",
      },
      placeConfig: {
        rating: "Đánh giá sao (Rating)",
        distance: "Khoảng cách (m)",
        price: "Mức giá (Price Level)",
        chain: "Là chuỗi cửa hàng thương hiệu lớn (Chain Business)",
        chainDesc: "Nếu tích chọn, local_factor sẽ tự động bằng 0 và bị phạt điểm.",
        access: "Có lối đi cho xe lăn (Accessibility)",
      },
      mathSteps: {
        title: "Các bước tính toán chi tiết",
        tree1: "Tree 1 (Locality-first):",
        tree1Desc: "Tập trung hoàn toàn vào local_factor và trạng thái hoạt động.",
        tree2: "Tree 2 (Proximity-first):",
        tree2Desc: "Ưu tiên khoảng cách ngắn, phạt khoảng cách xa.",
        tree3: "Tree 3 (Quality-first):",
        tree3Desc: "Đánh giá chất lượng và mức giá phù hợp túi tiền.",
        bagging: "Bagging (Trung bình cộng 3 cây):",
        baggingDesc: "Giảm phương sai điểm số.",
        boosting1: "Boosting Vòng 1 (Phạt chuỗi cửa hàng):",
        boosting1Desc: "Hiệu chỉnh tuần tự để giảm bias cho doanh nghiệp lớn.",
        boosting2: "Boosting Vòng 2 (Thưởng tiếp cận):",
        boosting2Desc: "Thưởng cho khả năng phục vụ người khuyết tật.",
        final: "Điểm cuối cùng (Final Score):",
        finalDesc: "Sau khi giới hạn trong khoảng [0, 1].",
      },
      formula: "Toán học Ensemble",
    },
    responsible: {
      title: "5 Trục Responsible AI",
      desc: "Dự án tuân thủ nghiêm ngặt 5 trục AI có trách nhiệm để đảm bảo tác động tích cực đến xã hội và công nghệ bền vững.",
      axes: [
        {
          title: "1. Reliability (Độ tin cậy)",
          desc: "Đảm bảo thông tin văn hóa/lịch sử chính xác tuyệt đối. Áp dụng RAG Strict Grounding và đánh giá tự động bằng RAGAS 0.4.3.",
          metric: "Chỉ số Faithfulness >= 0.85, Answer Relevance >= 0.80.",
        },
        {
          title: "2. Bias & Fairness (Công bằng)",
          desc: "Hỗ trợ sinh kế tiểu thương địa phương qua Ensemble Re-ranker, chống thiên vị kinh tế. Thích ứng đa ngôn ngữ và phương ngữ.",
          metric: "Tỷ lệ cơ sở địa phương xuất hiện trong top-5 >= 40%.",
        },
        {
          title: "3. Robustness (Chịu lỗi & Bảo mật)",
          desc: "Chặn prompt injection qua Input Guardrails, kiểm soát chủ đề off-topic, tự động fallback SQLite khi Goong API lỗi.",
          metric: "Chặn 99% injection. Khôi phục trạng thái agent qua PostgresSaver.",
        },
        {
          title: "4. Social Impact (Tác động xã hội)",
          desc: "Tôn vinh và bảo vệ di sản văn hóa phi vật thể Hàm Ninh. Cảnh báo tiếp cận cho người khuyết tật và người cao tuổi.",
          metric: "Metadata bản địa phủ sóng >= 80% cơ sở đã đăng ký.",
        },
        {
          title: "5. Explainability (Minh bạch)",
          desc: "Không dùng mô hình hộp đen. Cung cấp reasoning log đầy đủ cho Supervisor và hiển thị chi tiết điểm số re-ranking.",
          metric: "100% gợi ý địa điểm có Score Breakdown và Citation nguồn.",
        },
      ],
    },
  },
  en: {
    tabs: {
      overview: "System Overview",
      agentFlow: "Agent Flow (LangGraph)",
      rag: "RAG Pipeline",
      rerank: "Re-ranker Simulator",
      responsible: "5 Axes of Responsible AI",
    },
    overview: {
      title: "Overall System Architecture",
      desc: "Describes how all components connect, from the user interface to location intelligence APIs and databases.",
      clickPrompt: "Click on any component in the diagram to view its role and technical specifications.",
      techDetails: "Technical Specifications",
      responsibility: "Core Responsibility",
      protocol: "Connection Protocol",
      nodes: {
        user: {
          name: "👤 User Browser (Client)",
          desc: "Frontend user interface with Goong Map Tiles, and chat input/SSE stream display.",
          tech: "React 19 / Mapbox GL",
          resp: "Capture user input, render maps, draw recommendation pins, handle SSE token streaming, and show citation/reasoning UI.",
          proto: "HTTPS / Server-Sent Events (SSE)",
        },
        nextjs: {
          name: "Frontend Next.js 16",
          desc: "Frontend application host providing i18n, API proxying, and explicit caching control.",
          tech: "Next.js 16.2.6 LTS / next-intl / proxy.ts",
          resp: "Serve static resources using Cache Components, define network boundary with proxy.ts to hide sensitive API keys.",
          proto: "REST API / SSE (Proxy to Backend)",
        },
        fastapi: {
          name: "Backend FastAPI",
          desc: "High-performance API gateway handling auth, schema enforcement, and observability routing.",
          tech: "FastAPI 0.136.1 / Pydantic v2",
          resp: "Handle JWT user authentication, OTP validation, correlation ID injection, rate limiting, and request schema parsing.",
          proto: "REST API / SSE (to Frontend), LangGraph invoke",
        },
        langgraph: {
          name: "Agent Orchestrator",
          desc: "Stateful agent runtime coordinating workers through a persistent StateGraph.",
          tech: "LangGraph 1.1.10 / LangChain Core",
          resp: "Coordinate Supervisor routing node, spawn RAG and Maps worker nodes in parallel or sequence, manage session memory.",
          proto: "Python Service Calls, PostgresSaver state",
        },
        qdrant: {
          name: "Qdrant Vector DB",
          desc: "Vector store holding Ham Ninh cultural and culinary knowledge embeddings.",
          tech: "Qdrant v1.13.6 / HNSW Index / Gridstore",
          resp: "Execute dense vector cosine similarity search with thresholds >= 0.70.",
          proto: "gRPC (High Performance) / REST",
        },
        goong: {
          name: "Goong Maps API V2",
          desc: "Local mapping APIs providing geocoding, text search, place details, and matrix routing.",
          tech: "Goong Places & Routes REST API",
          resp: "Fetch candidates via Text / Nearby Search, enrich details, and measure actual road distance via computeRouteMatrix.",
          proto: "REST API (Server-only key)",
        },
        langfuse: {
          name: "Langfuse 4.6.1",
          desc: "Observability platform built for tracking and evaluating LLM workflows.",
          tech: "Langfuse SDK v4 (Rewrite)",
          resp: "Track nested execution traces, calculate token costs, log latency, and record live RAGAS feedback.",
          proto: "HTTPS Async Tracing (Background task)",
        },
        redis: {
          name: "Redis 8.0 Cache",
          desc: "In-memory database for semantic query cache and session throttling.",
          tech: "Redis Search / JSON native",
          resp: "Cache semantic matches (cosine sim >= 0.95), manage short-term session storage, and rate limiting tokens.",
          proto: "TCP (Redis protocol)",
        },
        postgres: {
          name: "PostgreSQL 17",
          desc: "Relational database storing user details and LangGraph execution checkpoints.",
          tech: "PostgreSQL 17 / Alembic / PostgresSaver",
          resp: "Store user account data, community metadata, local_factor ratings, and save agent state checkpoints for crash recovery.",
          proto: "TCP / asyncpg connection pool",
        },
      },
    },
    agentFlow: {
      title: "Multi-Agent Workflow",
      desc: "LangGraph controls execution steps using a Supervisor/Worker topology. Click on a node to inspect its rules and details.",
      nodeDetails: "Node Details",
      status: "Status",
      input: "Input Received",
      output: "Output Returned",
      nodes: {
        guardrails_in: {
          name: "1. Input Guardrails",
          desc: "Secures inputs using NeMo Guardrails to identify prompt injections and filter out off-topic requests.",
          status: "Active",
          input: "Raw user query",
          output: "Cleaned query or safe decline response",
          rule: "Blocks 99% of 'ignore instruction' attacks and roleplays. Screens queries outside of Ham Ninh context.",
        },
        router: {
          name: "2. Semantic Router",
          desc: "Performs fast intent classification using cosine similarity against pre-defined utterance embeddings.",
          status: "Active",
          input: "Cleaned query",
          output: "Intent (CULTURE_HISTORY, FOOD_CULTURE, NEARBY_SEARCH, ROUTE_NAVIGATION, OFF_TOPIC)",
          rule: "Thresholds: CULTURE/FOOD >= 0.82; NEARBY/ROUTE >= 0.80. Queries below fallback to Supervisor LLM routing.",
        },
        supervisor: {
          name: "3. Supervisor Agent",
          desc: "The central coordinator that uses LLM reasoning to determine which worker agent nodes to invoke.",
          status: "Active",
          input: "Query + Intent + History",
          output: "Routing decision (RAG, Maps, or parallel hybrid)",
          rule: "Routes historical/cultural questions to RAG Agent, location/travel inquiries to Maps Agent. Runs both for hybrid queries.",
        },
        rag_agent: {
          name: "4a. RAG Agent (Local Guide)",
          desc: "Retrieves localized heritage facts and answers questions about history, festivals, and culinary culture.",
          status: "Active",
          input: "Culture sub-query",
          output: "Citation-backed narrative answers",
          rule: "Strict Grounding: Answers must use retrieved chunks only. Hallucinations are forbidden.",
        },
        maps_agent: {
          name: "4b. Maps Agent (Concierge)",
          desc: "Queries real-world place indexes and resolves routing metrics.",
          status: "Active",
          input: "Query terms, user location coordinates, price/accessibility filters",
          output: "Raw place candidate list from Goong API",
          rule: "Per-node timeout = 10s. Activates a circuit breaker pointing to local SQLite cache if Goong fails 3 times.",
        },
        reranker: {
          name: "5. Ensemble Re-ranker",
          desc: "Re-ranks place listings using Bagging and Boosting rules to counter corporate visibility bias.",
          status: "Active",
          input: "Raw places list + user preferences",
          output: "Ranked top-5 places with score_breakdown",
          rule: "Ensembles 3 pre-defined decision trees (Locality, Proximity, Quality) and 2 Boosting stumps (chain penalty, accessibility).",
        },
        guardrails_out: {
          name: "6. Output Guardrails",
          desc: "Validates facts and guarantees output safety before serving the final response to the user.",
          status: "Active",
          input: "Merged response + places list",
          output: "Final ChatResponse + Citations + Places",
          rule: "Grounding check: Strip any recommendation references generated by the LLM that do not exist in the API results.",
        },
      },
    },
    rag: {
      title: "RAG Retrieval Pipeline",
      desc: "Visualizes the RAG workflow which grounds culture and history answers to prevent AI hallucinations.",
      steps: [
        {
          title: "1. Query Embedding",
          desc: "The user query is normalized and converted into a 768-dimensional vector using Gemini Embedding models.",
        },
        {
          title: "2. Vector Store Similarity",
          desc: "Queries are searched against Qdrant collections. The HNSW cosine index fetches the top-5 chunks with a threshold >= 0.70.",
        },
        {
          title: "3. Strict Grounding Filter",
          desc: "Enforces system prompts restricting the LLM to context chunks. The model replies 'No data' instead of making assumptions.",
        },
        {
          title: "4. Generation & Citations",
          desc: "Compiles response text and extracts precise citations containing document titles and chunk IDs for verification.",
        },
      ],
      collections: {
        title: "Qdrant Collections Structure",
        desc: "Knowledge datasets are indexed across three collections to optimize routing accuracy:",
        items: [
          {
            name: "hamninh_culture",
            desc: "Fishing village history, ancient shrines, local folklore, sea worshipping festivals.",
            dim: "768 vectors - Cosine distance",
          },
          {
            name: "hamninh_food",
            desc: "Traditional cooking methods, regional recipes (Ham Ninh crab, shrimp paste, local catches).",
            dim: "768 vectors - Cosine distance",
          },
          {
            name: "hamninh_businesses",
            desc: "Metadata directory of registered local vendors, shops, and family-owned stalls.",
            dim: "768 vectors - Cosine distance",
          },
        ],
      },
    },
    rerank: {
      title: "Ensemble Re-ranking Simulator",
      desc: "Simulate how the local business fairness engine calculates recommendation scores using Bagging and Boosting rules.",
      inputs: "Candidate Place Configuration",
      metrics: "Algorithm Score Output",
      localFactorTitle: "Local Livelihood Factor (local_factor)",
      localFactorDesc: "Calculated based on community signals (accumulative, max 1.0):",
      criteria: {
        business: "Registered household business in Ham Ninh (+0.4)",
        fishing: "Owned by a local fishing family (+0.25)",
        traditional: "Certified local traditional craft/guild (+0.2)",
        elderly: "Employs elderly or disabled residents (+0.15)",
      },
      placeConfig: {
        rating: "User Rating (Stars)",
        distance: "Distance to User (m)",
        price: "Price Level",
        chain: "Is a Corporate Chain Business",
        chainDesc: "Checking this forces local_factor to 0 and applies a ranking penalty.",
        access: "Has Wheelchair Access (Accessibility)",
      },
      mathSteps: {
        title: "Mathematical Step-by-Step",
        tree1: "Tree 1 (Locality-first):",
        tree1Desc: "Focuses on local_factor and business status.",
        tree2: "Tree 2 (Proximity-first):",
        tree2Desc: "Prioritizes shorter distances, discounts far candidates.",
        tree3: "Tree 3 (Quality-first):",
        tree3Desc: "Evaluates quality scores and affordable pricing.",
        bagging: "Bagging (Averaging 3 Trees):",
        baggingDesc: "Reduces scoring variance across simple trees.",
        boosting1: "Boosting Round 1 (Chain Business Penalty):",
        boosting1Desc: "Sequential correction reducing bias for large platforms.",
        boosting2: "Boosting Round 2 (Accessibility Bonus):",
        boosting2Desc: "Rewards spaces accommodating people with disabilities.",
        final: "Final Score:",
        finalDesc: "Clipped output within the [0, 1] range.",
      },
      formula: "Ensemble Mathematics",
    },
    responsible: {
      title: "5 Axes of Responsible AI",
      desc: "The system is built on ethical principles to maximize local benefits and protect historical truth.",
      axes: [
        {
          title: "1. Reliability",
          desc: "Grounds cultural references using RAG and automatically evaluates outputs using RAGAS 0.4.3.",
          metric: "Target Faithfulness >= 0.85, Answer Relevance >= 0.80.",
        },
        {
          title: "2. Bias & Fairness",
          desc: "Counters popularity bias via re-ranking. Supports local dialects and handles dual languages natively.",
          metric: "At least 40% local businesses in top-5 recommendations.",
        },
        {
          title: "3. Robustness",
          desc: "Screens inputs via NeMo Guardrails, filters off-topic queries, and fallbacks to SQLite on API errors.",
          metric: "Blocks 99% of prompt injections. Keeps state via PostgresSaver.",
        },
        {
          title: "4. Social Impact",
          desc: "Supports community livelihood and preserves heritage. Triggers accessibility warning overlays.",
          metric: "Local metadata coverage exceeds 80% of registered vendors.",
        },
        {
          title: "5. Explainability",
          desc: "Avoids black-box decisions. Integrates reasoning accordions and explains scoring formulas.",
          metric: "100% of recommendations include score breakdowns and citations.",
        },
      ],
    },
  },
};

export function InteractiveArchitecture({ locale }: InteractiveArchitectureProps) {
  const isVi = locale === "vi";
  const t = isVi ? dict.vi : dict.en;

  const [activeTab, setActiveTab] = useState<"overview" | "agentFlow" | "rag" | "rerank" | "responsible">("overview");

  // Tab 1: System Overview Interaction state
  const [selectedNode, setSelectedNode] = useState<string>("user");

  // Tab 2: Agent Flow Interaction state
  const [selectedAgent, setSelectedAgent] = useState<string>("supervisor");

  // Tab 4: Re-ranking Simulator state
  const [hasBusiness, setHasBusiness] = useState(true);
  const [hasFishing, setHasFishing] = useState(true);
  const [hasTraditional, setHasTraditional] = useState(false);
  const [hasElderly, setHasElderly] = useState(false);

  const [rating, setRating] = useState(4.5);
  const [distance, setDistance] = useState(450);
  const [priceLevel, setPriceLevel] = useState(1);
  const [isChain, setIsChain] = useState(false);
  const [wheelchair, setWheelchair] = useState(true);

  // Compute local_factor
  let computedLocalFactor = 0;
  if (!isChain) {
    if (hasBusiness) computedLocalFactor += 0.4;
    if (hasFishing) computedLocalFactor += 0.25;
    if (hasTraditional) computedLocalFactor += 0.2;
    if (hasElderly) computedLocalFactor += 0.15;
  }
  computedLocalFactor = Math.min(1.0, computedLocalFactor);
  computedLocalFactor = Math.round(computedLocalFactor * 100) / 100;

  const localFactor = isChain ? 0 : computedLocalFactor;

  // Tree 1: Locality-first
  let tree1Score = 0.2;
  if (localFactor > 0.6) {
    tree1Score = 0.9;
  } else if (localFactor > 0.3) {
    tree1Score = 0.5;
  }
  tree1Score = Math.round(tree1Score * 100) / 100;

  // Tree 2: Proximity-first
  let tree2Score = 0.15;
  if (distance < 300) {
    tree2Score = 0.9;
  } else if (distance < 800) {
    tree2Score = 0.65 + (rating - 3.0) * 0.1;
  } else if (distance < 2000) {
    tree2Score = 0.4 + localFactor * 0.2;
  }
  tree2Score = Math.round(tree2Score * 100) / 100;

  // Tree 3: Quality-first
  let tree3Score = 0.2;
  if (rating >= 4.5 && priceLevel <= 2) {
    tree3Score = 0.85 + localFactor * 0.15;
  } else if (rating >= 4.0 && priceLevel <= 1) {
    tree3Score = 0.75;
  } else if (rating >= 3.5) {
    tree3Score = 0.5 + (2 - priceLevel) * 0.05;
  }
  tree3Score = Math.round(tree3Score * 100) / 100;

  // Bagging
  const baggingScore = Math.round(((tree1Score + tree2Score + tree3Score) / 3) * 1000) / 1000;

  // Boosting
  const boostingDelta1 = isChain ? -0.15 : 0;
  const boosting1Result = baggingScore + 0.3 * boostingDelta1;

  const boostingDelta2 = wheelchair ? 0.10 : 0;
  const boosting2Result = boosting1Result + 0.3 * boostingDelta2;

  // Final score clipped
  const finalScore = Math.max(0, Math.min(1, Math.round(boosting2Result * 1000) / 1000));

  return (
    <div className="w-full">
      {/* Tab Selectors */}
      <div className="flex flex-wrap justify-center border-b border-border/40 mb-12 gap-2 pb-2">
        {(Object.keys(t.tabs) as Array<keyof typeof t.tabs>).map((tabKey) => (
          <button
            key={tabKey}
            onClick={() => setActiveTab(tabKey)}
            className={`px-5 py-3 rounded-lg text-sm font-medium transition-all duration-300 flex items-center gap-2 ${
              activeTab === tabKey
                ? "bg-primary text-primary-foreground shadow-md"
                : "text-muted-foreground hover:bg-muted/50 hover:text-foreground"
            }`}
          >
            {tabKey === "overview" && <Layers className="h-4 w-4" />}
            {tabKey === "agentFlow" && <Cpu className="h-4 w-4" />}
            {tabKey === "rag" && <Database className="h-4 w-4" />}
            {tabKey === "rerank" && <Sliders className="h-4 w-4" />}
            {tabKey === "responsible" && <ShieldCheck className="h-4 w-4" />}
            {t.tabs[tabKey]}
          </button>
        ))}
      </div>

      {/* Tab Content 1: Overview */}
      {activeTab === "overview" && (
        <div className="space-y-8 animate-fadeIn">
          <div className="text-center max-w-3xl mx-auto space-y-4">
            <h3 className="text-2xl font-bold text-foreground">{t.overview.title}</h3>
            <p className="text-muted-foreground">{t.overview.desc}</p>
            <p className="text-xs text-primary/80 flex items-center justify-center gap-1">
              <HelpCircle className="h-3 w-3 animate-pulse" />
              {t.overview.clickPrompt}
            </p>
          </div>

          <div className="grid gap-8 lg:grid-cols-[1.3fr_0.7fr]">
            {/* Visual Interactive Diagram */}
            <div className="relative border rounded-2xl bg-card/40 backdrop-blur-xs p-6 md:p-8 flex flex-col items-center justify-center min-h-[450px]">
              <div className="w-full max-w-lg space-y-6">
                {/* User node */}
                <div className="flex justify-center">
                  <button
                    onClick={() => setSelectedNode("user")}
                    className={`w-48 p-4 rounded-xl border-2 transition-all duration-300 text-center font-medium ${
                      selectedNode === "user"
                        ? "bg-primary text-primary-foreground border-primary scale-105 shadow-lg shadow-primary/20"
                        : "bg-background border-border/80 hover:border-primary/50"
                    }`}
                  >
                    {t.overview.nodes.user.name}
                    <div className="text-2xs opacity-80 mt-1">React 19 / Mapbox GL</div>
                  </button>
                </div>

                {/* Arrow */}
                <div className="flex justify-center text-muted-foreground/60 h-4">
                  <ArrowRight className="h-5 w-5 rotate-90" />
                </div>

                {/* Gateway Group (Next.js & FastAPI) */}
                <div className="grid grid-cols-2 gap-4">
                  <button
                    onClick={() => setSelectedNode("nextjs")}
                    className={`p-4 rounded-xl border-2 transition-all duration-300 text-center font-medium ${
                      selectedNode === "nextjs"
                        ? "bg-primary text-primary-foreground border-primary scale-105 shadow-lg shadow-primary/20"
                        : "bg-background border-border/80 hover:border-primary/50"
                    }`}
                  >
                    {t.overview.nodes.nextjs.name}
                    <div className="text-2xs opacity-80 mt-1">Next.js 16</div>
                  </button>

                  <button
                    onClick={() => setSelectedNode("fastapi")}
                    className={`p-4 rounded-xl border-2 transition-all duration-300 text-center font-medium ${
                      selectedNode === "fastapi"
                        ? "bg-primary text-primary-foreground border-primary scale-105 shadow-lg shadow-primary/20"
                        : "bg-background border-border/80 hover:border-primary/50"
                    }`}
                  >
                    {t.overview.nodes.fastapi.name}
                    <div className="text-2xs opacity-80 mt-1">FastAPI Gateway</div>
                  </button>
                </div>

                {/* Gateway to Logic Arrow */}
                <div className="flex justify-center text-muted-foreground/60 h-4">
                  <ArrowRight className="h-5 w-5 rotate-90" />
                </div>

                {/* Core AI Orchestrator */}
                <div className="flex justify-center">
                  <button
                    onClick={() => setSelectedNode("langgraph")}
                    className={`w-56 p-4 rounded-xl border-2 transition-all duration-300 text-center font-medium ${
                      selectedNode === "langgraph"
                        ? "bg-primary text-primary-foreground border-primary scale-105 shadow-lg shadow-primary/20"
                        : "bg-background border-border/80 hover:border-primary/50"
                    }`}
                  >
                    🧠 {t.overview.nodes.langgraph.name}
                    <div className="text-2xs opacity-80 mt-1">LangGraph StateGraph</div>
                  </button>
                </div>

                {/* Data to services arrows */}
                <div className="flex justify-between px-12 text-muted-foreground/60 h-4">
                  <ArrowRight className="h-5 w-5 rotate-135" />
                  <ArrowRight className="h-5 w-5 rotate-90 animate-bounce" />
                  <ArrowRight className="h-5 w-5 rotate-45" />
                </div>

                {/* Services/Data Layer */}
                <div className="grid grid-cols-3 gap-3">
                  <button
                    onClick={() => setSelectedNode("qdrant")}
                    className={`p-3 rounded-lg border-2 transition-all duration-300 text-center text-xs font-semibold ${
                      selectedNode === "qdrant"
                        ? "bg-primary text-primary-foreground border-primary scale-105 shadow-md shadow-primary/25"
                        : "bg-background border-border/80 hover:border-primary/50"
                    }`}
                  >
                    🗄️ Qdrant
                    <div className="text-4xs opacity-75 mt-0.5">Vector DB</div>
                  </button>

                  <button
                    onClick={() => setSelectedNode("goong")}
                    className={`p-3 rounded-lg border-2 transition-all duration-300 text-center text-xs font-semibold ${
                      selectedNode === "goong"
                        ? "bg-primary text-primary-foreground border-primary scale-105 shadow-md shadow-primary/25"
                        : "bg-background border-border/80 hover:border-primary/50"
                    }`}
                  >
                    🗺️ Goong Map API
                    <div className="text-4xs opacity-75 mt-0.5">Places V2</div>
                  </button>

                  <button
                    onClick={() => setSelectedNode("redis")}
                    className={`p-3 rounded-lg border-2 transition-all duration-300 text-center text-xs font-semibold ${
                      selectedNode === "redis"
                        ? "bg-primary text-primary-foreground border-primary scale-105 shadow-md shadow-primary/25"
                        : "bg-background border-border/80 hover:border-primary/50"
                    }`}
                  >
                    ⚡ Redis
                    <div className="text-4xs opacity-75 mt-0.5">Semantic Cache</div>
                  </button>
                </div>

                {/* Database & Observability */}
                <div className="grid grid-cols-2 gap-4 pt-2">
                  <button
                    onClick={() => setSelectedNode("postgres")}
                    className={`p-3 rounded-xl border-2 transition-all duration-300 text-center text-xs font-semibold ${
                      selectedNode === "postgres"
                        ? "bg-primary text-primary-foreground border-primary scale-105 shadow-md shadow-primary/25"
                        : "bg-background border-border/80 hover:border-primary/50"
                    }`}
                  >
                    🐘 PostgreSQL 17
                    <div className="text-4xs opacity-75 mt-0.5">Checkpoints & Accounts</div>
                  </button>

                  <button
                    onClick={() => setSelectedNode("langfuse")}
                    className={`p-3 rounded-xl border-2 transition-all duration-300 text-center text-xs font-semibold ${
                      selectedNode === "langfuse"
                        ? "bg-primary text-primary-foreground border-primary scale-105 shadow-md shadow-primary/25"
                        : "bg-background border-border/80 hover:border-primary/50"
                    }`}
                  >
                    📊 Langfuse 4.6.1
                    <div className="text-4xs opacity-75 mt-0.5">LLM Observability</div>
                  </button>
                </div>
              </div>
            </div>

            {/* Details Panel */}
            <div className="border rounded-2xl bg-card p-6 space-y-6 flex flex-col justify-between">
              <div>
                <h4 className="text-xl font-bold text-foreground pb-2 border-b border-border/40">
                  {t.overview.nodes[selectedNode as keyof typeof t.overview.nodes].name}
                </h4>
                <p className="text-sm text-muted-foreground mt-4 leading-relaxed">
                  {t.overview.nodes[selectedNode as keyof typeof t.overview.nodes].desc}
                </p>

                <div className="mt-6 space-y-4">
                  <div>
                    <h5 className="text-xs font-semibold text-primary uppercase tracking-wider">
                      {t.overview.techDetails}
                    </h5>
                    <p className="text-sm font-mono text-foreground mt-1 bg-muted/30 px-3 py-1.5 rounded-md border">
                      {t.overview.nodes[selectedNode as keyof typeof t.overview.nodes].tech}
                    </p>
                  </div>

                  <div>
                    <h5 className="text-xs font-semibold text-primary uppercase tracking-wider">
                      {t.overview.responsibility}
                    </h5>
                    <p className="text-sm text-foreground mt-1 leading-relaxed">
                      {t.overview.nodes[selectedNode as keyof typeof t.overview.nodes].resp}
                    </p>
                  </div>
                </div>
              </div>

              <div className="pt-4 border-t border-border/40">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider block">
                  {t.overview.protocol}
                </span>
                <span className="inline-flex items-center gap-1.5 text-xs text-primary font-semibold mt-1 bg-primary/10 px-2.5 py-1 rounded-full border border-primary/20">
                  <Activity className="h-3 w-3" />
                  {t.overview.nodes[selectedNode as keyof typeof t.overview.nodes].proto}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab Content 2: Agent Flow (LangGraph) */}
      {activeTab === "agentFlow" && (
        <div className="space-y-8 animate-fadeIn">
          <div className="text-center max-w-3xl mx-auto space-y-4">
            <h3 className="text-2xl font-bold text-foreground">{t.agentFlow.title}</h3>
            <p className="text-muted-foreground">{t.agentFlow.desc}</p>
          </div>

          <div className="grid gap-8 lg:grid-cols-[1.4fr_0.6fr]">
            {/* LangGraph Node Chain View */}
            <div className="border rounded-2xl bg-card/40 backdrop-blur-xs p-6 md:p-8 flex flex-col justify-center gap-4 min-h-[450px]">
              {/* Row 1: Guardrails & Router */}
              <div className="grid grid-cols-2 gap-4">
                <button
                  onClick={() => setSelectedAgent("guardrails_in")}
                  className={`p-4 rounded-xl border-2 transition-all duration-300 text-left ${
                    selectedAgent === "guardrails_in"
                      ? "bg-primary text-primary-foreground border-primary scale-102 shadow-md"
                      : "bg-background border-border hover:border-primary/50"
                  }`}
                >
                  <div className="text-xs font-bold opacity-75">Step 1</div>
                  <div className="font-semibold text-sm mt-1">{t.agentFlow.nodes.guardrails_in.name}</div>
                  <div className="text-2xs opacity-80 mt-2 line-clamp-1">NeMo Guardrails security checks</div>
                </button>

                <button
                  onClick={() => setSelectedAgent("router")}
                  className={`p-4 rounded-xl border-2 transition-all duration-300 text-left ${
                    selectedAgent === "router"
                      ? "bg-primary text-primary-foreground border-primary scale-102 shadow-md"
                      : "bg-background border-border hover:border-primary/50"
                  }`}
                >
                  <div className="text-xs font-bold opacity-75">Step 2</div>
                  <div className="font-semibold text-sm mt-1">{t.agentFlow.nodes.router.name}</div>
                  <div className="text-2xs opacity-80 mt-2 line-clamp-1">Fast Cosine Intent Router</div>
                </button>
              </div>

              {/* Arrow */}
              <div className="flex justify-center text-muted-foreground/40 h-2">
                <ArrowRight className="h-4 w-4 rotate-90" />
              </div>

              {/* Row 2: Supervisor */}
              <div className="flex justify-center">
                <button
                  onClick={() => setSelectedAgent("supervisor")}
                  className={`w-full max-w-md p-4 rounded-xl border-2 transition-all duration-300 text-center font-bold ${
                    selectedAgent === "supervisor"
                      ? "bg-primary text-primary-foreground border-primary scale-102 shadow-md"
                      : "bg-background border-border hover:border-primary/50"
                  }`}
                >
                  <div className="text-xs font-bold opacity-75">Step 3</div>
                  <div className="mt-1">🧠 {t.agentFlow.nodes.supervisor.name}</div>
                  <div className="text-2xs font-normal opacity-80 mt-1">LangGraph Supervisor router node</div>
                </button>
              </div>

              {/* Split Arrows */}
              <div className="flex justify-around px-24 text-muted-foreground/40 h-2">
                <ArrowRight className="h-4 w-4 rotate-135" />
                <ArrowRight className="h-4 w-4 rotate-45" />
              </div>

              {/* Row 3: Parallel Workers */}
              <div className="grid grid-cols-2 gap-4">
                <button
                  onClick={() => setSelectedAgent("rag_agent")}
                  className={`p-4 rounded-xl border-2 transition-all duration-300 text-left ${
                    selectedAgent === "rag_agent"
                      ? "bg-primary text-primary-foreground border-primary scale-102 shadow-md"
                      : "bg-background border-border hover:border-primary/50"
                  }`}
                >
                  <div className="text-xs font-bold opacity-75">Step 4a - Worker</div>
                  <div className="font-semibold text-sm mt-1">{t.agentFlow.nodes.rag_agent.name}</div>
                  <div className="text-2xs opacity-80 mt-2 line-clamp-1">Qdrant cultural facts lookup</div>
                </button>

                <button
                  onClick={() => setSelectedAgent("maps_agent")}
                  className={`p-4 rounded-xl border-2 transition-all duration-300 text-left ${
                    selectedAgent === "maps_agent"
                      ? "bg-primary text-primary-foreground border-primary scale-102 shadow-md"
                      : "bg-background border-border hover:border-primary/50"
                  }`}
                >
                  <div className="text-xs font-bold opacity-75">Step 4b - Worker</div>
                  <div className="font-semibold text-sm mt-1">{t.agentFlow.nodes.maps_agent.name}</div>
                  <div className="text-2xs opacity-80 mt-2 line-clamp-1">Goong Places V2 geolocations</div>
                </button>
              </div>

              {/* Convergence Arrow */}
              <div className="flex justify-around px-24 text-muted-foreground/40 h-2">
                <ArrowRight className="h-4 w-4 rotate-45" />
                <ArrowRight className="h-4 w-4 rotate-135" />
              </div>

              {/* Row 4: Re-ranker & Output Guardrails */}
              <div className="grid grid-cols-2 gap-4">
                <button
                  onClick={() => setSelectedAgent("reranker")}
                  className={`p-4 rounded-xl border-2 transition-all duration-300 text-left ${
                    selectedAgent === "reranker"
                      ? "bg-primary text-primary-foreground border-primary scale-102 shadow-md"
                      : "bg-background border-border hover:border-primary/50"
                  }`}
                >
                  <div className="text-xs font-bold opacity-75">Step 5</div>
                  <div className="font-semibold text-sm mt-1">{t.agentFlow.nodes.reranker.name}</div>
                  <div className="text-2xs opacity-80 mt-2 line-clamp-1">Bagging & Boosting scoring</div>
                </button>

                <button
                  onClick={() => setSelectedAgent("guardrails_out")}
                  className={`p-4 rounded-xl border-2 transition-all duration-300 text-left ${
                    selectedAgent === "guardrails_out"
                      ? "bg-primary text-primary-foreground border-primary scale-102 shadow-md"
                      : "bg-background border-border hover:border-primary/50"
                  }`}
                >
                  <div className="text-xs font-bold opacity-75">Step 6</div>
                  <div className="font-semibold text-sm mt-1">{t.agentFlow.nodes.guardrails_out.name}</div>
                  <div className="text-2xs opacity-80 mt-2 line-clamp-1">Output safety & grounding verification</div>
                </button>
              </div>
            </div>

            {/* Info details */}
            <div className="border rounded-2xl bg-card p-6 space-y-6 flex flex-col justify-between">
              <div>
                <h4 className="text-xl font-bold text-foreground pb-2 border-b border-border/40">
                  {t.agentFlow.nodes[selectedAgent as keyof typeof t.agentFlow.nodes].name}
                </h4>
                <p className="text-sm text-muted-foreground mt-4 leading-relaxed">
                  {t.agentFlow.nodes[selectedAgent as keyof typeof t.agentFlow.nodes].desc}
                </p>

                <div className="mt-6 space-y-4">
                  <div className="flex justify-between items-center bg-muted/20 px-3 py-2 rounded-lg border text-sm">
                    <span className="font-semibold text-muted-foreground">{t.agentFlow.status}</span>
                    <span className="font-semibold text-emerald-500 flex items-center gap-1">
                      <CheckCircle2 className="h-4 w-4" />
                      {t.agentFlow.nodes[selectedAgent as keyof typeof t.agentFlow.nodes].status}
                    </span>
                  </div>

                  <div className="space-y-1">
                    <span className="text-xs font-semibold text-primary uppercase tracking-wider block">
                      {t.agentFlow.input}
                    </span>
                    <p className="text-xs font-mono bg-muted/30 px-3 py-1.5 rounded-md border text-foreground">
                      {t.agentFlow.nodes[selectedAgent as keyof typeof t.agentFlow.nodes].input}
                    </p>
                  </div>

                  <div className="space-y-1">
                    <span className="text-xs font-semibold text-primary uppercase tracking-wider block">
                      {t.agentFlow.output}
                    </span>
                    <p className="text-xs font-mono bg-muted/30 px-3 py-1.5 rounded-md border text-foreground">
                      {t.agentFlow.nodes[selectedAgent as keyof typeof t.agentFlow.nodes].output}
                    </p>
                  </div>
                </div>
              </div>

              <div className="pt-4 border-t border-border/40">
                <span className="text-xs font-semibold text-amber-500 uppercase tracking-wider flex items-center gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  Rule / Execution Guard
                </span>
                <p className="text-xs text-foreground mt-1 leading-relaxed font-semibold">
                  {t.agentFlow.nodes[selectedAgent as keyof typeof t.agentFlow.nodes].rule}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab Content 3: RAG Pipeline */}
      {activeTab === "rag" && (
        <div className="space-y-12 animate-fadeIn">
          <div className="text-center max-w-3xl mx-auto space-y-4">
            <h3 className="text-2xl font-bold text-foreground">{t.rag.title}</h3>
            <p className="text-muted-foreground">{t.rag.desc}</p>
          </div>

          {/* Steps Timeline */}
          <div className="grid gap-6 md:grid-cols-4">
            {t.rag.steps.map((step, i) => (
              <div key={step.title} className="relative border rounded-2xl bg-card p-6 transition-all duration-300 hover:shadow-lg hover:-translate-y-1 flex flex-col justify-between">
                <div>
                  <span className="inline-flex size-9 items-center justify-center rounded-full bg-primary/10 text-primary font-bold text-sm mb-4">
                    {i === 0 && <FileText className="h-4 w-4" />}
                    {i === 1 && <Search className="h-4 w-4" />}
                    {i === 2 && <ShieldCheck className="h-4 w-4" />}
                    {i === 3 && <BookOpen className="h-4 w-4" />}
                  </span>
                  <h4 className="text-base font-bold text-foreground leading-tight">{step.title}</h4>
                  <p className="text-xs text-muted-foreground mt-3 leading-relaxed">{step.desc}</p>
                </div>
                {i < 3 && (
                  <div className="hidden md:block absolute -right-3 top-1/2 -translate-y-1/2 z-10 bg-background border rounded-full p-1 text-muted-foreground">
                    <ArrowRight className="h-3.5 w-3.5" />
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Qdrant collections specs */}
          <div className="border rounded-2xl bg-card/40 backdrop-blur-xs p-6 md:p-8 space-y-6">
            <div className="max-w-2xl">
              <h4 className="text-xl font-bold text-foreground flex items-center gap-2">
                <Database className="h-5 w-5 text-primary" />
                {t.rag.collections.title}
              </h4>
              <p className="text-sm text-muted-foreground mt-2">{t.rag.collections.desc}</p>
            </div>

            <div className="grid gap-6 md:grid-cols-3">
              {t.rag.collections.items.map((col) => (
                <div key={col.name} className="border rounded-xl bg-background p-5 space-y-4">
                  <div>
                    <span className="text-xs font-mono font-bold text-primary bg-primary/10 px-2 py-0.5 rounded border border-primary/20">
                      {col.name}
                    </span>
                    <p className="text-xs text-foreground mt-3 leading-relaxed min-h-[50px]">{col.desc}</p>
                  </div>
                  <div className="pt-3 border-t border-border/40 flex justify-between items-center text-3xs font-mono text-muted-foreground">
                    <span>Dimension: 768</span>
                    <span>Metric: Cosine</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab Content 4: Re-ranking Simulator */}
      {activeTab === "rerank" && (
        <div className="space-y-8 animate-fadeIn">
          <div className="text-center max-w-3xl mx-auto space-y-4">
            <h3 className="text-2xl font-bold text-foreground">{t.rerank.title}</h3>
            <p className="text-muted-foreground">{t.rerank.desc}</p>
          </div>

          <div className="grid gap-8 lg:grid-cols-[0.95fr_1.05fr]">
            {/* Input Controls */}
            <div className="border rounded-2xl bg-card p-6 md:p-8 space-y-6 shadow-sm">
              <h4 className="text-lg font-bold text-foreground pb-2 border-b border-border/40 flex items-center gap-2">
                <Settings className="h-5 w-5 text-primary" />
                {t.rerank.inputs}
              </h4>

              {/* Local Factor Builder */}
              <div className="space-y-3">
                <label className="text-sm font-semibold text-foreground flex items-center gap-1.5">
                  <Scale className="h-4 w-4 text-primary" />
                  {t.rerank.localFactorTitle}:{" "}
                  <span className="font-bold text-primary tabular-nums">
                    {localFactor}
                  </span>
                </label>
                <p className="text-2xs text-muted-foreground leading-normal">
                  {t.rerank.localFactorDesc}
                </p>

                <div className="space-y-2 bg-muted/20 p-3 rounded-lg border">
                  <label className="flex items-start gap-2.5 text-xs text-foreground cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={hasBusiness && !isChain}
                      disabled={isChain}
                      onChange={(e) => setHasBusiness(e.target.checked)}
                      className="mt-0.5 rounded border-border text-primary focus:ring-primary h-3.5 w-3.5"
                    />
                    <span>{t.rerank.criteria.business}</span>
                  </label>

                  <label className="flex items-start gap-2.5 text-xs text-foreground cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={hasFishing && !isChain}
                      disabled={isChain}
                      onChange={(e) => setHasFishing(e.target.checked)}
                      className="mt-0.5 rounded border-border text-primary focus:ring-primary h-3.5 w-3.5"
                    />
                    <span>{t.rerank.criteria.fishing}</span>
                  </label>

                  <label className="flex items-start gap-2.5 text-xs text-foreground cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={hasTraditional && !isChain}
                      disabled={isChain}
                      onChange={(e) => setHasTraditional(e.target.checked)}
                      className="mt-0.5 rounded border-border text-primary focus:ring-primary h-3.5 w-3.5"
                    />
                    <span>{t.rerank.criteria.traditional}</span>
                  </label>

                  <label className="flex items-start gap-2.5 text-xs text-foreground cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={hasElderly && !isChain}
                      disabled={isChain}
                      onChange={(e) => setHasElderly(e.target.checked)}
                      className="mt-0.5 rounded border-border text-primary focus:ring-primary h-3.5 w-3.5"
                    />
                    <span>{t.rerank.criteria.elderly}</span>
                  </label>
                </div>
              </div>

              {/* Other Place Configs */}
              <div className="space-y-4">
                {/* Rating Slider */}
                <div className="space-y-2">
                  <div className="flex justify-between text-xs font-semibold">
                    <span className="text-foreground">{t.rerank.placeConfig.rating}</span>
                    <span className="text-primary font-bold tabular-nums">{rating.toFixed(1)} ⭐</span>
                  </div>
                  <input
                    type="range"
                    min="1.0"
                    max="5.0"
                    step="0.1"
                    value={rating}
                    onChange={(e) => setRating(parseFloat(e.target.value))}
                    className="w-full h-1.5 rounded-lg bg-muted appearance-none cursor-pointer accent-primary"
                  />
                </div>

                {/* Distance Slider */}
                <div className="space-y-2">
                  <div className="flex justify-between text-xs font-semibold">
                    <span className="text-foreground">{t.rerank.placeConfig.distance}</span>
                    <span className="text-primary font-bold tabular-nums">{distance}m</span>
                  </div>
                  <input
                    type="range"
                    min="100"
                    max="3000"
                    step="50"
                    value={distance}
                    onChange={(e) => setDistance(parseInt(e.target.value))}
                    className="w-full h-1.5 rounded-lg bg-muted appearance-none cursor-pointer accent-primary"
                  />
                </div>

                {/* Price Level and Accessibility Toggles */}
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <span className="text-xs font-semibold text-foreground block">{t.rerank.placeConfig.price}</span>
                    <div className="flex border rounded-lg overflow-hidden h-9 bg-background">
                      {[0, 1, 2, 3, 4].map((p) => (
                        <button
                          key={p}
                          type="button"
                          onClick={() => setPriceLevel(p)}
                          className={`flex-1 text-xs font-bold transition-colors ${
                            priceLevel === p
                              ? "bg-primary text-primary-foreground"
                              : "hover:bg-muted text-foreground"
                          }`}
                        >
                          {p === 0 ? "Free" : "$".repeat(p)}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-2 flex flex-col justify-end">
                    <label className="flex items-center gap-2 text-xs font-semibold text-foreground cursor-pointer select-none h-9 border rounded-lg px-3 bg-background hover:bg-muted/30">
                      <input
                        type="checkbox"
                        checked={wheelchair}
                        onChange={(e) => setWheelchair(e.target.checked)}
                        className="rounded border-border text-primary focus:ring-primary h-4 w-4"
                      />
                      <span className="flex items-center gap-1">
                        ♿ {t.rerank.placeConfig.access}
                      </span>
                    </label>
                  </div>
                </div>

                {/* Corporate Chain Business Penalty */}
                <div className="bg-destructive/5 border border-destructive/20 rounded-lg p-3 space-y-1.5">
                  <label className="flex items-start gap-2.5 text-xs text-foreground cursor-pointer font-semibold select-none">
                    <input
                      type="checkbox"
                      checked={isChain}
                      onChange={(e) => setIsChain(e.target.checked)}
                      className="mt-0.5 rounded border-destructive/30 text-destructive focus:ring-destructive h-3.5 w-3.5"
                    />
                    <span className="text-destructive flex items-center gap-1">
                      <Building className="h-3.5 w-3.5" />
                      {t.rerank.placeConfig.chain}
                    </span>
                  </label>
                  <p className="text-3xs text-muted-foreground leading-normal ml-6">
                    {t.rerank.placeConfig.chainDesc}
                  </p>
                </div>
              </div>
            </div>

            {/* Calculations & Charts */}
            <div className="border rounded-2xl bg-card p-6 md:p-8 space-y-6 flex flex-col justify-between">
              <div>
                <h4 className="text-lg font-bold text-foreground pb-2 border-b border-border/40 flex items-center gap-2">
                  <Activity className="h-5 w-5 text-primary" />
                  {t.rerank.metrics}
                </h4>

                {/* Visual Chart */}
                <div className="space-y-4 mt-6">
                  {/* Tree 1 */}
                  <div>
                    <div className="flex justify-between text-xs font-medium mb-1">
                      <span>Tree 1 (Locality)</span>
                      <span className="font-bold text-primary">{Math.round(tree1Score * 100)}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-primary/70 rounded-full transition-all duration-300" style={{ width: `${tree1Score * 100}%` }} />
                    </div>
                  </div>

                  {/* Tree 2 */}
                  <div>
                    <div className="flex justify-between text-xs font-medium mb-1">
                      <span>Tree 2 (Proximity)</span>
                      <span className="font-bold text-primary">{Math.round(tree2Score * 100)}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-primary/70 rounded-full transition-all duration-300" style={{ width: `${tree2Score * 100}%` }} />
                    </div>
                  </div>

                  {/* Tree 3 */}
                  <div>
                    <div className="flex justify-between text-xs font-medium mb-1">
                      <span>Tree 3 (Quality)</span>
                      <span className="font-bold text-primary">{Math.round(tree3Score * 100)}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-primary/70 rounded-full transition-all duration-300" style={{ width: `${tree3Score * 100}%` }} />
                    </div>
                  </div>

                  {/* Bagging Score */}
                  <div className="pt-2 border-t border-border/40">
                    <div className="flex justify-between text-xs font-bold mb-1">
                      <span className="text-foreground">Bagging Score (Average)</span>
                      <span className="font-bold text-primary">{Math.round(baggingScore * 100)}%</span>
                    </div>
                    <div className="h-2.5 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-primary rounded-full transition-all duration-300" style={{ width: `${baggingScore * 100}%` }} />
                    </div>
                  </div>

                  {/* Final Score Gauge */}
                  <div className="bg-primary/5 border border-primary/20 rounded-xl p-4 flex items-center justify-between mt-4">
                    <div className="space-y-1">
                      <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider block">
                        {t.rerank.formula}
                      </span>
                      <span className="text-lg font-bold text-foreground">Ensemble Final Score</span>
                    </div>
                    <div className="text-center">
                      <div className="text-3xl font-extrabold text-primary tabular-nums">
                        {finalScore.toFixed(3)}
                      </div>
                      <div className="text-2xs text-muted-foreground">Range: 0.0 - 1.0</div>
                    </div>
                  </div>
                </div>

                {/* Mathematical Steps Details */}
                <div className="mt-6 space-y-3 bg-muted/10 p-4 rounded-xl border text-xs">
                  <h5 className="font-bold text-foreground uppercase tracking-wider mb-2">
                    {t.rerank.mathSteps.title}
                  </h5>

                  <div className="grid grid-cols-[1.5fr_2.5fr] gap-x-2 gap-y-1.5">
                    <span className="font-semibold text-muted-foreground">{t.rerank.mathSteps.tree1}</span>
                    <span className="font-mono text-foreground font-semibold">
                      {tree1Score} <span className="text-2xs font-normal text-muted-foreground">({t.rerank.mathSteps.tree1Desc})</span>
                    </span>

                    <span className="font-semibold text-muted-foreground">{t.rerank.mathSteps.tree2}</span>
                    <span className="font-mono text-foreground font-semibold">
                      {tree2Score} <span className="text-2xs font-normal text-muted-foreground">({t.rerank.mathSteps.tree2Desc})</span>
                    </span>

                    <span className="font-semibold text-muted-foreground">{t.rerank.mathSteps.tree3}</span>
                    <span className="font-mono text-foreground font-semibold">
                      {tree3Score} <span className="text-2xs font-normal text-muted-foreground">({t.rerank.mathSteps.tree3Desc})</span>
                    </span>

                    <span className="font-semibold text-muted-foreground border-t border-border/40 pt-1.5">{t.rerank.mathSteps.bagging}</span>
                    <span className="font-mono text-primary font-bold border-t border-border/40 pt-1.5">
                      {baggingScore}
                    </span>

                    <span className="font-semibold text-muted-foreground">{t.rerank.mathSteps.boosting1}</span>
                    <span className="font-mono text-foreground font-semibold">
                      {boostingDelta1 !== 0 ? `+ 0.3 * (${boostingDelta1}) = ` : "+ 0 = "}
                      {Math.round(boosting1Result * 1000) / 1000}
                      {boostingDelta1 !== 0 && (
                        <span className="text-4xs text-rose-500 font-semibold ml-1">({t.rerank.mathSteps.boosting1Desc})</span>
                      )}
                    </span>

                    <span className="font-semibold text-muted-foreground">{t.rerank.mathSteps.boosting2}</span>
                    <span className="font-mono text-foreground font-semibold">
                      {boostingDelta2 !== 0 ? `+ 0.3 * (${boostingDelta2}) = ` : "+ 0 = "}
                      {Math.round(boosting2Result * 1000) / 1000}
                      {boostingDelta2 !== 0 && (
                        <span className="text-4xs text-emerald-500 font-semibold ml-1">({t.rerank.mathSteps.boosting2Desc})</span>
                      )}
                    </span>

                    <span className="font-bold text-foreground border-t-2 border-primary/20 pt-1.5">{t.rerank.mathSteps.final}</span>
                    <span className="font-mono text-primary font-extrabold text-sm border-t-2 border-primary/20 pt-1.5">
                      {finalScore}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab Content 5: Responsible AI 5 Axes */}
      {activeTab === "responsible" && (
        <div className="space-y-8 animate-fadeIn">
          <div className="text-center max-w-3xl mx-auto space-y-4">
            <h3 className="text-2xl font-bold text-foreground">{t.responsible.title}</h3>
            <p className="text-muted-foreground">{t.responsible.desc}</p>
          </div>

          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {t.responsible.axes.map((axis, i) => (
              <div
                key={axis.title}
                className="border rounded-2xl bg-card p-6 flex flex-col justify-between transition-all duration-300 hover:shadow-lg hover:-translate-y-1"
              >
                <div className="space-y-4">
                  <span className="inline-flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    {i === 0 && <ShieldCheck className="h-5 w-5" />}
                    {i === 1 && <Scale className="h-5 w-5" />}
                    {i === 2 && <Zap className="h-5 w-5" />}
                    {i === 3 && <Building className="h-5 w-5" />}
                    {i === 4 && <FileText className="h-5 w-5" />}
                  </span>
                  <h4 className="text-lg font-bold text-foreground">{axis.title}</h4>
                  <p className="text-xs leading-relaxed text-muted-foreground">{axis.desc}</p>
                </div>

                <div className="mt-6 pt-4 border-t border-border/40">
                  <span className="text-2xs font-semibold text-primary uppercase tracking-wider block">
                    Target Metric
                  </span>
                  <span className="text-xs font-semibold text-foreground mt-1 block font-mono">
                    {axis.metric}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
