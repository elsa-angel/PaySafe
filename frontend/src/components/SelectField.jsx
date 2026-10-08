import { useId } from 'react'

export default function SelectField({ label, error, options, placeholder, ...selectProps }) {
  const id = useId()
  return (
    <div className={`field${error ? ' field--invalid' : ''}`}>
      <label className="field__label" htmlFor={id}>{label}</label>
      <div className="field__control">
        <select
          id={id}
          className="field__input field__input--plain field__select"
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
          {...selectProps}
        >
          <option value="">{placeholder}</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
      </div>
      {error && <p id={`${id}-error`} className="field__error">{error}</p>}
    </div>
  )
}
