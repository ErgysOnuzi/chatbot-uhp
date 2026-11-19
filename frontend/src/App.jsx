import { useEffect, useState } from 'react'
import Chat from './Chat.jsx'
import Admin from './Admin.jsx'
import Survey from './Survey.jsx'

function currentRoute() {
  const hash = window.location.hash
  if (hash.startsWith('#/admin')) return 'admin'
  if (hash.startsWith('#/pyetesori')) return 'survey'
  return 'chat'
}

export default function App() {
  const [route, setRoute] = useState(currentRoute())

  useEffect(() => {
    const onChange = () => setRoute(currentRoute())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  return (
    <div className="app">
      <header className="topbar">
        <a href="#/" className="brand">
          <span className="brand-mark">UHP</span>
          <span>
            <strong>Asistenti i Studentëve</strong>
            <small>Universiteti "Ukshin Hoti" Prizren</small>
          </span>
        </a>
        <nav>
          {route === 'chat' ? (
            <>
              <a href="#/pyetesori">Pyetësori</a>
              <a href="#/admin">Administrata</a>
            </>
          ) : (
            <a href="#/">Kthehu te chat-i</a>
          )}
        </nav>
      </header>
      <main className="content">
        {route === 'admin' ? <Admin /> : route === 'survey' ? <Survey /> : <Chat />}
      </main>
    </div>
  )
}
