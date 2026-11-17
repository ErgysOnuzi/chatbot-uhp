import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { sendFeedback, streamChat } from './api.js'

const SUGGESTIONS = [
  'Si bëhet paraqitja e provimeve?',
  'Cilat janë hapat për dorëzimin e temës së diplomës?',
  'Sa është kufiri i plagjiaturës për temën e diplomës?',
  'Kur fillon afati i provimeve në janar?',
]

const WELCOME =
  'Përshëndetje! Jam asistenti virtual i Universitetit "Ukshin Hoti" Prizren. ' +
  'Më pyet për provimet, oraret, afatet ose procedurat e fakultetit.'

export default function Chat() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [conversationId, setConversationId] = useState(null)
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Përditëson mesazhin e fundit (përgjigjen që po vjen).
  const updateLast = (change) =>
    setMessages((prev) => {
      const next = [...prev]
      next[next.length - 1] = { ...next[next.length - 1], ...change(next[next.length - 1]) }
      return next
    })

  async function ask(text) {
    const question = text.trim()
    if (!question || loading) return
    setInput('')
    setLoading(true)
    setMessages((prev) => [
      ...prev,
      { role: 'user', content: question },
      { role: 'assistant', content: '', sources: [], pending: true },
    ])

    try {
      for await (const event of streamChat(question, conversationId)) {
        if (event.type === 'meta') {
          setConversationId(event.conversation_id)
          updateLast(() => ({ sources: event.sources }))
        } else if (event.type === 'token') {
          updateLast((m) => ({ content: m.content + event.text }))
        } else if (event.type === 'error') {
          updateLast(() => ({ content: event.text, error: true }))
        } else if (event.type === 'done') {
          updateLast((m) => ({
            id: event.message_id,
            pending: false,
            sources: event.answered ? m.sources : [],
          }))
        }
      }
    } catch (err) {
      updateLast(() => ({ content: err.message, error: true, pending: false }))
    } finally {
      updateLast(() => ({ pending: false }))
      setLoading(false)
    }
  }

  async function rate(index, value) {
    const message = messages[index]
    if (!message.id || message.feedback) return
    setMessages((prev) => prev.map((m, i) => (i === index ? { ...m, feedback: value } : m)))
    try {
      await sendFeedback(message.id, value)
    } catch {
      /* vlerësimi nuk është kritik */
    }
  }

  function newConversation() {
    setMessages([])
    setConversationId(null)
  }

  return (
    <section className="chat">
      <div className="messages">
        <div className="bubble assistant">
          <p>{WELCOME}</p>
        </div>

        {messages.length === 0 && (
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => ask(s)}>
                {s}
              </button>
            ))}
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role} ${m.error ? 'error' : ''}`}>
            {m.role === 'assistant' ? (
              <>
                {m.pending && !m.content ? (
                  <span className="typing" aria-label="Duke shkruar">
                    <i />
                    <i />
                    <i />
                  </span>
                ) : (
                  <ReactMarkdown>{m.content}</ReactMarkdown>
                )}
                {!m.pending && m.sources?.length > 0 && (
                  <p className="sources">
                    Burimi:{' '}
                    {m.sources.map((s, index) => (
                      <span key={s.id}>
                        {index > 0 && ', '}
                        {s.source_url?.startsWith('http://') || s.source_url?.startsWith('https://') ? (
                          <a href={s.source_url} target="_blank" rel="noreferrer">
                            {s.title}
                          </a>
                        ) : (
                          s.title
                        )}
                      </span>
                    ))}
                  </p>
                )}
                {!m.pending && m.id && !m.error && (
                  <div className="feedback">
                    {m.feedback ? (
                      <span>Faleminderit për vlerësimin.</span>
                    ) : (
                      <>
                        <span>A ju ndihmoi?</span>
                        <button onClick={() => rate(i, 1)}>Po</button>
                        <button onClick={() => rate(i, -1)}>Jo</button>
                      </>
                    )}
                  </div>
                )}
              </>
            ) : (
              <p>{m.content}</p>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault()
          ask(input)
        }}
      >
        {messages.length > 0 && (
          <button type="button" className="ghost" onClick={newConversation} disabled={loading}>
            Bisedë e re
          </button>
        )}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Shkruani pyetjen tuaj…"
          maxLength={1000}
          disabled={loading}
          aria-label="Pyetja"
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Dërgo
        </button>
      </form>
      <p className="disclaimer">
        Përgjigjet bazohen në dokumentet zyrtare të universitetit. Për raste specifike kontaktoni administratën.
      </p>
    </section>
  )
}
