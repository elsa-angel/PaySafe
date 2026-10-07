import { Link } from 'react-router-dom'
import Logo from '../components/Logo'

export default function NotFound() {
  return (
    <div className="loader-screen notfound">
      <Logo />
      <h1>Page not found</h1>
      <p>The page you're looking for doesn't exist.</p>
      <Link className="btn btn--primary" to="/">Back to PaySafe</Link>
    </div>
  )
}
