"""Loads ``backend/.env`` into ``os.environ`` with an explicit, documented precedence.

Precedence (highest first):

1. A real environment variable with a NON-EMPTY value (deployment platform, systemd, Docker, CI, an
   ``export`` in your shell). Deployment configuration is never overridden by the file.
2. The value in ``backend/.env`` (local development file, never committed).
3. The default written in ``config/settings.py`` (only for settings that have one).

An environment variable that exists but is EMPTY (or only whitespace) carries no configuration, so it is
treated as "not set" and the ``.env`` value fills it. ``python-dotenv``'s default behaviour is to keep any
existing variable, even an empty one, which is how a stray ``export FRAUD_INR_PER_USD=`` in a shell profile,
an IDE run configuration or a copied ``.env.example`` silently turned a valid ``.env`` value into "not set".

The file is read as UTF-8 and a leading byte-order mark (added by some Windows editors) is ignored; without
that the first key of the file would be misnamed. Values are never logged.
"""
import os
from pathlib import Path

from dotenv import dotenv_values


def load_env_file(path):
    """Applies ``path`` to ``os.environ`` using the precedence above.

    Returns a dict of non-secret facts (never values) that the system checks can report:
    ``{'path': str, 'found': bool, 'applied': [names], 'kept_from_environment': [names]}``.
    """
    path = Path(path)
    report = {'path': str(path), 'found': path.is_file(), 'applied': [], 'kept_from_environment': []}
    if not report['found']:
        return report
    for name, value in dotenv_values(path, encoding='utf-8-sig').items():
        if value is None:                       # a bare "NAME" line without "="
            continue
        if os.environ.get(name, '').strip():    # a real, non-empty variable wins
            report['kept_from_environment'].append(name)
            continue
        os.environ[name] = value
        report['applied'].append(name)
    return report
