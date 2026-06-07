import { getTranslations } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { cn } from '@/lib/utils';
import { LocaleSwitcher } from './locale-switcher';
import { AuthNav } from './auth-nav';
import { HeaderNavigation } from './header-navigation';

type SiteHeaderProps = {
  locale: string;
  className?: string;
};

export async function SiteHeader({ locale, className }: SiteHeaderProps) {
  const t = await getTranslations('Navigation');
  const navItems = [
    { href: '/' as const, label: t('home') },
    { href: '/chat' as const, label: t('chat') },
    { href: '/map' as const, label: t('map') },
    { href: '/architecture' as const, label: t('architecture') },
  ];

  return (
    <header
      className={cn(
        'sticky top-0 z-50 h-16 w-full border-b border-[#e5e7eb] bg-white/95 backdrop-blur-sm',
        className
      )}
      role="banner"
    >
      <nav
        className="mx-auto grid h-16 max-w-7xl grid-cols-[1fr_auto] items-center px-4 sm:px-6 md:grid-cols-[1fr_auto_1fr] lg:px-8"
        aria-label={t('localeLabel')}
      >
        <Link
          href="/"
          className="flex w-fit shrink-0 items-center gap-2.5"
        >
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-[#087fb9] text-white">
            <svg
              data-testid="ham-ninh-logo"
              viewBox="0 0 64 64"
              className="h-8 w-8"
              fill="none"
              aria-hidden="true"
            >
              <path d="M32 10v14" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" />
              <path d="M19 43 32 18l13 25H19Z" fill="currentColor" />
              <circle cx="32" cy="33" r="4.5" fill="#087fb9" />
              <path d="M11 33H5m54 0h-6" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" />
              <path d="M17 47c5-3 10-3 15 0s10 3 15 0v8c-5 3-10 3-15 0s-10-3-15 0v-8Z" fill="currentColor" />
            </svg>
          </span>
          <span className="hidden text-sm font-bold tracking-tight text-[#005d90] sm:inline">
            Hàm Ninh AI
          </span>
        </Link>

        <HeaderNavigation items={navItems} />

        <div className="flex items-center justify-end gap-2 sm:gap-3">
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
