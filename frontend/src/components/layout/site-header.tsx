import { getTranslations } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { cn } from '@/lib/utils';
import { LocaleSwitcher } from './locale-switcher';
import { AuthNav } from './auth-nav';

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
        'sticky top-0 z-50 w-full border-b border-border/60 bg-background/80 backdrop-blur-md',
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
          className="flex shrink-0 items-center gap-2 group"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-700 text-white transition-transform duration-200 group-hover:-translate-y-0.5">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </div>
          <span className="text-base font-semibold text-teal-800 dark:text-teal-300">
            Hàm Ninh <span className="text-teal-600 dark:text-teal-400 font-bold">AI</span>
          </span>
        </Link>

        {/* Desktop navigation links */}
        <ul className="hidden items-center gap-2 md:flex">
          {navItems.map(({ href, translationKey }) => (
            <li key={href}>
              <Link
                href={href}
                className="block px-5 py-2 text-sm font-medium text-gray-600 rounded-lg border border-transparent transition-all duration-200 hover:border-gray-200 hover:shadow-md hover:-translate-y-0.5 dark:text-gray-300 dark:hover:border-gray-600"
              >
                {t(translationKey)}
              </Link>
            </li>
          ))}
        </ul>

        {/* Right side: locale switcher + auth */}
        <div className="flex items-center gap-3">
          <LocaleSwitcher />
          <AuthNav
            locale={locale}
            translations={{
              login: t('login'),
              register: t('register'),
              logout: t('logout'),
            }}
          />
        </div>
      </nav>
    </header>
  );
}
