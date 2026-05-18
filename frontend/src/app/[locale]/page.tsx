import { getTranslations, setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';

import { AlgorithmShowcase } from '@/components/landing/algorithm-showcase';
import { DemoCtaSection } from '@/components/landing/demo-cta-section';
import { HeroSection } from '@/components/landing/hero-section';
import { ProblemSection } from '@/components/landing/problem-section';
import { ResponsibleAiSection } from '@/components/landing/responsible-ai-section';
import { SolutionSection } from '@/components/landing/solution-section';
import { TechStackSection } from '@/components/landing/tech-stack-section';
import { routing } from '@/i18n/routing';

type LocalePageProps = Readonly<{
  params: Promise<{ locale: string }>;
}>;

type TrustBadge = Readonly<{ label: string; description: string }>;
type ProblemCard = Readonly<{ title: string; description: string; metric: string }>;
type SolutionPillar = Readonly<{ title: string; description: string }>;
type ResponsibleAxis = Readonly<{ id: string; title: string; description: string; metric: string }>;
type AlgorithmBar = Readonly<{ key: string; label: string; value: number; description: string }>;
type AlgorithmStep = Readonly<{ title: string; description: string }>;
type TechStackItem = Readonly<{ name: string; description: string }>;
type DemoItem = Readonly<{ title: string; description: string }>;

export default async function LocalePage({ params }: LocalePageProps) {
  const { locale } = await params;

  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) {
    notFound();
  }

  setRequestLocale(locale);
  const t = await getTranslations('Landing');

  const trustBadges = t.raw('hero.trustBadges') as TrustBadge[];
  const problemCards = t.raw('problem.cards') as ProblemCard[];
  const solutionPillars = t.raw('solution.pillars') as SolutionPillar[];
  const responsibleAxes = t.raw('responsibleAI.axes') as ResponsibleAxis[];
  const algorithmChart = t.raw('algorithmShowcase.chart') as Readonly<{
    title: string;
    ariaLabel: string;
    description: string;
    bars: AlgorithmBar[];
  }>;
  const algorithmSteps = t.raw('algorithmShowcase.steps') as AlgorithmStep[];
  const techStackItems = t.raw('techStack.items') as TechStackItem[];
  const demoItems = t.raw('demo.items') as DemoItem[];

  return (
    <div className="min-h-screen bg-background text-foreground">
      <HeroSection
        eyebrow={t('hero.eyebrow')}
        title={t('hero.title')}
        description={t('hero.description')}
        ctaExplore={t('hero.ctaExplore')}
        ctaArchitecture={t('hero.ctaArchitecture')}
        trustBadges={trustBadges}
      />
      <ProblemSection
        eyebrow={t('problem.eyebrow')}
        heading={t('problem.heading')}
        body={t('problem.body')}
        cards={problemCards}
      />
      <SolutionSection
        eyebrow={t('solution.eyebrow')}
        heading={t('solution.heading')}
        body={t('solution.body')}
        pillars={solutionPillars}
      />
      <ResponsibleAiSection
        eyebrow={t('responsibleAI.eyebrow')}
        heading={t('responsibleAI.heading')}
        body={t('responsibleAI.body')}
        axes={responsibleAxes}
      />
      <AlgorithmShowcase
        eyebrow={t('algorithmShowcase.eyebrow')}
        heading={t('algorithmShowcase.heading')}
        body={t('algorithmShowcase.body')}
        chart={algorithmChart}
        steps={algorithmSteps}
      />
      <TechStackSection
        eyebrow={t('techStack.eyebrow')}
        heading={t('techStack.heading')}
        body={t('techStack.body')}
        items={techStackItems}
      />
      <DemoCtaSection
        locale={locale}
        eyebrow={t('demo.eyebrow')}
        heading={t('demo.heading')}
        body={t('demo.body')}
        primaryCta={t('demo.primaryCta')}
        secondaryCta={t('demo.secondaryCta')}
        note={t('demo.note')}
        items={demoItems}
      />
    </div>
  );
}
