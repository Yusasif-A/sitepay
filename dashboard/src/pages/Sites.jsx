import { useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../lib/AuthContext'

export default function Sites() {
  const { token, me, refresh, setSiteId } = useAuth()
  const [name, setName] = useState('')
  const [location, setLocation] = useState('')
  const [error, setError] = useState('')

  async function add(e) {
    e.preventDefault()
    setError('')
    try {
      const site = await api.post('/api/sites', { name, location }, token)
      setName(''); setLocation('')
      await refresh(); setSiteId(site.site_id)
    } catch (err) { setError(err.message) }
  }

  return (
    <div>
      <div className="page-header"><div><h1>Sites</h1><p>Each site has its own crew, register and pay runs.</p></div></div>
      {error && <div className="banner banner-error">{error}</div>}
      <form className="card panel" onSubmit={add}>
        <h2>New site</h2>
        <div className="field-row">
          <div className="field"><label>Name</label><input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Ikeja Warehouse" /></div>
          <div className="field"><label>Location</label><input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Ikeja, Lagos" /></div>
        </div>
        <button className="btn btn-primary">Add site</button>
      </form>
      <div className="card">
        <table className="table">
          <thead><tr><th>Site</th><th>Location</th><th></th></tr></thead>
          <tbody>{me?.sites.map((s) => (
            <tr key={s.site_id}><td><strong>{s.name}</strong></td><td>{s.location}</td>
              <td><button className="btn btn-secondary btn-sm" onClick={() => setSiteId(s.site_id)}>Switch to</button></td></tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  )
}
