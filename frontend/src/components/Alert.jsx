import { AlertIcon, CheckIcon } from './Icons'

/** variant: 'error' (default), 'success' or 'info'. */
export default function Alert({ variant = 'error', children }) {
  if (!children) return null
  const Icon = variant === 'success' ? CheckIcon : AlertIcon
  return (
    <div className={`alert alert--${variant}`} role={variant === 'error' ? 'alert' : 'status'}>
      <Icon className="alert__icon" />
      <span>{children}</span>
    </div>
  )
}
