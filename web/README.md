# Операторська вебсистема

Вебчастина етапу 3: оператор створює заявки, фоновий обробник оцінює їх через `core.service`, а дошка,
сторінка заявки, проєкти і статистика показують результат. Повне завдання — `docs/web_system.md`.

Вебкод не змінює оцінювання: `core/`, `models/`, `pricedb/`, `config.toml` лишаються як є. Увесь новий код —
у цій теці `web/`, тести — у `tests/web/`, залежності — окрема група `web` у `pyproject.toml`.

## Установлення

1. Залежності вебчастини:

   ```bash
   uv sync --extra web            # або: pip install "fastapi" "uvicorn" "jinja2" "python-multipart"
   ```

2. Набір тестових кейсів (для симулятора): розпакувати `devpack.zip` у корінь репозиторію, щоб вийшло
   `devpack/index.json`. Теку в git не додавати (вона в `.gitignore`).

## Запуск (розробка, без ваг моделі й без ключів)

Два процеси у двох терміналах:

```bash
# 1) вебсервер
DAMAGE_ENGINE=simulator uvicorn web.server:app --reload --port 8000

# 2) фоновий обробник
DAMAGE_ENGINE=simulator python -m web.worker
```

Відкрити http://localhost:8000 . База (`data/web.db`), теки завантажень (`data/uploads/`) і результатів
(`data/results/`) створюються автоматично на першому запуску.

Сервер і обробник спілкуються лише через базу: можна закрити вкладку, перезапустити сервер чи обробник —
обробка все одно завершиться, а застряглі в `Processing` заявки після перезапуску обробника повертаються в чергу.

## Справжня модель (інтеграція)

Коли з'являться ваги моделі, вебкод не змінюється — лише рушій обробника:

```bash
DAMAGE_ENGINE=real python -m web.worker
```

## Змінні середовища

| Змінна | Типово | Призначення |
|---|---|---|
| `DAMAGE_ENGINE` | `real` | `simulator` — обробка з набору `devpack`, без моделі й ключа |
| `DAMAGE_PACK` | `<repo>/devpack` | де лежить набір кейсів для симулятора |
| `DAMAGE_SIM_DELAY` | `3-8` | скільки секунд «обробляє» симулятор (`0` у тестах) |
| `DAMAGE_SIM_FAIL_RATE` | `0` | частка випадкових збоїв симулятора (0…1) |
| `DAMAGE_WEB_DATA` | `<repo>/data` | куди писати базу, завантаження і результати (тести — у тимчасову теку) |

Жодних запитів до Gemini вебчастина не робить: `DAMAGE_LLM_MODE` лишається `offline`, ключів немає.

## Сценарії для перевірки (demo на захисті)

Завантаження для кожного — у `devpack/inputs/`. Відповідають таблиці з `docs/web_system.md`, розділ 5.

| # | Дія | Очікується |
|---|---|---|
| 1 | заявка з `inputs/download11_3/` | Created → Processing → Processed; III / 4 |
| 2 | ще 5–6 заявок з інших тек | дошка заповнена, фільтри працюють |
| 3 | `inputs/_duplicates/copy_of_photo_single.jpg` після `photo_single` | попередження про дублікат, вибір відхилити / об'єднати / продовжити |
| 6 | `inputs/_special/fail_test.jpg` | Failed з текстом помилки; «Повторити» |
| 7 | `inputs/_special/lowconf_test.jpg` | Processed, «Недостатньо даних», без категорії й вартості |
| 9 | змінити поверхи на сторінці заявки | вартість змінилась, редакція 2 |
| 10 | затвердити одну, відхилити іншу з причиною | статуси й історія оновилися |
| 11 | проєкт із кількох заявок | сума вартості проєкту |
| 12 | перезапустити обробник під час обробки | застрягла заявка знову в черзі |

## Тести

```bash
python -m pytest tests/web -q
```

Тести ганяють сценарії вище на симуляторі в тимчасовій базі (`DAMAGE_WEB_DATA`), ваги моделі не потрібні.

## Структура

```
web/
  config.py        теки й ліміти (з core.config / config.toml)
  db.py            SQLAlchemy: engine, сесії, init_db (SQLite + WAL)
  models.py        application, application_file, project, status_change, статуси
  service.py       бізнес-логіка: створення, статуси, дублікати, статистика (без FastAPI і без рушія)
  files.py         збереження завантажень, sha256, перевірка типів/розміру
  worker.py        фоновий обробник: python -m web.worker (єдине місце, де працює рушій)
  server.py        FastAPI: монтування статики, підключення маршрутів
  templating.py    Jinja2 + українські довідники й фільтри
  routes/          applications, projects, statistics
  templates/       board, new, application, project(s), statistics, partials
  static/app.css
```
