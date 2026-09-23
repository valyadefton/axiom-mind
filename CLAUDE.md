📝 Готовый CLAUDE.md (копируй целиком)
markdown
# Axiom Mind — B2B AI-агент для поиска клиентов

## 👤 КТО Я
Валя, 17 лет, ПГТ Серышево, Амурская область, Россия.
Строю AI-агента для B2B-поиска клиентов. Цель: выйти на рынок США, переехать в Америку.
Работаю одна. Без бюджета. Без команды. Без менторов.

## 🎯 МИССИЯ ПРОЕКТА
**Zero-Trust Outbound** — AI, который гарантирует, что письмо дойдёт и попадёт в боль.

Отличие от конкурентов:
- **Signal-First** — ищем не «IT-компании», а тех, у кого триггер: наняли SDR, привлекли раунд, сменили CRO
- **Verified-Only** — верификация email в момент отправки. Гарантия: bounce <1%
- **5-Minute Review** — человек в цикле, но без рутины
- **Ценник:** $99–199/мес (не $19)

## 🛠️ ТЕКУЩИЙ СТЕК

| Компонент | Инструмент | Статус |
|---|---|---|
| Оркестрация | n8n (Docker, порт 5678) | ✅ Работает |
| AI Agent | n8n AI Agent + Claude Haiku 4.5 | ✅ Работает |
| LLM | Polza.ai (`anthropic/claude-haiku-4.5`) | ✅ Работает |
| Поиск компаний | Serper.dev | ✅ Работает |
| База данных | Supabase (`leads`, `contacts`, `emails`, `searches`) | ✅ Работает |
| Email-поиск | Intel-Harvester (порт 8001) | ⚠️ Возвращает мусор |
| Email-поиск (цель) | Prospector MCP (порт 8080) | ❌ Не подключается |
| Бэкенд | FastAPI (`main.py`) | ✅ Работает |
| Фронтенд | HTML/CSS/JS (`index.html`) | ✅ Работает |

## 🏗️ АРХИТЕКТУРА
Webhook (POST /axiom-mind)
↓
AI Agent (Claude Haiku 4.5 через Polza.ai)
├── Tool: serper_search (поиск компаний) ✅
├── Tool: save_lead (Supabase) ✅
└── Tool: find_email (Prospector MCP) ❌
↓
Respond to Webhook

text

## 📁 ФАЙЛЫ ПРОЕКТА
C:\axiom-mind-backend-claude
├── main.py # FastAPI бэкенд (v15.1)
├── index.html # Фронтенд (тёмная тема, 3 таба)
├── requirements.txt # Зависимости
├── .env # Ключи (НЕ в GitHub)
├── .env.example # Шаблон
└── supabase_schema.sql # Схема БД

C:\intel-harvester
├── harvest.py # Поиск email (мусорный)
└── harvester_server.py # HTTP-обёртка (порт 8001)

C:\Users\Admin\AppData\Roaming\npm\node_modules\prospector-mcp
└── src
└── http-server.js # Prospector HTTP-сервер (порт 8080)

text

## 🚨 ТЕКУЩАЯ ПРОБЛЕМА: Prospector MCP

### Симптом
При подключении n8n к Prospector через MCP Client Tool:
Test prospector
Could not connect to your MCP server

text
`activeClients` остаётся `0`.

### Root Cause (найден в GitHub Issues)
Это **известный баг в n8n** — MCP Client Tool не может поддерживать постоянную SSE-сессию, которая нужна для MCP-протокола.

- MCP требует **persistent SSE connection**
- n8n MCP Client Tool создаёт **новую HTTP-сессию** для каждого запроса
- Теряется состояние инициализации MCP
- Сервер отвечает: `"Server not initialized"`

### Что уже сделано
1. ✅ Установлен Node.js (`v24.21.0`) и npm (`11.19.0`)
2. ✅ Установлен `prospector-mcp`
3. ✅ Запущен Prospector HTTP-сервер на порту **8080**
4. ✅ Проверка `/health` работает (`status: ok`)
5. ✅ Открыт порт 8080 в Windows Firewall

### Что попробовать (по приоритету)
1. **Community-нода `n8n-nodes-mcp`** — работает корректно, в отличие от встроенной
2. **Отключить gzip** в n8n (`N8N_SKIP_RESPONSE_COMPRESSION=true`)
3. **Заменить Endpoint** на IP Windows (`http://192.168.x.x:8080/mcp`)
4. **Проверить `serverTransport`** через Expression mode (`=httpStreamable`)
5. **Fallback:** Intel-Harvester + верификация через Prospector отдельным шагом

## 🔑 КЛЮЧИ (в `.env`)

```env
SUPABASE_URL=https://weltzzqphidbcesvlndp.supabase.co
SUPABASE_KEY=твой_ключ
GROQ_API_KEY=твой_ключ
SERPER_API_KEY=твой_ключ
POLZA_API_KEY=твой_ключ
🗄️ БАЗА ДАННЫХ (Supabase)
Таблицы:

leads — компании (id, company_name, website, fit_score, why_fit, niche, city)

contacts — контакты (id, lead_id, full_name, position, email, email_status)

emails — письма (id, lead_id, variant, subject, body)

searches — история поисков (id, user_id, product_description, niche, city)

Не трогать: telegram_users (старая таблица FreeDrive).

📝 КОМАНДЫ ЗАПУСКА
n8n:

powershell
docker run -it --rm --name n8n -p 5678:5678 -e GENERIC_TIMEZONE="Asia/Yakutsk" -e TZ="Asia/Yakutsk" -e N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true -v n8n_data:/home/node/.n8n docker.n8n.io/n8nio/n8n
Prospector MCP:

powershell
$env:PROSPECTOR_PORT=8080
node "C:\Users\Admin\AppData\Roaming\npm\node_modules\prospector-mcp\src\http-server.js"
Проверка Prospector:

powershell
Invoke-RestMethod -Uri "http://localhost:8080/health" -Method Get
Тест Axiom Mind:

powershell
Invoke-RestMethod -Uri "http://localhost:5678/webhook-test/axiom-mind" -Method Post -ContentType "application/json" -Body '{"niche": "dental clinics", "city": "Moscow", "product": "SaaS for appointment management"}'
🎯 ЧТО НУЖНО СДЕЛАТЬ (довести до идеала)
Приоритет 1: Починить email
Подключить Prospector MCP к n8n (через community-ноду или обход)

Или использовать альтернативу (StartupHub.ai, Anymail Finder)

Добавить verify_email шаг перед сохранением контакта

Приоритет 2: Добавить Signals (триггеры)
Парсинг вакансий (найм SDR)

Парсинг новостей (раунды инвестиций)

Парсинг LinkedIn (смена CRO)

Приоритет 3: Персонализация писем
3-шаговая последовательность с разными углами

Без «созвонов» в первом письме

Упоминание конкретного триггера

Приоритет 4: Фронтенд RU/EN
Переключатель языка

Тёмная/светлая тема

Анимации

Приоритет 5: Хостинг 24/7
VPS (Hetzner €4.99 или Timeweb 200₽)

Docker Compose: n8n + FastAPI + Caddy

Приоритет 6: Монетизация
Freemium: 5 лидов/мес

Pay-per-use: $0.40–0.60 за лид

Подписка: $19–99/мес

💡 ПРАВИЛА РАБОТЫ
Пиши код полностью, не кусками.

Объясняй каждый шаг — я новичок.

Давай команды для PowerShell (Windows).

Если предлагаешь решение — объясни, почему оно сработает.

Не удаляй существующую логику без объяснения.

Не предлагай платные решения без бесплатной альтернативы.

Говори честно, если решение не сработает.

📊 МЕТРИКИ УСПЕХА
Время от запроса до результата ≤ 90–120 секунд

% валидных email ≥ 70–75%

CAC < $5–7 на платящего клиента

3 из 10 первых пользователей возвращаются сами

🌍 ЯЗЫКИ
Русский — для общения со мной

Английский — для кода, промптов, писем (рынок США)

📌 ФИЛОСОФИЯ
Миссия: Свобода через понимание. Дать инструмент, а не «спасти всех».

Принципы: Без войны. Без жадности. Свои правила. Польза людям.

Цель: $10,000/день — не деньги, а точка, где деньги перестают быть вопросом.

Путь: Агент → 10 человек → продукт → 1000 → платформа → движение.

text

### 🛠️ Что делать

1. **Создай файл** `CLAUDE.md` в папке `C:\axiom-mind-backend-claude`.
2. **Вставь текст выше.**
3. **Сохрани.**
4. **Запусти Claude Code** в терминале (в этой папке):
   ```bash
   claude
