/** Typed fetch client for the JalSakshi HTTP API (ARCHITECTURE.md §13). */

import type {
  ActionResult,
  ActivityItem,
  AddHouseholdRequest,
  AddHouseholdResponse,
  AddQualityRequest,
  ApiErrorBody,
  Brief,
  Broadcast,
  BulkAddResponse,
  CallLanguage,
  CreatePanchayatRequest,
  CreatePanchayatResponse,
  FamilyRow,
  RegisterPhotoResponse,
  VillageSettings,
  CreateVillageRequest,
  Operator,
  Person,
  Place,
  TeamRole,
  Village,
  BroadcastList,
  BroadcastSent,
  CheckInMasked,
  CloseResult,
  ConsentLedger,
  DayStatus,
  DraftBroadcastRequest,
  IsoDate,
  IsoDateTime,
  Me,
  PolicyDenied,
  PublicVillageRow,
  PublicVillageView,
  Purpose,
  QualityList,
  QualityTest,
  RaiseTicketRequest,
  RunCheckinResponse,
  SimInputRequest,
  SimInputResponse,
  SimStartRequest,
  SimStartResponse,
  Ticket,
  TicketOverview,
  TicketQuery,
  VillageAnalytics,
  VillageDetail,
  VillageSummary,
  WaterPoint,
  WaterPointInput,
  WeeklySummary,
} from './types';

/** Everything the console calls. Implemented by the HTTP client and by the mock. */
export interface JalApi {
  // ---- Gram Panchayat (§15.12), signed in
  listWaterPoints(vid: string): Promise<WaterPoint[]>;
  /** Create (no id) or update (id) a water point; saving marks it no longer provisional. */
  saveWaterPoint(vid: string, input: WaterPointInput): Promise<WaterPoint>;
  /** Adds a family's number; the family gets the consent call before any check-in. */
  addHousehold(vid: string, request: AddHouseholdRequest): Promise<AddHouseholdResponse>;
  getConsents(vid: string): Promise<ConsentLedger>;
  /** A complaint brought to the Panchayat office on behalf of a registered family. */
  raiseTicket(vid: string, request: RaiseTicketRequest): Promise<Ticket>;
  listBroadcasts(vid: string): Promise<BroadcastList>;
  draftBroadcast(vid: string, request: DraftBroadcastRequest): Promise<Broadcast>;
  /** Sarpanch only (Cedar ApproveBroadcast); a deny is a value, not an exception. */
  approveBroadcast(vid: string, bid: string): Promise<ActionResult<Broadcast>>;
  /** Approved, at most 2 a week (Cedar SendBroadcast); a deny is a value, not an exception. */
  sendBroadcast(vid: string, bid: string): Promise<ActionResult<BroadcastSent>>;
  cancelBroadcast(vid: string, bid: string): Promise<Broadcast>;
  listQuality(vid: string): Promise<QualityList>;
  addQuality(vid: string, request: AddQualityRequest): Promise<QualityTest>;
  getAnalytics(vid: string, from?: IsoDate, to?: IsoDate): Promise<VillageAnalytics>;
  getSummary(vid: string): Promise<WeeklySummary>;
  // ---- residents' view (§15.11): no sign-in, never sends the access token
  listPublicVillages(): Promise<PublicVillageRow[]>;
  getPublicVillage(vid: string): Promise<PublicVillageView>;
  // ---- §13
  listVillages(): Promise<VillageSummary[]>;
  getVillage(vid: string): Promise<VillageDetail>;
  getDays(vid: string, from: IsoDate, to: IsoDate): Promise<DayStatus[]>;
  getCheckins(vid: string, date: IsoDate, purpose?: Purpose): Promise<CheckInMasked[]>;
  runCheckin(vid: string): Promise<RunCheckinResponse>;
  listTickets(query?: TicketQuery): Promise<Ticket[]>;
  getTicket(tid: string): Promise<Ticket>;
  operatorFixed(tid: string, operatorId: string): Promise<Ticket>;
  /** AI overview and suggested next step (advice only). */
  getOverview(tid: string): Promise<TicketOverview>;
  /** The secretary sends the complaint to the Sarpanch, who gets a call about it. */
  sendToSarpanch(tid: string): Promise<Ticket>;
  callOperatorAgain(tid: string): Promise<{ call: 'queued' }>;
  /** A Cedar deny (403) is a normal outcome here, not an exception. */
  closeTicket(tid: string): Promise<CloseResult>;
  getBrief(vid: string, from?: IsoDate, to?: IsoDate): Promise<Brief>;
  getActivity(since?: IsoDateTime): Promise<ActivityItem[]>;
  simStartCall(request: SimStartRequest): Promise<SimStartResponse>;
  simInput(callId: string, request: SimInputRequest): Promise<SimInputResponse>;
  /** The signed-in user and their role (GET /api/me). */
  getMe(): Promise<Me>;
  // ---- first-time setup (§16)
  listPlaces(q?: string): Promise<Place[]>;
  createVillage(request: CreateVillageRequest): Promise<Village>;
  /** Team members; phone_e164 is masked by the API. */
  getTeam(vid: string): Promise<Operator[]>;
  saveTeamMember(vid: string, role: TeamRole, person: Person): Promise<Operator>;
  /** Many numbers at once; each new family gets one consent call (25 waiting at most). */
  addHouseholdsBulk(vid: string, phones: string | string[]): Promise<BulkAddResponse>;
  /** Families with names and areas (e.g. read from a register photo). */
  addFamilies(vid: string, families: FamilyRow[]): Promise<BulkAddResponse>;
  /** Another consent call to a family that has not answered yet. */
  callAgain(vid: string, hid: string): Promise<{ call: 'queued' }>;
  /** Reads names, mobiles and areas from a photo; adds nothing. */
  readRegisterPhoto(vid: string, imageBase64: string, mediaType: string): Promise<RegisterPhotoResponse>;
  listLanguages(): Promise<CallLanguage[]>;
  saveVillageSettings(vid: string, settings: VillageSettings): Promise<Village>;
  /** JalSakshi team only. */
  createPanchayat(request: CreatePanchayatRequest): Promise<CreatePanchayatResponse>;
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
  /** Residents' routes (/public/*): no Authorization header, and a 401 never signs anyone out. */
  isPublic?: boolean;
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

/** Turns a Cedar deny (PolicyDeniedError) into a value; every other failure still throws. */
export async function denialAsValue<T>(pending: Promise<T>): Promise<ActionResult<T>> {
  try {
    return { ok: true, value: await pending };
  } catch (err) {
    if (err instanceof PolicyDeniedError) return { ok: false, denied: err.denied };
    throw err;
  }
}

/** Creates the real API client. */
export function createHttpApi(options: HttpApiOptions): JalApi {
  const fetchImpl: typeof fetch = options.fetchImpl ?? ((input, init) => fetch(input, init));
  const timeoutMs = options.timeoutMs ?? 20_000;

  async function send(spec: RequestSpec): Promise<RawResponse> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (spec.body !== undefined) headers['Content-Type'] = 'application/json';
    const token = !spec.isPublic && options.getToken ? await options.getToken() : null;
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
      if (res.status === 401 && !spec.isPublic) options.onUnauthorized?.();
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

  const village = (vid: string, rest = '') => `/api/villages/${seg(vid)}${rest}`;
  const broadcastPath = (vid: string, bid: string, action: string) =>
    village(vid, `/broadcasts/${seg(bid)}/${action}`);

  return {
    listWaterPoints: (vid) => call({ method: 'GET', path: village(vid, '/water-points') }),
    saveWaterPoint: (vid, input) =>
      call({ method: 'POST', path: village(vid, '/water-points'), body: input }),
    addHousehold: (vid, request) =>
      call({ method: 'POST', path: village(vid, '/households'), body: request }),
    getConsents: (vid) => call({ method: 'GET', path: village(vid, '/consents') }),
    raiseTicket: (vid, request) =>
      call({ method: 'POST', path: village(vid, '/tickets'), body: request }),
    listBroadcasts: (vid) => call({ method: 'GET', path: village(vid, '/broadcasts') }),
    draftBroadcast: (vid, request) =>
      call({ method: 'POST', path: village(vid, '/broadcasts'), body: request }),
    approveBroadcast: (vid, bid) =>
      denialAsValue(call<Broadcast>({ method: 'POST', path: broadcastPath(vid, bid, 'approve'), body: {} })),
    sendBroadcast: (vid, bid) =>
      denialAsValue(call<BroadcastSent>({ method: 'POST', path: broadcastPath(vid, bid, 'send'), body: {} })),
    cancelBroadcast: (vid, bid) =>
      call({ method: 'POST', path: broadcastPath(vid, bid, 'cancel'), body: {} }),
    listQuality: (vid) => call({ method: 'GET', path: village(vid, '/quality') }),
    addQuality: (vid, request) =>
      call({ method: 'POST', path: village(vid, '/quality'), body: request }),
    getAnalytics: (vid, from, to) =>
      call({ method: 'GET', path: village(vid, '/analytics'), query: { from, to } }),
    getSummary: (vid) => call({ method: 'GET', path: village(vid, '/summary') }),
    listPublicVillages: () => call({ method: 'GET', path: '/public/villages', isPublic: true }),
    getPublicVillage: (vid) =>
      call({ method: 'GET', path: `/public/villages/${seg(vid)}`, isPublic: true }),

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
    getOverview: (tid) => call({ method: 'GET', path: `/api/tickets/${seg(tid)}/overview` }),
    sendToSarpanch: (tid) => call({ method: 'POST', path: `/api/tickets/${seg(tid)}/send-to-sarpanch` }),
    callOperatorAgain: (tid) => call({ method: 'POST', path: `/api/tickets/${seg(tid)}/call-operator` }),
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
    getMe: () => call({ method: 'GET', path: '/api/me' }),
    listPlaces: (q) => call({ method: 'GET', path: '/api/places', query: { q } }),
    createVillage: (request) => call({ method: 'POST', path: '/api/villages', body: request }),
    getTeam: (vid) => call({ method: 'GET', path: village(vid, '/team') }),
    saveTeamMember: (vid, role, person) =>
      call({ method: 'POST', path: village(vid, '/team'), body: { role, ...person } }),
    addHouseholdsBulk: (vid, phones) =>
      call({ method: 'POST', path: village(vid, '/households/bulk'), body: { phones } }),
    addFamilies: (vid, families) =>
      call({ method: 'POST', path: village(vid, '/households/bulk'), body: { families } }),
    callAgain: (vid, hid) =>
      call({ method: 'POST', path: village(vid, `/households/${encodeURIComponent(hid)}/consent-call`) }),
    readRegisterPhoto: (vid, image_base64, media_type) =>
      call({ method: 'POST', path: village(vid, '/register-photo'), body: { image_base64, media_type } }),
    listLanguages: () => call({ method: 'GET', path: '/api/languages' }),
    saveVillageSettings: (vid, settings) =>
      call({ method: 'POST', path: village(vid, '/settings'), body: settings }),
    createPanchayat: (request) => call({ method: 'POST', path: '/api/admin/panchayats', body: request }),
  };
}
