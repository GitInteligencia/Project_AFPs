import { NextResponse, type NextRequest } from 'next/server';
import { SESSION_COOKIE, verifySessionCookie } from '@/lib/auth-server';

// verifySessionCookie() validates the Identity Platform session cookie
// signature against Google's public keys (fetched once and cached by
// firebase-admin), so it's cheap — but we still cache the verdict per cookie
// value for a short TTL so a signed-in user navigating between tabs/modules
// does no crypto work at all. A changed cookie (login/logout) is a different
// key, so it never serves a stale identity, and the TTL bounds revocation lag
// to 60s (same behaviour as the previous Supabase-based proxy).
const AUTH_CACHE_TTL_MS = 60_000;
const authCache = new Map<string, { ok: boolean; exp: number }>();

export async function proxy(request: NextRequest) {
  const response = NextResponse.next({ request });

  const { pathname } = request.nextUrl;
  const isLoginRoute = pathname === '/login';

  const cookieValue = request.cookies.get(SESSION_COOKIE)?.value ?? null;

  let ok = false;
  if (cookieValue) {
    const hit = authCache.get(cookieValue);
    if (hit && hit.exp > Date.now()) {
      ok = hit.ok;
    } else {
      ok = (await verifySessionCookie(cookieValue)) !== null;
      // Opportunistic cleanup so the map doesn't grow unbounded.
      if (authCache.size > 500) authCache.clear();
      authCache.set(cookieValue, { ok, exp: Date.now() + AUTH_CACHE_TTL_MS });
    }
  }

  if (!ok && !isLoginRoute) {
    const url = request.nextUrl.clone();
    url.pathname = '/login';
    url.searchParams.set('redirect', pathname);
    return NextResponse.redirect(url);
  }

  if (ok && isLoginRoute) {
    const url = request.nextUrl.clone();
    url.pathname = '/';
    return NextResponse.redirect(url);
  }

  return response;
}

export const config = {
  matcher: [
    // Match everything except API routes (/api/revalidate is token-protected
    // and called by the sync job without a session), static assets and
    // Next.js internals.
    '/((?!api/|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
  ],
};
