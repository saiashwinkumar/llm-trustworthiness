"""Create a local research-server key without printing it or replacing an existing key."""
from pathlib import Path
import secrets

path = Path(__file__).resolve().parent / ".env"
try:
    with path.open("x", encoding="utf-8") as handle:
        handle.write("MODEL_BASE_URL=http://127.0.0.1:8000\n")
        handle.write("MODEL_API_KEY=" + secrets.token_urlsafe(36) + "\n")
        handle.write("MODEL_TIMEOUT_SECONDS=180\n")
except FileExistsError:
    raise SystemExit(".env already exists; it was left unchanged.")
try:
    path.chmod(0o600)
except OSError:
    pass
print("Created .env. Open it in VS Code and copy MODEL_API_KEY when the AWS server asks for it. Keep it private.")
