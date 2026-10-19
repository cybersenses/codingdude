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
import Editor, { DiffEditor } from '@monaco-editor/react'
import { langFor } from './editor'

const THEME = {
  base: 'vs-dark',
  inherit: true,
  rules: [],
  colors: { 'editor.background': '#0a0a0a' },
}

function baseOptions() {
  return {
    fontSize: 12.5,
    minimap: { enabled: false },
    lineNumbers: 'on',
    scrollBeyondLastLine: false,
    tabSize: 2,
    wordWrap: 'on',
    automaticLayout: true,
  }
}

export default function CodeEditor({ path, value, onChange, onSelectionChange, height = '100%' }) {
  function handleMount(editor, monaco) {
    if (onSelectionChange) {
      // Only commit the selection on mouse-up / key-up: reporting mid-drag
      // mounts the action bar, shifts layout under the cursor and collapses
      // multi-line drags.
      const report = () => {
        const sel = editor.getSelection()
        const model = editor.getModel()
        onSelectionChange(model && sel && !sel.isEmpty() ? model.getValueInRange(sel) : '')
      }
      editor.onMouseUp(report)
      editor.onKeyUp(report)
    }
  }
  return (
    <Editor
      language={langFor(path || '')}
      value={value}
      theme="cd-dark"
      beforeMount={(monaco) => { monaco.editor.defineTheme('cd-dark', THEME) }}
      onMount={handleMount}
      onChange={onChange}
      height={height}
      options={baseOptions()}
    />
  )
}

// HITL review view: git HEAD baseline vs current buffer (agent's edits / draft).
export function CodeDiff({ path, original, modified, height = '100%' }) {
  const lang = langFor(path || '')
  return (
    <DiffEditor
      language={lang}
      original={original}
      modified={modified}
      theme="cd-dark"
      beforeMount={(monaco) => { monaco.editor.defineTheme('cd-dark', THEME) }}
      height={height}
      options={{ ...baseOptions(), renderSideBySide: true }}
    />
  )
}
