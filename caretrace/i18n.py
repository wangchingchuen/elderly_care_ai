"""Shared system-message catalog. User data and machine identifiers stay unchanged."""
import json
import re
from pathlib import Path

EN = json.loads((Path(__file__).parent / 'locales/en.json').read_text(encoding='utf-8'))


def translate(message, locale='zh-TW', *values):
    template = EN.get(message, message) if locale == 'en' else message
    return re.sub(r'\{(\d+)\}', lambda m: str(values[int(m[1])]), template) if values else template


def system_message(message, locale):
    if not message or locale != 'en':
        return message
    if message in EN:
        return EN[message]
    match = re.fullmatch(r'語言模型不可用或輸出未通過驗證（([^）]+)），改用關鍵字備援', message)
    if match:
        return translate('語言模型不可用或輸出未通過驗證（{0}），改用關鍵字備援', locale, match[1])
    return message
