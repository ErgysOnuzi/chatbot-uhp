import { useState } from "react"
import { getDomainPlan } from "./api.js"

function dnsText(plan) {
  return plan.records.map((record) => [record.type, record.host, record.value, record.ttl].join("\t")).join("\n")
}

export default function DomainSetup({ token, onError, setNotice }) {
  const [domain, setDomain] = useState("")
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)

  async function generate(e) {
    e.preventDefault()
    setBusy(true)
    try {
      const result = await getDomainPlan(token, domain)
      setPlan(result)
      setNotice("Udhëzimet për " + result.domain + " u përgatitën.")
    } catch (err) {
      onError(err)
    } finally {
      setBusy(false)
    }
  }

  async function copy(value, label) {
    try {
      await navigator.clipboard.writeText(value)
      setNotice(label + " u kopjua.")
    } catch {
      setNotice("Kopjimi automatik nuk lejohet në këtë shfletues.")
    }
  }

  return (
    <div className="card domain-setup">
      <h3>Lidh një domen të blerë</h3>
      <p className="hint">
        Pasi ta blesh domenin te Namecheap, shkruaje këtu. Paneli përgatit vlerat e sakta për DNS-në dhe Coolify.
      </p>
      <form className="domain-form" onSubmit={generate}>
        <label>
          Domeni
          <input
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            placeholder="p.sh. universiteti-yt.com"
            autoComplete="off"
          />
        </label>
        <button type="submit" disabled={busy || !domain.trim()}>
          {busy ? "Duke përgatitur…" : "Gjenero udhëzimet"}
        </button>
      </form>

      {plan && (
        <div className="domain-results">
          <div className="domain-block">
            <div className="domain-block-head">
              <h4>1. Shto rregullat te Namecheap</h4>
              <button className="ghost small" onClick={() => copy(dnsText(plan), "Lista e DNS-së")}>
                Kopjo të gjitha
              </button>
            </div>
            <ol className="steps">
              <li>Hap <strong>Domain List → Manage → Advanced DNS</strong>.</li>
              <li>Te Nameservers zgjidh <strong>Namecheap BasicDNS</strong>.</li>
              <li>Fshi URL Redirect Record ose A/CNAME ekzistuese për <code>@</code> dhe <code>www</code>. Mos fshi MX ose TXT.</li>
              <li>Shto këto dy rregulla:</li>
            </ol>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Host</th>
                    <th>Value</th>
                    <th>TTL</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {plan.records.map((record) => (
                    <tr key={record.type + "-" + record.host}>
                      <td>{record.type}</td>
                      <td><code>{record.host}</code></td>
                      <td><code>{record.value}</code></td>
                      <td>{record.ttl}</td>
                      <td>
                        <button
                          className="ghost small"
                          onClick={() => copy([record.type, record.host, record.value, record.ttl].join("\t"), record.host)}
                        >
                          Kopjo
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="two-col">
            <div className="domain-block">
              <h4>2. Shto domenin te Coolify</h4>
              <p className="hint">Te resource-i <strong>chatbot-uhp → frontend → General → Domains</strong>, shto të dyja:</p>
              <ul className="value-list">
                {plan.coolify_domains.map((value) => (
                  <li key={value}>
                    <code>{value}</code>
                    <button className="ghost small" onClick={() => copy(value, value)}>Kopjo</button>
                  </li>
                ))}
              </ul>
              <p className="hint">Ruaj ndryshimin dhe bëj redeploy. Coolify do të kërkojë automatikisht certifikatën HTTPS.</p>
            </div>
            <div className="domain-block">
              <h4>3. Verifiko DNS-në</h4>
              <p className="hint">Pas 5–30 minutash, kontrollo që adresa të kthejë IP-në <code>{plan.server_ip}</code>:</p>
              <pre className="command">{plan.verification_commands.join("\n")}</pre>
              <button className="ghost small" onClick={() => copy(plan.verification_commands.join("\n"), "Komandat")}>
                Kopjo komandat
              </button>
              <p className="domain-warning">
                Mos përdor Cloudflare Proxy menjëherë. Për certifikatën e parë, lëre DNS-në te Namecheap me A/CNAME direkt.
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
