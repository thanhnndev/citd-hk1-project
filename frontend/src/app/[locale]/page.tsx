import { getTranslations, setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { routing } from '@/i18n/routing';

type LocalePageProps = Readonly<{
  params: Promise<{ locale: string }>;
}>;

export default async function LocalePage({ params }: LocalePageProps) {
  const { locale } = await params;

  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) {
    notFound();
  }

  setRequestLocale(locale);
  const t = await getTranslations('Landing');

  return (
    <main className="min-h-screen bg-background text-foreground">
      <section id="hero" className="mx-auto flex min-h-screen max-w-5xl flex-col justify-center px-6 py-24">
        <p className="mb-4 text-sm font-semibold uppercase tracking-[0.3em] text-primary">
          Ham Ninh AI Guide
        </p>
        <h1 className="max-w-4xl text-4xl font-bold tracking-tight text-foreground sm:text-6xl">
          {t('hero.title')}
        </h1>
        <p className="mt-6 max-w-2xl text-lg leading-8 text-muted-foreground">
          {t('hero.description')}
        </p>
        <div className="mt-10 flex flex-col gap-3 sm:flex-row">
          <a
            className="rounded-lg bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground shadow-sm transition hover:bg-primary/90"
            href="#problem"
          >
            {t('hero.ctaExplore')}
          </a>
          <a
            className="rounded-lg border border-border bg-card px-5 py-3 text-sm font-semibold text-card-foreground shadow-sm transition hover:bg-muted"
            href="#architecture"
          >
            {t('hero.ctaArchitecture')}
          </a>
        </div>
      </section>
    </main>
  );
}
