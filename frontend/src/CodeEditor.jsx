import Editor from '@monaco-editor/react'
import { langFor } from './editor'

const THEME = {
  base: 'vs-dark',
  inherit: true,
  rules: [],
  colors: { 'editor.background': '#0a0a0a' },
}

export default function CodeEditor({ path, value, onChange, height = '100%' }) {
  return (
    <Editor
      language={langFor(path || '')}
      value={value}
      theme="cd-dark"
      beforeMount={(monaco) => { monaco.editor.defineTheme('cd-dark', THEME) }}
      onChange={onChange}
      height={height}
      options={{
        fontSize: 12.5,
        minimap: { enabled: false },
        lineNumbers: 'on',
        scrollBeyondLastLine: false,
        tabSize: 2,
        wordWrap: 'on',
        automaticLayout: true,
      }}
    />
  )
}
