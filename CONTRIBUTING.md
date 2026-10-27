# Contributing

Thanks for taking a look. This is an early-stage project maintained by one
person, so the most useful contributions are small and focused.

## Good first issues
- Add an executor for another thinking-kernel CLI (Ollama, llama.cpp, etc.).
- Improve the rule engine (more languages / more commands).
- Add tests for `price_slot` and `cron_match`.
- Improve the mobile UI accessibility.

## Ground rules
1. Do not commit secrets. `.env` is git-ignored; use `.env.example` for keys.
2. Keep the core small. This project deliberately avoids a plugin system, a
   web framework, and an ORM.
3. If you change behaviour, update `docs/ARCHITECTURE.md` and `CHANGELOG.md`.
4. One logical change per pull request.

## Development
```bash
python -m venv .venv
. .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
cp agents.yaml.template agents.yaml
python -m vigiliae
```

Open http://127.0.0.1:8110. With an empty `BOT_TOKEN` the app runs in open dev
mode; set one before exposing it to a network.

## Reporting bugs
Please include: OS, Python version, the command you ran, the relevant log lines
from `data/logs/`, and whether a thinking kernel was configured.
