# Bootstrap

Пошаговая установка harness. Все имена ниже — дефолтные; если репозитории
называются иначе, поправьте `core/targets/*.yml` и repo variables.

## 1. Репозитории

Создайте три пустых репозитория (private или public):

- `harness-core` — диспетчер, проверки, publish;
- `harness-work` — worker и model chain;
- `harness-sandbox` — пустой target для первого прогона.

Репозитории должны иметь ветку `main`. В `harness-sandbox` достаточно
`.gitkeep`; README появится в первой задаче.

## 2. GitHub App `harness-bot`

Settings -> Developer settings -> GitHub Apps -> New GitHub App.

- Homepage URL: любой (например, `https://github.com/OWNER/harness-core`).
- Webhook: выключен.
- Repository permissions:
  - Contents: Read and write
  - Pull requests: Read and write
  - Issues: Read and write
  - Commit statuses: Read and write
  - Checks: Read-only (нужно для чтения нативного CI)
  - Actions: Read and write
  - Workflows: Read and write (нужно для kernel PR, меняющих `.github/workflows`)
  - Metadata: Read-only
- Install App на `harness-core`, `harness-work`, `harness-sandbox`.

Сгенерируйте private key. В `harness-core` и `harness-work` добавьте secrets:

- `APP_ID`
- `APP_PRIVATE_KEY` (содержимое `.pem`)

## 3. Secrets и variables

В `harness-work` -> Settings -> Secrets and variables -> Actions:

Secrets:

- `NVIDIA_API_KEY` (все NVIDIA NIM модели: GLM-5.3-Flash, Nemotron 3 Ultra, Nemotron 3.5 Super VL)
- `GROQ_API_KEY`

Variables (опционально):

- `HERMES_IMAGE` — digest образа; по умолчанию
  `nousresearch/hermes-agent@sha256:ef0650d523ee1b5ab32c779acabc446d9936869a9932591553688a62bcf0c42f`.
- `HARNESS_CORE_REPO` — `OWNER/harness-core` (для `work/notify`).
- `HARNESS_WORK_REPO` — `OWNER/harness-work` (для `core/dispatch`).

В `harness-core` variables:

- `HARNESS_WORK_REPO` — `OWNER/harness-work`.
- `HARNESS_DRY_RUN` — `true` для phase 0, потом `false`.
- `HARNESS_PAUSED` и `HARNESS_FAILURES` создаются автоматически.

## 4. Labels

В `harness-core`:

```bash
GH_TOKEN=<token> python scripts/bootstrap_labels.py --repo OWNER/harness-core
```

Или создайте вручную:

| Label | Назначение |
|---|---|
| `harness:task` | открытая задача |
| `harness:active` | взята в работу |
| `harness:failed` | была ошибка |
| `harness:blocked` | вторая ошибка, не брать |
| `harness:done` | закрыта |
| `harness:needs-approval` | kernel PR ждёт approve |
| `harness:dry-run` | PR создан без merge |
| `allow-tests` | разрешить менять tests |
| `allow-deps` | разрешить менять зависимости |
| `target:sandbox` | target sandbox |
| `target:core` | target core |

## 5. Branch protection

Для `harness-core` и `harness-sandbox`:

- Require a pull request before merging.
- Require status checks: `harness/verify`.
- «Require branches to be up to date» можно не включать: harness не делает update-branch.
- Для `harness-core` дополнительно `ci` (workflow `.github/workflows/ci.yml`).
- Allow squash merging; merge commit и rebase можно выключить.
- Restrict direct pushes (включить branch protection / ruleset).
- Не требовать approvals: PR создаёт bot, approve будет только для kernel.
- Не включать «Require signed commits»: bot-коммиты не подписаны.

Для `harness-work`: PR + `ci`, direct push запрещён.

Важно: branch protection не должна требовать `harness/verify` на `harness-work`.

## 6. Первый push

```bash
cd core && git init -b main && git add -A && git commit -m "core: phase 0-2 skeleton"
git remote add origin git@github.com:free-autonomy-harness/harness-core.git && git push -u origin main

cd ../work && git init -b main && git add -A && git commit -m "work: hermes model chain"
git remote add origin git@github.com:free-autonomy-harness/harness-work.git && git push -u origin main

cd ../sandbox && git init -b main && git add -A && git commit -m "sandbox: init"
git remote add origin git@github.com:free-autonomy-harness/harness-sandbox.git && git push -u origin main
```

Сначала запушьте `sandbox`, затем `core` и `work`: `core/dispatch` читает
base SHA из target.

## 7. Smoke моделей

В `harness-work` запустите `work / check-models` (workflow_dispatch). Должны
пройти четыре маршрута:

- `glm-5.3-flash-nvidia` (NVIDIA NIM, GLM-5.3-Flash, **холодный старт до 45 сек**, таймаут 40 мин)
- `nemotron-ultra-nvidia` (NVIDIA NIM, Nemotron 3 Ultra 550B)
- `nemotron-super-vl-nvidia` (NVIDIA NIM, Nemotron 3.5 Super VL)
- `gpt-oss-groq` (Groq, gpt-oss-120b)

## 8. Phase 0: dry-run

1. `HARNESS_DRY_RUN=true` в `harness-core`.
2. Создайте issue:
   - title: `[sandbox] Add README`
   - labels: `harness:task`, `target:sandbox`
   - body:
     ```
     Details: Create README.md with project name and how to run.
     Done when: README.md exists and is not empty.
     Constraints: Only README.md.
     ```
3. Запустите `core / dispatch` вручную.
4. Проверьте цепочку: `work / agent` -> `work / notify` -> `core / publish`.
5. В issue появится PR и комментарий `Dry-run`; merge не произойдёт.
6. Проверьте патч и лог. Если всё ок — `HARNESS_DRY_RUN=false`, закройте
   dry-run issue или создайте новую задачу.

## 9. Phase 1: первый merge

С `HARNESS_DRY_RUN=false` создайте ту же задачу. Ожидаемый результат:

- PR в `harness-sandbox` с `README.md`;
- status `harness/verify` = success;
- squash merge;
- issue закрыт с `harness:done`.

Повторите 3 раза, чтобы проверить стабильность.

## 10. Проверка предохранителей

- Создайте задачу, которая меняет `.env` — guard должен отклонить.
- Создайте core-задачу, меняющую `guard/rules.yml` — PR должен получить
  `harness:needs-approval` и не мержиться.
- Две ошибки подряд -> `harness:blocked` + `HARNESS_PAUSED=true`;
  `core / resume` снимает паузу.
