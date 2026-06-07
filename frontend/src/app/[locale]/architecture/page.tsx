import type { ComponentType, SVGProps } from 'react';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import {
  Activity,
  BookOpen,
  BrainCircuit,
  ChevronRight,
  Database,
  GitBranch,
  History,
  Languages,
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

import { routing } from '@/i18n/routing';

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

type IconComponent = ComponentType<SVGProps<SVGSVGElement>>;

type CardEntry = Readonly<{ title: string; description: string }>;

type SectionData = Readonly<{
  id: string;
  eyebrow: string;
  heading: string;
  body: string;
  cards: ReadonlyArray<CardEntry>;
  icons: ReadonlyArray<IconComponent>;
}>;

type FlowNode = Readonly<{
  title: string;
  description: string;
  icon: IconComponent;
}>;

const borderGray = '#E5E7EB';

function isCardEntryArray(value: unknown): CardEntry[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is CardEntry =>
      typeof item === 'object' &&
      item !== null &&
      typeof (item as CardEntry).title === 'string' &&
      typeof (item as CardEntry).description === 'string',
  );
}

function FlowDiagram({ nodes }: { nodes: ReadonlyArray<FlowNode> }) {
  return (
    <div className="mx-auto mt-8 max-w-[920px] overflow-x-auto px-1 pb-2">
      <div className="grid min-w-[860px] grid-cols-6 items-stretch gap-4">
        {nodes.map((node, index) => {
          const Icon = node.icon;
          const isLast = index === nodes.length - 1;

          return (
            <div key={node.title} className="relative">
              <div className="h-full rounded-xl border bg-white px-4 py-5 text-center shadow-[0_10px_28px_rgba(0,93,144,0.06)]" style={{ borderColor: borderGray }}>
                <div className="mx-auto flex h-9 w-9 items-center justify-center rounded-lg bg-[#005d90]/10 text-[#005d90]">
                  <Icon className="h-4 w-4" />
                </div>
                <h3 className="mt-3 text-xs font-black text-[#003653]">{node.title}</h3>
                <p className="mt-1.5 text-[11px] leading-4 text-[#577487]">{node.description}</p>
              </div>
              {!isLast ? (
                <div className="absolute right-[-18px] top-1/2 z-10 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-full border bg-white text-[#005d90] shadow-sm" style={{ borderColor: borderGray }}>
                  <ChevronRight className="h-3.5 w-3.5" />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ArchitectureSection({ section }: { section: SectionData }) {
  const isPipelineSection = section.id === 'rag-pipeline';

  return (
    <section
      id={section.id}
      className="border-t px-6 py-16 sm:px-10 sm:py-20 lg:px-20 xl:px-28 2xl:px-36"
      style={{ borderColor: borderGray }}
    >
      <div
        className={`mx-auto ${
          isPipelineSection ? 'max-w-[1040px]' : 'max-w-[960px]'
        }`}
      >
        <div className="mx-auto max-w-3xl text-center">
          <p className="text-xs font-black uppercase tracking-[0.26em] text-[#0075b4]">{section.eyebrow}</p>
          <h2 className="mt-3 text-3xl font-black tracking-[-0.045em] text-[#002f49] sm:text-4xl">
            {section.heading}
          </h2>
          <p className="mt-5 text-sm leading-7 text-[#577487] sm:text-base">{section.body}</p>
        </div>

        <div className="mt-9 grid gap-5 md:grid-cols-3">
          {section.cards.map((card, index) => {
            const Icon = section.icons[index] ?? Sparkles;

            return (
              <article
                key={card.title}
                className={`rounded-xl border bg-white shadow-[0_10px_30px_rgba(0,93,144,0.045)] transition hover:-translate-y-1 hover:shadow-[0_18px_45px_rgba(0,93,144,0.10)] ${
                  isPipelineSection ? 'p-7' : 'p-6'
                }`}
                style={{ borderColor: borderGray }}
              >
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#005d90]/10 text-[#005d90]">
                  <Icon className="h-[18px] w-[18px]" />
                </div>
                <h3 className="mt-5 text-base font-black text-[#003653]">{card.title}</h3>
                <p className="mt-3 text-sm leading-6 text-[#577487]">{card.description}</p>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

export default async function ArchitecturePage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);

  const t = await getTranslations('Architecture');
  const isVietnamese = locale !== 'en';

  const flowNodes: FlowNode[] = [
    {
      title: isVietnamese ? 'Người dùng' : 'User',
      description: isVietnamese ? 'Gửi yêu cầu' : 'Send request',
      icon: UserRound,
    },
    {
      title: 'Frontend',
      description: isVietnamese ? 'Giao diện React' : 'React interface',
      icon: Monitor,
    },
    {
      title: 'Agent Orchestrator',
      description: 'LangGraph Logic',
      icon: BrainCircuit,
    },
    {
      title: 'Worker',
      description: isVietnamese ? 'RAG, Maps và xử lý tác vụ' : 'RAG, Maps and task processing',
      icon: Settings2,
    },
    {
      title: 'SSE Streaming',
      description: isVietnamese ? 'Truyền tải dữ liệu' : 'Data delivery',
      icon: RadioTower,
    },
    {
      title: isVietnamese ? 'Phản hồi' : 'Response',
      description: isVietnamese ? 'Streaming kết quả' : 'Streamed result',
      icon: Send,
    },
  ];

  const sections: SectionData[] = [
    {
      id: 'rag-pipeline',
      eyebrow: t('ragPipeline.eyebrow'),
      heading: t('ragPipeline.heading'),
      body: t('ragPipeline.body'),
      cards: isCardEntryArray(t.raw('ragPipeline.cards')),
      icons: [Database, Search, BookOpen],
    },
    {
      id: 'maps-api',
      eyebrow: t('mapsApi.eyebrow'),
      heading: t('mapsApi.heading'),
      body: t('mapsApi.body'),
      cards: isCardEntryArray(t.raw('mapsApi.cards')),
      icons: [MapPin, Route, ShieldAlert],
    },
    {
      id: 'ensemble-reranker',
      eyebrow: t('ensembleReranker.eyebrow'),
      heading: t('ensembleReranker.heading'),
      body: t('ensembleReranker.body'),
      cards: isCardEntryArray(t.raw('ensembleReranker.cards')),
      icons: [GitBranch, SlidersHorizontal, Scale],
    },
    {
      id: 'orchestration',
      eyebrow: t('orchestration.eyebrow'),
      heading: t('orchestration.heading'),
      body: t('orchestration.body'),
      cards: isCardEntryArray(t.raw('orchestration.cards')),
      icons: [BrainCircuit, MessageSquare, History],
    },
    {
      id: 'frontend-shell',
      eyebrow: t('frontendShell.eyebrow'),
      heading: t('frontendShell.heading'),
      body: t('frontendShell.body'),
      cards: isCardEntryArray(t.raw('frontendShell.cards')),
      icons: [Monitor, Languages, Activity],
    },
  ];

  return (
    <main className="min-h-screen bg-[#f9f9ff] text-[#002f49]">
      <section id="architecture-hero" className="relative overflow-hidden px-4 py-14 sm:px-6 sm:py-16 lg:px-8">
        <div className="absolute left-1/2 top-[-220px] h-[420px] w-[820px] -translate-x-1/2 rounded-full bg-[#005d90]/10 blur-3xl" />
        <div className="relative mx-auto max-w-6xl">
          <div className="mx-auto max-w-3xl text-center">
            <p className="inline-flex rounded-full border bg-white px-4 py-2 text-xs font-black uppercase tracking-[0.24em] text-[#005d90]" style={{ borderColor: borderGray }}>
              {isVietnamese ? 'Kiến trúc hệ thống' : 'System architecture'}
            </p>
            <h1 className="mt-7 text-4xl font-black tracking-[-0.055em] text-[#002f49] sm:text-5xl">
              {isVietnamese ? 'Trợ lý AI đa agent cho du lịch Hàm Ninh' : 'Multi-agent AI assistant for Ham Ninh travel'}
            </h1>
            <p className="mx-auto mt-6 max-w-2xl text-sm leading-7 text-[#577487] sm:text-base">
              {isVietnamese
                ? 'Kiến trúc kết hợp RAG, Maps API, điều phối LangGraph và streaming để trả lời câu hỏi du lịch có nguồn tham khảo, vị trí realtime và gợi ý công bằng.'
                : 'A system combining RAG, Maps API, LangGraph orchestration, and streaming responses for grounded travel answers, realtime places, and fair recommendations.'}
            </p>
          </div>

          <section id="architecture-flow" className="mx-auto mt-10 max-w-5xl">
            <div className="text-center">
              <p className="text-xs font-black uppercase tracking-[0.26em] text-[#0075b4]">
                {isVietnamese ? 'Luồng dữ liệu' : 'Data flow'}
              </p>
              <h2 className="mt-3 text-3xl font-black tracking-[-0.04em] text-[#002f49] sm:text-[2.5rem]">
                {isVietnamese ? 'Kiến trúc luồng dữ liệu hệ thống' : 'System data-flow architecture'}
              </h2>
            </div>
            <FlowDiagram nodes={flowNodes} />
          </section>
        </div>
      </section>

      {sections.map((section) => (
        <ArchitectureSection key={section.id} section={section} />
      ))}

      <footer className="border-t bg-white/70 py-10 text-center text-xs text-[#577487]" style={{ borderColor: borderGray }}>
        <p className="font-semibold text-[#003653]">Ham Ninh Guide AI Architecture</p>
        <p className="mt-2">Next.js 16 · FastAPI · LangGraph · Qdrant · Goong Maps Platform</p>
      </footer>
    </main>
  );
}
