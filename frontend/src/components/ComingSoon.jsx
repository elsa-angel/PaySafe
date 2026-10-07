import { Link } from 'react-router-dom'
import { ClockIcon } from './Icons'

/** Placeholder card for features that are navigation-only for now. */
export default function ComingSoon({ title, message }) {
  return (
    <section className="card empty-state">
      <span className="empty-state__icon"><ClockIcon width={28} height={28} /></span>
      <h2>{title}</h2>
      <p>{message}</p>
      <Link to="/" className="btn btn--primary">Back to dashboard</Link>
    </section>
  )
}
