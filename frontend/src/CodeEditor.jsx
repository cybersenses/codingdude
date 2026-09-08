import CodeMirror from '@uiw/react-codemirror'
import { oneDark } from '@codemirror/theme-one-dark'
import { javascript } from '@codemirror/lang-javascript'
import { python } from '@codemirror/lang-python'
import { markdown as markdownLang } from '@codemirror/lang-markdown'
import { html } from '@codemirror/lang-html'
import { css } from '@codemirror/lang-css'

function langFor(path) {
  const ext = path.split('.').pop().toLowerCase()
  if (['js', 'jsx', 'mjs'].includes(ext)) return javascript()
  if (['ts', 'tsx'].includes(ext)) return javascript({ typescript: true })
  if (ext === 'py') return python()
  if (['md', 'markdown'].includes(ext)) return markdownLang()
  if (['html', 'htm'].includes(ext)) return html()
  if (ext === 'css') return css()
  return []
}

export default function CodeEditor({ path, value, onChange, height = '100%' }) {
  return (
    <CodeMirror
      value={value}
      height={height}
      theme={oneDark}
      extensions={langFor(path || '')}
      basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: true }}
      onChange={onChange}
      style={{ fontSize: 12.5 }}
    />
  )
}
