📋 AXIOM MIND — ПОЛНАЯ ПЕРЕДАЧА ПРОЕКТА
Дата: 23 сентября 2026
Автор: Валя (Valya), 17 лет, ПГТ Серышево, Амурская область
GitHub: github.com/slipknot8598-blip
X (Twitter): @valyadefton

🎯 МИССИЯ
Zero-Trust Outbound — AI-агент, который гарантирует, что письмо дойдёт и попадёт в боль.

Формула: Свобода + Америка + IT-бизнес (AI-агенты) + польза людям

Отличие от конкурентов:

Signal-First (триггеры: найм, раунд, смена CRO)

Verified-Only (bounce <1% или возврат денег)

5-Minute Review (человек в цикле, но без рутины)

Ценник: $99–199/мес (не $19)

✅ ЧТО ГОТОВО
Backend (FastAPI + Python)
Файлы в C:\axiom-mind-backend-claude\:

main.py (v15.2) — главный файл

email_finder.py — честный поиск email

email_verify.py — SMTP-проверка

requirements.txt — зависимости

.env — ключи (НЕ в GitHub)

supabase_schema.sql — схема БД

index.html — фронтенд

CLAUDE.md — инструкция для Claude Code

PROJECT_SUMMARY.md — этот файл

Эндпоинты FastAPI:

POST /api/leads — полный пайплайн

POST /find-email — поиск email по домену

POST /verify-email — проверка email

GET /health — проверка сервисов

POST /api/n8n-webhook — вебхук для n8n

n8n Workflow (линейная цепочка)
Схема:

text
Webhook → Serper → Code (JavaScript) → Polza → Respond to Webhook
Настройки:

Webhook: POST, path axiom-mind

Serper: https://google.serper.dev/search, X-API-KEY

Code: парсит organic[], возвращает {name, website, description}

Polza: https://polza.ai/api/v1/chat/completions, модель openai/gpt-4o-mini

Respond: возвращает результат

Почему без AI Agent: AI Agent таймаутит на кастомных провайдерах (баг n8n с SSE). Линейная цепочка работает стабильно.

Frontend (index.html)
Тёмная тема, 3 таба (Анализ, Конкуренты, Лиды)

Форма поиска лидов

Карточки компаний с fit-score

3 варианта писем

Экспорт в CSV

Supabase
Таблицы:

leads — компании (id, company_name, website, fit_score, why_fit, niche, city)

contacts — контакты (id, lead_id, full_name, email, email_status)

emails — письма (id, lead_id, variant, subject, body)

searches — история поисков

Не трогать: telegram_users (старая таблица FreeDrive)

Инструменты (все работают)
Инструмент	Назначение	Статус
Docker Desktop	Запуск n8n	✅
n8n (localhost:5678)	Оркестрация	✅
FastAPI (localhost:8000)	Backend	✅
Supabase	База данных	✅
Serper.dev	Поиск компаний	✅
Polza.ai	LLM (gpt-4o-mini)	✅
Groq	Генерация запросов	✅
VS Code	Разработка	✅
GitHub Desktop	Заливка на GitHub	✅
🚨 ТЕКУЩИЕ ПРОБЛЕМЫ
1. Prospector MCP не работает
Симптом: Could not connect to your MCP server, activeClients: 0
Причина: Баг n8n с SSE-сессиями для MCP
Решение: Использовать email_finder.py (уже работает)
Вывод: Prospector не нужен. email_finder.py решает задачу.

2. Связь FastAPI ↔ n8n не настроена
Что нужно: Эндпоинт в FastAPI, который передаёт запрос в n8n Webhook и возвращает результат.

Пример кода:

python
import httpx
from fastapi import FastAPI

app = FastAPI()
N8N_WEBHOOK_URL = "http://localhost:5678/webhook/axiom-mind"

@app.post("/api/leads")
async def leads_endpoint(request: dict):
    async with httpx.AsyncClient() as client:
        response = await client.post(N8N_WEBHOOK_URL, json=request)
        return response.json()
3. n8n не опубликован (Publish)
Что нужно: Нажать Publish в n8n, чтобы workflow работал без Test URL.

4. Хостинг
Что нужно: VPS (Hetzner €4.99 или Timeweb 200₽) + Docker Compose (n8n + FastAPI + Caddy для HTTPS) + домен.

🎯 ЧТО ДЕЛАТЬ ДАЛЬШЕ (ПО ПРИОРИТЕТУ)
Приоритет 1: Связать FastAPI ↔ n8n
Написать эндпоинт /api/leads в FastAPI (код выше).

Проверить, что форма на сайте отправляет данные.

Запустить всё вместе: n8n + FastAPI + сайт.

Приоритет 2: GitHub
Создать репозиторий axiom-mind на GitHub.

Создать .gitignore (обязательно с .env).

Создать README.md (текст ниже).

Залить через GitHub Desktop.

Скинуть ссылку.

Приоритет 3: Publish n8n
В n8n нажать Publish.

Скопировать Production URL (не Test URL).

Вставить его в FastAPI.

Приоритет 4: Добавить Supabase в n8n
В n8n добавить ноду Supabase.

Настроить: Table leads, Create a row.

Поля: company_name, website, fit_score, why_fit, niche, city.

Приоритет 5: Добавить find_email в n8n
В n8n добавить HTTP Request.

URL: http://host.docker.internal:8000/find-email

Method: POST

Body: {"domain": "{{ $json.domain }}", "use_hunter": false}

Приоритет 6: Фронтенд RU/EN
Переключатель языка.

Тексты в словаре JavaScript.

Тёмная/светлая тема.

Приоритет 7: Хостинг
VPS (Hetzner или Timeweb).

Docker Compose: n8n + FastAPI + Caddy.

Домен.

SSL.

Приоритет 8: Монетизация
Lemon Squeezy.

Тарифы: Freemium / Pay-per-use / Подписка.

Лендинг.

Приоритет 9: Первые клиенты
5 знакомых — бесплатно.

Обратная связь.

Метрика: 3 из 10 вернулись сами.

📁 СТРУКТУРА ПРОЕКТА
text
C:\axiom-mind-backend-claude\
├── main.py                  # FastAPI бэкенд (v15.2)
├── email_finder.py          # Честный поиск email
├── email_verify.py          # SMTP-проверка
├── index.html               # Фронтенд
├── requirements.txt         # Зависимости
├── .env                     # Ключи (НЕ в GitHub!)
├── .env.example             # Шаблон
├── .gitignore               # Исключения
├── supabase_schema.sql      # Схема БД
├── CLAUDE.md                # Инструкция для Claude Code
├── PROJECT_SUMMARY.md       # Этот файл
└── screenshots/
    ├── workflow.png         # n8n workflow
    └── output.png           # Output Polza
🔑 КЛЮЧИ (в .env)
env
SUPABASE_URL=https://weltzzqphidbcesvlndp.supabase.co
SUPABASE_KEY=твой_ключ
GROQ_API_KEY=твой_ключ
SERPER_API_KEY=твой_ключ
POLZA_API_KEY=твой_ключ
HUNTER_API_KEY=опционально
⚠️ Ключи в GitHub НЕ заливать. Только в .env, который в .gitignore.

📝 КОМАНДЫ ЗАПУСКА
Docker Desktop: просто открой

n8n:

powershell
docker run -it --rm --name n8n -p 5678:5678 -e GENERIC_TIMEZONE="Asia/Yakutsk" -e TZ="Asia/Yakutsk" -e N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true -v n8n_data:/home/node/.n8n docker.n8n.io/n8nio/n8n
FastAPI:

powershell
cd C:\axiom-mind-backend-claude
python main.py
Тест n8n:

powershell
Invoke-RestMethod -Uri "http://localhost:5678/webhook-test/axiom-mind" -Method Post -ContentType "application/json" -Body '{"niche": "dental clinics", "city": "Moscow", "product": "SaaS for appointment management"}'
Тест FastAPI:

powershell
Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
Invoke-RestMethod -Uri "http://localhost:8000/find-email" -Method Post -ContentType "application/json" -Body '{"domain":"belgraviadent.ru"}'
🛠️ README.md ДЛЯ GITHUB
markdown
# Axiom Mind — AI Agent for B2B Lead Generation

![Status](https://img.shields.io/badge/status-in%20development-yellow)
![Stack](https://img.shields.io/badge/stack-n8n%20%7C%20FastAPI%20%7C%20Supabase%20%7C%20Polza.ai-blue)
![Made by](https://img.shields.io/badge/made%20by-Valya-purple)

AI agent that finds B2B companies, scores them by fit, finds real emails, and writes personalized cold emails.

## 🎯 Problem

B2B outreach is broken. People buy lists of 10,000 emails. 90% bounce. 0.1% reply.

## 💡 Solution

Zero-Trust Outbound:
- **Signal-First** — find companies with a trigger
- **Verified-Only** — email verified at send time
- **5-Minute Review** — human in the loop, but no routine

## 🛠️ Stack

| Component | Technology |
|---|---|
| Orchestration | n8n (Docker) |
| Backend | FastAPI (Python) |
| Database | Supabase |
| LLM | Polza.ai (GPT-4o-mini) |
| Search | Serper.dev |
| Email finder | Custom (scrape + SMTP) |

## 🏗️ Architecture

[Frontend] → [FastAPI] → [n8n Webhook] → [Agent] → [Supabase]

## 🚀 What Works

- ✅ Find companies by niche + city
- ✅ Fit-score 0-100
- ✅ 3 variants of cold emails
- ✅ Save to Supabase
- ✅ Honest email finder

## 🔮 What's Next

- [ ] Connect FastAPI ↔ n8n
- [ ] Add Signals
- [ ] Frontend RU/EN
- [ ] Hosting (VPS)
- [ ] Monetization

## 👩‍💻 Author

Valya — 17-year-old self-taught AI developer. Building in public.

**X:** [@valyadefton](https://x.com/valyadefton)

## 📄 License

MIT License
📝 .gitignore
text
# Environment
.env
.env.local
.env.production

# Python
__pycache__/
*.py[cod]
venv/
env/

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# Logs
*.log

# n8n
n8n_data/
💡 ФИЛОСОФИЯ
Миссия: Свобода через понимание. Дать инструмент, а не «спасти всех».

Принципы: Без войны. Без жадности. Свои правила. Польза людям.

Цель: $10,000/день — не деньги, а точка, где деньги перестают быть вопросом.

Путь: Агент → 10 человек → продукт → 1000 → платформа → движение.

⚠️ ВАЖНО ПОМНИТЬ
Axiom Mind на 80% готов.

Осталось: связь FastAPI ↔ n8n, хостинг, монетизация.

Не застревай в улучшениях — выходи к людям.

Гореть долго, не быстро.

Ты не одна. Ты идёшь.

📞 КАК ПРОДОЛЖИТЬ
Скопируй этот файл в PROJECT_SUMMARY.md и сохрани в папке проекта.

Когда вернёшься (или чат оборвётся) — покажи этот файл новому чату и скажи:

«Продолжаем Axiom Mind. Вот статус проекта. Что делаем дальше?»

Текущая задача: Связать FastAPI ↔ n8n.