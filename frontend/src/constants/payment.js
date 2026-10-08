import { BankIcon, CardIcon, UpiIcon, WalletIcon } from '../components/Icons'

// Values mirror the Django choices in payments/models.py (the backend validates them).
export const PAYMENT_METHODS = [
  { value: 'CARD', label: 'Card', icon: CardIcon },
  { value: 'UPI', label: 'UPI', icon: UpiIcon },
  { value: 'BANK_TRANSFER', label: 'Bank Transfer', icon: BankIcon },
  { value: 'WALLET', label: 'Wallet', icon: WalletIcon },
]

export const METHOD_ICONS = Object.fromEntries(PAYMENT_METHODS.map(({ value, icon }) => [value, icon]))

export const CARD_NETWORKS = [
  { value: 'VISA', label: 'Visa' },
  { value: 'MASTERCARD', label: 'Mastercard' },
  { value: 'RUPAY', label: 'RuPay' },
  { value: 'OTHER', label: 'Other' },
]

export const BANKS = [
  { value: 'SBI', label: 'State Bank of India' },
  { value: 'HDFC', label: 'HDFC Bank' },
  { value: 'ICICI', label: 'ICICI Bank' },
  { value: 'AXIS', label: 'Axis Bank' },
  { value: 'KOTAK', label: 'Kotak Mahindra Bank' },
  { value: 'PNB', label: 'Punjab National Bank' },
  { value: 'BOB', label: 'Bank of Baroda' },
  { value: 'CANARA', label: 'Canara Bank' },
  { value: 'OTHER', label: 'Other' },
]

export const WALLETS = [
  { value: 'PAYTM', label: 'Paytm' },
  { value: 'PHONEPE', label: 'PhonePe' },
  { value: 'GOOGLE_PAY', label: 'Google Pay' },
  { value: 'AMAZON_PAY', label: 'Amazon Pay' },
  { value: 'OTHER', label: 'Other' },
]

/** The one method-specific field shown for each payment method. */
export const METHOD_DETAIL = {
  CARD: { field: 'cardNetwork', apiField: 'card_network', label: 'Card type', placeholder: 'Select card type', options: CARD_NETWORKS, error: 'Select the card type.' },
  UPI: { field: 'upiId', apiField: 'upi_id', label: 'UPI ID', placeholder: 'name@bank' },
  BANK_TRANSFER: { field: 'bankName', apiField: 'bank_name', label: 'Bank name', placeholder: 'Select bank', options: BANKS, error: 'Select the bank.' },
  WALLET: { field: 'walletProvider', apiField: 'wallet_provider', label: 'Wallet provider', placeholder: 'Select wallet', options: WALLETS, error: 'Select the wallet provider.' },
}
