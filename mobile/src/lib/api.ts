import Constants from 'expo-constants';

import { getItem, removeItem, setItem } from './storage';
import type {
  Alerts, Bill, BillSummary, Device, Forecast, ForecastSummary, Me, Plan, PlanCatalog, PlanSettings, Session, Site, Subscription,
} from './types';

const TOKEN_KEY = 'auth_token';
const SERVER_KEY = 'api_url_override';

let token: string | null = null;
let serverOverride: string | null = null;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/** Order: URL typed in the app (Cont → Server) > EXPO_PUBLIC_API_URL > app.json extra.apiUrl > Android emulator host. */
export function baseUrl(): string {
  const fromEnv = process.env.EXPO_PUBLIC_API_URL;
  const fromConfig = (Constants.expoConfig?.extra as { apiUrl?: string } | undefined)?.apiUrl;
  const url = serverOverride || fromEnv || fromConfig || 'http://10.0.2.2:8000';
  return url.replace(/\/+$/, '');
}

export async function loadStored(): Promise<string | null> {
  serverOverride = await getItem(SERVER_KEY);
  token = await getItem(TOKEN_KEY);
  return token;
}

export async function setServer(url: string | null): Promise<void> {
  serverOverride = url ? url.trim().replace(/\/+$/, '') : null;
  if (serverOverride) await setItem(SERVER_KEY, serverOverride);
  else await removeItem(SERVER_KEY);
}

export async function setToken(t: string | null): Promise<void> {
  token = t;
  if (t) await setItem(TOKEN_KEY, t);
  else await removeItem(TOKEN_KEY);
}

function messageOf(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') {
    const d = detail as { message?: string; msg?: string } | { msg?: string }[];
    if (Array.isArray(d)) return d.map((x) => x.msg).filter(Boolean).join('; ') || `Eroare ${status}`;
    if (d.message) return d.message;
  }
  return `Eroare ${status}`;
}

async function request<T>(method: string, path: string, body?: unknown, timeoutMs = 60000): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body; // fetch sets the multipart boundary itself
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${baseUrl()}${path}`, { method, headers, body: payload, signal: ctrl.signal });
  } catch {
    throw new ApiError(0, `Serverul nu răspunde (${baseUrl()}). Verificați conexiunea sau adresa serverului din Cont.`);
  } finally {
    clearTimeout(timer);
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    throw new ApiError(res.status, messageOf((data as { detail?: unknown } | null)?.detail, res.status));
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export type UploadFile = { uri: string; name: string; type: string };

function form(file: UploadFile): FormData {
  const fd = new FormData();
  // React Native's FormData accepts {uri, name, type} file descriptors.
  fd.append('file', { uri: file.uri, name: file.name, type: file.type } as unknown as Blob);
  return fd;
}

export const api = {
  health: () => request<{ ok: boolean }>('GET', '/health', undefined, 15000),
  demo: () => request<Session>('POST', '/auth/demo'),
  login: (email: string, password: string) => request<Session>('POST', '/auth/login', { email, password }),
  register: (email: string, password: string) => request<Session>('POST', '/auth/register', { email, password }),
  me: () => request<Me>('GET', '/me'),
  saveSite: (site: Partial<Site>) => request<Me>('PUT', '/site', site),
  geocode: (q: string) =>
    request<{ name: string; admin?: string; lat: number; lon: number; elevation?: number }[]>(
      'GET', `/geocode?q=${encodeURIComponent(q)}`),

  uploadBill: (file: UploadFile) => request<Bill>('POST', '/bills', form(file), 120000),
  bills: () => request<BillSummary[]>('GET', '/bills'),
  bill: (id: number) => request<Bill>('GET', `/bills/${id}`),
  confirmBill: (id: number, lines: Partial<Bill['lines'][number]>[]) =>
    request<Bill>('POST', `/bills/${id}/confirm`, { lines }),
  recheckBill: (id: number, threshold_pct: number, carried_in_kwh?: number | null) =>
    request<Bill>('POST', `/bills/${id}/check`, { threshold_pct, carried_in_kwh }),
  deleteBill: (id: number) => request<{ deleted: number }>('DELETE', `/bills/${id}`),

  uploadReadings: (file: UploadFile) =>
    request<{ hours: number; format: string | null; report: { warnings: string[]; start: string; end: string } }>(
      'POST', '/readings', form(file), 180000),
  readingsSummary: () =>
    request<{ rows: number; start: string | null; end: string | null; has_load: boolean; has_export: boolean }>(
      'GET', '/readings/summary'),
  train: () => request<Record<string, Record<string, unknown>>>('POST', '/models/train', undefined, 180000),

  forecast: (force = false) => request<Forecast>('GET', `/forecast${force ? '?force=true' : ''}`, undefined, 90000),
  forecastSummary: () => request<ForecastSummary>('GET', '/forecast/summary', undefined, 90000),

  alerts: () => request<Alerts>('GET', '/alerts'),
  testAlert: () => request<{ delivered: boolean }>('POST', '/alerts/test'),
  demoAlert: () => request<{ delivered: boolean; title: string; message: string }>('POST', '/alerts/demo'),

  planCatalog: () => request<PlanCatalog>('GET', '/plan/catalog'),
  planSettings: () => request<PlanSettings>('GET', '/plan/settings'),
  savePlanSettings: (s: Partial<PlanSettings>) => request<PlanSettings>('PUT', '/plan/settings', s),
  devices: () => request<Device[]>('GET', '/devices'),
  addDevice: (d: Device) => request<Device>('POST', '/devices', d),
  updateDevice: (id: number, d: Device) => request<Device>('PUT', `/devices/${id}`, d),
  deleteDevice: (id: number) => request<{ deleted: number }>('DELETE', `/devices/${id}`),
  plan: (force = false) => request<Plan>('POST', `/plan${force ? '?force=true' : ''}`, undefined, 120000),

  subscription: () => request<Subscription>('GET', '/subscription'),
  checkout: (return_url: string) => request<{ url: string }>('POST', '/subscription/checkout', { return_url }),
  demoUnlock: () => request<Me>('POST', '/subscription/demo-unlock'),
  cancel: () => request<Me>('POST', '/subscription/cancel'),
};
