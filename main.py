"""
Axiom Mind - Enterprise B2B Intelligence & Lead Generation Platform
Version 15.2 - Serper.dev + Polza.ai (Claude Haiku 4.5) + email_finder (website scrape + SMTP verify)
"""

import os
import re
import json
import uuid
import glob
import csv
import logging
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from groq import Groq
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from email_verify import verify_email_address
from email_finder import find_emails_for_domain

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger("axiom_mind")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")
POLZA_API_KEY = os.environ.get("POLZA_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

SERPER_URL = "https://google.serper.dev/search"
POLZA_URL = "https://polza.ai/api/v1/chat/completions"
POLZA_MODEL = "anthropic/claude-haiku-4.5"
GROQ_QUERY_MODEL = "llama-3.1-8b-instant"

MAX_CANDIDATE_LEADS = 30
TOP_LEADS_TO_ENRICH = 10
HUNTER_MIN_SCORE = 90  # Hunter.io (если задан HUNTER_API_KEY) — только для лидов с fit_score >= этого
CONCURRENCY_LIMIT = 5
INTEL_HARVESTER_PATH = "C:\\intel-harvester"

supabase: Optional[Client] = None
groq_client: Optional[Groq] = None
http_client: Optional[httpx.AsyncClient] = None

JOBS: Dict[str, Dict] = {}


def init_clients():
    global supabase, groq_client
    try:
        if SUPABASE_URL and SUPABASE_KEY:
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            logger.info("Supabase client готов")
        else:
            logger.warning("SUPABASE_URL/SUPABASE_KEY не заданы — сохранение в БД отключено")
    except Exception as e:
        logger.error(f"Supabase init failed: {e}")

    try:
        if GROQ_API_KEY:
            groq_client = Groq(api_key=GROQ_API_KEY)
            logger.info("Groq client готов")
        else:
            logger.warning("GROQ_API_KEY не задан — генерация запросов упадёт на фолбэк")
    except Exception as e:
        logger.error(f"Groq init failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=30.0)
    init_clients()
    yield
    await http_client.aclose()


app = FastAPI(title="Axiom Mind", version="15.2", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    query: str
    industry: Optional[str] = None


class CompetitorRequest(BaseModel):
    url: str


class LeadsRequest(BaseModel):
    niche: str
    city: str
    product: str = ""
    user_id: Optional[str] = None


class VerifyEmailRequest(BaseModel):
    email: str


class FindEmailRequest(BaseModel):
    domain: str
    limit: int = 3
    use_hunter: bool = False


class N8nWebhookRequest(BaseModel):
    product: str
    niche: str
    city: str
    user_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"\*", "", text)
    text = re.sub(r"#{1,6}\s", "", text)
    text = re.sub(r"`", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_domain(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1) if m else url


def safe_json_parse(text: str) -> Optional[Dict]:
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


retryable_http = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    reraise=True,
)


# ---------------------------------------------------------------------------
# External API wrappers
# ---------------------------------------------------------------------------
@retryable_http
async def serper_search(query: str, max_results: int = 10) -> List[Dict]:
    if not SERPER_API_KEY:
        logger.error("SERPER_API_KEY не задан — поиск пропущен")
        return []
    try:
        resp = await http_client.post(
            SERPER_URL,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": max_results, "gl": "us", "hl": "en"},
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("organic", [])[:max_results]:
            if item.get("link") and item.get("title"):
                results.append({
                    "title": clean_text(item["title"]),
                    "url": item["link"],
                    "body": clean_text(item.get("snippet", "")),
                })
        return results
    except Exception as e:
        logger.warning(f"Serper search error for '{query}': {e}")
        return []


@retryable_http
async def polza_chat(messages: List[Dict], max_tokens: int = 3000, temperature: float = 0.7) -> str:
    if not POLZA_API_KEY:
        logger.error("POLZA_API_KEY не задан — запрос к LLM пропущен")
        return ""
    try:
        resp = await http_client.post(
            POLZA_URL,
            headers={"Authorization": f"Bearer {POLZA_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": POLZA_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"Polza.ai error: {e}")
        return ""


async def groq_generate_queries(niche: str, city: str, product: str, n: int = 7) -> List[str]:
    fallback = [
        f"{niche} {city}",
        f"best {niche} in {city}",
        f"top {niche} companies {city}",
        f"{niche} near {city}",
    ]
    if not groq_client:
        return fallback
    try:
        prompt = f"""Generate {n} diverse, specific Google search queries in English to find B2B companies that could be leads.
Niche: {niche}
City/region: {city}
Product being sold to them: {product or 'general B2B product'}

Return ONLY a JSON array of strings, no explanation, no markdown. Example: ["query 1", "query 2"]"""
        response = groq_client.chat.completions.create(
            model=GROQ_QUERY_MODEL,
            messages=[
                {"role": "system", "content": "You generate precise search queries. Respond with a raw JSON array only."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
            max_tokens=500,
        )
        content = response.choices[0].message.content
        parsed = safe_json_parse(content)
        if isinstance(parsed, list) and parsed:
            return [str(q) for q in parsed[:n]]
    except Exception as e:
        logger.warning(f"Groq query generation failed: {e}")
    return fallback


async def find_contacts_intel_harvester(domain: str, limit: int = 5) -> List[Dict]:
    """
    LEGACY (больше не вызывается): контакты через Intel-Harvester (CLI).
    Оставлено для истории/отката; возвращает мусорные email (один и тот же для всех доменов).
    Запускает harvest.py, парсит последний CSV-файл.
    """
    if not domain:
        return []

    try:
        import subprocess

        # Запускаем harvest.py для одного домена
        result = subprocess.run(
            ["python", "harvest.py", "-"],
            input=domain,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=INTEL_HARVESTER_PATH
        )

        if result.returncode != 0:
            logger.warning(f"Intel-Harvester error for {domain}: {result.stderr[:200]}")
            return []

        # Находим последний CSV-файл
        csv_files = glob.glob(os.path.join(INTEL_HARVESTER_PATH, "harvest_*.csv"))
        if not csv_files:
            logger.warning(f"Intel-Harvester: no CSV found for {domain}")
            return []

        latest_csv = max(csv_files, key=os.path.getctime)

        # Парсим CSV
        contacts = []
        with open(latest_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if len(contacts) >= limit:
                    break
                email = (row.get("email") or "").strip()
                if email and "@" in email:
                    contacts.append({
                        "full_name": (row.get("name") or "").strip() or "—",
                        "position": (row.get("title") or "").strip() or "—",
                        "email": email,
                        "email_status": "verified" if row.get("email_verified") else "unknown",
                        "linkedin_url": (row.get("linkedin") or "").strip() or None,
                    })

        return contacts

    except subprocess.TimeoutExpired:
        logger.warning(f"Intel-Harvester timeout for {domain}")
        return []
    except Exception as e:
        logger.warning(f"Intel-Harvester error for {domain}: {e}")
        return []


async def find_contacts(domain: str, limit: int = 5, use_hunter: bool = False) -> List[Dict]:
    """
    Честный поиск email: сайт компании -> проверка MX/SMTP -> (опционально) Hunter.io.
    Ничего не выдумывает: если email не найден, возвращает пустой список.
    """
    if not domain:
        return []
    try:
        return await find_emails_for_domain(http_client, domain, limit=limit, verify=True, use_hunter=use_hunter)
    except Exception as e:
        logger.warning(f"find_contacts error for {domain}: {e}")
        return []


async def score_lead(company_name: str, description: str, product: str) -> Tuple[int, str]:
    if not product:
        return 50, "Продукт не указан — базовая оценка без персонализации."

    prompt = f"""Оцени от 0 до 100, насколько эта компания подходит для продукта: {product}.
Компания: {company_name}
Описание: {description[:800]}

Верни ТОЛЬКО валидный JSON без markdown-обёртки, строго в формате:
{{"score": <int 0-100>, "why_fit": "<краткое объяснение на русском, 1-2 предложения>"}}"""

    content = await polza_chat(
        messages=[
            {"role": "system", "content": "You are a B2B sales analyst. Always respond with raw JSON only, no markdown fences."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=300,
        temperature=0.3,
    )
    parsed = safe_json_parse(content)
    if parsed and "score" in parsed:
        try:
            score = max(0, min(100, int(parsed["score"])))
            why_fit = str(parsed.get("why_fit", "")).strip() or "Обоснование не предоставлено."
            return score, why_fit
        except (ValueError, TypeError):
            pass
    return 40, "Не удалось автоматически оценить компанию — требуется ручная проверка."


async def generate_emails(lead: Dict, product: str) -> List[Dict]:
    company_name = lead.get("name", "компания")
    description = (lead.get("description") or "")[:600]
    why_fit = lead.get("why_fit", "")

    prompt = f"""Напиши 3 варианта холодного письма для B2B-продажи.

Продукт: {product}
Компания-получатель: {company_name}
Что известно о компании: {description}
Почему подходит: {why_fit}

Варианты:
1. "short" — очень короткое (3-4 строки), прямое, без воды
2. "medium" — среднее (один абзац), с одной персонализированной деталью о компании
3. "case" — с упоминанием похожего кейса/результата, чуть длиннее остальных

Каждое письмо должно упоминать конкретную деталь о компании {company_name}, а не быть шаблонным.

Верни ТОЛЬКО валидный JSON без markdown-обёртки:
{{"emails": [
  {{"variant": "short", "subject": "...", "body": "..."}},
  {{"variant": "medium", "subject": "...", "body": "..."}},
  {{"variant": "case", "subject": "...", "body": "..."}}
]}}"""

    content = await polza_chat(
        messages=[
            {"role": "system", "content": "You are an expert B2B copywriter. Respond with raw JSON only, no markdown fences. Write the emails in Russian."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1500,
        temperature=0.7,
    )
    parsed = safe_json_parse(content)
    if parsed and isinstance(parsed.get("emails"), list) and parsed["emails"]:
        emails = []
        for e in parsed["emails"]:
            emails.append({
                "variant": e.get("variant", "unknown"),
                "subject": clean_text(e.get("subject", "")),
                "body": clean_text(e.get("body", "")),
            })
        return emails

    return [{
        "variant": "short",
        "subject": f"Насчёт {product}",
        "body": f"Здравствуйте! Заметил, что {company_name} может быть интересен наш продукт «{product}». Готовы обсудить в течение 15 минут на этой неделе?",
    }]


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------
async def run_leads_pipeline(niche: str, city: str, product: str, user_id: Optional[str] = None) -> Dict:
    logger.info(f"Pipeline start: niche={niche!r}, city={city!r}, product={(product or '')[:60]!r}")

    queries = await groq_generate_queries(niche, city, product, n=7)
    logger.info(f"Сгенерировано {len(queries)} поисковых запросов")

    search_batches = await asyncio.gather(*[serper_search(q, 10) for q in queries])
    all_results = [item for batch in search_batches for item in batch]

    seen_domains = set()
    candidate_leads: List[Dict] = []
    for r in all_results:
        domain = extract_domain(r["url"])
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            candidate_leads.append({
                "name": r["title"],
                "website": r["url"],
                "domain": domain,
                "description": r["body"],
            })

    logger.info(f"Найдено {len(candidate_leads)} уникальных кандидатов")

    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)

    async def score_with_sem(lead):
        async with sem:
            score, why_fit = await score_lead(lead["name"], lead["description"], product)
            lead["fit_score"] = score
            lead["why_fit"] = why_fit
            return lead

    scored_leads = await asyncio.gather(
        *[score_with_sem(l) for l in candidate_leads[:MAX_CANDIDATE_LEADS]]
    )
    scored_leads.sort(key=lambda x: x["fit_score"], reverse=True)

    top_leads = scored_leads[:TOP_LEADS_TO_ENRICH]

    async def enrich_with_sem(lead):
        async with sem:
            contacts = await find_contacts(
                lead["domain"],
                limit=5,
                use_hunter=lead.get("fit_score", 0) >= HUNTER_MIN_SCORE,
            )
            if not contacts:
                contacts = [{
                    "full_name": "—",
                    "position": "—",
                    "email": "email not found",
                    "email_status": "not_found",
                    "linkedin_url": None,
                }]
            emails = await generate_emails(lead, product)
            lead["contacts"] = contacts
            lead["emails"] = emails
            return lead

    enriched_leads = list(await asyncio.gather(*[enrich_with_sem(l) for l in top_leads]))

    if supabase:
        try:
            supabase.table("searches").insert({
                "user_id": user_id,
                "product_description": product,
                "niche": niche,
                "city": city,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.warning(f"Supabase searches insert failed: {e}")

        for lead in enriched_leads:
            try:
                lead_res = supabase.table("leads").insert({
                    "user_id": user_id,
                    "company_name": lead["name"],
                    "website": lead["website"],
                    "description": lead["description"],
                    "fit_score": lead["fit_score"],
                    "why_fit": lead["why_fit"],
                    "niche": niche,
                    "city": city,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
                lead_id = lead_res.data[0]["id"] if lead_res.data else None
                lead["id"] = lead_id
            except Exception as e:
                logger.warning(f"Supabase leads insert failed for {lead.get('name')}: {e}")
                lead_id = None

            if not lead_id:
                continue

            for c in lead.get("contacts", []):
                if c.get("email") and c["email"] != "email not found":
                    try:
                        supabase.table("contacts").insert({
                            "lead_id": lead_id,
                            "full_name": c["full_name"],
                            "position": c["position"],
                            "email": c["email"],
                            "email_status": c.get("email_status", "unknown"),
                            "linkedin_url": c.get("linkedin_url"),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }).execute()
                    except Exception as e:
                        logger.warning(f"Supabase contacts insert failed: {e}")

            for em in lead.get("emails", []):
                try:
                    supabase.table("emails").insert({
                        "lead_id": lead_id,
                        "variant": em["variant"],
                        "subject": em["subject"],
                        "body": em["body"],
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }).execute()
                except Exception as e:
                    logger.warning(f"Supabase emails insert failed: {e}")

    logger.info(f"Pipeline завершён: {len(enriched_leads)} обогащённых лидов из {len(scored_leads)} оценённых")
    return {
        "total": len(scored_leads),
        "leads": enriched_leads,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/analyze")
async def analyze(request: QueryRequest):
    try:
        web = await serper_search(f"{request.query} {request.industry or ''}".strip(), 5)
        context_text = "".join(f"{w['title']}. {w['body']}\n" for w in web[:5])

        prompt = f"""Answer this question thoroughly and completely. No markdown, plain text only.

Question: {request.query}
Industry: {request.industry or 'General'}

Research data:
{context_text[:3000]}

Provide a complete, detailed answer with:
1. Key insights (3-5 points, detailed)
2. Risks (3-5 points, detailed)
3. Action steps (3-5 steps, specific)
4. Additional recommendations

Be specific, practical, and comprehensive. Answer in Russian."""

        answer = await polza_chat(
            messages=[
                {"role": "system", "content": "You are a business expert. Answer in Russian. Plain text only. Be thorough and detailed."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2000,
        )
        return {
            "answer": clean_text(answer) or "Не удалось получить ответ от LLM. Проверьте POLZA_API_KEY.",
            "sources": [{"title": w["title"], "url": w["url"]} for w in web[:5]],
        }
    except Exception as e:
        logger.error(f"/api/analyze error: {e}")
        return {"answer": f"Ошибка: {str(e)[:200]}", "sources": []}


@app.post("/api/competitor")
async def competitor(request: CompetitorRequest):
    try:
        brand = request.url.strip()
        searches = await asyncio.gather(
            serper_search(f"{brand} reviews complaints", 5),
            serper_search(f"{brand} pricing cost", 5),
            serper_search(f"{brand} features weaknesses", 5),
        )
        all_data = [item for batch in searches for item in batch]
        seen, unique_data = set(), []
        for item in all_data:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique_data.append(item)

        context_text = "".join(f"{d['title']}. {d['body']}\n" for d in unique_data[:10])
        prompt = f"""Analyze competitor thoroughly: {brand}

Data:
{context_text[:3000]}

Provide complete analysis:
1. Weaknesses (detailed)
2. Strengths (detailed)
3. Pricing analysis
4. Customer sentiment
5. Strategy to compete
6. Opportunities

Plain text, no markdown. Answer in Russian. Be thorough."""

        analysis = await polza_chat(
            messages=[
                {"role": "system", "content": "Competitive analyst. Answer in Russian. Plain text. Be detailed."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2000,
        )
        return {
            "competitor": brand,
            "analysis": clean_text(analysis) or "Не удалось получить анализ. Проверьте POLZA_API_KEY.",
            "sources": [{"title": d["title"], "url": d["url"]} for d in unique_data[:10]],
        }
    except Exception as e:
        logger.error(f"/api/competitor error: {e}")
        return {"competitor": request.url, "analysis": f"Ошибка: {str(e)[:200]}", "sources": []}


@app.post("/api/leads")
async def leads_endpoint(request: LeadsRequest):
    try:
        return await run_leads_pipeline(request.niche, request.city, request.product, request.user_id)
    except Exception as e:
        logger.error(f"/api/leads error: {e}")
        return {"total": 0, "leads": [], "error": str(e)[:200]}


async def _run_job(job_id: str, req: N8nWebhookRequest):
    JOBS[job_id]["status"] = "running"
    try:
        result = await run_leads_pipeline(req.niche, req.city, req.product, req.user_id)
        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["result"] = result
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(e)[:300]


@app.post("/api/n8n-webhook")
async def n8n_webhook(request: N8nWebhookRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "queued", "created_at": datetime.now(timezone.utc).isoformat()}
    background_tasks.add_task(_run_job, job_id, request)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/find-email")
async def find_email_endpoint(request: FindEmailRequest):
    """Честный поиск email по домену. Вызывается из n8n (HTTP Request Tool)."""
    contacts = await find_contacts(request.domain, limit=request.limit, use_hunter=request.use_hunter)
    if not contacts:
        return {"domain": request.domain, "found": False, "email": "email not found", "contacts": []}
    return {"domain": request.domain, "found": True, "email": contacts[0]["email"], "contacts": contacts}


@app.post("/verify-email")
async def verify_email_endpoint(request: VerifyEmailRequest):
    """Проверка email через MX + SMTP. Вызывается из n8n (HTTP Request Tool)."""
    try:
        return await verify_email_address(request.email)
    except Exception as e:
        logger.error(f"/verify-email error: {e}")
        return {"email": request.email, "status": "unknown", "reason": f"internal_error: {str(e)[:150]}"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "serper_configured": bool(SERPER_API_KEY),
        "polza_configured": bool(POLZA_API_KEY),
        "groq_configured": bool(GROQ_API_KEY),
        "supabase_configured": supabase is not None,
    }


@app.get("/")
async def root():
    return {"status": "Axiom Mind", "version": "15.2"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)