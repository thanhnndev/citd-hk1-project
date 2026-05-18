import { defineRouting } from 'next-intl/routing';
import { createNavigation } from 'next-intl/navigation';

export const routing = defineRouting({
  locales: ['vi', 'en'],
  defaultLocale: 'vi',
  localePrefix: 'always'
});

// Lightweight wrappers around next/link and next/navigation
// that automatically handle the current locale
export const { Link, redirect, usePathname, useRouter, getPathname } =
  createNavigation(routing);
