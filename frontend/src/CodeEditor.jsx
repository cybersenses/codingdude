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
import { useEffect, useRef } from 'react'
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

export default function CodeEditor({ path, value, onChange, onSelectionChange, reveal, height = '100%' }) {
  // R69 #261: reveal = {path, startLine, endLine, nonce}. The editor ref
  // only exists after monaco's async mount, so the latest reveal is also
  // kept in a ref and applied in handleMount when it arrived early.
  const editorRef = useRef(null)
  const monacoRef = useRef(null)
  const pendingRevealRef = useRef(null)

  function applyReveal(editor, monaco, r) {
    if (!editor || !monaco || !r) return
    const start = Math.max(1, r.startLine)
    const end = Math.max(start, r.endLine ?? start)
    const range = new monaco.Range(start, 1, end, 1)
    editor.setSelection(range)
    editor.revealLineInCenter(start)
    editor.createDecorationsCollection([{
      range,
      options: {
        isWholeLine: true,
        className: 'cd-reveal-line',
        overviewRuler: { color: '#4f7cff', position: 3 }, // monaco OverviewRulerLane.Right
      },
    }])
  }

  function handleMount(editor, monaco) {
    editorRef.current = editor
    monacoRef.current = monaco
    if (pendingRevealRef.current) {
      applyReveal(editor, monaco, pendingRevealRef.current)
      pendingRevealRef.current = null
    }
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

  // Child effects (monaco's value application) run before this parent
  // effect, so the model already holds the new content when we scroll.
  useEffect(() => {
    if (!reveal) return
    if (editorRef.current) applyReveal(editorRef.current, monacoRef.current, reveal)
    else pendingRevealRef.current = reveal
  }, [reveal?.nonce])

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
