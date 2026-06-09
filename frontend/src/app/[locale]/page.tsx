import { getTranslations, setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import {
  TourismHomepage,
  type TourismHomepageContent,
} from '@/components/landing/tourism-homepage';
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
  const content = t.raw('homepage') as TourismHomepageContent;

  return <TourismHomepage content={content} />;
}
