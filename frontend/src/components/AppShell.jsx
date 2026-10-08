import { Link } from 'react-router-dom'
import { ArrowLeftIcon } from './Icons'
import Logo from './Logo'
import UserMenu from './UserMenu'

/**
 * Shared frame for every signed-in page: blue header with logo and user menu,
 * a page heading, and the content area. `backTo` shows a back link.
 */
export default function AppShell({ eyebrow, title, backTo, backLabel = 'Dashboard', children }) {
  return (
    <div className="dash">
      <header className="dash__header">
        <div className="dash__bar">
          <Link to="/" aria-label="PaySafe dashboard"><Logo light /></Link>
          <UserMenu />
        </div>
        <div className="dash__welcome">
          {backTo && (
            <Link to={backTo} className="dash__back"><ArrowLeftIcon width={16} height={16} /> {backLabel}</Link>
          )}
          {eyebrow && <p>{eyebrow}</p>}
          <h1>{title}</h1>
        </div>
      </header>
      <main className="dash__body">{children}</main>
    </div>
  )
}
