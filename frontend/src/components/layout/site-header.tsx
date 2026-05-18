import { getTranslations } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { cn } from '@/lib/utils';
import { LocaleSwitcher } from './locale-switcher';

type SiteHeaderProps = {
  locale: string;
  className?: string;
};

const navItems = [
  { href: '/', translationKey: 'home' as const },
  { href: '/chat', translationKey: 'chat' as const },
  { href: '/map', translationKey: 'map' as const },
  { href: '/architecture', translationKey: 'architecture' as const },
] as const;

export async function SiteHeader({ locale, className }: SiteHeaderProps) {
  const t = await getTranslations('Navigation');

  return (
    <header
      className={cn(
        'sticky top-0 z-50 w-full border-b border-gray-200 bg-white/80 backdrop-blur-md dark:border-gray-700 dark:bg-gray-900/80',
        className
      )}
      role="banner"
    >
      <nav
        className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8"
        aria-label={t('localeLabel')}
      >
        {/* Logo / Brand */}
        <Link
          href="/"
          className="flex shrink-0 items-center text-lg font-semibold text-gray-900 transition-colors hover:text-blue-600 dark:text-gray-100 dark:hover:text-blue-400"
        >
          Hàm Ninh AI
        </Link>

        {/* Desktop navigation links */}
        <ul className="hidden items-center gap-6 md:flex">
          {navItems.map(({ href, translationKey }) => (
            <li key={href}>
              <Link
                href={href}
                className="text-sm font-medium text-gray-600 transition-colors hover:text-blue-600 dark:text-gray-300 dark:hover:text-blue-400"
              >
                {t(translationKey)}
              </Link>
            </li>
          ))}
        </ul>

        {/* Locale switcher */}
        <LocaleSwitcher />
      </nav>
    </header>
  );
}
