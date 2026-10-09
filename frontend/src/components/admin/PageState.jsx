import Alert from '../Alert'
import Button from '../Button'

export function PageLoader({ label = 'Loading' }) {
  return (
    <section className="card empty-state">
      <span className="spinner spinner--lg" role="status" aria-label={label} />
    </section>
  )
}

export function PageError({ message, onRetry }) {
  return (
    <section className="card empty-state">
      <Alert>{message}</Alert>
      {onRetry && <Button type="button" onClick={onRetry}>Try again</Button>}
    </section>
  )
}

/** Renders loading / error / content, keeping old content visible (dimmed) while refreshing. */
export function DataState({ data, error, isLoading, onRetry, errorMessage, children }) {
  if (!data && error) return <PageError message={errorMessage || "We couldn't load this data."} onRetry={onRetry} />
  if (!data) return <PageLoader />
  return (
    <div className={isLoading ? 'is-refreshing' : undefined} aria-busy={isLoading}>
      {error && <Alert>{errorMessage || "We couldn't refresh this data."}</Alert>}
      {children}
    </div>
  )
}
