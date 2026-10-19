import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Alert from '../components/Alert'
import AppShell from '../components/AppShell'
import Button from '../components/Button'
import { MailIcon, NoteIcon, UserIcon } from '../components/Icons'
import MethodSelector from '../components/MethodSelector'
import { BankFields, CardFields, UpiFields, WalletFields } from '../components/payment/MethodFields'
import TextField from '../components/TextField'
import { createIdempotencyKey, paymentService } from '../services/paymentService'
import { requestLocation, warmUpLocation } from '../utils/geolocation'
import {
  API_METHOD_FIELD_MAP,
  buildMethodPayload,
  EMPTY_METHOD_VALUES,
  INPUT_FORMATTERS,
  METHOD_FIELDS,
  validateMethodFields,
} from '../utils/paymentValidation'
import {
  DESCRIPTION_MAX_LENGTH,
  parseApiError,
  validateAmount,
  validateDescription,
  validateRecipientEmail,
  validateRecipientName,
} from '../utils/validation'

const INITIAL_VALUES = {
  amount: '',
  paymentMethod: 'CARD',
  description: '',
  recipientName: '',
  recipientEmail: '',
  ...EMPTY_METHOD_VALUES,
}

const API_FIELD_MAP = {
  amount: 'amount',
  payment_method: 'paymentMethod',
  description: 'description',
  recipient_name: 'recipientName',
  recipient_email: 'recipientEmail',
  ...API_METHOD_FIELD_MAP,
}

const METHOD_TITLES = { CARD: 'Card', UPI: 'UPI', BANK_TRANSFER: 'Bank transfer', WALLET: 'Wallet' }

/** Validates the common fields plus only the selected method's fields. */
function validate(values) {
  return {
    amount: validateAmount(values.amount),
    description: validateDescription(values.description),
    recipientName: validateRecipientName(values.recipientName),
    recipientEmail: validateRecipientEmail(values.recipientEmail),
    ...validateMethodFields(values.paymentMethod, values),
  }
}

const withoutMethodErrors = (errors) => ({
  ...errors,
  ...Object.fromEntries(Object.values(METHOD_FIELDS).flat().map((name) => [name, ''])),
})

export default function Payment() {
  const navigate = useNavigate()
  const [values, setValues] = useState(INITIAL_VALUES)
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const idempotencyKeyRef = useRef(createIdempotencyKey())

  // If location permission was already granted, fetch it quietly in advance (no prompt).
  useEffect(() => {
    warmUpLocation()
  }, [])

  const handleChange = (event) => {
    const { name } = event.target
    const value = INPUT_FORMATTERS[name] ? INPUT_FORMATTERS[name](event.target.value) : event.target.value
    setValues((current) => {
      const next = { ...current, [name]: value }
      if (name === 'walletIdentifierType') next.walletIdentifier = '' // the old value was for the other type
      return next
    })
    setErrors((current) => {
      const next = { ...current, [name]: '' }
      if (name === 'walletIdentifierType') next.walletIdentifier = ''
      if (name === 'cardNetwork') Object.assign(next, { cardNumber: '', cardCvv: '' })
      if (name === 'bankName') next.ifscCode = ''
      if (name === 'accountNumber') next.confirmAccountNumber = ''
      return next
    })
    setFormError('')
  }

  const handleBlur = (event) => {
    const { name } = event.target
    if (!values[name]) return
    setErrors((current) => ({ ...current, [name]: validate(values)[name] || '' }))
  }

  // Switching methods wipes every method-specific value so nothing from one method can be sent with another.
  const handleMethodChange = (paymentMethod) => {
    if (paymentMethod === values.paymentMethod) return
    setValues((current) => ({ ...current, ...EMPTY_METHOD_VALUES, paymentMethod }))
    setErrors((current) => withoutMethodErrors(current))
    setFormError('')
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (submittingRef.current) return // blocks double-clicks before state has re-rendered

    const nextErrors = validate(values)
    setErrors(nextErrors)
    if (Object.values(nextErrors).some(Boolean)) {
      setFormError('')
      return
    }

    submittingRef.current = true
    setIsSubmitting(true)
    setFormError('')
    try {
      const location = await requestLocation() // never rejects; denial just means no coordinates
      const transaction = await paymentService.create(
        {
          amount: values.amount.trim(),
          payment_method: values.paymentMethod,
          ...buildMethodPayload(values.paymentMethod, values),
          description: values.description.trim(),
          recipient_name: values.recipientName.trim(),
          recipient_email: values.recipientEmail.trim(),
          latitude: location.latitude,
          longitude: location.longitude,
          location_status: location.locationStatus,
        },
        idempotencyKeyRef.current,
      )
      navigate(`/payment/success/${transaction.transaction_id}`, { replace: true })
    } catch (error) {
      // A processing failure (422) was recorded as its own transaction, so a retry needs a fresh key.
      // Network errors keep the key: if the request did arrive, the retry will not pay twice.
      if (error.status === 422) idempotencyKeyRef.current = createIdempotencyKey()
      const parsed = parseApiError(error, API_FIELD_MAP)
      setErrors(parsed.fieldErrors)
      setFormError(parsed.formError)
      submittingRef.current = false
      setIsSubmitting(false)
    }
  }

  const field = (name) => ({
    name,
    value: values[name],
    error: errors[name],
    onChange: handleChange,
    onBlur: handleBlur,
    disabled: isSubmitting,
  })

  const method = values.paymentMethod

  return (
    <AppShell eyebrow="Payments" title="Make Payment" backTo="/">
      <form className="card card--narrow payment-form" onSubmit={handleSubmit} noValidate>
        <Alert>{formError}</Alert>
        <p className="form-note">Fields marked <span className="field__required">*</span> are required.</p>

        <section className="form-section">
          <h2 className="form-section__title">Payment details</h2>
          <TextField
            label="Amount"
            required
            prefix="₹"
            inputMode="decimal"
            autoComplete="off"
            placeholder="0.00"
            {...field('amount')}
          />
          <MethodSelector value={method} onChange={handleMethodChange} disabled={isSubmitting} />
          <TextField
            label="Note (optional)"
            icon={NoteIcon}
            placeholder="What is this payment for?"
            maxLength={DESCRIPTION_MAX_LENGTH}
            autoComplete="off"
            {...field('description')}
          />
        </section>

        <section className="form-section">
          <h2 className="form-section__title">Recipient details</h2>
          <TextField
            label="Recipient name"
            required
            icon={UserIcon}
            autoComplete="off"
            placeholder="Full name"
            {...field('recipientName')}
          />
          <TextField
            label="Recipient email"
            required
            type="email"
            icon={MailIcon}
            autoComplete="off"
            placeholder="recipient@example.com"
            {...field('recipientEmail')}
          />
        </section>

        <section className="form-section" aria-label={`${METHOD_TITLES[method]} details`}>
          <h2 className="form-section__title">Payment method details</h2>
          <Alert variant="info">
            This is a simulated payment: no real money moves. Use test details only. PaySafe never stores your full
            card number, CVV or account number.
            {method === 'CARD' && ' Test card: 4111 1111 1111 1111, any future expiry, any 3-digit CVV.'}
          </Alert>
          {method === 'CARD' && <CardFields field={field} />}
          {method === 'UPI' && <UpiFields field={field} />}
          {method === 'BANK_TRANSFER' && <BankFields field={field} />}
          {method === 'WALLET' && <WalletFields field={field} identifierType={values.walletIdentifierType} />}
        </section>

        <Button type="submit" isLoading={isSubmitting} loadingText="Processing payment…">
          Continue Payment
        </Button>
      </form>
    </AppShell>
  )
}
