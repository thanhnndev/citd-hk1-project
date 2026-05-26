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
import PlaceholderPage from '@/components/placeholder/placeholder-page';
import { SiteFooter } from '@/components/layout/site-footer';

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
  const p = await getTranslations('Placeholder');
  return (
  <>
    <PlaceholderPage
      title={t('title')}
      description={p('architectureDescription')}
      comingSoonLabel={p('comingSoon')}
      statusUnderConstruction={p('statusUnderConstruction')}
      backToLandingLabel={p('backToLanding')}
    />
    <SiteFooter locale={locale} />
  </>
);
}
