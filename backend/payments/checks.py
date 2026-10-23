"""Django system checks for fraud-analysis and e-mail configuration.

They report problems by variable NAME only. They never print values, credentials or file contents.
Run them with ``python manage.py check``.
"""
from email.utils import parseaddr

from django.conf import settings
from django.core.checks import Error, Warning, register

CONSOLE_LIKE = (
    'django.core.mail.backends.console.EmailBackend',
    'django.core.mail.backends.dummy.EmailBackend',
    'django.core.mail.backends.filebased.EmailBackend',
)
SMTP = 'django.core.mail.backends.smtp.EmailBackend'


@register()
def fraud_configuration(app_configs, **kwargs):
    if not settings.FRAUD_MODEL_ENABLED or settings.FRAUD_INR_PER_USD:
        return []
    report = getattr(settings, 'ENV_FILE_REPORT', {})
    problem = getattr(settings, 'FRAUD_INR_PER_USD_PROBLEM', None) or 'FRAUD_INR_PER_USD is not set.'
    hint = ('Fraud verification will be reported as unavailable and no payment can proceed. '
            'Set a positive number in backend/.env or the process environment (an EMPTY variable in your '
            'shell or IDE is treated as unset).')
    if not report.get('found', True):
        hint += f" The expected file {report.get('path')} was not found."
    return [Warning(problem, hint=hint, id='payments.W001')]


@register()
def email_configuration(app_configs, **kwargs):
    problems = []
    backend = settings.EMAIL_BACKEND
    if backend in CONSOLE_LIKE and not settings.DEBUG:
        problems.append(Error(
            'A development-only e-mail backend is configured while DJANGO_DEBUG is off.',
            hint='It would print or discard one-time codes. Set EMAIL_BACKEND to the SMTP backend.',
            id='payments.E001'))
    if backend == SMTP:
        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            problems.append(Warning(
                'SMTP is selected but EMAIL_HOST_USER or EMAIL_HOST_PASSWORD is empty.',
                hint='E-mails will fail (and no code will be issued). Fill them in backend/.env, or use the '
                     'console backend for local development.',
                id='payments.W002'))
        sender = parseaddr(settings.DEFAULT_FROM_EMAIL)[1].lower()
        account = (settings.EMAIL_HOST_USER or '').strip().lower()
        if 'gmail.com' in (settings.EMAIL_HOST or '') and account and sender != account:
            problems.append(Warning(
                'DEFAULT_FROM_EMAIL differs from EMAIL_HOST_USER on Gmail SMTP.',
                hint='Gmail only sends as the authenticated account (or a verified "Send mail as" alias); '
                     'otherwise it rewrites or rejects the sender.',
                id='payments.W003'))
    return problems
