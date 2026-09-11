"""Atomic patch: visible frontend build stamp + backend version/boot marker.

Edits three files (vite.config.js, server.py, App.jsx). Validate-then-write.
Run from repo root:  python _version_patch.py
"""
import pathlib
import sys

EDITS = [
    # ---- vite.config.js: inject version + build time ----
    ("frontend/vite.config.js",
     "import { defineConfig } from 'vite'\n"
     "import react from '@vitejs/plugin-react'\n"
     "import tailwindcss from '@tailwindcss/vite'\n"
     "\n"
     "export default defineConfig({\n"
     "  plugins: [react(), tailwindcss()],\n",
     "import { defineConfig } from 'vite'\n"
     "import react from '@vitejs/plugin-react'\n"
     "import tailwindcss from '@tailwindcss/vite'\n"
     "import { readFileSync } from 'node:fs'\n"
     "\n"
     "const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'))\n"
     "\n"
     "export default defineConfig({\n"
     "  plugins: [react(), tailwindcss()],\n"
     "  // Build-time constants so the running bundle identifies itself on screen.\n"
     "  define: {\n"
     "    __APP_VERSION__: JSON.stringify(pkg.version),\n"
     "    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),\n"
     "  },\n"),
    # ---- server.py: version + boot time on /health ----
    ("src/codingdude/server.py",
     "import sys\nfrom pathlib import Path\n",
     "import sys\nfrom datetime import UTC, datetime\nfrom pathlib import Path\n"),
    ("src/codingdude/server.py",
     "from .config import config_home\n",
     "from . import __version__\nfrom .config import config_home\n"),
    ("src/codingdude/server.py",
     "HOST = '127.0.0.1'  # localhost only, by design\n",
     "HOST = '127.0.0.1'  # localhost only, by design\n\n"
     "# When this server process started — surfaced in the UI so a restart is\n"
     "# visible (a stale server shows an old boot time).\n"
     "_STARTED_AT = datetime.now(UTC).isoformat()\n"),
    ("src/codingdude/server.py",
     "    @app.get('/health')\n    def health() -> dict:\n        return {'ok': True}\n",
     "    @app.get('/health')\n    def health() -> dict:\n"
     "        return {'ok': True, 'version': __version__, 'started_at': _STARTED_AT}\n"),
    # ---- App.jsx: build constants ----
    ("frontend/src/App.jsx",
     "import { api, authLocal, call, checkAuth, login } from './api'\n",
     "import { api, authLocal, call, checkAuth, login } from './api'\n\n"
     "// Injected at build time by vite.config.js — makes the running build visible\n"
     "// so a stale bundle (or a server that hasn't restarted) is obvious on screen.\n"
     "const UI_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'dev'\n"
     "const UI_BUILD = typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : ''\n"
     "const shortStamp = (iso) => (iso ? iso.slice(5, 16).replace('T', ' ') : '')\n"),
    # ---- App.jsx: fetch backend marker ----
    ("frontend/src/App.jsx",
     "  const [status, setStatus] = useState('idle')\n",
     "  const [status, setStatus] = useState('idle')\n  const [srv, setSrv] = useState(null)\n"),
    ("frontend/src/App.jsx",
     "  // Notifications: tab title + sound + toast on run state changes.\n",
     "  // Backend build marker (version + boot time): fetched once logged in.\n"
     "  useEffect(() => {\n"
     "    if (!loggedIn) return\n"
     "    call('/health').then(setSrv).catch(() => {})\n"
     "  }, [loggedIn])\n\n"
     "  // Notifications: tab title + sound + toast on run state changes.\n"),
    # ---- App.jsx: render it in the footer ----
    ("frontend/src/App.jsx",
     "        <span className={streaming ? 'text-brand-400' : ''}>{status}</span>\n      </footer>\n",
     "        <span className=\"text-neutral-600\" title=\"frontend build · backend server build\">\n"
     "          ui v{UI_VERSION} {shortStamp(UI_BUILD)} · srv v{srv?.version ?? '?'} {shortStamp(srv?.started_at)}\n"
     "        </span>\n"
     "        <span className={streaming ? 'text-brand-400' : ''}>{status}</span>\n      </footer>\n"),
]


def main() -> int:
    for path, old, new in EDITS:
        f = pathlib.Path(path)
        s = f.read_text(encoding='utf-8')
        n = s.count(old)
        if n != 1:
            print(f'VALIDATE FAIL {path}: {n} matches (expected 1)')
            print(repr(old[:160]))
            return 1
    for path, old, new in EDITS:
        f = pathlib.Path(path)
        f.write_text(f.read_text(encoding='utf-8').replace(old, new, 1), encoding='utf-8')
        print('patched', path)
    print('DONE')
    return 0


if __name__ == '__main__':
    sys.exit(main())
