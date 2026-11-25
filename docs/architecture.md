# Architecture

Один issue = один прогон = один патч.

## Роли

- `work` — Hermes worker. Read-only checkout target, патч как artifact. GitHub-токен
  в контейнер не передаётся; контейнер получает только ключ выбранного маршрута.
- `core` — диспетчер, guard/verify, PR, merge, revert. Единственный репозиторий
  с write/merge.
- target (`sandbox`, позже проектные repos) — код, который меняет агент.

## Цепочка

1. `core/dispatch` (cron 15m или manual):
   - проверяет `HARNESS_PAUSED`;
   - не запускает второй прогон, если есть `harness:active`;
   - берёт старейший `harness:task`, ставит `harness:active`;
   - читает `targets/<alias>.yml`, берёт base SHA target;
   - dispatch `work/agent`.
2. `work/agent`:
   - checkout target на base SHA с `persist-credentials: false`;
   - host забирает title/body issue (только их) и рендерит prompt;
   - `run_chain.py` по очереди запускает Hermes в Docker для каждого маршрута;
   - workspace сбрасывается перед попыткой; ключ передаётся только в свой контейнер;
   - успешный патч собирается в чистом worktree на base SHA;
   - artifact `harness-output` (`meta.json`, `patch.diff`, `usage*.json`, логи).
3. `work/notify` (workflow_run):
   - скачивает `meta.json`;
   - dispatch `core/publish` с target/issue/run_id.
4. `core/publish`:
   - скачивает artifact из `work` по `actions/download-artifact` (cross-repo token);
   - чистый clone target на base SHA;
   - `git apply --index --binary`;
   - guard (пути, режимы, binary, размеры, labels, gitleaks);
   - verify (манифест из base core, отдельная копия дерева);
   - commit + push ветки, PR, status `harness/verify`;
   - dry-run: PR без merge;
   - kernel core: PR + `harness:needs-approval`, без merge;
   - иначе wait CI -> squash merge -> post-merge verify;
   - ошибка: revert PR + issue + `harness:failed`; две подряд -> `harness:blocked`
     и `HARNESS_PAUSED=true`.
5. `core/resume` снимает pause, сбрасывает failures и возвращает blocked -> task.

## Модели

Chain в `work/scripts/model_chain.json` (все NVIDIA через NIM, один ключ `NVIDIA_API_KEY`):

1. `zai-org/glm-5.3-flash` (NVIDIA NIM) — primary, 60 мин таймаут.
2. `nvidia/nemotron-3-ultra-550b-a55b` (NVIDIA NIM) — fallback на таймаут GLM, 30 мин.
3. `nvidia/nemotron-3.5-super-vl-120b-a12b` (NVIDIA NIM) — fallback, 20 мин.
4. `openai/gpt-oss-120b` (Groq, simple) — last resort, 15 мин.

`validate_chain()` разрешает только эти 3 NVIDIA-модели и `gpt-oss-120b` на Groq.

## Границы

- Патч применяется в чистый clone на base SHA; рабочее дерево агента копируется
  без `.git`.
- `guard/`, `verify/`, `publish/`, `.github/`, `targets/`, dispatch/publish scripts,
  `scripts/common.py` — kernel core: PR + ручной approve.
- Остальной core (docs, tests, helpers) может мержиться автоматически.
- Verify всегда берёт манифест из base-версии core, не из патча.

## Dry-run

`HARNESS_DRY_RUN=true` (repo variable core) доводит прогон до PR и status, но не
мержит и не закрывает issue. Используется в phase 0.
