// Brand kit loader.
//
// In production, the brand is baked into index.html (see vite.config.js)
// so initial paint uses the right colors. This module exposes the full
// brand/config.json to React components via a context, loaded lazily at
// startup from /brand/config.json (served statically by Fastify).
//
// Why a runtime fetch at all? So operators can override brand/config.json
// via a volume mount (see docker-compose.yml) and the change shows up
// without a rebuild.

import { createContext, useContext, useEffect, useState } from 'react';

const BrandContext = createContext(null);

export function BrandProvider({ children }) {
  const [brand, setBrand] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch('/brand/config.json')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setBrand)
      .catch((err) => {
        // Fall back to a minimal default brand so the app keeps rendering
        console.warn('brand config load failed, using defaults', err);
        setBrand({
          name: 'app',
          display_name: 'App',
          tagline: '',
          colors: {},
          fonts: {},
          logo: {},
          contact: {},
        });
        setError(err);
      });
  }, []);

  if (!brand) {
    // Minimal loader — matches the body styles from index.html so no flash
    return (
      <div style={{ padding: '2rem', textAlign: 'center' }}>Loading…</div>
    );
  }

  return (
    <BrandContext.Provider value={{ brand, error }}>
      {children}
    </BrandContext.Provider>
  );
}

export function useBrand() {
  const ctx = useContext(BrandContext);
  if (!ctx) throw new Error('useBrand must be used inside <BrandProvider>');
  return ctx.brand;
}
