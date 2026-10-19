/*
 * CodingDude — a personal coding agent.
 * Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published
 * by the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */
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
