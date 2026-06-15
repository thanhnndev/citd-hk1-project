import type { ComponentType, SVGProps } from 'react';
import { setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import {
  Activity,
  BookOpen,
  BrainCircuit,
  ChevronRight,
  Database,
  GitBranch,
  History,
  MapPin,
  MessageSquare,
  Monitor,
  RadioTower,
  Route,
  Scale,
  Search,
  Send,
  Settings2,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  UserRound,
} from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import { routing } from '@/i18n/routing';

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

type CardEntry = Readonly<{
  title: string;
  description: string;
}>;

type SectionData = Readonly<{
  id: string;
  eyebrow: string;
  heading: string;
  cards: ReadonlyArray<CardEntry>;
  icons: ReadonlyArray<IconComponent>;
}>;

type FlowNode = Readonly<{
  title: string;
  description: string;
  icon: IconComponent;
}>;

type PageCopy = Readonly<{
  heroTitle: string;
  heroDescription: string;
  flowEyebrow: string;
  flowHeading: string;
  flowNodes: ReadonlyArray<FlowNode>;
  sections: ReadonlyArray<SectionData>;
  copyright: string;
}>;

const borderGray = '#E5E7EB';

function FlowDiagram({ nodes }: { nodes: ReadonlyArray<FlowNode> }) {
  return (
    <div className="mt-7 rounded-[10px] border border-[#bfc7d1] bg-[#f0f3ff] px-4 py-7 sm:px-5">
      <div className="overflow-x-auto px-1 pb-1">
        <div className="grid min-w-[900px] grid-cols-6 items-stretch gap-12">
          {nodes.map((node, index) => {
            const Icon = node.icon;
            const isLast = index === nodes.length - 1;

            return (
              <div key={node.title} className="relative">
                <div className="flex h-full min-h-[136px] flex-col items-center justify-center rounded-[6px] border border-[#E5E7EB] bg-white px-4 py-4 text-center shadow-[0_4px_14px_rgba(0,93,144,0.025)]">
                  <div className="grid size-9 place-items-center rounded-full bg-[#e7eeff] text-[#005d90]">
                    <Icon aria-hidden="true" className="size-[18px]" strokeWidth={2.35} />
                  </div>
                  <h3 className="mt-4 text-[18px] font-black leading-6 text-[#001b3c]">{node.title}</h3>
                  <p className="mt-2 text-base font-bold leading-6 text-[#001b3c]">{node.description}</p>
                </div>
                {!isLast ? (
                  <div className="absolute right-[-34px] top-1/2 z-10 -translate-y-1/2 text-[#94ccff]">
                    <ChevronRight aria-hidden="true" className="size-4" strokeWidth={1.8} />
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function ArchitectureSection({ section }: { section: SectionData }) {
  return (
    <section
      id={section.id}
      className="border-t bg-white py-20 sm:py-24"
      style={{ borderColor: section.id === 'rag-pipeline' ? '#e7eeff' : borderGray }}
    >
      <div className="mx-auto w-full max-w-6xl px-6">
        <div className="mx-auto max-w-[780px] text-center">
          <p className="text-2xl font-extrabold text-[#005d90]">{section.eyebrow}</p>
          <h2 className="mt-5 text-[56px] font-black leading-[1.04] tracking-[-0.065em] text-[#001b3c] sm:text-[84px]">
            {section.heading}
          </h2>
          <div className="mx-auto mt-5 h-[3px] w-[72px] rounded-full bg-[#0077b6]" />
        </div>

        <div className="mt-12 grid gap-5 lg:grid-cols-3">
          {section.cards.map((card, index) => {
            const Icon = section.icons[index] ?? Sparkles;

            return (
              <Card
                key={card.title}
                className="relative overflow-hidden border-primary/10 bg-card transition-all duration-300 hover:-translate-y-1 hover:shadow-lg hover:shadow-primary/10"
              >
                <CardContent className="space-y-5">
                  <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary transition-transform duration-300 group-hover:scale-110">
                    <Icon aria-hidden="true" className="size-5" />
                  </div>
                  <div>
                    <h3 className="text-[32px] font-bold leading-10 tracking-tight text-foreground">{card.title}</h3>
                    <p className="mt-5 text-xl leading-9 text-muted-foreground">{card.description}</p>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function getPageCopy(isVietnamese: boolean): PageCopy {
  if (!isVietnamese) {
    return {
      heroTitle: 'Multi-agent AI assistant for Ham Ninh travel',
      heroDescription:
        'The architecture combines a large language model (LLM), Retrieval-Augmented Generation (RAG), and Multi-Agent logic to provide accurate, realtime tour and heritage knowledge for Ham Ninh.',
      flowEyebrow: 'Data flow',
      flowHeading: 'System data-flow architecture',
      copyright: '© 2026 Ham Ninh Guide AI. AI can make mistakes - please verify important information.',
      flowNodes: [
        { title: 'User', description: 'Send request', icon: UserRound },
        { title: 'Frontend', description: 'React interface', icon: Monitor },
        { title: 'Agent Orchestrator', description: 'LangGraph logic', icon: BrainCircuit },
        { title: 'Worker', description: 'RAG, Maps, retrieval and processing', icon: Settings2 },
        { title: 'SSE Streaming', description: 'Data delivery', icon: RadioTower },
        { title: 'Response', description: 'Stream result', icon: Send },
      ],
      sections: [
        {
          id: 'rag-pipeline',
          eyebrow: 'Knowledge retrieval',
          heading: 'RAG Pipeline - Tour Q&A with citations',
          cards: [
            {
              title: 'Knowledge base',
              description: 'Stores tourism, policy, and local knowledge in chunks optimized for semantic search.',
            },
            {
              title: 'Vector search',
              description: 'Embeds the user query and retrieves the most relevant documents for each travel question.',
            },
            {
              title: 'Source-grounded answer',
              description: 'The LLM summarizes final answers with inline citations to keep recommendations transparent.',
            },
          ],
          icons: [Database, Search, BookOpen],
        },
        {
          id: 'maps-api',
          eyebrow: 'Realtime place data',
          heading: 'Maps & Places API - Realtime Ham Ninh places',
          cards: [
            {
              title: 'Find places',
              description: 'Integrates Places API to fetch the latest restaurants, services, and points of interest.',
            },
            {
              title: 'Plan itineraries',
              description: 'Calculates distance and travel time between places to optimize day-trip schedules.',
            },
            {
              title: 'Fallback handling',
              description: 'Uses cache and backup providers when the primary API is slow or unavailable.',
            },
          ],
          icons: [MapPin, Route, ShieldAlert],
        },
        {
          id: 'ensemble-reranker',
          eyebrow: 'Smart ranking',
          heading: 'Ensemble Re-ranking - Fair Ham Ninh tour suggestions',
          cards: [
            {
              title: 'Multi-factor scoring',
              description: 'Analyzes user intent, price, location, and popularity to produce a blended recommendation score.',
            },
            {
              title: 'Policy weights',
              description: 'Adjusts ranking priorities based on active tourism policies or sustainability campaigns.',
            },
            {
              title: 'Fair ranking',
              description: 'Balances relevance with diversity to avoid hiding smaller local businesses.',
            },
          ],
          icons: [GitBranch, Scale, SlidersHorizontal],
        },
        {
          id: 'orchestration',
          eyebrow: 'Agent',
          heading: 'Agent Orchestration - LangGraph supervision model',
          cards: [
            {
              title: 'Supervisor model',
              description: 'Uses LangGraph to coordinate specialized worker flows for short and complex conversations.',
            },
            {
              title: 'Streaming distribution',
              description: 'Splits responses into streaming chunks so the interface can show progress and context quickly.',
            },
            {
              title: 'Full traceability',
              description: 'Records agent decisions, tool calls, and correction steps for auditing and quality review.',
            },
          ],
          icons: [MessageSquare, RadioTower, History],
        },
        {
          id: 'frontend-shell',
          eyebrow: 'App',
          heading: 'Frontend Shell & System Observability',
          cards: [
            {
              title: 'Platform interface',
              description: 'Builds on Next.js with a modern, accessible UI that supports the daily needs of Ham Ninh visitors.',
            },
            {
              title: 'Realtime monitoring',
              description: 'Dashboards track system metrics, error rates, and user feedback signals.',
            },
            {
              title: 'AI safety layer',
              description: 'Screens inputs and outputs to limit inappropriate guidance or serious misinformation.',
            },
          ],
          icons: [Monitor, Activity, ShieldAlert],
        },
      ],
    };
  }

  return {
    heroTitle: 'Trợ lý AI đa agent cho du lịch Hàm Ninh',
    heroDescription:
      'Kiến trúc hiện đại kết hợp mô hình ngôn ngữ lớn (LLM), Retrieval-Augmented Generation (RAG) và hệ thống Multi-Agent để cung cấp tri thức tour & hải sản Hàm Ninh chính xác, realtime.',
    flowEyebrow: 'Luồng dữ liệu',
    flowHeading: 'Kiến trúc luồng dữ liệu hệ thống',
    copyright: '© 2026 Hàm Ninh Guide AI. AI có thể mắc lỗi - vui lòng kiểm tra thông tin quan trọng.',
    flowNodes: [
      { title: 'Người dùng', description: 'Gửi yêu cầu', icon: UserRound },
      { title: 'Frontend', description: 'Giao diện React', icon: Monitor },
      { title: 'Bộ điều phối Agent', description: 'LangGraph Logic', icon: BrainCircuit },
      { title: 'Worker (RAG, Maps)', description: 'Truy xuất & xử lý', icon: Settings2 },
      { title: 'SSE Streaming', description: 'Truyền tải dữ liệu', icon: RadioTower },
      { title: 'Phản hồi', description: 'Streaming kết quả', icon: Send },
    ],
    sections: [
      {
        id: 'rag-pipeline',
        eyebrow: 'Truy xuất tri thức',
        heading: 'RAG Pipeline - Hỏi đáp tour có trích dẫn',
        cards: [
          {
            title: 'Kho dữ liệu',
            description:
              'Lưu trữ các văn bản du lịch, chính sách giá và thông tin tour được phân mảnh (chunking) tối ưu cho việc tìm kiếm semantic.',
          },
          {
            title: 'Tìm kiếm vector',
            description:
              'Sử dụng Embedding Model cao cấp để tìm kiếm các đoạn văn bản có ý nghĩa gần nhất với câu hỏi của khách du lịch.',
          },
          {
            title: 'Câu trả lời có nguồn',
            description:
              'LLM tổng hợp câu trả lời cuối cùng kèm theo trích dẫn chính xác từ kho dữ liệu, đảm bảo tính minh bạch và tin cậy.',
          },
        ],
        icons: [Database, Search, BookOpen],
      },
      {
        id: 'maps-api',
        eyebrow: 'Dữ liệu địa điểm thực tế',
        heading: 'Maps & Places API - Địa điểm Hàm Ninh realtime',
        cards: [
          {
            title: 'Tìm kiếm địa điểm',
            description:
              'Tích hợp Google Places API để lấy thông tin các khách sạn, nhà bè, và địa điểm tại Hàm Ninh mới nhất.',
          },
          {
            title: 'Lập lịch hành trình',
            description:
              'Tính toán khoảng cách và thời gian di chuyển thực tế giữa các điểm đến để tối ưu hóa lịch trình tham quan làng chài.',
          },
          {
            title: 'Xử lý dự phòng',
            description:
              'Cơ chế caching thông minh và fallback dữ liệu của phương khi API bên thứ ba gặp sự cố hoặc quá tải.',
          },
        ],
        icons: [MapPin, Route, ShieldAlert],
      },
      {
        id: 'ensemble-reranker',
        eyebrow: 'Xếp hạng thông minh',
        heading: 'Ensemble Re-ranking - Gợi ý tour Hàm Ninh công bằng',
        cards: [
          {
            title: 'Chấm điểm đa chiều',
            description:
              'Phân tích đánh giá người dùng, giá cả và độ phổ biến để tạo ra bộ điểm số tổng hợp cho mỗi kết quả đề xuất.',
          },
          {
            title: 'Trọng số chính sách',
            description:
              'Điều chỉnh thứ tự hiển thị dựa trên các chiến dịch khuyến mãi hoặc đối tác ưu tiên một cách linh hoạt.',
          },
          {
            title: 'Xếp hạng công bằng',
            description:
              'Đảm bảo sự đa dạng trong kết quả, tránh việc các địa điểm lớn lấn át hoàn toàn các doanh nghiệp địa phương nhỏ lẻ tại Hàm Ninh.',
          },
        ],
        icons: [GitBranch, Scale, SlidersHorizontal],
      },
      {
        id: 'orchestration',
        eyebrow: 'Agent',
        heading: 'Điều phối Agent - Mô hình giám sát LangGraph',
        cards: [
          {
            title: 'Mô hình giám sát',
            description:
              'Sử dụng LangGraph để thiết kế luồng suy nghĩ (state machine) cho AI, giúp quản lý các hội thoại phức tạp.',
          },
          {
            title: 'Phân tán streaming',
            description:
              'Phân phối được đầy đủ giao diện theo thời gian thực (streaming token) giúp giảm thiểu độ trễ cảm nhận cho người dùng.',
          },
          {
            title: 'Theo dõi toàn trình',
            description:
              'Ghi lại toàn bộ quá trình đưa ra quyết định của Agent để phục vụ việc tinh chỉnh và kiểm soát chất lượng nội dung.',
          },
        ],
        icons: [MessageSquare, RadioTower, History],
      },
      {
        id: 'frontend-shell',
        eyebrow: 'App',
        heading: 'Frontend Shell & Quan sát hệ thống',
        cards: [
          {
            title: 'Giao diện đa nền tảng',
            description:
              'Xây dựng trên nền tảng Next.js hiện đại, hỗ trợ SSR và PWA để truy cập nhanh chóng ngay cả khi mạng yếu tại Hàm Ninh.',
          },
          {
            title: 'Quan sát thời gian thực',
            description:
              'Dashboard theo dõi hiệu năng hệ thống, tỷ lệ chính xác của câu trả lời và phản hồi tiêu cực từ người dùng.',
          },
          {
            title: 'Lớp bảo mật AI',
            description:
              'Kiểm duyệt đầu vào và đầu ra để ngăn chặn các nội dung không phù hợp hoặc sai lệch thông tin nghiêm trọng.',
          },
        ],
        icons: [Monitor, Activity, ShieldAlert],
      },
    ],
  };
}

export default async function ArchitecturePage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);

  const copy = getPageCopy(locale !== 'en');

  return (
    <div className="min-h-screen bg-[#f9f9ff] text-[#001b3c]">
      <section
        id="architecture-hero"
        className="px-4 sm:px-6 lg:px-8"
        style={{ paddingBottom: 72, paddingTop: 92 }}
      >
        <div className="mx-auto" style={{ maxWidth: 960 }}>
          <div className="mx-auto text-center" style={{ maxWidth: 760 }}>
            <h1
              className="font-black text-[#001b3c]"
              style={{
                fontFamily: '"Be Vietnam Pro", Arial, sans-serif',
                fontSize: 'clamp(42px, 4vw, 58px)',
                fontWeight: 800,
                letterSpacing: '-0.025em',
                lineHeight: 1.08,
              }}
            >
              {copy.heroTitle}
            </h1>
            <p
              className="mx-auto mt-5 font-medium text-[#001b3c]"
              style={{ fontSize: 16, lineHeight: '28px', maxWidth: 610 }}
            >
              {copy.heroDescription}
            </p>
          </div>

          <section id="architecture-flow" className="mx-auto mt-7 max-w-[960px]">
            <div className="text-center">
              <p className="text-2xl font-extrabold text-[#005d90]">{copy.flowEyebrow}</p>
              <h2 className="mt-5 text-[56px] font-black leading-[1.04] tracking-[-0.065em] text-[#001b3c] sm:text-[86px]">
                {copy.flowHeading}
              </h2>
            </div>
            <FlowDiagram nodes={copy.flowNodes} />
          </section>
        </div>
      </section>

      {copy.sections.map((section) => (
        <ArchitectureSection key={section.id} section={section} />
      ))}

      <footer className="border-t bg-[#e7eeff] px-4 py-10 text-center text-[22px] font-semibold leading-8 text-[#707881]" style={{ borderColor: borderGray }}>
        <p>{copy.copyright}</p>
        <nav aria-label="Legal links" className="mt-6 flex flex-wrap items-center justify-center gap-x-10 gap-y-4 text-xl font-black text-[#707881]">
          <a href="#" className="transition hover:text-[#005d90]">
            Privacy Policy
          </a>
          <a href="#" className="transition hover:text-[#005d90]">
            Terms of Service
          </a>
          <a href="#" className="transition hover:text-[#005d90]">
            Security Disclosure
          </a>
        </nav>
      </footer>
    </div>
  );
}
