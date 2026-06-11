/**
 * Typed API client for /api/auth/* proxy routes.
 */

/* ── Request shapes ─────────────────────────────────────────── */

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface VerifyEmailRequest {
  email: string;
  otp: string;
}

export interface ResendOtpRequest {
  email: string;
}

/* ── Response shapes ────────────────────────────────────────── */

export interface UserResponse {
  id: string;
  username: string;
  email: string;
  is_active: boolean;
  is_verified: boolean;
  is_admin: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface AuthError {
  detail: string;
}

/* ── Helpers ────────────────────────────────────────────────── */

async function authFetch<T>(
  path: string,
  options: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });

  const data = await res.json().catch(() => null);

  if (!res.ok) {
    const message =
      (data as AuthError | null)?.detail ??
      `Request failed (${res.status})`;
    throw new Error(message);
  }

  return data as T;
}

/* ── Public API ─────────────────────────────────────────────── */

export async function register(body: RegisterRequest): Promise<UserResponse> {
  return authFetch<UserResponse>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function login(body: LoginRequest): Promise<TokenResponse> {
  return authFetch<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function verifyEmail(body: VerifyEmailRequest): Promise<{ message: string; verified: boolean }> {
  return authFetch("/api/auth/verify-email", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function resendOtp(body: ResendOtpRequest): Promise<{ message: string }> {
  return authFetch("/api/auth/resend-otp", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getMe(token: string): Promise<UserResponse> {
  return authFetch<UserResponse>("/api/auth/me", {
    method: "GET",
    headers: { Authorization: `Bearer ${token}` },
  });
}
