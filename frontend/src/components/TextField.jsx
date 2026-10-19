import { useId, useState } from 'react'
import { EyeIcon, EyeOffIcon } from './Icons'

export default function TextField({ label, error, icon: Icon, prefix, type = 'text', hint, required = false, ...inputProps }) {
  const id = useId()
  const [revealed, setRevealed] = useState(false)
  const isPassword = type === 'password'
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined

  return (
    <div className={`field${error ? ' field--invalid' : ''}`}>
      <label className="field__label" htmlFor={id}>
        {label}
        {required && <span className="field__required" aria-hidden="true"> *</span>}
      </label>
      <div className="field__control">
        {Icon && <Icon className="field__icon" />}
        {!Icon && prefix && <span className="field__prefix" aria-hidden="true">{prefix}</span>}
        <input
          id={id}
          className={`field__input${!Icon && !prefix ? ' field__input--plain' : ''}${prefix ? ' field__input--prefixed' : ''}`}
          type={isPassword && revealed ? 'text' : type}
          aria-required={required || undefined}
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy}
          {...inputProps}
        />
        {isPassword && (
          <button
            type="button"
            className="field__toggle"
            onClick={() => setRevealed((value) => !value)}
            aria-label={revealed ? 'Hide password' : 'Show password'}
            aria-pressed={revealed}
          >
            {revealed ? <EyeOffIcon /> : <EyeIcon />}
          </button>
        )}
      </div>
      {error && <p id={`${id}-error`} className="field__error">{error}</p>}
      {!error && hint && <p id={`${id}-hint`} className="field__hint">{hint}</p>}
    </div>
  )
}
