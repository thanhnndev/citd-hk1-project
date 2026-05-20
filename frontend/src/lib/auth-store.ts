/**
 * Auth token store — persists JWT in localStorage.
 * Safe to import in both client and server components
 * (server-side calls are no-ops since localStorage is unavailable).
 */

const TOKEN_KEY = "ham_ninh_token";
const USER_KEY = "ham_ninh_user";
export const AUTH_CHANGED_EVENT = "ham-ninh-auth-changed";

export interface StoredUser {
  id: string;
  username: string;
  email: string;
  is_verified: boolean;
}

function isClient(): boolean {
  return typeof window !== "undefined";
}

function notifyAuthChanged(): void {
  if (!isClient()) return;
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
}

export function saveToken(token: string): void {
  if (!isClient()) return;
  localStorage.setItem(TOKEN_KEY, token);
  notifyAuthChanged();
}

export function getToken(): string | null {
  if (!isClient()) return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function saveUser(user: StoredUser): void {
  if (!isClient()) return;
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  notifyAuthChanged();
}

export function getUser(): StoredUser | null {
  if (!isClient()) return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredUser;
  } catch {
    return null;
  }
}

export function logout(): void {
  if (!isClient()) return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  notifyAuthChanged();
}

export function isLoggedIn(): boolean {
  return getToken() !== null;
}
