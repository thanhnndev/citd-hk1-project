import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin();

const nextConfig = {
  // Next.js 16 config — Turbopack is default bundler
  // Cache Components for static sections (HeroSection, AlgorithmShowcase, etc.)
};

export default withNextIntl(nextConfig);
