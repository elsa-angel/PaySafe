export default function FullScreenLoader() {
  return (
    <div className="loader-screen" role="status" aria-live="polite">
      <span className="spinner spinner--lg" aria-hidden="true" />
      <span className="sr-only">Loading…</span>
    </div>
  )
}
