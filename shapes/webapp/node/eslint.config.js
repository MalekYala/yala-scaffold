export default [
  {
    files: ['src/**/*.{js,jsx}', 'scripts/**/*.js', 'server.js', 'qa_check.js', 'vite.config.js'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
      globals: {
        AbortController: 'readonly',
        console: 'readonly',
        document: 'readonly',
        fetch: 'readonly',
        process: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        URL: 'readonly',
      },
    },
    rules: {
      'no-undef': 'error',
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
    },
  },
  {
    files: ['src/**/*.jsx'],
    rules: {
      'no-unused-vars': 'off',
    },
  },
];
