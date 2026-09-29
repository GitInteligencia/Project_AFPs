'use server';

import { redirect } from 'next/navigation';
import { revalidatePath } from 'next/cache';
import { cookies } from 'next/headers';
import {
  AuthError,
  SESSION_COOKIE,
  SESSION_MAX_AGE_S,
  createSessionCookie,
  revokeSession,
  signInWithEmailPassword,
} from '@/lib/auth-server';

const COOKIE_OPTIONS = {
  httpOnly: true,
  // Browsers accept Secure cookies on http://localhost, but not on other
  // plain-http hosts; relax only outside production so `next dev` keeps working.
  secure: process.env.NODE_ENV === 'production',
  sameSite: 'lax' as const,
  path: '/',
};

export async function login(formData: FormData) {
  const email = String(formData.get('email') ?? '').trim();
  const password = String(formData.get('password') ?? '');
  const redirectTo = String(formData.get('redirect') ?? '/');

  let sessionCookie: string;
  try {
    const { idToken } = await signInWithEmailPassword(email, password);
    sessionCookie = await createSessionCookie(idToken);
  } catch (err) {
    const message =
      err instanceof AuthError ? err.message : 'Sign-in failed. Please try again';
    redirect(`/login?error=${encodeURIComponent(message)}`);
  }

  const store = await cookies();
  store.set(SESSION_COOKIE, sessionCookie, {
    ...COOKIE_OPTIONS,
    maxAge: SESSION_MAX_AGE_S,
  });

  revalidatePath('/', 'layout');
  redirect(redirectTo);
}

export async function logout() {
  const store = await cookies();
  const current = store.get(SESSION_COOKIE)?.value;
  await revokeSession(current);
  store.set(SESSION_COOKIE, '', { ...COOKIE_OPTIONS, maxAge: 0 });
  revalidatePath('/', 'layout');
  redirect('/login');
}
