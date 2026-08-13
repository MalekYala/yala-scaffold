# Locales — internationalization

This directory holds all translatable strings for the project. Every shape
that has user-facing text (webapp, report, and optionally service) reads
translations from here.

## Structure

```
locales/
├── en.json          Primary (required) — English, the source of truth
├── es.json          Spanish (example second language)
├── <ISO>.json       Any ISO 639-1 language code; one file per language
└── README.md        This file
```

## Key conventions

- **Namespaced**: keys are nested under `app`, `nav`, `actions`, `errors`,
  `footer`, etc. — not flat. Makes bulk translation easier and keeps UI
  sections organized.
- **Interpolation**: double-braces for variables, e.g. `"welcome": "Welcome to {{name}}"`.
  The same syntax works in react-i18next (frontend) and Jinja2 (reports).
- **Pluralization**: use i18next plural keys — `item` / `item_other` — when
  the language supports it. Example:
  ```json
  {
    "cart": {
      "item_one": "{{count}} item",
      "item_other": "{{count}} items"
    }
  }
  ```
- **HTML inside values**: avoid if possible. If unavoidable, mark the key
  with a `_html` suffix and render via `<Trans>` component (react-i18next)
  or `{{{triple-braces}}}` (Jinja2) — never with `{{double-braces}}`.

## Adding a new language

1. Copy `en.json` to `<lang>.json` (e.g., `de.json`).
2. Translate every value, preserving keys, interpolation variables, and
   pluralization suffixes.
3. Run `scripts/check_locales.py` (shipped with the project) to verify no
   keys are missing and all interpolation vars match.
4. Rebuild the webapp so the new language appears in the language switcher.
5. Regenerate branded reports with `LANG=<lang> make report` if the project
   uses the report shape.
6. Add a row to `README.md`'s "Supported languages" table and a line to
   `CHANGELOG.md`.

## Automating translation

The project ships `scripts/translate_docs.sh` which wraps an operator-supplied
`$TRANSLATOR` backend (local LLM, OpenAI API, DeepL, or manual). Usage:

```bash
export TRANSLATOR=local-llm   # or openai, deepl, manual
export TARGET_LANG=de
./scripts/translate_docs.sh locales/en.json locales/de.json
```

The script is **a wrapper** — it fails loudly if `$TRANSLATOR` is unset. The
operator is responsible for providing the actual translation engine.

## What reads this directory

| Consumer | How |
|---|---|
| `webapp` | i18next loads `locales/<lang>.json` at app startup; language detected from URL `?lang=` then browser header then default (en) |
| `report` | `generate_report.py` loads `locales/<lang>.json` and renders one PDF per locale (`outputs/report_en.pdf`, `outputs/report_es.pdf`, etc.) |
| `service` | Optional — if the service returns localized error messages, load based on `Accept-Language` header |

## Keeping translations in sync

English (`en.json`) is the source of truth. Other files may lag behind.
`scripts/check_locales.py` will flag:

- Keys in `en.json` but missing from `<lang>.json` (untranslated)
- Keys in `<lang>.json` but missing from `en.json` (stale)
- Mismatched interpolation variable sets (`{{name}}` vs `{{nombre}}`)

Run it in CI as part of the lint stage. PRs that add a key without
translating it will be flagged (but not blocked — translation is a separate
workflow).
