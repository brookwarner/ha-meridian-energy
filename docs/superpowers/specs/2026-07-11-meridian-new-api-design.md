# Meridian Energy — New API Migration Design

**Date:** 2026-07-11
**Status:** Approved design (pending spec review)

## Problem

Meridian Energy replaced the old customer portal (`secure.meridianenergy.co.nz`)
with a new Kraken-platform app (`app.meridianenergy.nz`) backed by a GraphQL API
(`api.meridianenergy.nz/v1/graphql/`) and Firebase authentication. The current
integration authenticates by scraping a CSRF token and posting an email/password
form, then downloads an EIEP-13A CSV. Both the auth and the data endpoint no
longer exist, so the integration is completely broken.

This is a rewrite of the auth + data layers. Config identity (`DOMAIN`,
statistic IDs) is preserved so existing Home Assistant long-term statistics and
Energy dashboard history carry over.

## Findings (from reverse-engineering the live app)

The app is an Expo/React-Native-Web SPA. Config was extracted from its JS bundle.

### Firebase / auth

- Auth project: **`meridian-retail-ciam`** (matches the JWT `aud`/`iss`).
- Firebase Web API key (public, embedded in app):
  `AIzaSyCYCKXQhGmo7haJxAAyO_7mIPrV7jtxsK8`
- The user's token has `sign_in_provider: "custom"` — the app's primary login is
  **email OTP** (passwordless). Password sign-in is *enabled* on the project
  (a bogus-credential probe returned `INVALID_LOGIN_CREDENTIALS`, not
  `PASSWORD_LOGIN_DISABLED`), but the user reports logging in via emailed code,
  so we build around OTP.

### OTP login flow (reproducible headlessly)

1. Generate a `journeyId` — a client-side UUID v4 (the app just makes one up).
2. `POST https://auth.meridianenergy.nz/cf/email-connector`
   body `{email, brand:"meridian", journeyId, otpEnabled:true, redirectUrl:<app url>}`,
   header `X-Client-Platform: web`. → Meridian emails a one-time code.
3. `POST https://auth.meridianenergy.nz/cf/email-otp-authenticator`
   body `{email, otp, brand:"meridian", journeyId}` → `{customToken}`.
4. `POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key=<CIAM_KEY>`
   body `{token:customToken, returnSecureToken:true}` → `{idToken, refreshToken, expiresIn}`.
5. Refresh: `POST https://securetoken.googleapis.com/v1/token?key=<CIAM_KEY>`
   body `grant_type=refresh_token&refresh_token=<rt>` → new `idToken` (+ possibly rotated `refreshToken`).

The `idToken` is the `Authorization` bearer for GraphQL. It expires in ~1 hour.
The `refreshToken` is long-lived (until revoked) and is what we persist.

**Items to verify at implementation time with a real login** (need a live code):
- Exact success/response shape of `email-connector` and `email-otp-authenticator`
  (field names, whether `redirectUrl` is required, any rate limiting).
- Whether `refreshToken` is rotated on refresh (store the latest returned).

### GraphQL data

- Endpoint: `https://api.meridianenergy.nz/v1/graphql/?opName=<op>`, header
  `Authorization: <idToken>` (raw token, no `Bearer` prefix — matches captured curl).
- **Account number** is embedded in the `idToken` claims
  (`accounts:[{account_number}]`), so no separate lookup is needed to bootstrap.
- `account(accountNumber)` query → `properties[].id` (propertyId), `meterPoints`,
  `registers[]` with `identifier` and `isFeedIn` (solar export detection),
  `marketIdentifier` (ICP).
- `measurements` query (per captured curl) with variables:
  `{accountNumber, propertyId, endOn, last:<N>, readingFrequencyType:"HOUR_INTERVAL",
  readingDirectionType:"CONSUMPTION"|"GENERATION", readingQualityType:"ACTUAL"}`,
  `timezone:"Pacific/Auckland"`. Returns hourly interval nodes with `value`,
  `unit`, `startAt`/`endAt`, cursor pagination (`pageInfo`), and
  `metaData.statistics[].costInclTax.estimatedAmount` (per-interval cost estimate).

**Item to verify at implementation time:** exact path of the per-interval cost in
the response (`metaData.statistics` array shape) against a real response.

## Decisions

| Decision | Choice |
|---|---|
| Login | Email OTP, done inside a two-step HA config flow. Store `refreshToken`. |
| Day/night split | Hour-based, **configurable** night window (default 21:00–07:00). |
| Cost | Default to API per-interval estimate; explicit configured rates override. |
| Architecture | Full modernization: async `DataUpdateCoordinator`, `aiohttp` via HA's shared session. |
| Statistics | Preserve existing `statistic_id`s and units; fix cumulative-sum continuity (see below). |

## Architecture

Async throughout. All HTTP via `homeassistant.helpers.aiohttp_client.async_get_clientsession`.

### Modules

- **`auth.py` — `MeridianAuth`**
  - Owns the Firebase token lifecycle: OTP request, OTP validation →
    custom-token → `idToken`/`refreshToken`, and refresh.
  - Public: `async request_otp(email) -> journeyId`,
    `async validate_otp(email, otp, journeyId) -> {id_token, refresh_token, account_number}`,
    `async valid_id_token() -> str` (refreshes if expiring within a margin),
    constructed from a stored `refresh_token` for normal operation.
  - Decodes the `idToken` payload (no signature verification needed client-side)
    to read `account_number` and `exp`.
  - Raises typed errors: `MeridianAuthError` (bad OTP, revoked token → triggers
    HA reauth), `MeridianConnectionError` (network/5xx → retryable).

- **`api.py` — `MeridianApi`**
  - GraphQL client. Takes `MeridianAuth`; injects the bearer, retries once on
    401 after forcing a refresh.
  - Public: `async get_account() -> Account` (propertyId, registers, has_solar),
    `async get_measurements(property_id, direction, end_on, last, after=None)`
    with cursor pagination helper `async iter_measurements(...)`.

- **`coordinator.py` — `MeridianCoordinator(DataUpdateCoordinator)`**
  - Update interval 3h (unchanged cadence).
  - On each refresh: ensure account cached; fetch new CONSUMPTION intervals (and
    GENERATION only if `has_solar`); hand raw intervals to the statistics builder.
  - Exposes latest snapshot (e.g. most recent interval, daily totals) for the
    sensor entity's state/attributes.

- **`statistics.py` — pure functions**
  - `build_statistics(intervals, config, baselines) -> dict[statistic_id, list[StatisticData]]`.
  - Buckets CONSUMPTION intervals into day/night by local hour vs configured
    window; GENERATION → return-to-grid. Computes cost (API estimate default,
    configured-rate override). **Cumulative sums continue from `baselines`**
    (last known sum per statistic_id) rather than resetting to 0.
  - Fully unit-testable with no HA/network dependencies.

- **`sensor.py`** — thin `CoordinatorEntity`; state + attributes from coordinator.
  Calls `async_add_external_statistics` for each statistic_id. Same statistic IDs
  and units as today.

- **`config_flow.py`** — two-step user flow (`async_step_user` email →
  `async_step_otp` code), `async_step_reauth`/`async_step_reauth_confirm` for
  revoked tokens, and options flow for cost rates + night-window hours.

- **`const.py`** — add CIAM key, auth URLs, GraphQL endpoint, brand, default
  night window (`CONF_NIGHT_START=21`, `CONF_NIGHT_END=7`). Keep `DOMAIN`,
  `SENSOR_NAME`, rate keys/defaults.

- **`__init__.py`** — create `MeridianAuth`+`MeridianApi`+coordinator, store on
  `entry.runtime_data`, `await coordinator.async_config_entry_first_refresh()`.

- **`manifest.json`** — no new pip requirements (aiohttp is core; JWT decode is a
  base64 split, no `pyjwt` needed).

## Statistics continuity (hard requirement)

Existing history lives in HA's recorder keyed by `statistic_id`, independent of
the config entry. Preserving it requires:

1. **Same `statistic_id`s and units** — `meridian_energy:consumption_day`,
   `:consumption_night`, `:return_to_grid`, and `:*_cost` variants; kWh / NZD.
2. **Continuous cumulative sum.** *Latent bug in current code:* it resets each
   running sum to 0 at the start of every 365-day import window, so the injected
   `sum` is only a within-window total and the baseline slides each run. The
   rewrite instead reads the last known sum + timestamp per statistic_id via
   `recorder.statistics.get_last_statistics` (run in the recorder executor),
   fetches only intervals **after** the last imported hour, and continues the
   cumulative sum from that baseline. First run (no existing stats) backfills the
   available history starting sum at 0.
3. **Idempotent re-import** with a small overlap window so `ACTUAL` reads that
   arrive late correct earlier `ESTIMATED`/missing points without breaking sums.

## Data integrity guarantees (prevents spikes / negatives / resets / bad format)

The previous integration exhibited: random resets to zero, giant negative values,
giant spikes, and data HA's Energy dashboard rejected. These are all
external-statistics `sum` failures. The rewrite treats the following as a hard
contract, enforced in `statistics.py` and covered by tests.

1. **Cumulative, never per-interval.** `StatisticData.sum` is a running cumulative
   total; `state` (if set) is the per-interval value. They are never conflated.
2. **Baseline continuation, never reset.** The running sum for each statistic_id
   starts from the recorder's last known sum (`get_last_statistics`), not 0.
   Reset to 0 happens *only* when the statistic has no prior rows (true first run).
   → fixes "random reset to zero" and the negative seam it causes.
3. **Strict chronological order.** The API returns newest-first via `last:N` +
   cursors. All intervals are collected, then **sorted ascending by start instant**
   before accumulating. → fixes zig-zag negatives.
4. **Monotonic non-decreasing sums.** Consumption/generation values are ≥ 0, so
   each statistic's sum only increases. Negative or absurd interval values are
   rejected (logged, skipped) rather than injected. An assertion in tests verifies
   `sum[i] >= sum[i-1]` for every produced series. → fixes negatives/spikes.
5. **One point per hour, de-duplicated.** Collapse any duplicate/overlapping
   intervals to a single point per hour boundary (actual-wins). Duplicate `start`
   values corrupt sums. → fixes spikes.
6. **ACTUAL reads only + deterministic overlap re-import.** Query
   `readingQualityType:"ACTUAL"`. Each run re-imports a small bounded overlap
   window (e.g. last ~48h), recomputing that window's sums **from the pre-overlap
   baseline** so a late-corrected value produces a consistent series with no seam,
   never a spike. → fixes spikes from late corrections.
7. **Hour-aligned, tz-aware, DST-safe timestamps.** Each `start` is timezone-aware
   at the top of the hour. We use the API's offset-aware `startAt` (hourly, already
   Pacific/Auckland) as the absolute instant; HA stores UTC internally. Day/night
   bucketing uses the *local* hour derived from that offset-aware time, so NZ DST
   transitions (duplicated 02:00 in autumn, skipped 02:00 in spring) are handled
   by real instants rather than naïve local arithmetic. Any interval not aligned to
   an exact hour is dropped/logged. → fixes "wrong format" rejections.
8. **Locked units & IDs.** Each statistic_id keeps a fixed
   `unit_of_measurement` (kWh / NZD) and `has_sum=True`, `has_mean=False`, matching
   what already exists in the recorder. Changing a unit for an existing ID breaks
   HA statistics, so units are constants, never derived from API `unit` strings
   (API values are validated against the expected unit, not trusted blindly).
9. **Per-bucket isolation.** day, night, return_to_grid, and each `_cost` series
   carry independent baselines and running sums — never shared.

**Verification:** unit tests assert monotonicity, no duplicate hours, correct
hour-alignment, continuation across a simulated baseline, and DST-boundary
correctness. Post-implementation, validated live in HA by watching the Energy
dashboard render without spikes/negatives (the `verify` skill / real run).

## Data flow

```
config flow (OTP)  ──►  refresh_token stored in entry
        │
__init__  ──►  MeridianAuth(refresh_token) ──► MeridianApi ──► MeridianCoordinator
        │
every 3h:  coordinator ──► valid idToken ──► GraphQL account + measurements
        │                                        │
        │              recorder.get_last_statistics (baselines)
        │                                        │
        └──►  statistics.build_statistics ──► async_add_external_statistics
                                             └► sensor state/attributes
```

## Error handling

- Auth failure on refresh (revoked / bad token) → raise `ConfigEntryAuthFailed`
  → HA reauth flow (user re-does OTP).
- Network / 5xx → `UpdateFailed` (coordinator retries next cycle).
- Bad OTP in config flow → form error, let user retry.
- GraphQL `errors` array present → surface message; 401 → one forced-refresh retry.

## Testing

- `statistics.py`: pure unit tests — day/night bucketing at window edges,
  configurable window, solar routing, cost (estimate vs override vs missing),
  cumulative-sum continuation from baselines, empty input.
- `auth.py`: mocked HTTP for OTP request/validate/refresh, token-expiry margin,
  idToken claim decode, error mapping.
- `api.py`: mocked GraphQL for account parse (solar detection) and measurement
  pagination; 401→refresh→retry.
- config flow: two-step happy path, bad OTP, reauth.

## Out of scope / later

- Register-based day/night split (revisit once live meter data can be inspected).
- Migration shim from the old email/password entry — users re-auth via OTP once;
  statistics history is unaffected because it is keyed by statistic_id.
```
