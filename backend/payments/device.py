"""Derives coarse device information from the User-Agent request header.

The user never enters this; it is collected from the request in the background.
"""
import re

from .models import DeviceType

UNKNOWN = 'Unknown'

_BROWSERS = [
    ('Edge', re.compile(r'(?:Edg|EdgA|EdgiOS|Edge)/(\d+)')),
    ('Opera', re.compile(r'(?:OPR|Opera)/(\d+)')),
    ('Samsung Internet', re.compile(r'SamsungBrowser/(\d+)')),
    ('Firefox', re.compile(r'(?:Firefox|FxiOS)/(\d+)')),
    ('Chrome', re.compile(r'(?:Chrome|CriOS)/(\d+)')),
    ('Safari', re.compile(r'Version/(\d+)[\d.]* (?:Mobile/\S+ )?Safari/')),
]


def _device_type(ua):
    lowered = ua.lower()
    if 'ipad' in lowered or 'tablet' in lowered or 'kindle' in lowered:
        return DeviceType.TABLET
    if 'android' in lowered and 'mobile' not in lowered:
        return DeviceType.TABLET
    if any(token in lowered for token in ('iphone', 'ipod', 'mobile', 'android')):
        return DeviceType.MOBILE
    return DeviceType.DESKTOP


def _browser(ua):
    for name, pattern in _BROWSERS:
        match = pattern.search(ua)
        if match:
            return f'{name} {match.group(1)}'
    return 'Other'


def _operating_system(ua):
    # Order matters: Android UAs contain "Linux"; iOS UAs contain "like Mac OS X".
    if 'Windows' in ua:
        return 'Windows'
    if 'Android' in ua:
        return 'Android'
    if any(token in ua for token in ('iPhone', 'iPad', 'iPod')):
        return 'iOS'
    if 'CrOS' in ua:
        return 'ChromeOS'
    if 'Mac OS X' in ua or 'Macintosh' in ua:
        return 'macOS'
    if 'Linux' in ua or 'X11' in ua:
        return 'Linux'
    return 'Other'


def parse_user_agent(user_agent):
    """Returns (device_type, browser, operating_system)."""
    ua = (user_agent or '').strip()[:512]
    if not ua:
        return DeviceType.UNKNOWN, UNKNOWN, UNKNOWN
    return _device_type(ua), _browser(ua), _operating_system(ua)
