import { useCallback, useEffect, useState } from 'react'
import { deleteDocument, getStats, listDocuments, login, uploadDocument } from './api.js'

const TOKEN_KEY = 'uhp-admin-token'

function loadToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

function saveToken(token) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ruajtja nuk është e mundur në këtë shfletues */
  }
}

function Login({ onLogin }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setError('')
    try {
      onLogin(await login(username, password))
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <form className="card login" onSubmit={submit}>
      <h2>Kyçu si administratë</h2>
      <label>
        Emri i përdoruesit
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
      </label>
      <label>
        Fjalëkalimi
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
        />
      </label>
      {error && <p className="form-error">{error}</p>}
      <button type="submit">Kyçu</button>
    </form>
  )
}

export default function Admin() {
  const [token, setToken] = useState(loadToken())
  const [documents, setDocuments] = useState([])
  const [stats, setStats] = useState(null)
  const [file, setFile] = useState(null)
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const logout = useCallback(() => {
    saveToken(null)
    setToken(null)
  }, [])

  const handleError = useCallback(
    (err) => {
      if (err.unauthorized) logout()
      setNotice(err.message)
    },
    [logout],
  )

  const refresh = useCallback(async () => {
    if (!token) return
    try {
      const [docs, st] = await Promise.all([listDocuments(token), getStats(token)])
      setDocuments(docs)
      setStats(st)
    } catch (err) {
      handleError(err)
    }
  }, [token, handleError])

  useEffect(() => {
    refresh()
  }, [refresh])

  if (!token) {
    return (
      <Login
        onLogin={(t) => {
          saveToken(t)
          setToken(t)
        }}
      />
    )
  }

  async function upload(e) {
    e.preventDefault()
    if (!file || !title.trim()) return
    setBusy(true)
    setNotice('Duke përpunuar dokumentin…')
    try {
      const result = await uploadDocument(token, file, title, category)
      setNotice(`"${result.title}" u ngarkua dhe u nda në ${result.chunks} pjesë.`)
      setFile(null)
      setTitle('')
      setCategory('')
      e.target.reset()
      refresh()
    } catch (err) {
      handleError(err)
    } finally {
      setBusy(false)
    }
  }

  async function remove(doc) {
    if (!window.confirm(`Ta fshij dokumentin "${doc.title}"?`)) return
    try {
      await deleteDocument(token, doc.id)
      setNotice(`"${doc.title}" u fshi.`)
      refresh()
    } catch (err) {
      handleError(err)
    }
  }

  return (
    <section className="admin">
      <div className="admin-head">
        <h2>Paneli i administratës</h2>
        <button className="ghost" onClick={logout}>
          Çkyçu
        </button>
      </div>

      {notice && <p className="notice">{notice}</p>}

      {stats && (
        <div className="stats">
          <div className="stat">
            <strong>{stats.conversations}</strong>
            <span>Biseda</span>
          </div>
          <div className="stat">
            <strong>{stats.questions}</strong>
            <span>Pyetje</span>
          </div>
          <div className="stat">
            <strong>{stats.answered_rate ?? '–'}%</strong>
            <span>Me përgjigje</span>
          </div>
          <div className="stat">
            <strong>
              {stats.feedback_positive} / {stats.feedback_negative}
            </strong>
            <span>Vlerësime po / jo</span>
          </div>
        </div>
      )}

      <form className="card" onSubmit={upload}>
        <h3>Ngarko dokument të ri</h3>
        <p className="hint">PDF, DOCX, TXT ose MD. PDF-të e skanuara (foto) nuk mund të lexohen.</p>
        <label>
          Skedari
          <input
            type="file"
            accept=".pdf,.docx,.txt,.md"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
        </label>
        <label>
          Titulli
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="p.sh. Rregullorja e studimeve" />
        </label>
        <label>
          Kategoria (opsionale)
          <input value={category} onChange={(e) => setCategory(e.target.value)} placeholder="p.sh. Provimet" />
        </label>
        <button type="submit" disabled={busy || !file || !title.trim()}>
          {busy ? 'Duke ngarkuar…' : 'Ngarko'}
        </button>
      </form>

      <div className="card">
        <h3>Dokumentet ({documents.length})</h3>
        {documents.length === 0 ? (
          <p className="hint">Ende nuk ka dokumente. Pa dokumente, chatbot-i nuk mund të përgjigjet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Titulli</th>
                <th>Kategoria</th>
                <th>Pjesë</th>
                <th>Data</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td>{doc.title}</td>
                  <td>{doc.category || '–'}</td>
                  <td>{doc.chunks}</td>
                  <td>{new Date(doc.created_at).toLocaleDateString('sq-AL')}</td>
                  <td>
                    <button className="danger" onClick={() => remove(doc)}>
                      Fshij
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {stats && (
        <div className="two-col">
          <div className="card">
            <h3>Pyetjet pa përgjigje</h3>
            <p className="hint">Këto tregojnë cilat dokumente mungojnë.</p>
            {stats.recent_unanswered.length === 0 ? (
              <p className="hint">Asnjë deri tani.</p>
            ) : (
              <ul>
                {stats.recent_unanswered.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            )}
          </div>
          <div className="card">
            <h3>Pyetjet më të shpeshta</h3>
            {stats.top_questions.length === 0 ? (
              <p className="hint">Asnjë deri tani.</p>
            ) : (
              <ol>
                {stats.top_questions.map((q, i) => (
                  <li key={i}>
                    {q.question} <span className="count">({q.count})</span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
