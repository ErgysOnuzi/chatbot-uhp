import { useCallback, useEffect, useState } from 'react'
import {
  deleteDocument,
  getJob,
  getStats,
  getSurveyResults,
  listDocuments,
  login,
  pruneExcluded,
  startCrawl,
  startFetchOfficial,
  uploadDocument,
} from './api.js'
import DomainSetup from './DomainSetup.jsx'

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
  const [survey, setSurvey] = useState(null)
  const [file, setFile] = useState(null)
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [job, setJob] = useState(null)
  const [pruneList, setPruneList] = useState(null)

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
      const [docs, st, sv] = await Promise.all([listDocuments(token), getStats(token), getSurveyResults(token)])
      setDocuments(docs)
      setStats(st)
      setSurvey(sv)
    } catch (err) {
      handleError(err)
    }
  }, [token, handleError])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    if (!job || job.status !== 'running' || !token) return undefined
    const timer = setTimeout(async () => {
      try {
        const next = await getJob(token, job.id)
        setJob(next)
        if (next.status !== 'running') refresh()
      } catch (err) {
        handleError(err)
      }
    }, 3000)
    return () => clearTimeout(timer)
  }, [job, token, refresh, handleError])

  async function runJob(start) {
    try {
      setJob(await start(token))
    } catch (err) {
      handleError(err)
    }
  }

  async function prune(apply) {
    if (apply && !window.confirm(`Të fshihen ${pruneList?.count ?? ''} dokumente? Ky veprim nuk kthehet.`)) return
    try {
      const result = await pruneExcluded(token, apply)
      setPruneList(apply ? null : result)
      setNotice(apply ? `U fshinë ${result.count} dokumente.` : `${result.count} dokumente do të fshiheshin.`)
      if (apply) refresh()
    } catch (err) {
      handleError(err)
    }
  }

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

      <DomainSetup token={token} onError={handleError} setNotice={setNotice} />

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
        <h3>Mirëmbajtja e bazës së njohurive</h3>
        <p className="hint">Punët ekzekutohen në server, një nga një. Crawl-i mund të zgjasë deri në 15 minuta.</p>
        <div className="actions">
          <button onClick={() => runJob(startFetchOfficial)} disabled={job?.status === 'running'}>Ngarko rregulloret zyrtare</button>
          <button onClick={() => runJob(startCrawl)} disabled={job?.status === 'running'}>Rifresko faqet (crawl)</button>
          <button className="ghost" onClick={() => prune(false)}>Shiko dokumentet e vjetra</button>
        </div>
        {pruneList && pruneList.count > 0 && (
          <>
            <ul className="prune-list">
              {pruneList.documents.map((d) => (
                <li key={d.id}>{d.title} <span className="count">({d.reason})</span></li>
              ))}
            </ul>
            <button className="danger" onClick={() => prune(true)}>Fshi këto {pruneList.count} dokumente</button>
          </>
        )}
        {job && (
          <div className="job">
            <strong>{job.kind}: {job.status === 'running' ? 'duke punuar…' : job.status === 'done' ? 'përfundoi' : 'dështoi'}</strong>
            <pre>{job.log.join('\n')}</pre>
          </div>
        )}
      </div>

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
                  <td>
                    {doc.source_url ? (
                      <a href={doc.source_url} target="_blank" rel="noreferrer">
                        {doc.title}
                      </a>
                    ) : (
                      doc.title
                    )}
                  </td>
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

      {survey && (
        <div className="card survey-results">
          <h3>Pyetësori i studentëve</h3>
          <p className="hint">
            {survey.responses} përgjigje anonime. Lidhja për studentët: <a href="#/pyetesori">{window.location.origin}/#/pyetesori</a>
          </p>
          {survey.responses > 0 && (
            <>
              <table>
                <thead>
                  <tr>
                    <th>Pohimi</th>
                    <th>Mesatarja</th>
                    <th>Pajtohen (4–5)</th>
                    <th>1 / 2 / 3 / 4 / 5</th>
                  </tr>
                </thead>
                <tbody>
                  {survey.statements.map((s) => (
                    <tr key={s.statement}>
                      <td>{s.statement}</td>
                      <td>{s.mean?.toFixed(2)}</td>
                      <td>{s.agree_share}%</td>
                      <td className="bar">{s.distribution.join(' / ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {survey.comments.length > 0 && (
                <>
                  <h3>Komentet</h3>
                  <ul>
                    {survey.comments.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </div>
      )}
    </section>
  )
}
