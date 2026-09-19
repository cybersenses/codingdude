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
