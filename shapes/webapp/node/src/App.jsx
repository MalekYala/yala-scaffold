// Root React component for <name>.
//
// Demonstrates:
//   - Reading brand config via useBrand()
//   - Translating strings via useTranslation()
//   - A language switcher that persists via localStorage
//
// Replace the contents of this file with your real app. The brand and i18n
// providers wrap everything in main.jsx — any child component can use
// useBrand() / useTranslation() without further setup.

import { useTranslation } from 'react-i18next';
import { useBrand } from './brand.jsx';
import { SUPPORTED_LOCALES } from './i18n.js';

export default function App() {
  const { t, i18n } = useTranslation();
  const brand = useBrand();

  const year = new Date().getFullYear();

  return (
    <main style={{ maxWidth: 720, margin: '0 auto', padding: '2rem 1rem' }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '2rem' }}>
        {brand.logo?.light && (
          <img
            src={`/${brand.logo.light}`}
            alt={brand.logo.alt_text || `${brand.display_name} logo`}
            style={{ height: 48 }}
          />
        )}
        <div style={{ flex: 1 }}>
          <h1 style={{ margin: 0 }}>{t('app.title', { defaultValue: brand.display_name })}</h1>
          <p style={{ margin: '0.25rem 0 0', color: 'var(--brand-text-muted, #6b7280)' }}>
            {t('app.tagline', { defaultValue: brand.tagline })}
          </p>
        </div>
        <LanguageSwitcher currentLang={i18n.language} onChange={(lng) => i18n.changeLanguage(lng)} />
      </header>

      <section>
        <h2>{t('nav.home')}</h2>
        <p>{t('app.welcome', { name: brand.display_name })}</p>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button>{t('actions.submit')}</button>
          <button style={{ background: 'var(--brand-secondary, #6b7280)' }}>
            {t('actions.cancel')}
          </button>
        </div>
      </section>

      <footer style={{ marginTop: '3rem', paddingTop: '1rem', borderTop: '1px solid var(--brand-border, #d0d7de)', fontSize: '0.85rem', color: 'var(--brand-text-muted, #6b7280)' }}>
        {t('footer.copyright', { year, company: brand.legal?.company_name || brand.display_name })}
        {brand.contact?.email && (
          <>
            {' · '}
            <a href={`mailto:${brand.contact.email}`}>{brand.contact.email}</a>
          </>
        )}
      </footer>
    </main>
  );
}

function LanguageSwitcher({ currentLang, onChange }) {
  return (
    <select
      value={currentLang?.split('-')[0] || 'en'}
      onChange={(e) => onChange(e.target.value)}
      aria-label="Language"
      style={{
        padding: '0.4em 0.6em',
        borderRadius: 6,
        border: '1px solid var(--brand-border, #d0d7de)',
        background: 'var(--brand-surface, #f6f8fa)',
        fontFamily: 'inherit',
      }}
    >
      {SUPPORTED_LOCALES.map((lng) => (
        <option key={lng} value={lng}>
          {lng.toUpperCase()}
        </option>
      ))}
    </select>
  );
}
