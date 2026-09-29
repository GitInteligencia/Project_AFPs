import { createHash, timingSafeEqual } from 'node:crypto';
import { NextResponse, type NextRequest } from 'next/server';
import { revalidatePath, revalidateTag } from 'next/cache';
import { BQ_CACHE_TAG } from '@/lib/db';

// POST /api/revalidate — called by the sync job (Cloud Run Job) after a data
// load so the web serves fresh BigQuery results immediately instead of after
// the 300 s data TTL. Protected by a shared secret in `x-revalidate-token`.
// proxy.ts excludes /api/ from the auth matcher, so no session is needed.

export const runtime = 'nodejs';

const HEADER = 'x-revalidate-token';

// Constant-time comparison: hash both sides so lengths always match.
function tokensMatch(provided: string, expected: string): boolean {
  const a = createHash('sha256').update(provided).digest();
  const b = createHash('sha256').update(expected).digest();
  return timingSafeEqual(a, b);
}

export async function POST(request: NextRequest) {
  const expected = process.env.REVALIDATE_TOKEN;
  if (!expected) {
    return NextResponse.json(
      { ok: false, error: 'REVALIDATE_TOKEN is not configured on the server' },
      { status: 503 },
    );
  }

  const provided = request.headers.get(HEADER);
  if (!provided || !tokensMatch(provided, expected)) {
    return NextResponse.json({ ok: false, error: 'Unauthorized' }, { status: 401 });
  }

  // { expire: 0 } = purge now (the pre-Next-16 single-argument semantics);
  // the next render re-queries BigQuery instead of serving stale rows.
  revalidateTag(BQ_CACHE_TAG, { expire: 0 });
  revalidatePath('/', 'layout');

  return NextResponse.json({ ok: true, revalidated_at: new Date().toISOString() });
}
