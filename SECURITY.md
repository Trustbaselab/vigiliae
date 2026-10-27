# Security

Vigiliae runs commands on a server. Treat it like a shell with an HTTP front
door, because that is what it is.

## Defaults
- `VIGILIAE_HOST` defaults to `127.0.0.1`. Put nginx/Caddy in front if you need
  public access. Do not expose port 8110 directly.
- If `BOT_TOKEN` is unset the app runs in open dev mode and prints a warning.
  Always set a long random token on a public host.
- The login cookie is `HttpOnly` and `SameSite=Lax`.
- Tasks are read-only unless `write_perm=1`; dangerous shell patterns are
  blocked even then.
- Tasks with `need_approve=1` are parked until approved through the API/UI.
- `agent` tasks inherit the permissions of the thinking-kernel process. Run that
  process as an unprivileged user.

## Not a sandbox
The `shell` executor is **not** a sandbox. Regex blocklists are a speed bump,
not a security boundary. If you need real isolation, run each task in a
container/VM, or restrict the executor to `http`/`agent`.

## Secrets
- Keep `.env` out of git (it is in `.gitignore`).
- Do not put API keys in `payload` fields; inject them through the environment.
- Rotate `BOT_TOKEN` if a device is lost: change it and restart.

## Reporting a vulnerability
Open a private security advisory on GitHub, or email the maintainer listed in
the repository profile. Please do not open a public issue for an exploitable
bug.
