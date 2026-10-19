"""Validation and masking of payment-method details.

Full card numbers, CVVs, expiry dates and bank account numbers are validated here
and then DISCARDED: only masked or non-sensitive values are returned for storage.
Error messages are static and never echo what the user typed.
"""
import re
from datetime import date

from .models import (
    Bank,
    CardNetwork,
    PaymentMethod,
    UpiProvider,
    WalletIdentifierType,
    WalletProvider,
)

UPI_ID_PATTERN = re.compile(r'^[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31}$')
IFSC_PATTERN = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
EXPIRY_PATTERN = re.compile(r'^(0[1-9]|1[0-2])\s*/\s*(\d{2}|\d{4})$')
MOBILE_PATTERN = re.compile(r'^[6-9]\d{9}$')
WALLET_ID_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._@+-]{3,63}$')

CARD_LENGTHS = {
    CardNetwork.VISA: range(16, 17),
    CardNetwork.MASTERCARD: range(16, 17),
    CardNetwork.RUPAY: range(16, 17),
    CardNetwork.OTHER: range(12, 20),
}
CVV_LENGTHS = {CardNetwork.OTHER: (3, 4)}
DEFAULT_CVV_LENGTHS = (3,)
MAX_EXPIRY_YEARS_AHEAD = 20
BANK_ACCOUNT_LENGTHS = range(9, 19)  # 9 to 18 digits

# The first four letters of an IFSC identify the bank.
IFSC_BANK_PREFIX = {
    Bank.SBI: 'SBIN', Bank.HDFC: 'HDFC', Bank.ICICI: 'ICIC', Bank.AXIS: 'UTIB',
    Bank.KOTAK: 'KKBK', Bank.PNB: 'PUNB', Bank.BOB: 'BARB', Bank.CANARA: 'CNRB',
}


class InvalidDetail(ValueError):
    """Raised with a static, user-safe message."""


def _digits(value, message):
    cleaned = re.sub(r'[\s-]', '', value)
    if not cleaned or not cleaned.isdigit() or not cleaned.isascii():
        raise InvalidDetail(message)
    return cleaned


def luhn_valid(number):
    total = 0
    for index, char in enumerate(reversed(number)):
        digit = int(char)
        if index % 2 == 1:
            digit = digit * 2 - 9 if digit > 4 else digit * 2
        total += digit
    return total % 10 == 0


def clean_person_name(value, message):
    name = ' '.join(value.split())
    letters = [c for c in name if c.isalpha()]
    if len(letters) < 2 or len(name) > 60 or any(not (c.isalpha() or c in " .'-") for c in name):
        raise InvalidDetail(message)
    return name


def clean_card_number(value, network):
    number = _digits(value, 'Enter a valid card number.')
    allowed = CARD_LENGTHS.get(network, CARD_LENGTHS[CardNetwork.OTHER])
    # The first digit is the issuer category; no real card starts with 0 (all-zero numbers pass Luhn).
    if number[0] == '0' or len(number) not in allowed or not luhn_valid(number):
        raise InvalidDetail('Enter a valid card number.')
    return number


def clean_expiry(value, today):
    match = EXPIRY_PATTERN.match(value)
    if not match:
        raise InvalidDetail('Enter the expiry date as MM/YY.')
    month, year = int(match.group(1)), int(match.group(2))
    year += 2000 if year < 100 else 0
    if (year, month) < (today.year, today.month):
        raise InvalidDetail('This card has expired.')
    if year > today.year + MAX_EXPIRY_YEARS_AHEAD:
        raise InvalidDetail('Enter a valid expiry date.')
    return month, year


def clean_cvv(value, network):
    lengths = CVV_LENGTHS.get(network, DEFAULT_CVV_LENGTHS)
    if not value.isdigit() or not value.isascii() or len(value) not in lengths:
        raise InvalidDetail(f'Enter the {" or ".join(map(str, lengths))}-digit CVV.')
    return value


def clean_account_number(value):
    number = _digits(value, 'Enter a valid account number (digits only).')
    if len(number) not in BANK_ACCOUNT_LENGTHS:
        raise InvalidDetail('Account numbers have 9 to 18 digits.')
    return number


def clean_ifsc(value, bank):
    code = value.strip().upper()
    if not IFSC_PATTERN.match(code):
        raise InvalidDetail('Enter a valid IFSC code, like HDFC0001234.')
    expected = IFSC_BANK_PREFIX.get(bank)
    if expected and not code.startswith(expected):
        raise InvalidDetail('This IFSC code does not belong to the selected bank.')
    return code


def clean_mobile(value):
    number = re.sub(r'[\s-]', '', value)
    for prefix in ('+91', '91', '0'):
        if number.startswith(prefix) and len(number) - len(prefix) == 10:
            number = number[len(prefix):]
            break
    if not MOBILE_PATTERN.match(number):
        raise InvalidDetail('Enter a valid 10-digit mobile number.')
    return number


def clean_wallet_id(value):
    identifier = value.strip()
    if not WALLET_ID_PATTERN.match(identifier):
        raise InvalidDetail('Enter a valid wallet ID (4 to 64 letters, numbers or . _ @ + -).')
    return identifier


def mask_last4(digits):
    return f'**** {digits[-4:]}'


def mask_mobile(mobile):
    return f'******{mobile[-4:]}'


def mask_identifier(identifier):
    visible = identifier[:2] + '***' + identifier[-2:] if len(identifier) >= 8 else '***' + identifier[-2:]
    return visible[:32]


def _text(data, key):
    return str(data.get(key) or '').strip()


def _choice(data, key, choices, required_message, invalid_message, errors):
    value = _text(data, key)
    if not value:
        errors[key] = required_message
        return ''
    if value not in choices.values:
        errors[key] = invalid_message
        return ''
    return value


def _guard(errors, key, function, *args):
    try:
        return function(*args)
    except InvalidDetail as exc:
        errors[key] = str(exc)
        return None


def _card(data, today, errors):
    network = _choice(data, 'card_network', CardNetwork, 'Select the card network.', 'Choose a valid card network.', errors)
    name = _text(data, 'cardholder_name')
    if not name:
        errors['cardholder_name'] = 'Enter the cardholder name.'
    else:
        _guard(errors, 'cardholder_name', clean_person_name, name, 'Enter the name as it appears on the card.')
    raw_number = _text(data, 'card_number')
    number = None
    if not raw_number:
        errors['card_number'] = 'Enter the card number.'
    else:
        number = _guard(errors, 'card_number', clean_card_number, raw_number, network or CardNetwork.OTHER)
    raw_expiry = _text(data, 'card_expiry')
    if not raw_expiry:
        errors['card_expiry'] = 'Enter the expiry date.'
    else:
        _guard(errors, 'card_expiry', clean_expiry, raw_expiry, today)
    raw_cvv = _text(data, 'card_cvv')
    if not raw_cvv:
        errors['card_cvv'] = 'Enter the CVV.'
    else:
        _guard(errors, 'card_cvv', clean_cvv, raw_cvv, network or CardNetwork.OTHER)
    return {'card_network': network, 'masked_reference': mask_last4(number) if number else ''}


def _upi(data, today, errors):
    provider = _choice(data, 'upi_provider', UpiProvider, 'Select the UPI app.', 'Choose a valid UPI app.', errors)
    upi_id = _text(data, 'upi_id')
    if not upi_id:
        errors['upi_id'] = 'Enter the UPI ID.'
    elif not UPI_ID_PATTERN.match(upi_id):
        errors['upi_id'] = 'Enter a valid UPI ID, like name@bank.'
    return {'upi_provider': provider, 'upi_id': upi_id.lower()}


def _bank(data, today, errors):
    bank = _choice(data, 'bank_name', Bank, 'Select the bank.', 'Choose a valid bank.', errors)
    holder = _text(data, 'account_holder_name')
    if not holder:
        errors['account_holder_name'] = 'Enter the account holder name.'
    else:
        _guard(errors, 'account_holder_name', clean_person_name, holder, 'Enter the account holder name as it appears on the account.')
    raw_account, raw_confirm = _text(data, 'account_number'), _text(data, 'confirm_account_number')
    account = None
    if not raw_account:
        errors['account_number'] = 'Enter the account number.'
    else:
        account = _guard(errors, 'account_number', clean_account_number, raw_account)
    if not raw_confirm:
        errors['confirm_account_number'] = 'Confirm the account number.'
    elif account and re.sub(r'[\s-]', '', raw_confirm) != account:
        errors['confirm_account_number'] = 'Account numbers do not match.'
    raw_ifsc = _text(data, 'ifsc_code')
    ifsc = None
    if not raw_ifsc:
        errors['ifsc_code'] = 'Enter the IFSC code.'
    else:
        ifsc = _guard(errors, 'ifsc_code', clean_ifsc, raw_ifsc, bank)
    return {'bank_name': bank, 'ifsc_code': ifsc or '', 'masked_reference': mask_last4(account) if account else ''}


def _wallet(data, today, errors):
    provider = _choice(data, 'wallet_provider', WalletProvider, 'Select the wallet provider.', 'Choose a valid wallet provider.', errors)
    id_type = _choice(data, 'wallet_identifier_type', WalletIdentifierType, 'Choose how to identify your wallet.', 'Choose a valid identifier type.', errors)
    raw = _text(data, 'wallet_identifier')
    masked = ''
    if not raw:
        errors['wallet_identifier'] = 'Enter the mobile number.' if id_type == WalletIdentifierType.MOBILE else 'Enter the wallet identifier.'
    elif id_type == WalletIdentifierType.MOBILE:
        mobile = _guard(errors, 'wallet_identifier', clean_mobile, raw)
        masked = mask_mobile(mobile) if mobile else ''
    elif id_type == WalletIdentifierType.WALLET_ID:
        identifier = _guard(errors, 'wallet_identifier', clean_wallet_id, raw)
        masked = mask_identifier(identifier) if identifier else ''
    return {'wallet_provider': provider, 'wallet_identifier_type': id_type, 'masked_reference': masked}


_METHODS = {
    PaymentMethod.CARD: _card,
    PaymentMethod.UPI: _upi,
    PaymentMethod.BANK_TRANSFER: _bank,
    PaymentMethod.WALLET: _wallet,
}

# Every method-specific column on the Transaction model; unused ones are stored blank.
STORED_DEFAULTS = {
    'card_network': '', 'upi_id': '', 'upi_provider': '', 'bank_name': '', 'ifsc_code': '',
    'wallet_provider': '', 'wallet_identifier_type': '', 'masked_reference': '',
}


def validate_method_details(method, data, today=None):
    """Returns (values_to_store, errors).

    ``data`` may contain raw sensitive input; ``values_to_store`` never does. Fields that
    belong to other payment methods are ignored (and therefore never stored).
    """
    errors = {}
    stored = _METHODS[method](data, today or date.today(), errors)
    return {**STORED_DEFAULTS, **stored}, errors
