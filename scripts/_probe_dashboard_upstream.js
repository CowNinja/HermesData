const DASH = 'http://127.0.0.1:9119'
const WS = 'http://127.0.0.1:3001'
const PW = 'HermesLAN2026SecureAccess'

async function main() {
  const html = await (await fetch(`${DASH}/`)).text()
  const m = html.match(/window\._+HERMES_+SESSION_+TOKEN__+\s*=\s*["']([^"']+)["']/)
  const token = m ? m[1] : ''
  console.log('dashboard token', token ? `${token.slice(0, 12)}...` : 'MISSING')

  const headers = { Authorization: `Bearer ${token}` }
  const paths = [
    '/api/status',
    '/api/cron/jobs',
    '/api/model/info',
    '/api/analytics/usage?days=30',
    '/api/plugins/hermes-achievements/recent-unlocks?limit=5',
    '/api/plugins/hermes-achievements/achievements',
    '/api/plugins/kanban/board',
    '/api/logs?lines=24',
  ]
  for (const p of paths) {
    const t = Date.now()
    try {
      const r = await fetch(`${DASH}${p}`, { headers, signal: AbortSignal.timeout(120000) })
      console.log(r.status, `${Date.now() - t}ms`, p)
    } catch (e) {
      console.log('ERR', `${Date.now() - t}ms`, p, e.message)
    }
  }

  const login = await fetch(`${WS}/api/auth`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password: PW }),
  })
  const cookies = login.headers.getSetCookie?.() || []
  const cookie = cookies.map((c) => c.split(';')[0]).join('; ')
  const t0 = Date.now()
  const ov = await fetch(`${WS}/api/dashboard/overview?days=30&achievements=5`, {
    headers: { Cookie: cookie },
    signal: AbortSignal.timeout(120000),
  })
  console.log('overview', ov.status, `${Date.now() - t0}ms`, (await ov.text()).slice(0, 80))
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})