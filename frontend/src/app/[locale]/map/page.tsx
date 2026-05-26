import { getTranslations, setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';

import { PlaceProofMap } from '@/components/map/place-proof-map';
import { routing } from '@/i18n/routing';

import { SiteFooter } from '@/components/layout/site-footer';

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

export default async function MapPage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);

  const t = await getTranslations('Map');
  const translations = {
    title: t('title'),
    intro: t('intro'),
    defaultQuery: t('defaultQuery'),
    queryLabel: t('queryLabel'),
    searchPlaceholder: t('searchPlaceholder'),
    submit: t('submit'),
    loading: t('loading'),
    error: t('error'),
    unavailable: t('unavailable'),
    noResults: t('noResults'),
    fallback: t('fallback'),
    resultCount: t('resultCount', { count: 0 }),
    detailTitle: t('detailTitle'),
    selectPlace: t('selectPlace'),
    pinReady: t('pinReady'),
    pinUnavailable: t('pinUnavailable'),
    mapsLink: t('mapsLink'),
    rating: t('rating'),
    reviews: t('reviews'),
    openNow: t('openNow'),
    closedNow: t('closedNow'),
    openUnknown: t('openUnknown'),
    businessStatus: t('businessStatus'),
    type: t('type'),
    accessibility: t('accessibility'),
    address: t('address'),
    coordinates: t('coordinates'),
    unknown: t('unknown'),
    responseNote: t('responseNote'),
  };

  return (
  <div lang={locale}>
    <PlaceProofMap locale={locale} translations={translations} />
    <SiteFooter locale={locale} />
  </div>
);
}
