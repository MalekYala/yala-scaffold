# Brand kit

This directory holds the project's **brand kit** — the single source of truth
for colors, fonts, logos, and company metadata. Every shape that produces
user-facing output (webapp, report, site, etc.) reads from here.

## Structure

```
brand/
├── config.json       Schema-checked brand configuration (colors, fonts, contact)
├── logo.svg          Primary logo (light backgrounds)
├── logo-dark.svg     Dark-mode variant (for dark backgrounds)
├── favicon.svg       Favicon / app icon
├── wordmark.svg      Text-only logo for marketing materials
└── assets/           Additional brand imagery (screenshots, patterns, OG images)
```

## White-labeling / overriding

**Do not edit these files to customize branding per deployment.** Instead,
operators point the `BRAND_CONFIG_PATH` environment variable at their own
brand directory. The project loads from there at build/runtime:

```bash
export BRAND_CONFIG_PATH=/path/to/acme-brand
docker compose up -d
```

This keeps the upstream repo public-safe and lets operators white-label
without forking.

## What reads this directory

| Shape | How |
|---|---|
| `webapp` | Vite reads `config.json` at build time → CSS variables + `<title>` + favicon |
| `report` | `generate_report.py` injects brand into Pandoc/WeasyPrint templates and produces branded PDFs |
| `service` | Optional — if the service renders HTML emails or a landing page, it reads `brand/config.json` |
| `backtest` | Optional — matplotlib graphs can pick up `brand.colors.primary` for the equity curve |
| `worker`, `analysis`, `notebook`, `pipeline` | Ships as stub; use if you later generate user-facing output |

## Updating the brand kit

When you change `config.json` or any asset:

1. Update `config.json` — it is schema-checked by `scripts/check_brand.py`.
2. Regenerate any derived assets (e.g. `favicon.ico` from `favicon.svg`).
3. Rebuild the webapp so CSS variables pick up the new values.
4. Regenerate reports so PDFs reflect the new logo/colors.
5. Add an entry to `CHANGELOG.md` under `### Changed` — brand changes are
   user-visible (AGENTS.md §7).
