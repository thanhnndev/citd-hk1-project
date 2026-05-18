import createMiddleware from 'next-intl/middleware';
import type { NextRequest } from 'next/server';
import { routing } from './i18n/routing';

// Next.js 16: proxy.ts replaces middleware.ts as the network boundary file
// Runtime is 'nodejs' (Edge runtime not supported for proxy.ts)
const intlMiddleware = createMiddleware(routing);

export default async function proxy(request: NextRequest) {
  // Skip i18n middleware for /api routes, /_next, and static files
  const url = new URL(request.url);
  const isApiRoute = url.pathname.startsWith('/api');
  const isNextAsset = url.pathname.startsWith('/_next');
  const isStaticFile = url.pathname.match(/\.(ico|png|jpg|jpeg|gif|svg|css|js|woff2?)$/i);

  if (isApiRoute || isNextAsset || isStaticFile) {
    // For API routes: proxy to backend service if needed
    // Backend runs on host port from compose.yaml (default 48721)
    return new Response(null, { status: 404 });
  }

  return intlMiddleware(request);
}

export const config = {
  // Matcher excludes API routes, Next.js internals, and static files
  matcher: ['/((?!api|_next|.*\\..*).*)']
};
