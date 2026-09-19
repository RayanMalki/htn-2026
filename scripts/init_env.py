"""Create local configuration without printing or committing generated secrets."""
import secrets
from pathlib import Path

destination = Path(".env")
if destination.exists():
    raise SystemExit(".env already exists; left unchanged")
text = Path(".env.example").read_text()
text = text.replace("replace-with-a-long-random-password", secrets.token_hex(24))
text = text.replace("ADMIN_TOKEN=\n", f"ADMIN_TOKEN={secrets.token_hex(24)}\n")
text = text.replace("MEDIA_ROOT=/data", "MEDIA_ROOT=data")
text = text.replace("REDIS_URL=redis://redis:6379/0", "REDIS_URL=redis://127.0.0.1:6379/0")
lines = ["DATABASE_URL=sqlite:///./data/hypecheck.db" if line.startswith("DATABASE_URL=") else line for line in text.splitlines()]
destination.write_text("\n".join(lines) + "\n")
destination.chmod(0o600)
print("Created .env with generated local secrets. Add external service keys there.")
