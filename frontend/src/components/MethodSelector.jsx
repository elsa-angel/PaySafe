import { useId } from 'react'
import { PAYMENT_METHODS } from '../constants/payment'

/** Payment method cards (a radio group). */
export default function MethodSelector({ value, onChange, disabled }) {
  const name = useId()
  return (
    <fieldset className="method-selector" disabled={disabled}>
      <legend className="field__label">Payment method</legend>
      <div className="method-selector__grid">
        {PAYMENT_METHODS.map(({ value: optionValue, label, icon: Icon }) => (
          <label key={optionValue} className={`method-card${value === optionValue ? ' is-selected' : ''}`}>
            <input
              type="radio"
              name={name}
              value={optionValue}
              checked={value === optionValue}
              onChange={() => onChange(optionValue)}
            />
            <Icon width={22} height={22} />
            <span>{label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
