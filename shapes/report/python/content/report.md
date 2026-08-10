---
title: "{{ brand.display_name }}"
subtitle: "{{ brand.tagline }}"
author: "{{ brand.legal.company_name }}"
date: "{{ now }}"
lang: "{{ lang }}"
---

# {{ t.app.title }}

> {{ brand.tagline }}

{{ t.app.welcome | replace('{{name}}', brand.display_name) }}

## {{ t.nav.about }}

{{ brand.description or brand.tagline }}

This document was generated in language code **{{ lang }}** from the
content in `content/report.md` using brand settings from `brand/config.json`
and translations from `locales/{{ lang }}.json`.

The same source renders a PDF, a standalone HTML page, a reveal.js
slideshow, and an Excel summary — one of each per language.

## Brand color palette

| Swatch | Token | Value |
|---|---|---|
| **primary** | `brand.colors.primary` | `{{ brand.colors.primary }}` |
| **secondary** | `brand.colors.secondary` | `{{ brand.colors.secondary }}` |
| **accent** | `brand.colors.accent` | `{{ brand.colors.accent }}` |
| **text** | `brand.colors.text` | `{{ brand.colors.text }}` |
| **background** | `brand.colors.background` | `{{ brand.colors.background }}` |

## {{ t.nav.contact }}

{% if brand.contact.email %}
- {{ t.nav.contact }}: **{{ brand.contact.email }}**
{% endif %}
{% if brand.contact.url %}
- Web: <{{ brand.contact.url }}>
{% endif %}

---

*Replace the contents of `content/report.md` with your real document.
You can reference any brand field as* `{{ "{{ brand.FIELD }}" }}` *and any
translation key as* `{{ "{{ t.NAMESPACE.KEY }}" }}`. *Use*
`BUILD_LANGS=en,es` *to limit which languages are rendered for faster
iteration.*
