const LABELS = { COMPLETED: 'Completed', PENDING: 'Pending', FAILED: 'Failed', CANCELLED: 'Cancelled' }

export default function StatusBadge({ status, label }) {
  return (
    <span className={`status-badge status-badge--${status.toLowerCase()}`}>
      {label || LABELS[status] || status}
    </span>
  )
}
