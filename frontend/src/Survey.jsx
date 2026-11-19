import { useEffect, useState } from 'react'
import { getSurvey, submitSurvey } from './api.js'

const SCALE = [1, 2, 3, 4, 5]
const DONE_KEY = 'uhp-survey-done'

function alreadySubmitted() {
  try {
    return localStorage.getItem(DONE_KEY) === '1'
  } catch {
    return false
  }
}

export default function Survey() {
  const [form, setForm] = useState(null)
  const [answers, setAnswers] = useState([])
  const [program, setProgram] = useState('')
  const [comment, setComment] = useState('')
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const [done, setDone] = useState(alreadySubmitted())

  useEffect(() => {
    getSurvey()
      .then((data) => {
        setForm(data)
        setAnswers(data.statements.map(() => 0))
      })
      .catch((err) => setError(err.message))
  }, [])

  async function submit(event) {
    event.preventDefault()
    if (answers.some((a) => a === 0)) {
      setError('Ju lutem vlerësoni të gjitha pohimet.')
      return
    }
    setSending(true)
    setError('')
    try {
      await submitSurvey(answers, program, comment.trim())
      try {
        localStorage.setItem(DONE_KEY, '1')
      } catch {
        /* pa localStorage */
      }
      setDone(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  if (done) {
    return (
      <section className="survey">
        <div className="card">
          <h2>Faleminderit!</h2>
          <p className="hint">Përgjigjet tuaja u ruajtën. Ato përdoren vetëm në mënyrë anonime për vlerësimin e chatbot-it.</p>
          <a href="#/">Kthehu te chat-i</a>
        </div>
      </section>
    )
  }

  return (
    <section className="survey">
      <form className="card" onSubmit={submit}>
        <h2>Pyetësori për chatbot-in</h2>
        <p className="hint">
          Plotësojeni pasi ta keni përdorur chatbot-in me disa pyetje. Pyetësori është anonim: nuk kërkohet emri as
          emaili, dhe përgjigjet nuk ruhen bashkë me IP-në. Për çdo pohim zgjidhni sa pajtoheni: 1 = nuk pajtohem
          aspak, 5 = pajtohem plotësisht.
        </p>
        {!form && !error && <p className="hint">Duke u ngarkuar…</p>}
        {form && (
          <>
            <ol className="survey-list">
              {form.statements.map((statement, i) => (
                <li key={i}>
                  <span>{statement}</span>
                  <div className="scale" role="radiogroup" aria-label={statement}>
                    {SCALE.map((score) => (
                      <label key={score} className={answers[i] === score ? 'selected' : ''}>
                        <input
                          type="radio"
                          name={`q${i}`}
                          value={score}
                          checked={answers[i] === score}
                          onChange={() => setAnswers((prev) => prev.map((a, j) => (j === i ? score : a)))}
                        />
                        {score}
                      </label>
                    ))}
                  </div>
                </li>
              ))}
            </ol>
            <label>
              Programi i studimit (opsional)
              <select value={program} onChange={(e) => setProgram(e.target.value)}>
                <option value="">—</option>
                {form.programs.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Çfarë do të përmirësonit? Cilat pyetje nuk i gjetën përgjigje? (opsional)
              <textarea rows={4} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} />
            </label>
            {error && <p className="form-error">{error}</p>}
            <button type="submit" disabled={sending}>
              {sending ? 'Duke dërguar…' : 'Dërgo'}
            </button>
          </>
        )}
        {!form && error && <p className="form-error">{error}</p>}
      </form>
    </section>
  )
}
