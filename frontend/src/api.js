// Komunikimi me backend-in. Në zhvillim, Vite i dërgon /api te http://localhost:8000.

async function errorMessage(res) {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return body.detail
  } catch {
    /* përgjigje pa JSON */
  }
  return `Gabim nga serveri (${res.status}).`
}

// Kthen ngjarjet e përgjigjes një nga një: meta, token, error, done.
export async function* streamChat(message, conversationId) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  })
  if (!res.ok) throw new Error(await errorMessage(res))

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()
    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line)
    }
  }
  if (buffer.trim()) yield JSON.parse(buffer)
}

export async function sendFeedback(messageId, value) {
  await fetch(`/api/messages/${messageId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  })
}

async function adminRequest(path, token, options = {}) {
  const res = await fetch(`/api/admin${path}`, {
    ...options,
    headers: { ...(options.headers || {}), Authorization: `Bearer ${token}` },
  })
  if (res.status === 401) {
    const err = new Error(await errorMessage(res))
    err.unauthorized = true
    throw err
  }
  if (!res.ok) throw new Error(await errorMessage(res))
  return res.json()
}

export async function login(username, password) {
  const res = await fetch('/api/admin/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!res.ok) throw new Error(await errorMessage(res))
  return (await res.json()).token
}

export const listDocuments = (token) => adminRequest('/documents', token)
export const getStats = (token) => adminRequest('/stats', token)
export const getDomainPlan = (token, domain) =>
  adminRequest(`/domain-plan?domain=${encodeURIComponent(domain)}`, token)

const postJson = (token, path, body) =>
  adminRequest(path, token, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) })
export const startFetchOfficial = (token) => postJson(token, '/jobs/fetch-official', {})
export const startCrawl = (token) => postJson(token, '/jobs/crawl', {})
export const pruneExcluded = (token, apply) => postJson(token, '/prune-excluded', { apply })
export const getJob = (token, id) => adminRequest(`/jobs/${id}`, token)
export const deleteDocument = (token, id) => adminRequest(`/documents/${id}`, token, { method: 'DELETE' })

export function uploadDocument(token, file, title, category) {
  const form = new FormData()
  form.append('file', file)
  form.append('title', title)
  if (category) form.append('category', category)
  return adminRequest('/documents', token, { method: 'POST', body: form })
}
