#!/usr/bin/env python3
"""Interactively write only OPENAI_API_KEY to a private, ignored EC2 file."""
import getpass
import os
from pathlib import Path
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    value = getpass.getpass('OpenAI API key (hidden): ').strip()
    if not value or any(c.isspace() for c in value):
        raise SystemExit('Key was empty or contained whitespace; nothing saved.')
    path = root / '.env.luna'
    with tempfile.NamedTemporaryFile(mode='w', dir=root, prefix='.env.luna.', delete=False) as stream:
        temp = stream.name
        os.fchmod(stream.fileno(), 0o600)
        stream.write('OPENAI_API_KEY=' + value + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    print('Credential saved privately in .env.luna (0600). Its value was not displayed.')


if __name__ == '__main__':
    main()
