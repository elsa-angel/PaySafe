import { NavLink } from 'react-router-dom'
import { useAuth } from '../../context/useAuth'
import AppShell from '../AppShell'
import { LogoutIcon } from '../Icons'

const NAV_ITEMS = [
  { to: '/admin', label: 'Overview', end: true },
  { to: '/admin/fraud', label: 'Fraud Statistics' },
  { to: '/admin/users', label: 'User Management' },
  { to: '/admin/transactions', label: 'Transactions' },
  { to: '/admin/reports', label: 'Reports' },
]

function AdminNav() {
  const { logout } = useAuth()
  return (
    <nav className="admin-nav" aria-label="Administration">
      {NAV_ITEMS.map(({ to, label, end }) => (
        <NavLink key={to} to={to} end={end} className="admin-nav__link">{label}</NavLink>
      ))}
      <button type="button" className="admin-nav__link admin-nav__logout" onClick={() => logout().catch(() => {})}>
        <LogoutIcon width={16} height={16} /> Logout
      </button>
    </nav>
  )
}

/** Frame for every admin page: the regular PaySafe header plus admin navigation. */
export default function AdminShell({ title, eyebrow = 'Administration', backTo, backLabel, children }) {
  return (
    <AppShell
      eyebrow={eyebrow}
      title={title}
      backTo={backTo}
      backLabel={backLabel}
      homeTo="/admin"
      nav={<AdminNav />}
      wide
    >
      {children}
    </AppShell>
  )
}
