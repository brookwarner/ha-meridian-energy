![Company logo](https://github.com/home-assistant/brands/blob/87e2d7c60931ee822776d2204244ef3eff4d22cf/custom_integrations/meridian_energy/logo.png?raw=true)

# Meridian Energy integration for Home Assistant

> **Maintained fork.** A continuation of [codyc1515/ha-meridian-energy](https://github.com/codyc1515/ha-meridian-energy),
> which has been inactive since late 2024. This fork adds historical statistics
> backfill, day/night/solar handling and assorted fixes, and is the version actively
> running in production. Contributions welcome.

## What this fork adds

* **Historical statistics import** into the Home Assistant recorder (long-term
  statistics / Energy dashboard), with persistent import-state across restarts
* **Day / Night / Solar export** usage sensors
* Configurable historical-data window and incremental consumption processing
* Fixes around duplicate usage and data backfill (the areas reported in upstream
  issues [#6](https://github.com/codyc1515/ha-meridian-energy/issues/6) /
  [#7](https://github.com/codyc1515/ha-meridian-energy/issues/7))

## Compatible plans

* Consumer EV Plan (Day & Night rates, with Solar)

Possibly others - let me know if you find one that works.

## Getting started
You will need to have an existing active consumer Meridian Energy account.

## Installation
Once installed, simply set-up from the `Devices and services` area. The first field is email and the next field is password for your account.

### HACS (recommended)
1. [Install HACS](https://hacs.xyz/docs/setup/download), if you did not already
2. In HACS, add this repository as a **custom repository**: `https://github.com/brookwarner/ha-meridian-energy` (category: Integration). Or use the button: [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=brookwarner&repository=ha-meridian-energy&category=integration)
3. Install the Meridian Energy integration
4. Restart Home Assistant

### Manually
Copy the `custom_components/meridian_energy` folder into your Home Assistant `config/custom_components/` directory, then restart Home Assistant.

## Known issues

* Labels don't show when using the config_flow

## Future enhancements
Your support is welcomed.

* Support for multiple ICPs (haven't tried a login with multiple ICPs)
* Support for energy rates (currently need to be set-up manually and is static thereafter)

## Acknowledgements
This integration is not supported / endorsed by, nor affiliated with, Meridian Energy.
