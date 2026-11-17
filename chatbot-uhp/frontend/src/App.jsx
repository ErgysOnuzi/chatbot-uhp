import { useEffect, useState } from 'react'
import Chat from './Chat.jsx'
import Admin from './Admin.jsx'

function currentRoute() {
  return window.location.hash.startsWith('#/admin') ? 'admin' : 'chat'
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
          {route === 'chat' ? <a href="#/admin">Administrata</a> : <a href="#/">Kthehu te chat-i</a>}
        </nav>
      </header>
      <main className="content">{route === 'admin' ? <Admin /> : <Chat />}</main>
    </div>
  )
}
