import Button from '../Button'

export default function Pagination({ page, count, pageSize = 20, onChange, disabled }) {
  const pages = Math.max(1, Math.ceil(count / pageSize))
  if (pages <= 1) return null
  return (
    <nav className="pagination" aria-label="Pagination">
      <Button type="button" variant="secondary" onClick={() => onChange(page - 1)} disabled={disabled || page <= 1}>Previous</Button>
      <span>Page {page} of {pages}</span>
      <Button type="button" variant="secondary" onClick={() => onChange(page + 1)} disabled={disabled || page >= pages}>Next</Button>
    </nav>
  )
}
