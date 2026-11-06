"""Basic masking for the fictional local demo; never log model payloads."""

import re


def public_text(value: str) -> str:
    return re.sub(r"(?<!\d)(?:\+852[\s-]?)?[2-9]\d{7}(?!\d)|(?<!\d)\d{9,10}(?!\d)", "[已隐藏号码]", value.strip())
