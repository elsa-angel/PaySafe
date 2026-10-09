import { PRESETS } from '../../utils/dateRange'
import SelectField from '../SelectField'
import DateInput from './DateInput'

const GROUP_OPTIONS = [
  { value: 'day', label: 'Day' },
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
]

export default function DateRangeFilter({ value, onChange, showGroupBy = false, disabled = false }) {
  const update = (changes) => onChange({ ...value, ...changes })
  const invalid = value.preset === 'custom' && value.from && value.to && value.from > value.to
  return (
    <div className="toolbar">
      <div className="toolbar__field">
        <SelectField
          label="Period"
          placeholder="Period"
          options={PRESETS}
          value={value.preset}
          onChange={(event) => update({ preset: event.target.value || '30d' })}
          disabled={disabled}
        />
      </div>
      {value.preset === 'custom' && (
        <>
          <DateInput label="From" value={value.from} onChange={(from) => update({ from })} disabled={disabled} />
          <DateInput label="To" value={value.to} onChange={(to) => update({ to })} disabled={disabled} />
        </>
      )}
      {showGroupBy && (
        <div className="toolbar__field">
          <label className="field__label" htmlFor="group-by">Group by</label>
          <div className="field__control">
            <select id="group-by" className="field__input field__input--plain field__select" value={value.groupBy}
              onChange={(event) => update({ groupBy: event.target.value })} disabled={disabled}>
              <option value="">Automatic</option>
              {GROUP_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
            </select>
          </div>
        </div>
      )}
      {invalid && <p className="field__error toolbar__error">The start date must not be after the end date.</p>}
    </div>
  )
}
