import { Link } from 'react-router-dom'
import HeroIllustration from './HeroIllustration'
import Logo from './Logo'
import { ActivityIcon, LockIcon, ShieldIcon } from './Icons'

const TRUST_POINTS = [
  { icon: ActivityIcon, text: 'Real-time fraud screening' },
  { icon: LockIcon, text: 'Encrypted, hashed credentials' },
  { icon: ShieldIcon, text: 'Built for safer payments' },
]

export default function AuthLayout({ title, subtitle, children, footer }) {
  return (
    <div className="auth">
      <aside className="auth__hero">
        <Link to="/" aria-label="PaySafe home"><Logo /></Link>
        <div className="auth__hero-copy">
          <h1>Pay smart.<br />Stay protected.</h1>
          <p>PaySafe watches every online payment for signs of fraud, so you can send and receive money with confidence.</p>
        </div>
        <HeroIllustration />
        <ul className="auth__trust">
          {TRUST_POINTS.map(({ icon: Icon, text }) => (
            <li key={text}><Icon width={18} height={18} /> {text}</li>
          ))}
        </ul>
      </aside>

      <main className="auth__panel">
        <svg className="auth__waves" viewBox="0 0 600 300" preserveAspectRatio="none" aria-hidden="true">
          <path d="M-20 90c90-60 150 40 250-10s120-60 200-20 120 10 180-20" fill="none" stroke="#fff" strokeOpacity=".35" />
          <path d="M-20 140c110-30 140 50 240 10s140-50 220-10 100 20 170 0" fill="none" stroke="#fff" strokeOpacity=".2" />
          <circle cx="90" cy="40" r="9" fill="#f8b76a" />
          <circle cx="520" cy="70" r="6" fill="#e2616f" />
          <path d="M470 20a14 14 0 0 1 14 14h-14Z" fill="#f8b76a" />
        </svg>

        <div className="auth__mobile-brand"><Logo light /></div>

        <div className="auth-card">
          <header className="auth-card__header">
            <h2>{title}</h2>
            <p>{subtitle}</p>
          </header>
          {children}
        </div>
        <p className="auth__switch">{footer}</p>
      </main>
    </div>
  )
}
