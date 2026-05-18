import { getTranslations, setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { routing } from '@/i18n/routing';
import { ChatInterface } from '@/components/chat/chat-interface';

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

export default async function ChatPage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);

  const t = await getTranslations('Chat');

  const translations = {
    title: t('title'),
    placeholder: t('placeholder'),
    send: t('send'),
    typing: t('typing'),
    error: t('error'),
    retry: t('retry'),
    citations: t('citations'),
    noEvidence: t('noEvidence'),
    newQuestion: t('newQuestion'),
  };

  return <ChatInterface locale={locale} translations={translations} />;
}
