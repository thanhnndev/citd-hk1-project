import { getTranslations } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { cn } from '@/lib/utils';

type SiteFooterProps = {
  locale: string;
  className?: string;
};

const navItems = [
  { href: '/', translationKey: 'home' as const },
  { href: '/chat', translationKey: 'chat' as const },
  { href: '/map', translationKey: 'map' as const },
  { href: '/architecture', translationKey: 'architecture' as const },
] as const;

export async function SiteFooter({ locale: _locale, className }: SiteFooterProps) {
  const t = await getTranslations('Navigation');
  const currentYear = new Date().getFullYear();

  return (
    <footer
      className={cn(
        'w-full border-t border-gray-200 bg-gray-900 text-gray-300 dark:border-gray-700 dark:bg-gray-950',
        className
      )}
      role="contentinfo"
    >
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {/* Navigation links */}
        <nav aria-label={t('localeLabel')} className="mb-6">
          <ul className="flex flex-wrap items-center justify-center gap-4 sm:gap-6">
            {navItems.map(({ href, translationKey }) => (
              <li key={href}>
                <Link
                  href={href}
                  className="text-sm font-medium text-gray-400 transition-colors hover:text-blue-400 dark:text-gray-500 dark:hover:text-blue-400"
                >
                  {t(translationKey)}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        {/* Tagline */}
        <p className="mb-4 text-center text-sm text-gray-500 dark:text-gray-600">
          {t('tagline')}
        </p>

        {/* Copyright */}
        <p className="text-center text-xs text-gray-600 dark:text-gray-700">
          {t('copyright', { year: currentYear })}
        </p>
      </div>
    </footer>
  );
}
