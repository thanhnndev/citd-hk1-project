import { getTranslations, setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import {
  ArrowRight,
  BookOpen,
  Database,
  Search,
  MapPin,
  Route,
  ShieldAlert,
  GitBranch,
  SlidersHorizontal,
  Scale,
  BrainCircuit,
  MessageSquare,
  History,
  Monitor,
  Languages,
  Activity,
} from 'lucide-react';

import { SectionShell } from '@/components/landing/section-shell';
import { Badge } from '@/components/ui/badge';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { routing } from '@/i18n/routing';

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

type SectionData = Readonly<{
  eyebrow: string;
  heading: string;
  body: string;
  cards: ReadonlyArray<Readonly<{ title: string; description: string }>>;
}>;

type CardEntry = Readonly<{ title: string; description: string }>;

const iconMap: Record<string, React.ElementType> = {
  ArrowRight,
  BookOpen,
  Database,
  Search,
  MapPin,
  Route,
  ShieldAlert,
  GitBranch,
  SlidersHorizontal,
  Scale,
  BrainCircuit,
  MessageSquare,
  History,
  Monitor,
  Languages,
  Activity,
};

function CardGrid({ cards, icons }: { cards: CardEntry[]; icons: string[] }) {
  return (
    <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
      {cards.map((card, i) => {
        const Icon = iconMap[icons[i] ?? 'ArrowRight'];
        return (
          <Card key={card.title} className="relative transition-all duration-300 hover:-translate-y-1 hover:shadow-lg">
            <CardHeader>
              <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary group-hover:scale-110 transition-transform">
                <Icon className="h-5 w-5" />
              </div>
              <CardTitle>{card.title}</CardTitle>
              <CardDescription>{card.description}</CardDescription>
            </CardHeader>
          </Card>
        );
      })}
    </div>
  );
}

export default async function ArchitecturePage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);

  const t = await getTranslations('Architecture');

  const overview = t.raw('overview') as SectionData;
  const ragPipeline = t.raw('ragPipeline') as SectionData;
  const mapsApi = t.raw('mapsApi') as SectionData;
  const ensembleReranker = t.raw('ensembleReranker') as SectionData;
  const orchestration = t.raw('orchestration') as SectionData;
  const frontendShell = t.raw('frontendShell') as SectionData;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <SectionShell
        id="overview"
        eyebrow={overview.eyebrow}
        heading={overview.heading}
        body={overview.body}
      >
        <CardGrid
          cards={overview.cards as CardEntry[]}
          icons={['ArrowRight']}
        />
      </SectionShell>

      <SectionShell
        id="rag-pipeline"
        eyebrow={ragPipeline.eyebrow}
        heading={ragPipeline.heading}
        body={ragPipeline.body}
      >
        <CardGrid
          cards={ragPipeline.cards as CardEntry[]}
          icons={['Database', 'Search', 'BookOpen']}
        />
      </SectionShell>

      <SectionShell
        id="maps-api"
        eyebrow={mapsApi.eyebrow}
        heading={mapsApi.heading}
        body={mapsApi.body}
      >
        <CardGrid
          cards={mapsApi.cards as CardEntry[]}
          icons={['MapPin', 'Route', 'ShieldAlert']}
        />
      </SectionShell>

      <SectionShell
        id="ensemble-reranker"
        eyebrow={ensembleReranker.eyebrow}
        heading={ensembleReranker.heading}
        body={ensembleReranker.body}
      >
        <CardGrid
          cards={ensembleReranker.cards as CardEntry[]}
          icons={['GitBranch', 'SlidersHorizontal', 'Scale']}
        />
      </SectionShell>

      <SectionShell
        id="orchestration"
        eyebrow={orchestration.eyebrow}
        heading={orchestration.heading}
        body={orchestration.body}
      >
        <CardGrid
          cards={orchestration.cards as CardEntry[]}
          icons={['BrainCircuit', 'MessageSquare', 'History']}
        />
      </SectionShell>

      <SectionShell
        id="frontend-shell"
        eyebrow={frontendShell.eyebrow}
        heading={frontendShell.heading}
        body={frontendShell.body}
      >
        <CardGrid
          cards={frontendShell.cards as CardEntry[]}
          icons={['Monitor', 'Languages', 'Activity']}
        />
      </SectionShell>

      <footer className="border-t border-border/40 py-12">
        <div className="mx-auto max-w-6xl px-6 text-center text-sm text-muted-foreground">
          <Badge variant="outline" className="mb-4 border-primary/30 bg-primary/5 text-primary">
            {t('title')}
          </Badge>
          <p>Built with Next.js 16, FastAPI, LangGraph, Qdrant, and Goong Maps Platform.</p>
        </div>
      </footer>
    </div>
  );
}
