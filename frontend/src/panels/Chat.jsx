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
import React, { useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import {
  ApprovalCard, AskUserCard, EditBlock, PlanCard, ToolTimeline,
} from '../cards/chatCards.jsx'

// R59 P0: moved verbatim out of App.jsx. Becomes the `chat` panel in P1; the
// prompt row is a separate panel (Prompt.jsx).
export function Chat({ messages, streaming, onStop, onDecide, sessionId, suggestMode, onEditRevert, runId }) {
  // R67 #254: stick-to-bottom autoscroll. The old bottomRef.scrollIntoView()
  // fired on EVERY messages change - i.e. on every streaming delta - and
  // yanked the scroller to the bottom no matter where the user had scrolled
  // to read, pinning them to the tail of the conversation ("every activity
  // forces it up again"). scrollIntoView also walks ALL scrollable ancestors,
  // so it must never be used here. Instead: scroll the chat's own scroller,
  // and only while the user is at (or within 24px of) the bottom. Scrolling
  // up to read disarms it; scrolling back to the bottom re-arms it. Sending
  // your own message always re-arms it (the last message is then yours).
  const scrollRef = useRef(null)
  const stickRef = useRef(true)
  useEffect(() => { stickRef.current = true }, [sessionId])
  const onScroll = () => {
    const el = scrollRef.current
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
  }
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const userJustSent = messages.length > 0 && messages[messages.length - 1].role === 'user'
    if (stickRef.current || userJustSent) el.scrollTop = el.scrollHeight
  }, [messages])
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scrollRef} onScroll={onScroll} className="flex-1 space-y-3 overflow-y-auto p-4">
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : ''}>
            <div
              className={`inline-block max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-base ${
                m.role === 'user' ? 'bg-brand-700 text-brand-fg' : 'bg-neutral-800 text-neutral-200'
              }`}
            >
              {m.role === 'user'
                ? m.text
                : <ReactMarkdown>{m.text}</ReactMarkdown>}
              {m.streaming && <span className="animate-pulse">▍</span>}
            </div>
            {m.toolEvents && <ToolTimeline events={m.toolEvents} />}
            {m.review && (
              <div className="my-1 rounded border border-accent/50 bg-accent/15 p-2 text-xs">
                <div className="font-semibold text-accent">Reviewer findings</div>
                <pre className="whitespace-pre-wrap text-neutral-300">{m.review}</pre>
              </div>
            )}
            {m.edits && suggestMode && m.edits.map((ed, ei) => (
              <EditBlock key={ei} edit={ed} sessionId={sessionId}
                onRevert={() => onEditRevert(i, ed)} />
            ))}
            {m.ask && runId && <AskUserCard ask={m.ask} runId={runId} />}
            {m.gate && !m.gate.startsWith('plan:') && <ApprovalCard command={m.gate} onDecide={onDecide} />}
            {m.gate && m.gate.startsWith('plan:') && sessionId && (
              <>
                <PlanCard sessionId={sessionId} onDecide={onDecide} />
                <div className="my-1 flex gap-2">
                  <button className="rounded bg-brand-700 px-3 py-1 text-xs text-brand-fg hover:bg-brand-600"
                    onClick={() => onDecide('approve')}>Approve plan</button>
                  <button className="rounded bg-danger px-3 py-1 text-xs text-danger-fg hover:bg-danger/90"
                    onClick={() => onDecide('deny')}>Reject</button>
                </div>
              </>
            )}
          </div>
        ))}
        {streaming && (
          <button
            className="rounded border border-danger/60 px-2 py-1 text-xs text-danger hover:bg-danger/20"
            onClick={onStop}
          >
            ■ Stop
          </button>
        )}
      </div>
    </div>
  )
}
