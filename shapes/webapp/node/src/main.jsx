// Entry point — bootstraps React, i18next, and brand loading.
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { I18nextProvider } from 'react-i18next';

import i18n from './i18n.js';
import { BrandProvider } from './brand.jsx';
import App from './App.jsx';

const root = createRoot(document.getElementById('root'));

root.render(
  <StrictMode>
    <I18nextProvider i18n={i18n}>
      <BrandProvider>
        <App />
      </BrandProvider>
    </I18nextProvider>
  </StrictMode>
);
