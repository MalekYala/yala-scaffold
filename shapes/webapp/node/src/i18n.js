// i18next setup.
//
// Translations live in /locales/<lang>.json and are loaded at runtime via
// i18next-http-backend. Language detection order: URL `?lang=` → browser
// → localStorage → default ('en').
//
// To add a language:
//   1. Create locales/<ISO>.json (copy en.json and translate values)
//   2. Add the language code to supportedLngs below
//   3. Rebuild

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import HttpBackend from 'i18next-http-backend';
import LanguageDetector from 'i18next-browser-languagedetector';

export const SUPPORTED_LOCALES = ['en', 'es'];
export const DEFAULT_LOCALE = 'en';

i18n
  .use(HttpBackend)
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: DEFAULT_LOCALE,
    supportedLngs: SUPPORTED_LOCALES,
    ns: ['translation'],
    defaultNS: 'translation',
    backend: {
      // Served by Fastify from /locales/ in production, by Vite in dev
      loadPath: '/locales/{{lng}}.json',
    },
    detection: {
      // URL query param wins — lets marketing links pin a language:
      // https://example.com/?lang=es
      order: ['querystring', 'navigator', 'localStorage', 'htmlTag'],
      lookupQuerystring: 'lang',
      caches: ['localStorage'],
    },
    interpolation: {
      escapeValue: false, // React already escapes
    },
  });

export default i18n;
