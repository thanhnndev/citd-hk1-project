import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin();

const nextConfig = {
  devIndicators: false as const,
  // Next.js 16 config — Turbopack is default bundler
  // Cache Components for static marketing and architecture sections.
};

export default withNextIntl(nextConfig);
