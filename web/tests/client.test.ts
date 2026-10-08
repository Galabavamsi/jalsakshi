import { describe, expect, it, vi } from 'vitest';
import {
  ApiError,
  PolicyDeniedError,
  buildUrl,
  createHttpApi,
  isPolicyDenied,
} from '../src/api/client';

const DENIED = {
  denied: true,
  policy_id: 'verify-needs-quorum',
  reason_hi: 'अभी 2 में से केवल 1 घर ने पुष्टि की है।',
  reason_en: 'Only 1 of 2 households confirmed water.',
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === undefined ? '' : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stubFetch(status: number, body: unknown) {
  return vi.fn<typeof fetch>(async () => jsonResponse(status, body));
}

describe('buildUrl', () => {
  it('joins base, path and only non-empty query values', () => {
    expect(buildUrl('https://api.test/', '/api/tickets', { state: 'OPEN', village_id: '' })).toBe(
      'https://api.test/api/tickets?state=OPEN',
    );
    expect(buildUrl('https://api.test', '/api/villages')).toBe('https://api.test/api/villages');
  });
});

describe('isPolicyDenied', () => {
  it('recognises the §13 deny body only', () => {
    expect(isPolicyDenied(DENIED)).toBe(true);
    expect(isPolicyDenied({ error: { code: 'x', message: 'y' } })).toBe(false);
    expect(isPolicyDenied(null)).toBe(false);
  });
});

describe('createHttpApi', () => {
  it('sends the bearer token and encodes path segments', async () => {
    const fetchImpl = stubFetch(200, []);
    const api = createHttpApi({
      baseUrl: 'https://api.test',
      getToken: async () => 'tok-123',
      fetchImpl,
    });
    await api.getDays('v/1', '2026-10-01', '2026-10-08');
    const [url, init] = fetchImpl.mock.calls[0] ?? [];
    expect(url).toBe('https://api.test/api/villages/v%2F1/days?from=2026-10-01&to=2026-10-08');
    expect((init?.headers as Record<string, string>).Authorization).toBe('Bearer tok-123');
    expect(init?.method).toBe('GET');
  });

  it('posts JSON bodies matching the contract', async () => {
    const fetchImpl = stubFetch(200, { execution_arn: 'arn:x' });
    const api = createHttpApi({ baseUrl: 'https://api.test', fetchImpl });
    await expect(api.runCheckin('v1')).resolves.toEqual({ execution_arn: 'arn:x' });
    const [, init] = fetchImpl.mock.calls[0] ?? [];
    expect(init?.method).toBe('POST');
    expect(JSON.parse(String(init?.body))).toEqual({ purpose: 'DAILY' });
  });

  it('returns a Cedar deny from close as a value, not an exception', async () => {
    const api = createHttpApi({ baseUrl: 'https://api.test', fetchImpl: stubFetch(403, DENIED) });
    await expect(api.closeTicket('t1')).resolves.toEqual({ ok: false, denied: DENIED });
  });

  it('returns the ticket when close succeeds', async () => {
    const ticket = { id: 't1', state: 'CLOSED_VERIFIED' };
    const api = createHttpApi({ baseUrl: 'https://api.test', fetchImpl: stubFetch(200, ticket) });
    await expect(api.closeTicket('t1')).resolves.toEqual({ ok: true, ticket });
  });

  it('throws PolicyDeniedError for a deny on other routes', async () => {
    const api = createHttpApi({ baseUrl: 'https://api.test', fetchImpl: stubFetch(403, DENIED) });
    const err = await api.runCheckin('v1').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(PolicyDeniedError);
    expect((err as PolicyDeniedError).denied.policy_id).toBe('verify-needs-quorum');
  });

  it('maps the error envelope to ApiError', async () => {
    const api = createHttpApi({
      baseUrl: 'https://api.test',
      fetchImpl: stubFetch(404, { error: { code: 'not_found', message: 'No village v9' } }),
    });
    const err = (await api.getVillage('v9').catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.code).toBe('not_found');
    expect(err.message).toBe('No village v9');
  });

  it('reports 401 to the app', async () => {
    const onUnauthorized = vi.fn();
    const api = createHttpApi({
      baseUrl: 'https://api.test',
      fetchImpl: stubFetch(401, { error: { code: 'unauthorized', message: 'no' } }),
      onUnauthorized,
    });
    await expect(api.listVillages()).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it('turns network failures into ApiError with status 0', async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new TypeError('Failed to fetch');
    });
    const api = createHttpApi({ baseUrl: 'https://api.test', fetchImpl });
    const err = (await api.listVillages().catch((e: unknown) => e)) as ApiError;
    expect(err.status).toBe(0);
    expect(err.code).toBe('network');
  });

  it('times out slow requests', async () => {
    const fetchImpl = vi.fn<typeof fetch>(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
        }),
    );
    const api = createHttpApi({ baseUrl: 'https://api.test', fetchImpl, timeoutMs: 10 });
    const err = (await api.listVillages().catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe('timeout');
  });
});
