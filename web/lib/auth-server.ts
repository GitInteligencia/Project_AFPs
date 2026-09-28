import 'server-only';
import { getApps, initializeApp, applicationDefault, type App } from 'firebase-admin/app';
import { getAuth, type DecodedIdToken } from 'firebase-admin/auth';

// Identity Platform (GCIP) auth for the dashboard — replaces Supabase Auth.
//
// Flow: the login server action posts email+password to the Identity Toolkit
// REST API (public API key, same as a browser SDK would), exchanges the
// returned ID token for a long-lived *session cookie* minted by firebase-admin,
// and stores it as `__session` (httpOnly). proxy.ts verifies that cookie on
// every navigation. No self-service sign-up: users are created in the
// Identity Platform console.
//
// firebase-admin is initialized lazily with Application Default Credentials
// (Cloud Run service account / `gcloud auth application-default login`), so
// importing this module never touches credentials — `next build` runs with no
// GCP env at all.

export const SESSION_COOKIE = '__session';

const PROJECT_ID = process.env.GCP_PROJECT_ID ?? 'pat-uat-global';
const SESSION_HOURS = Number(process.env.IDP_SESSION_HOURS) || 12;
// firebase-admin caps session cookies at 14 days and floors them at 5 minutes.
export const SESSION_MAX_AGE_S = Math.min(
  Math.max(SESSION_HOURS * 3600, 5 * 60),
  14 * 24 * 3600,
);

let app: App | null = null;

function getAdminApp(): App {
  if (app) return app;
  const existing = getApps()[0];
  app =
    existing ??
    initializeApp({ credential: applicationDefault(), projectId: PROJECT_ID });
  return app;
}

function adminAuth() {
  return getAuth(getAdminApp());
}

export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AuthError';
  }
}

// Identity Toolkit error codes → short user-facing messages (shown verbatim by
// /login?error=…). Anything unknown collapses to a generic message so we don't
// leak backend details.
const ERROR_MESSAGES: Record<string, string> = {
  INVALID_LOGIN_CREDENTIALS: 'Invalid login credentials',
  INVALID_PASSWORD: 'Invalid login credentials',
  EMAIL_NOT_FOUND: 'Invalid login credentials',
  INVALID_EMAIL: 'Invalid login credentials',
  MISSING_PASSWORD: 'Invalid login credentials',
  USER_DISABLED: 'This account has been disabled',
  TOO_MANY_ATTEMPTS_TRY_LATER: 'Too many attempts. Try again later',
};

function mapIdpError(code: string | undefined): string {
  // Codes can carry a suffix, e.g. "TOO_MANY_ATTEMPTS_TRY_LATER : Access to this account…"
  const key = (code ?? '').split(/[\s:]/)[0];
  return ERROR_MESSAGES[key] ?? 'Sign-in failed. Please try again';
}

export type SignInResult = {
  idToken: string;
  refreshToken: string;
  localId: string;
  email: string;
};

/**
 * Email + password sign-in against Identity Platform (REST). Throws AuthError
 * with a short, user-safe message on failure.
 */
export async function signInWithEmailPassword(
  email: string,
  password: string,
): Promise<SignInResult> {
  const apiKey = process.env.NEXT_PUBLIC_IDP_API_KEY;
  if (!apiKey) {
    throw new AuthError('Authentication is not configured (NEXT_PUBLIC_IDP_API_KEY)');
  }
  if (!email || !password) {
    throw new AuthError('Invalid login credentials');
  }

  let res: Response;
  try {
    res = await fetch(
      `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${encodeURIComponent(apiKey)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password, returnSecureToken: true }),
        cache: 'no-store',
      },
    );
  } catch {
    throw new AuthError('Authentication service unavailable');
  }

  const body = (await res.json().catch(() => ({}))) as {
    idToken?: string;
    refreshToken?: string;
    localId?: string;
    email?: string;
    error?: { message?: string };
  };

  if (!res.ok || !body.idToken) {
    throw new AuthError(mapIdpError(body.error?.message));
  }
  return {
    idToken: body.idToken,
    refreshToken: body.refreshToken ?? '',
    localId: body.localId ?? '',
    email: body.email ?? email,
  };
}

/** Exchange a fresh ID token for a session cookie valid SESSION_MAX_AGE_S seconds. */
export async function createSessionCookie(idToken: string): Promise<string> {
  return adminAuth().createSessionCookie(idToken, {
    expiresIn: SESSION_MAX_AGE_S * 1000,
  });
}

/**
 * Verify a session cookie. Returns the decoded claims, or null when the cookie
 * is missing, malformed, expired or (with checkRevoked) revoked. Never throws.
 */
export async function verifySessionCookie(
  cookie: string | undefined | null,
  checkRevoked = false,
): Promise<DecodedIdToken | null> {
  if (!cookie) return null;
  try {
    return await adminAuth().verifySessionCookie(cookie, checkRevoked);
  } catch {
    return null;
  }
}

/**
 * Revoke the refresh tokens behind a session cookie so it can't be reused
 * (checkRevoked verifications fail from now on). Best-effort: an invalid or
 * already-expired cookie is a no-op.
 */
export async function revokeSession(cookie: string | undefined | null): Promise<void> {
  const decoded = await verifySessionCookie(cookie, false);
  if (!decoded) return;
  try {
    await adminAuth().revokeRefreshTokens(decoded.sub);
  } catch {
    // Logout must succeed even if the revoke call fails (network, IAM).
  }
}
