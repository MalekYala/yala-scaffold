// Vite config for <name>.
//
// Key features:
//   - React + HMR in dev
//   - brand/config.json values become CSS variables at build time
//   - locales/ is copied into the built dist/ so i18next can fetch them

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync, cpSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const buildOutDir = process.env.BUILD_OUT_DIR || 'dist';

// Read brand config once so we can inject its values into both CSS and HTML.
const brandConfigPath = resolve(__dirname, 'brand/config.json');
const brand = existsSync(brandConfigPath)
  ? JSON.parse(readFileSync(brandConfigPath, 'utf8'))
  : { colors: {}, fonts: {}, display_name: 'App' };

// CSS variables derived from brand.colors and brand.fonts.
// Injected into every page via a <style> tag — see index.html.
const brandCssVars = [
  ...Object.entries(brand.colors || {}).map(([k, v]) => `--brand-${k.replace(/_/g, '-')}: ${v};`),
  ...Object.entries(brand.fonts || {}).map(([k, v]) => `--brand-font-${k.replace(/_/g, '-')}: ${v};`),
].join('\n    ');

export default defineConfig({
  plugins: [
    react(),
    {
      // Inject brand values into index.html at transform time.
      name: 'inject-brand',
      transformIndexHtml(html) {
        return html
          .replace(/__BRAND_TITLE__/g, brand.display_name || brand.name || 'App')
          .replace(/__BRAND_TAGLINE__/g, brand.tagline || '')
          .replace(/__BRAND_CSS_VARS__/g, brandCssVars)
          .replace(/__BRAND_FAVICON__/g, brand.logo?.favicon || 'brand/favicon.svg')
          .replace(/__BRAND_OG_TITLE__/g, brand.social?.og_title || brand.display_name || '')
          .replace(/__BRAND_OG_DESCRIPTION__/g, brand.social?.og_description || brand.tagline || '');
      },
    },
    {
      // Copy locales/ and brand/ into the build output so i18next-http-backend
      // and the /api/brand endpoint have something to serve.
      name: 'copy-locales-and-brand',
      closeBundle() {
        const dist = resolve(__dirname, buildOutDir);
        cpSync(resolve(__dirname, 'locales'), resolve(dist, 'locales'), { recursive: true });
        cpSync(resolve(__dirname, 'brand'), resolve(dist, 'brand'), { recursive: true });
      },
    },
  ],
  server: {
    host: '127.0.0.1',
    port: parseInt(process.env.VITE_PORT || '5173', 10),
  },
  build: {
    outDir: buildOutDir,
    emptyOutDir: true,
    sourcemap: true,
  },
});
