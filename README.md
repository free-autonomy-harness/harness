<<<<<<< HEAD
# harness-core

Диспетчер и единственный write/merge-узел harness.

- `scripts/dispatch.py` — очередь issue -> `work/agent`.
- `guard/` — проверка патча до PR.
- `verify/run.py` — проверки target из `targets/<alias>.yml`.
- `publish/run.py` — clone/apply/guard/verify/PR/merge/revert.
- `scripts/resume.py` — снять pause.
- `targets/` — манифесты target-репозиториев.

Локально:

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/check_config.py
```

Установка: `docs/bootstrap.md`.

