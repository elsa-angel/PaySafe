import { IFSC_BANK_PREFIX } from '../constants/payment'
import { validateUpiId } from './validation'

/* Method-specific payment details: validation, input formatting and API payloads.
 * These rules mirror payments/validators.py, which is the authority. Raw card and
 * account details are only ever sent to the server for validation; PaySafe stores
 * masked values, and never the CVV. */

export const METHOD_FIELDS = {
  CARD: ['cardholderName', 'cardNetwork', 'cardNumber', 'cardExpiry', 'cardCvv'],
  UPI: ['upiProvider', 'upiId'],
  BANK_TRANSFER: ['bankName', 'accountHolderName', 'accountNumber', 'confirmAccountNumber', 'ifscCode'],
  WALLET: ['walletProvider', 'walletIdentifierType', 'walletIdentifier'],
}

export const ALL_METHOD_FIELDS = Object.values(METHOD_FIELDS).flat()

/** Blank method-specific values (the wallet identifier type starts on its usual choice). */
export const EMPTY_METHOD_VALUES = {
  ...Object.fromEntries(ALL_METHOD_FIELDS.map((name) => [name, ''])),
  walletIdentifierType: 'MOBILE',
}

// ---------- input formatting (applied as the user types) ----------

const digits = (value) => value.replace(/\D/g, '')

export const INPUT_FORMATTERS = {
  cardNumber: (value) => digits(value).slice(0, 19).replace(/(.{4})(?=.)/g, '$1 '),
  cardExpiry: (value) => {
    const entered = digits(value).slice(0, 4)
    return entered.length > 2 ? `${entered.slice(0, 2)}/${entered.slice(2)}` : entered
  },
  cardCvv: (value) => digits(value).slice(0, 4),
  accountNumber: (value) => digits(value).slice(0, 18),
  confirmAccountNumber: (value) => digits(value).slice(0, 18),
  ifscCode: (value) => value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 11),
  walletIdentifier: (value) => value.slice(0, 64),
}

// ---------- validators ----------

const stripSeparators = (value) => value.replace(/[\s-]/g, '')

function luhnValid(number) {
  let total = 0
  const reversed = [...number].reverse()
  reversed.forEach((char, index) => {
    let digit = Number(char)
    if (index % 2 === 1) digit = digit > 4 ? digit * 2 - 9 : digit * 2
    total += digit
  })
  return total % 10 === 0
}

const CARD_LENGTHS = { VISA: [16, 16], MASTERCARD: [16, 16], RUPAY: [16, 16], OTHER: [12, 19] }
const CVV_LENGTHS = { OTHER: [3, 4] }

export function validateCardholderName(name) {
  const value = name.trim().replace(/\s+/g, ' ')
  if (!value) return 'Enter the cardholder name.'
  const letters = [...value].filter((char) => /\p{L}/u.test(char))
  const valid = letters.length >= 2 && value.length <= 60 && [...value].every((char) => /\p{L}/u.test(char) || " .'-".includes(char))
  return valid ? '' : 'Enter the name as it appears on the card.'
}

export function validateCardNetwork(network) {
  return network ? '' : 'Select the card network.'
}

export function validateCardNumber(raw, network) {
  const value = raw.trim()
  if (!value) return 'Enter the card number.'
  const number = stripSeparators(value)
  const [min, max] = CARD_LENGTHS[network] || CARD_LENGTHS.OTHER
  const valid = /^\d+$/.test(number) && number[0] !== '0' && number.length >= min && number.length <= max && luhnValid(number)
  return valid ? '' : 'Enter a valid card number.'
}

export function validateCardExpiry(raw, now = new Date()) {
  const value = raw.trim()
  if (!value) return 'Enter the expiry date.'
  const match = value.match(/^(0[1-9]|1[0-2])\s*\/\s*(\d{2}|\d{4})$/)
  if (!match) return 'Enter the expiry date as MM/YY.'
  const month = Number(match[1])
  let year = Number(match[2])
  if (year < 100) year += 2000
  const currentYear = now.getFullYear()
  const currentMonth = now.getMonth() + 1
  if (year < currentYear || (year === currentYear && month < currentMonth)) return 'This card has expired.'
  if (year > currentYear + 20) return 'Enter a valid expiry date.'
  return ''
}

export function validateCvv(raw, network) {
  const value = raw.trim()
  if (!value) return 'Enter the CVV.'
  const lengths = CVV_LENGTHS[network] || [3, 3]
  const valid = /^\d+$/.test(value) && value.length >= lengths[0] && value.length <= lengths[1]
  return valid ? '' : `Enter the ${lengths[0] === lengths[1] ? lengths[0] : `${lengths[0]} or ${lengths[1]}`}-digit CVV.`
}

export function validateUpiProvider(provider) {
  return provider ? '' : 'Select the UPI app.'
}

export function validateBankName(bank) {
  return bank ? '' : 'Select the bank.'
}

export function validateAccountHolderName(name) {
  const value = name.trim().replace(/\s+/g, ' ')
  if (!value) return 'Enter the account holder name.'
  const letters = [...value].filter((char) => /\p{L}/u.test(char))
  const valid = letters.length >= 2 && value.length <= 60 && [...value].every((char) => /\p{L}/u.test(char) || " .'-".includes(char))
  return valid ? '' : 'Enter the account holder name as it appears on the account.'
}

export function validateAccountNumber(raw) {
  const value = raw.trim()
  if (!value) return 'Enter the account number.'
  const number = stripSeparators(value)
  if (!/^\d+$/.test(number)) return 'Enter a valid account number (digits only).'
  return number.length >= 9 && number.length <= 18 ? '' : 'Account numbers have 9 to 18 digits.'
}

export function validateConfirmAccountNumber(account, confirm) {
  if (!confirm.trim()) return 'Confirm the account number.'
  return stripSeparators(account) === stripSeparators(confirm) ? '' : 'Account numbers do not match.'
}

export function validateIfsc(raw, bank) {
  const value = raw.trim().toUpperCase()
  if (!value) return 'Enter the IFSC code.'
  if (!/^[A-Z]{4}0[A-Z0-9]{6}$/.test(value)) return 'Enter a valid IFSC code, like HDFC0001234.'
  const expected = IFSC_BANK_PREFIX[bank]
  return expected && !value.startsWith(expected) ? 'This IFSC code does not belong to the selected bank.' : ''
}

export function validateWalletProvider(provider) {
  return provider ? '' : 'Select the wallet provider.'
}

export function validateWalletIdentifierType(type) {
  return type ? '' : 'Choose how to identify your wallet.'
}

export function validateWalletIdentifier(raw, type) {
  const value = raw.trim()
  if (!value) return type === 'MOBILE' ? 'Enter the mobile number.' : 'Enter the wallet identifier.'
  if (type === 'MOBILE') {
    let number = stripSeparators(value)
    for (const prefix of ['+91', '91', '0']) {
      if (number.startsWith(prefix) && number.length - prefix.length === 10) {
        number = number.slice(prefix.length)
        break
      }
    }
    return /^[6-9]\d{9}$/.test(number) ? '' : 'Enter a valid 10-digit mobile number.'
  }
  return /^[A-Za-z0-9][A-Za-z0-9._@+-]{3,63}$/.test(value)
    ? ''
    : 'Enter a valid wallet ID (4 to 64 letters, numbers or . _ @ + -).'
}

/** Validates only the fields of the selected method. Returns { fieldName: message } with '' for valid fields. */
export function validateMethodFields(method, v) {
  switch (method) {
    case 'CARD':
      return {
        cardholderName: validateCardholderName(v.cardholderName),
        cardNetwork: validateCardNetwork(v.cardNetwork),
        cardNumber: validateCardNumber(v.cardNumber, v.cardNetwork),
        cardExpiry: validateCardExpiry(v.cardExpiry),
        cardCvv: validateCvv(v.cardCvv, v.cardNetwork),
      }
    case 'UPI':
      return {
        upiProvider: validateUpiProvider(v.upiProvider),
        upiId: v.upiId.trim() ? validateUpiId(v.upiId) : 'Enter the UPI ID.',
      }
    case 'BANK_TRANSFER':
      return {
        bankName: validateBankName(v.bankName),
        accountHolderName: validateAccountHolderName(v.accountHolderName),
        accountNumber: validateAccountNumber(v.accountNumber),
        confirmAccountNumber: validateConfirmAccountNumber(v.accountNumber, v.confirmAccountNumber),
        ifscCode: validateIfsc(v.ifscCode, v.bankName),
      }
    case 'WALLET':
      return {
        walletProvider: validateWalletProvider(v.walletProvider),
        walletIdentifierType: validateWalletIdentifierType(v.walletIdentifierType),
        walletIdentifier: validateWalletIdentifier(v.walletIdentifier, v.walletIdentifierType),
      }
    default:
      return {}
  }
}

/** API fields for the selected method only (other methods' values are never sent). */
export function buildMethodPayload(method, v) {
  switch (method) {
    case 'CARD':
      return {
        card_network: v.cardNetwork,
        cardholder_name: v.cardholderName.trim(),
        card_number: stripSeparators(v.cardNumber),
        card_expiry: v.cardExpiry.trim(),
        card_cvv: v.cardCvv.trim(),
      }
    case 'UPI':
      return { upi_provider: v.upiProvider, upi_id: v.upiId.trim() }
    case 'BANK_TRANSFER':
      return {
        bank_name: v.bankName,
        account_holder_name: v.accountHolderName.trim(),
        account_number: stripSeparators(v.accountNumber),
        confirm_account_number: stripSeparators(v.confirmAccountNumber),
        ifsc_code: v.ifscCode.trim().toUpperCase(),
      }
    case 'WALLET':
      return {
        wallet_provider: v.walletProvider,
        wallet_identifier_type: v.walletIdentifierType,
        wallet_identifier: v.walletIdentifier.trim(),
      }
    default:
      return {}
  }
}

/** Server field names -> form field names, for showing API validation errors inline. */
export const API_METHOD_FIELD_MAP = {
  cardholder_name: 'cardholderName',
  card_network: 'cardNetwork',
  card_number: 'cardNumber',
  card_expiry: 'cardExpiry',
  card_cvv: 'cardCvv',
  upi_provider: 'upiProvider',
  upi_id: 'upiId',
  bank_name: 'bankName',
  account_holder_name: 'accountHolderName',
  account_number: 'accountNumber',
  confirm_account_number: 'confirmAccountNumber',
  ifsc_code: 'ifscCode',
  wallet_provider: 'walletProvider',
  wallet_identifier_type: 'walletIdentifierType',
  wallet_identifier: 'walletIdentifier',
}
