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
// R59 P2: the shell context shared by Workspace.jsx and workspace/panels.jsx.
// Extracted from Workspace.jsx so the panel module does not import the shell
// module that imports the panel module (a cycle bundlers resolve badly).
import { createContext, useContext } from 'react'

// Panels read their session/workdir/store wiring from this context rather
// than dockview `params`: params are serialized into the saved layout, so
// they cannot carry callbacks or live state. React portals keep the dock's
// panels inside the provider's tree, so context reaches them wherever they
// are docked.
//
// P4 caveat: a POPOUT panel is a separate document with its own React root
// and will not see this provider. Popout support must move this to a
// module-level store at that point (tech design §4.3/§4.7).
export const WorkspaceContext = createContext(null)

export function useShell() {
  const shell = useContext(WorkspaceContext)
  if (!shell) throw new Error('workspace panel rendered outside the shell provider')
  return shell
}
