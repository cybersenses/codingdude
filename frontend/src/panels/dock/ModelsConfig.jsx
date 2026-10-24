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
import React, { useState } from 'react'
import { call } from '../../api'

// R50 #209: user-managed LLM configuration editor.
// Field-level edits stay in a local draft; Save PUTs the whole lineup and
// shows the server's validation error verbatim (it is the source of truth).
// Config fields must be stable module-level components: defining them inside
// ModelsConfig gave them a new identity on every render (the dock's 4s config
// poll re-renders constantly), remounting the inputs and stealing focus.
//
// R59 P0: moved verbatim out of App.jsx. Becomes the `config` panel in P2.
export function CfgTextField({ label, value, onChange, placeholder }) {
  return (
    <label className="flex items-center gap-2 text-[11px]">
      <span className="w-32 shrink-0 text-neutral-500">{label}</span>
      <input
        className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
        value={value ?? ''}
        placeholder={placeholder || ''}
        list="provider-model-suggest"
        onChange={(e) => onChange(e.target.value || null)}
      />
    </label>
  )
}

export function CfgNumField({ label, value, onChange }) {
  return (
    <label className="flex items-center gap-2 text-[11px]">
      <span className="w-32 shrink-0 text-neutral-500">{label}</span>
      <input
        type="number"
        className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      />
    </label>
  )
}

export function ModelsConfig({ data, setData }) {
  const cfg = data.config
  // Hooks must run unconditionally — the early returns below (error/loading)
  // used to come before the keys/verify state, changing the hook count
  // between renders and crashing React (#310).
  const [draft, setDraft] = useState(null)
  const [msg, setMsg] = useState(null)
  const [keys, setKeys] = useState(null) // {provider: {key, base_url, env_var, clear, del}}
  const [newProv, setNewProv] = useState({ name: '', key: '', base_url: '', env_var: '' })
  const [verify, setVerify] = useState(null)
  const [verifying, setVerifying] = useState(false)

  // No configError branch here: a failed /config/models fetch is surfaced by
  // the dock's own error banner (#231), one path for every tab.
  if (!cfg) {
    return <div className="rounded border border-line bg-surface p-4 text-xs text-ink-muted">Loading model configuration…</div>
  }

  const model = draft ?? JSON.parse(JSON.stringify(cfg.models))
  const set = (k, v) => setDraft({ ...model, [k]: v })

  // #212: providers are user-defined — the draft edits name/base_url/key per
  // provider; blank key keeps the stored one, the clear flag removes it.
  const keyDraft = keys ?? Object.fromEntries(
    Object.entries(cfg.providers || {}).map(([n]) => [n, {
      key: '',
      base_url: cfg.provider_defs?.[n]?.base_url || '',
      env_var: cfg.provider_defs?.[n]?.env_var || '',
      clear: false,
      del: false,
    }])
  )
  const setKey = (n, patch) => setKeys({ ...keyDraft, [n]: { ...keyDraft[n], ...patch } })

  const newProvDirty = !!(newProv.name || newProv.key || newProv.base_url)
  const save = async () => {
    setMsg(null)
    try {
      const body = {}
      if (draft) body.models = model
      if (keys !== null || newProvDirty) {
        body.providers = {}
        for (const [n, e] of Object.entries(keyDraft)) {
          if (e.del) { body.providers[n] = null; continue }
          const def = {}
          if (e.clear) def.api_key = null // drop the stored key on save
          else if (e.key) def.api_key = e.key
          if ((e.base_url || '') !== (cfg.provider_defs?.[n]?.base_url || ''))
            def.base_url = e.base_url || null
          if ((e.env_var || '') !== (cfg.provider_defs?.[n]?.env_var || ''))
            def.env_var = e.env_var || null
          if (Object.keys(def).length) body.providers[n] = def
        }
        if (newProv.name && (newProv.key || newProv.base_url)) {
          body.providers[newProv.name.trim()] = {
            api_key: newProv.key || null,
            base_url: newProv.base_url || null,
            env_var: newProv.env_var || null,
          }
        }
      }
      const r = await call('/config/models', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      setData((d) => ({ ...d, config: r.effective }))
      setDraft(null)
      setKeys(null)
      setNewProv({ name: '', key: '', base_url: '', env_var: '' })
      setMsg({ ok: true, text: 'Saved — applies from the next run.' })
    } catch (err) {
      setMsg({ ok: false, text: String(err instanceof Error ? err.message : err) })
    }
  }

  const testKeys = async () => {
    setVerifying(true); setVerify(null); setMsg(null)
    try {
      const r = await call('/config/verify')
      setVerify(r.providers)
    } catch (err) {
      setMsg({ ok: false, text: String(err instanceof Error ? err.message : err) })
    } finally { setVerifying(false) }
  }

  const field = (label, k, placeholder) => (
    <CfgTextField key={k} label={label} value={model[k]} placeholder={placeholder} onChange={(v) => set(k, v)} />
  )
  const numField = (label, k) => (
    <CfgNumField key={k} label={label} value={model[k]} onChange={(v) => set(k, v)} />
  )

  return (
    <div className="flex h-full flex-col gap-3 overflow-auto p-1 text-ink">
      <div className="text-[10px] text-neutral-500">
        ~/.codingdude/config.toml — provider keys are stored there, masked in this UI.
      </div>
      {(cfg.warnings || []).length > 0 && (
        <div className="rounded border border-warning/40 bg-warning/10 px-2 py-1 text-[11px] text-warning">
          {(cfg.warnings || []).map((w) => <div key={w}>{w}</div>)}
        </div>
      )}
      <div className="space-y-1.5 rounded border border-line bg-surface p-3">
        <div className="text-[10px] uppercase tracking-wide text-ink-muted">Model lineup (provider:model)</div>
        {field('main', 'main')}
        {field('subagent', 'subagent')}
        {field('fallback', 'fallback')}
        {field('fallback base url', 'fallback_base_url', 'optional endpoint override')}
        <div className="text-[10px] text-neutral-500">
          Z.AI has two plans with different endpoints. GLM Coding Plan keys are rejected by the
          standard API —{' '}
          <button
            type="button"
            className="text-accent underline hover:opacity-80"
            onClick={() => set('fallback_base_url', 'https://api.z.ai/api/coding/paas/v4')}
          >set the coding-plan endpoint</button>
        </div>
        {field('vision', 'vision', 'e.g. zai:glm-5v (optional)')}
        <label className="flex items-center gap-2 text-[11px]">
          <span className="w-32 shrink-0 text-neutral-500">thinking</span>
          <select
            className="min-w-0 flex-1 rounded border border-line bg-surface px-1 py-0.5 font-mono text-[11px] text-ink"
            value={model.thinking ?? ''}
            onChange={(e) => set('thinking', e.target.value || null)}
          >
            <option value="">(provider default)</option>
            <option value="off">off</option>
            {(cfg.thinking_levels || []).map((lvl) => (
              <option key={lvl} value={lvl}>{lvl}</option>
            ))}
          </select>
        </label>
        {numField('max tokens', 'max_tokens')}
        {numField('context limit', 'context_limit')}
        {numField('request limit', 'request_limit')}
      </div>

      <div className="space-y-1.5 rounded border border-line bg-surface p-3">
        <div className="text-[10px] uppercase tracking-wide text-ink-muted">Providers</div>
        <div className="text-[10px] text-neutral-500">
          User-defined OpenAI-compatible providers. A name with a base URL makes
          `name:model` bindings work everywhere. Keys stored in
          ~/.codingdude/config.toml, never displayed; blank keeps a set key.
        </div>
        <datalist id="provider-model-suggest">
          {(cfg.provider_prefixes || []).map((p) => (
            <option key={p} value={`${p}:`} />
          ))}
        </datalist>
        {Object.entries(keyDraft).map(([name, e]) => e.del ? null : (
          <div key={name} className="flex flex-wrap items-center gap-2 text-[11px]">
            <span className="w-28 shrink-0 font-mono text-neutral-500">{name}</span>
            <input
              type="password"
              className="w-40 min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
              value={e.key}
              placeholder={e.clear ? 'cleared on save' : (cfg.providers?.[name] ? '● set — leave blank to keep' : 'api key')}
              onChange={(ev) => setKey(name, { key: ev.target.value, clear: false })}
            />
            <input
              className="w-48 min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
              value={e.base_url}
              placeholder="base URL (https://…/v1)"
              onChange={(ev) => setKey(name, { base_url: ev.target.value })}
            />
            <input
              className="w-32 min-w-0 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
              value={e.env_var}
              placeholder="env var (optional)"
              onChange={(ev) => setKey(name, { env_var: ev.target.value })}
            />
            {cfg.providers?.[name] && (
              <button type="button" title={e.clear ? 'undo clear' : 'clear stored key on save'}
                className="rounded border border-line px-1.5 py-0.5 text-[10px] text-neutral-400 hover:text-danger"
                onClick={() => setKey(name, { clear: !e.clear, key: '' })}
              >{e.clear ? 'undo' : 'clear'}</button>
            )}
            <button type="button" title="delete this provider"
              className="rounded border border-line px-1.5 py-0.5 text-[10px] text-neutral-400 hover:text-danger"
              onClick={() => setKey(name, { del: true })}
            >remove</button>
            {verify && name in verify && (
              <span className={verify[name].ok ? 'text-success' : 'text-danger'}>
                {verify[name].ok ? '✓ auth ok' : `✗ ${verify[name].status || ''} ${verify[name].detail || 'failed'}`.slice(0, 60)}
              </span>
            )}
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <span className="w-28 shrink-0 text-[10px] uppercase text-neutral-500">add</span>
          <input
            className="w-28 min-w-0 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
            placeholder="name" value={newProv.name}
            onChange={(e) => setNewProv({ ...newProv, name: e.target.value.replace(/[^A-Za-z0-9_-]/g, '').replace(/^[^A-Za-z0-9]+/, '') })}
          />
          <input
            type="password"
            className="w-40 min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
            placeholder="api key" value={newProv.key}
            onChange={(e) => setNewProv({ ...newProv, key: e.target.value })}
          />
          <input
            className="w-48 min-w-0 flex-1 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
            placeholder="base URL (https://…/v1)" value={newProv.base_url}
            onChange={(e) => setNewProv({ ...newProv, base_url: e.target.value })}
          />
          <input
            className="w-32 min-w-0 rounded border border-line bg-surface px-2 py-0.5 font-mono text-[11px] text-ink"
            placeholder="env var (optional)" value={newProv.env_var || ''}
            onChange={(e) => setNewProv({ ...newProv, env_var: e.target.value })}
          />
        </div>
        <button
          type="button"
          className="rounded border border-line px-2 py-0.5 text-[11px] text-neutral-400 hover:text-ink disabled:opacity-40"
          disabled={verifying}
          onClick={testKeys}
        >{verifying ? 'Testing…' : 'Test keys'}</button>
      </div>

      {msg && (
        <div className={`rounded px-2 py-1 text-[11px] ${msg.ok ? 'bg-success/15 text-brand-300' : 'bg-danger/15 text-danger'}`}>
          {msg.text}
        </div>
      )}
      <div className="flex gap-2">
        <button
          className="rounded bg-brand-600 px-3 py-1 text-[11px] text-white hover:bg-brand-500 disabled:opacity-40"
          disabled={!draft && keys === null && !newProvDirty}
          onClick={save}
        >Save</button>
        <button
          className="rounded border border-line px-3 py-1 text-[11px] text-neutral-400 hover:text-ink disabled:opacity-40"
          disabled={!draft && !keys}
          onClick={() => { setDraft(null); setKeys(null); setMsg(null); setVerify(null) }}
        >Revert</button>
      </div>
    </div>
  )
}
