import { useState } from 'react'
import Button from '../components/Button'
import { LogoutIcon, ShieldIcon } from '../components/Icons'
import Logo from '../components/Logo'
import { useAuth } from '../context/useAuth'

const formatDate = (iso) =>
  iso
    ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
    : '—'

export default function Dashboard() {
  const { user, logout } = useAuth()
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const firstName = user.full_name.split(' ')[0]

  const handleLogout = async () => {
    setIsLoggingOut(true)
    try {
      await logout()
    } catch {
      setIsLoggingOut(false)
    }
  }

  const details = [
    ['Full name', user.full_name],
    ['Email', user.email],
    ['Member since', formatDate(user.date_joined)],
    ['Last sign-in', formatDate(user.last_login)],
  ]

  return (
    <div className="dash">
      <header className="dash__header">
        <div className="dash__bar">
          <Logo light />
          <Button variant="ghost" onClick={handleLogout} isLoading={isLoggingOut} loadingText="Signing out…">
            <LogoutIcon width={18} height={18} /> Sign out
          </Button>
        </div>
        <div className="dash__welcome">
          <p>Welcome back,</p>
          <h1>{firstName}</h1>
        </div>
      </header>

      <main className="dash__body">
        <section className="card">
          <div className="card__title">
            <ShieldIcon /> <h2>Your account</h2>
            <span className={`badge${user.is_active ? ' badge--ok' : ''}`}>
              {user.is_active ? 'Active' : 'Inactive'}
            </span>
          </div>
          <dl className="details">
            {details.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      </main>
    </div>
  )
}
