import { getTranslations, setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { Badge } from '@/components/ui/badge';
import { routing } from '@/i18n/routing';
import { InteractiveArchitecture } from '@/components/architecture/interactive-architecture';

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

export default async function ArchitecturePage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);

  const t = await getTranslations('Architecture');

  return (
    <div className="min-h-screen bg-background text-foreground py-16 sm:py-24">
      <div className="mx-auto w-full max-w-7xl px-6 lg:px-8">
        {/* Header Section */}
        <div className="mx-auto max-w-3xl text-center mb-12 space-y-4">
          <Badge variant="outline" className="border-primary/30 bg-primary/5 text-primary px-3 py-1 text-xs font-semibold rounded-full">
            {t('title')}
          </Badge>
          <h1 className="text-4xl font-extrabold tracking-tight text-foreground sm:text-5xl">
            {locale === 'vi' ? 'Kiến trúc Hệ thống AI Trợ lý Hàm Ninh' : 'System Architecture of Ham Ninh AI Assistant'}
          </h1>
          <p className="text-base sm:text-lg text-muted-foreground leading-relaxed">
            {locale === 'vi' 
              ? 'Sơ đồ chi tiết và trình mô phỏng các giải pháp công nghệ: Multi-Agent AI (LangGraph), RAG (Qdrant), và Ensemble Re-ranking.'
              : 'Detailed diagrams and simulators of core technology solutions: Multi-Agent AI (LangGraph), RAG (Qdrant), and Ensemble Re-ranking.'}
          </p>
        </div>

        {/* Interactive Architecture Component */}
        <div className="mt-8 border border-border/40 rounded-3xl bg-card/25 backdrop-blur-xs p-6 md:p-8 shadow-xs">
          <InteractiveArchitecture locale={locale} />
        </div>
      </div>

      {/* Footer */}
      <footer className="mt-24 border-t border-border/40 py-12">
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
