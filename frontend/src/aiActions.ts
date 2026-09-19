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
