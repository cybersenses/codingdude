import react from 'eslint-plugin-react';
import globals from 'globals';

// Vite injects these at build time (see vite.config define).
const viteDefines = {
  __APP_VERSION__: 'readonly',
  __BUILD_TIME__: 'readonly',
  __GIT_SHA__: 'readonly',
};

export default [
  {
    files: ['src/**/*.jsx'],
    plugins: { react },
    languageOptions: {
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...viteDefines },
    },
    rules: {
      // The AgentStrip crash class: usage without definition — esbuild never catches it.
      'react/jsx-no-undef': 'error',
      'no-undef': 'error',
      'react/jsx-uses-vars': 'error',
    },
  },
];
