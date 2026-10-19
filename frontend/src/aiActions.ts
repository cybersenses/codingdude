// CodingDude — a personal coding agent.
// Copyright (C) 2025 Cyberflex (https://www.cyberflex.io)
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as published
// by the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.
// Selection AI actions (#83): turn a highlighted snippet into a scoped agent prompt.

export interface AiAction {
  id: 'explain' | 'fix' | 'optimise' | 'improve'
  label: string
  directive: string
}

export const ACTIONS: AiAction[] = [
  { id: 'explain', label: 'Explain', directive: 'Explain what this code does, step by step.' },
  { id: 'fix', label: 'Fix', directive: 'Find and fix the bug or problem in this code.' },
  { id: 'optimise', label: 'Optimise', directive: 'Optimise this code for performance. Keep behavior identical.' },
  { id: 'improve', label: 'Improve', directive: 'Improve this code (clarity, naming, structure). Keep behavior identical.' },
]

export function actionById(id: string): AiAction | undefined {
  return ACTIONS.find((a) => a.id === id)
}

export function buildActionPrompt(
  actionId: string,
  path: string,
  selection: string,
): string | null {
  const action = actionById(actionId)
  const code = selection.replace(/^\s*\n+/, '').replace(/\n\s*$/, '')
  if (!action || !code.trim()) return null
  return [
    `${action.directive}`,
    '',
    `File: ${path || '(unsaved)'}`,
    'Selected code:',
    '```',
    code,
    '```',
    '',
    'The snippet above may be out of context — read the file for surroundings before changing anything.',
  ].join('\n')
}
