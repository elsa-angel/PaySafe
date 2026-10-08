import { Link } from 'react-router-dom'
import AppShell from '../components/AppShell'
import { ArrowRightIcon, ListIcon, SendIcon } from '../components/Icons'
import RecentTransactions from '../components/RecentTransactions'
import { useAuth } from '../context/useAuth'

const ACTIONS = [
  {
    to: '/payment',
    icon: SendIcon,
    title: 'Make Payment',
    description: 'Send money securely, protected by fraud screening.',
    tone: 'blue',
  },
  {
    to: '/transactions',
    icon: ListIcon,
    title: 'Transactions',
    description: 'Review your payment activity.',
    tone: 'amber',
  },
]

export default function Dashboard() {
  const { user } = useAuth()
  const firstName = user.full_name.split(' ')[0]

  return (
    <AppShell eyebrow="Welcome back," title={firstName}>
      <div className="actions-grid">
        {ACTIONS.map(({ to, icon: Icon, title, description, tone }) => (
          <Link key={to} to={to} className={`action-card action-card--${tone}`}>
            <span className="action-card__icon"><Icon width={26} height={26} /></span>
            <span className="action-card__text">
              <strong>{title}</strong>
              <span>{description}</span>
            </span>
            <ArrowRightIcon className="action-card__arrow" />
          </Link>
        ))}
      </div>
      <RecentTransactions />
    </AppShell>
  )
}
