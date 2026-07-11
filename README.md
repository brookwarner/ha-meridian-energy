![Company logo](https://github.com/home-assistant/brands/blob/87e2d7c60931ee822776d2204244ef3eff4d22cf/custom_integrations/meridian_energy/logo.png?raw=true)

# Meridian Energy integration for Home Assistant

> **Maintained fork.** A continuation of [codyc1515/ha-meridian-energy](https://github.com/codyc1515/ha-meridian-energy),
> which has been inactive since late 2024. This fork adds historical statistics
> backfill, day/night/solar handling and assorted fixes, and is the version actively
> running in production. Contributions welcome.

## What this fork adds

* **New Meridian API support (2.0.0)** — Meridian retired the old
  `secure.meridianenergy.co.nz` portal for the new app
  (`app.meridianenergy.nz`, GraphQL API with Firebase **email one-time-code**
  login). This fork migrates to it; the old CSV/password integration no longer works.
* **Historical statistics import** into the Home Assistant recorder (long-term
  statistics / Energy dashboard). Cumulative sums **continue from the recorder's
  last value** (no resets/spikes) and **backfill any gap** since the last reading.
* **Day / Night / Solar export** usage + cost sensors. Cost uses Meridian's own
  per-interval estimate by default, or your manually configured rates.
* Async coordinator; compatible with Home Assistant 2026.6 (`mean_type`) and
  ready for 2026.11 (`unit_class`).

## Tested against

* **No-solar, flat single-rate, single-ICP** account on HA 2026.6.4 — fully
  verified end-to-end (auth, import, continuity, gap backfill, cost vs actual bill).

The following paths exist in the code but are **not yet verified against a real
account** — please open an issue with results if you have one:

* **Solar / feed-in** export (`return_to_grid`)
* **Time-of-use** plans (different day vs night prices)
* **Multiple ICPs / properties** (currently only the first property is used)

## Getting started
You will need an existing active Meridian Energy account, and access to the email
inbox for that account (a one-time code is emailed to you at sign-in).

## Installation
Set up from **Settings → Devices & services → Add Integration → Meridian Energy**.
Enter your account **email**; Meridian emails you a **one-time code**, which you
enter on the next screen. (There is no password — Meridian's new app uses one-time
codes.)

### Upgrading from 1.x
On first start after upgrading, your existing entry migrates automatically and
Home Assistant will prompt you to **re-authenticate** (enter your email + the
emailed one-time code). Your statistics history and any custom rates are preserved.

### HACS (recommended)
1. [Install HACS](https://hacs.xyz/docs/setup/download), if you did not already
2. In HACS, add this repository as a **custom repository**: `https://github.com/brookwarner/ha-meridian-energy` (category: Integration). Or use the button: [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=brookwarner&repository=ha-meridian-energy&category=integration)
3. Install the Meridian Energy integration
4. Restart Home Assistant

### Manually
Copy the `custom_components/meridian_energy` folder into your Home Assistant `config/custom_components/` directory, then restart Home Assistant.

## Future enhancements
Your support is welcomed.

* Verify / support **solar feed-in**, **time-of-use** plans, and **multiple
  ICPs/properties** (see *Tested against* above)
* Optional separate **daily fixed charge** (standing charge) cost sensor — the
  per-kWh cost intentionally excludes it today

## Acknowledgements
This integration is not supported / endorsed by, nor affiliated with, Meridian Energy.
