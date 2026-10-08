/** Typed fetch client for the JalSakshi HTTP API (ARCHITECTURE.md §13). */

import type {
  ActivityItem,
  ApiErrorBody,
  Brief,
  CheckInMasked,
  CloseResult,
  DayStatus,
  IsoDate,
  IsoDateTime,
  PolicyDenied,
  Purpose,
  RunCheckinResponse,
  SimInputRequest,
  SimInputResponse,
  SimStartRequest,
  SimStartResponse,
  Ticket,
  TicketQuery,
  VillageDetail,
  VillageSummary,
} from './types';

/** Everything the console calls. Implemented by the HTTP client and by the mock. */
export interface JalApi {
  listVillages(): Promise<VillageSummary[]>;
  getVillage(vid: string): Promise<VillageDetail>;
  getDays(vid: string, from: IsoDate, to: IsoDate): Promise<DayStatus[]>;
  getCheckins(vid: string, date: IsoDate, purpose?: Purpose): Promise<CheckInMasked[]>;
  runCheckin(vid: string): Promise<RunCheckinResponse>;
  listTickets(query?: TicketQuery): Promise<Ticket[]>;
  getTicket(tid: string): Promise<Ticket>;
  operatorFixed(tid: string, operatorId: string): Promise<Ticket>;
  /** A Cedar deny (403) is a normal outcome here, not an exception. */
  closeTicket(tid: string): Promise<CloseResult>;
  getBrief(vid: string, from?: IsoDate, to?: IsoDate): Promise<Brief>;
  getActivity(since?: IsoDateTime): Promise<ActivityItem[]>;
  simStartCall(request: SimStartRequest): Promise<SimStartResponse>;
  simInput(callId: string, request: SimInputRequest): Promise<SimInputResponse>;
}

/** Any failed request. `status` is 0 for network failures and timeouts. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

/** A 403 from a Cedar policy, carrying the bilingual reason to show the operator. */
export class PolicyDeniedError extends ApiError {
  readonly denied: PolicyDenied;

  constructor(denied: PolicyDenied) {
    super(403, `policy:${denied.policy_id}`, denied.reason_en);
    this.name = 'PolicyDeniedError';
    this.denied = denied;
  }
}

export interface HttpApiOptions {
  /** API Gateway base URL, no trailing slash needed. */
  baseUrl: string;
  /** Returns the Cognito access token, or null when signed out. */
  getToken?: () => Promise<string | null>;
  /** Called once per 401 so the app can send the user back to sign-in. */
  onUnauthorized?: () => void;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

type Query = Record<string, string | undefined>;

interface RequestSpec {
  method: 'GET' | 'POST';
  path: string;
  query?: Query;
  body?: unknown;
}

interface RawResponse {
  status: number;
  body: unknown;
}

/** Joins base URL, path and the non-empty query parameters. */
export function buildUrl(baseUrl: string, path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== '') params.set(key, value);
  }
  const qs = params.toString();
  return `${baseUrl.replace(/\/+$/, '')}${path}${qs ? `?${qs}` : ''}`;
}

/** True when a body is the §13 Cedar deny shape. */
export function isPolicyDenied(body: unknown): body is PolicyDenied {
  if (typeof body !== 'object' || body === null) return false;
  const b = body as Partial<PolicyDenied>;
  return b.denied === true && typeof b.reason_en === 'string' && typeof b.reason_hi === 'string';
}

function errorFromResponse({ status, body }: RawResponse): ApiError {
  if (status === 403 && isPolicyDenied(body)) return new PolicyDeniedError(body);
  const err = (body as Partial<ApiErrorBody> | null)?.error;
  if (err && typeof err.message === 'string') {
    return new ApiError(status, String(err.code ?? `http_${status}`), err.message);
  }
  return new ApiError(status, `http_${status}`, `The API answered with status ${status}.`);
}

async function readBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return { error: { code: 'bad_json', message: text.slice(0, 200) } };
  }
}

const seg = encodeURIComponent;

/** Creates the real API client. */
export function createHttpApi(options: HttpApiOptions): JalApi {
  const fetchImpl: typeof fetch = options.fetchImpl ?? ((input, init) => fetch(input, init));
  const timeoutMs = options.timeoutMs ?? 20_000;

  async function send(spec: RequestSpec): Promise<RawResponse> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (spec.body !== undefined) headers['Content-Type'] = 'application/json';
    const token = options.getToken ? await options.getToken() : null;
    if (token) headers.Authorization = `Bearer ${token}`;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetchImpl(buildUrl(options.baseUrl, spec.path, spec.query), {
        method: spec.method,
        headers,
        body: spec.body === undefined ? undefined : JSON.stringify(spec.body),
        signal: controller.signal,
      });
      const body = await readBody(res);
      if (res.status === 401) options.onUnauthorized?.();
      return { status: res.status, body };
    } catch (cause) {
      if (cause instanceof ApiError) throw cause;
      if (controller.signal.aborted) {
        throw new ApiError(0, 'timeout', `No answer from the API within ${timeoutMs / 1000} s.`);
      }
      throw new ApiError(0, 'network', 'Could not reach the JalSakshi API.');
    } finally {
      clearTimeout(timer);
    }
  }

  async function call<T>(spec: RequestSpec): Promise<T> {
    const raw = await send(spec);
    if (raw.status >= 200 && raw.status < 300) return raw.body as T;
    throw errorFromResponse(raw);
  }

  return {
    listVillages: () => call({ method: 'GET', path: '/api/villages' }),
    getVillage: (vid) => call({ method: 'GET', path: `/api/villages/${seg(vid)}` }),
    getDays: (vid, from, to) =>
      call({ method: 'GET', path: `/api/villages/${seg(vid)}/days`, query: { from, to } }),
    getCheckins: (vid, date, purpose = 'DAILY') =>
      call({
        method: 'GET',
        path: `/api/villages/${seg(vid)}/checkins`,
        query: { date, purpose },
      }),
    runCheckin: (vid) =>
      call({
        method: 'POST',
        path: `/api/villages/${seg(vid)}/checkin/run`,
        body: { purpose: 'DAILY' },
      }),
    listTickets: (query) =>
      call({
        method: 'GET',
        path: '/api/tickets',
        query: { state: query?.state, village_id: query?.village_id },
      }),
    getTicket: (tid) => call({ method: 'GET', path: `/api/tickets/${seg(tid)}` }),
    operatorFixed: (tid, operatorId) =>
      call({
        method: 'POST',
        path: `/api/tickets/${seg(tid)}/operator-fixed`,
        body: { operator_id: operatorId },
      }),
    async closeTicket(tid) {
      try {
        const ticket = await call<Ticket>({
          method: 'POST',
          path: `/api/tickets/${seg(tid)}/close`,
          body: {},
        });
        return { ok: true, ticket };
      } catch (err) {
        if (err instanceof PolicyDeniedError) return { ok: false, denied: err.denied };
        throw err;
      }
    },
    getBrief: (vid, from, to) =>
      call({ method: 'GET', path: `/api/villages/${seg(vid)}/brief`, query: { from, to } }),
    getActivity: (since) => call({ method: 'GET', path: '/api/activity', query: { since } }),
    simStartCall: (request) => call({ method: 'POST', path: '/sim/calls', body: request }),
    simInput: (callId, request) =>
      call({ method: 'POST', path: `/sim/calls/${seg(callId)}/input`, body: request }),
  };
}
