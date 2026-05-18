import { getTranslations, setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { routing } from '@/i18n/routing';
import PlaceholderPage from '@/components/placeholder/placeholder-page';

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

export default async function ChatPage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);
  const t = await getTranslations('Chat');
  const p = await getTranslations('Placeholder');
  return <PlaceholderPage title={t('title')} description={p('chatDescription')} comingSoonLabel={p('comingSoon')} statusUnderConstruction={p('statusUnderConstruction')} backToLandingLabel={p('backToLanding')} />;
}
