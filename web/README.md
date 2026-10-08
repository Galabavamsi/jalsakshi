# JalSakshi operator console (`web/`)

React 18 + Vite + TypeScript. Hindi first, English below. Works from 375 px up.
Used by the Panchayat Secretary or sarpanch, and in the demo video.

## Run

```bash
cd web
pnpm install
pnpm dev:mock        # seeded demo data, no network, no sign-in  -> http://localhost:5173
pnpm dev             # real API + Cognito (needs web/.env.local, see .env.example)
pnpm build           # typecheck + production build (dist/)
pnpm build:mock      # a deployable demo build on seeded data
pnpm lint && pnpm test
```

`VITE_API_MODE=mock` (or `vite --mode mock`) swaps the HTTP client for `src/api/mock.ts`:
two demo villages in Durg district, 14 days of statuses, one open ticket (verifying, 1 of 2
confirmations) and one `CLOSED_VERIFIED` ticket with a reopen in its history. Every number is
labelled demo and `simulated`. Simulator calls in mock mode record check-ins, recompute today's
status with a mirror of rule r1, and open, reopen or verify tickets, so the whole loop can be
shown offline.

## Environment (build time)

| Variable | Needed for | Example |
|---|---|---|
| `VITE_API_MODE` | `mock` for demo data | `mock` |
| `VITE_API_BASE` | real API | `https://abc123.execute-api.ap-south-1.amazonaws.com` |
| `VITE_COGNITO_DOMAIN` | sign-in | `https://jalsakshi-dev.auth.ap-south-1.amazoncognito.com` |
| `VITE_COGNITO_CLIENT_ID` | sign-in | public app client, no secret |
| `VITE_REDIRECT_URI` | sign-in | `https://<console>/auth/callback` |
| `VITE_LOGOUT_URI` | optional | defaults to the redirect URI's origin |
| `VITE_COGNITO_SCOPES` | optional | defaults to `openid email profile` |

Sign-in is the Cognito Hosted UI with authorization code + PKCE (`oidc-client-ts`). The access
token is sent as `Authorization: Bearer` to `/api/*` and `/sim/*`; tokens are kept in
`sessionStorage` and refreshed with the refresh token.

## Hosting notes

- CloudFront must serve `index.html` for unknown paths (403/404 to `/index.html`, status 200),
  because routes such as `/villages/v-1` and `/auth/callback` are client-side.
- The Cognito app client needs the callback URL `…/auth/callback`, the sign-out URL from
  `VITE_LOGOUT_URI`, the authorization code grant, and the scopes above.
- API Gateway CORS must allow the console origin and the `Authorization` and `Content-Type`
  headers.

## Layout

```
src/api/        types.ts (mirrors core/models.py + ARCHITECTURE §13), client.ts (fetch),
                mock*.ts (offline API), context.tsx
src/auth/       cognito.ts (PKCE via oidc-client-ts), AuthContext.tsx
src/components/ SourceBadge, StatusChip, StatusStrip, TallyTiles, Timeline, TicketParts,
                PolicyDenial, FeaturePhone, Markdown, Layout, PageState, Icons, Bi
src/lib/        pure helpers: IST dates, labels, formatting, simulator reducer, markdown
src/pages/      Villages, Village detail, Ticket, Gram Sabha brief, Simulator, Activity
tests/          vitest (node): client, mock API, IVR flow, simulator reducer, helpers
```

## Design

The page is limewash with indigo (`#EDF2F5`) and indigo ink, with the blue of painted
Har Ghar Jal walls (`#1F5FAE`) for actions and headlines. Rubber-stamp violet (`#5A3E9B`) marks
what households verified, and the same hatched violet marks anything simulated. Day statuses
always pair colour with an icon shape and a word. Type is Anek Devanagari (UI) and
Tiro Devanagari Hindi (the printed Gram Sabha sheet), both self-hosted.
