export default function DateInput({ label, value, onChange, disabled }) {
  const id = `date-${label.toLowerCase().replace(/\W+/g, '-')}`
  return (
    <div className="toolbar__field">
      <label className="field__label" htmlFor={id}>{label}</label>
      <div className="field__control">
        <input id={id} type="date" className="field__input field__input--plain" value={value}
          onChange={(event) => onChange(event.target.value)} disabled={disabled} />
      </div>
    </div>
  )
}
