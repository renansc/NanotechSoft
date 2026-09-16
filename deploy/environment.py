"""Read deployment selectors from dotenv without executing shell commands.

Credentials remain in the selected file, which Compose reads with --env-file.
Only operational selectors are exported here; inherited variables take priority.
"""
import os
from pathlib import Path
import re
import shlex
import sys

SELECTORS = {
    "NANOTECH_DEPLOY_PROFILE", "CLIENTE_DEPLOY_ID", "NS_DEPLOY_MODE",
    "NS_READ_ONLY", "NS_CACHE_PROVIDER", "COMPOSE_PROJECT_NAME",
    "NOTECHSOFT_APP_PORT", "NOTECHSOFT_HTTPS_PORT", "RB_HTTPS_PORT",
}


def deployment_environment(root, environ):
    explicit = environ.get("NANOTECH_ENV_FILE")
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            raise ValueError("NANOTECH_ENV_FILE nao aponta para um arquivo existente")
    else:
        path = next((root / name for name in (".env", ".env_local") if (root / name).is_file()), None)
    values = {}
    if path:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
            if not match or match[1] not in SELECTORS or match[1] in environ:
                continue
            try:
                parts = shlex.split(match[2], comments=True)
            except ValueError:
                raise ValueError(f"Valor invalido para {match[1]} no arquivo de ambiente") from None
            if len(parts) > 1 or (parts and re.search(r"[$`\r\n]", parts[0])):
                raise ValueError(f"Use um valor literal para {match[1]} no arquivo de ambiente")
            values[match[1]] = parts[0] if parts else ""
    # A quoted, fixed-name assignment is safe to eval; file contents are not shell code.
    lines = [f"export {key}={shlex.quote(value)}" for key, value in values.items()]
    if path:
        lines.append(f"export NANOTECH_ENV_FILE={shlex.quote(str(path.resolve()))}")
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        print(deployment_environment(Path(sys.argv[1]).resolve(), os.environ))
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
