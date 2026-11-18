# Chatbot për studentët – Universiteti "Ukshin Hoti" Prizren

Projekti praktik i punimit të diplomës: një asistent virtual që u përgjigjet studentëve për provimet, oraret, afatet dhe procedurat, duke u bazuar vetëm në dokumentet zyrtare të universitetit.

## Si funksionon (RAG)

```
Studenti ──► React (chat) ──► FastAPI ──► 1. embedding i pyetjes (lokal)
                                         2. kërkim në PostgreSQL + pgvector
                                         3. pjesët më relevante + pyetja ──► LLM (DeepSeek / Ollama)
                                         4. përgjigjja kthehet pjesë-pjesë (streaming) me burimin
```

| Pjesa | Teknologjia |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy |
| Modeli gjuhësor | DeepSeek API tani, Ollama lokal më vonë (i njëjti kod) |
| Embeddings | `paraphrase-multilingual-MiniLM-L12-v2` me fastembed, lokal, mbështet shqipen |
| Baza e të dhënave | PostgreSQL 16 + pgvector |
| Frontend | React 18 + Vite |
| Publikimi | Docker Compose + Nginx |

## Struktura e projektit

```
chatbot-uhp/
├── backend/
│   ├── app/
│   │   ├── main.py          # aplikacioni FastAPI
│   │   ├── config.py        # konfigurimi nga .env
│   │   ├── models.py        # tabelat: documents, chunks, conversations, messages
│   │   ├── chunking.py      # leximi i PDF/DOCX/TXT dhe ndarja në pjesë
│   │   ├── embeddings.py    # vektorët lokalë
│   │   ├── rag.py           # kërkimi + ndërtimi i kërkesës për LLM
│   │   ├── llm.py           # klienti DeepSeek/Ollama
│   │   ├── ratelimit.py     # kufizimi i pyetjeve për IP
│   │   ├── cli.py           # ngarkimi i dokumenteve nga dosja
│   │   └── routers/         # chat.py (publik), admin.py (paneli)
│   └── tests/
├── frontend/                # React: chat-i dhe paneli i administratës
├── docs/shembull/           # dokument shembull për testim
├── docker-compose.yml
└── .env.example
```

---

## 1. Përgatitja

1. Instalo **Docker Desktop**, **Python 3.12** dhe **Node.js 20**.
2. Merr çelës API nga DeepSeek: https://platform.deepseek.com (duhet të mbushësh pak kredit, p.sh. 2–5 $).
3. Kopjo konfigurimin:
   ```bash
   cp .env.example .env
   ```
   Hape `.env` dhe vendos `LLM_API_KEY`, fjalëkalimet dhe `JWT_SECRET`.
   Kontrollo emrin aktual të modelit te https://api-docs.deepseek.com dhe vendose te `LLM_MODEL`.

## 2. Nisja për zhvillim (në kompjuterin tënd)

```bash
# Baza e të dhënave
docker compose up -d db

# Backend (terminali 1)
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend (terminali 2)
cd frontend
npm install
npm run dev
```

- Chat-i: http://localhost:5173
- Paneli: http://localhost:5173/#/admin
- Dokumentacioni i API-së: http://localhost:8000/docs

Herën e parë backend-i shkarkon modelin e embeddings (rreth 250 MB).

## 3. Ngarkimi i dokumenteve

Pa dokumente chatbot-i përgjigjet gjithmonë "nuk e gjeta". Projekti vjen me dy grupe dokumentesh:

1. **`docs/universiteti/`**: informatat nga faqet publike të universitetit dhe të FSHK (programet, lëndët, kalendari, tarifat, regjistrimi, SMU, SAP, shërbimet, kontaktet, lista e rregulloreve). Secili skedar e ka burimin dhe datën e kontrollit.
2. **`docs/universiteti/burimet-zyrtare.json`**: lista e 11 rregulloreve zyrtare në PDF (punimi i diplomës, studimet bachelor, doracaku për studentë, etika, bursat, transferi, etj.). Këto shkarkohen direkt nga uni-prizren.com.

```bash
cd backend
# 1. Informatat nga faqet publike
python -m app.cli ingest ../docs/universiteti --category "Universiteti"
# 2. Rregulloret zyrtare (shkarkim + OCR)
python -m app.cli fetch-official ../docs/universiteti/burimet-zyrtare.json
```

Me Docker:
```bash
docker compose exec backend python -m app.cli ingest /app/docs/universiteti --category "Universiteti"
docker compose exec backend python -m app.cli fetch-official /app/docs/universiteti/burimet-zyrtare.json
```

Komandat mund të përsëriten: dokumenti me të njëjtin titull zëvendësohet, nuk dyfishohet.

**OCR për PDF të skanuara.** Shumica e rregulloreve në faqen e universitetit janë të skanuara (foto, pa tekst). Backend-i i dallon dhe i lexon me Tesseract në gjuhën shqipe. Në Docker kjo është e instaluar. Pa Docker duhet të instalosh Tesseract me paketën e gjuhës shqipe (`sqi`) dhe Poppler. Pas OCR-së, kontrollo në panel që dokumentet kanë numër të arsyeshëm pjesësh, sepse OCR-ja mund të ketë gabime.

Dokumente të reja (oraret e provimeve, njoftime) ngarkohen nga paneli: `#/admin` → "Ngarko dokument të ri".

### Crawler-i i faqeve zyrtare

Crawler-i lexon vetëm faqe publike të `uni-prizren.com` dhe nënfushave të saj. Ai respekton
`robots.txt`, pret konfigurueshëm mes kërkesave (1.5 sekonda si parazgjedhje), nuk plotëson
formularë dhe nuk kyçet askund. Konfigurimi është te `docs/universiteti/crawl.json`.

Për të parë URL-të që do të lexoheshin, pa ndryshuar bazën e të dhënave:

```bash
cd backend
python -m app.cli crawl --config ../docs/universiteti/crawl.json --max-pages 400 --dry-run
```

Për një crawl të plotë dhe ingestim në bazën ekzistuese:

```bash
docker compose exec backend python -m app.cli crawl --config /app/docs/universiteti/crawl.json --max-pages 400
```

Crawler-i ruan `data/crawl_manifest.json` për të anashkaluar përmbajtjen e pandryshuar dhe
shkruan përmbledhjen te `data/crawl_report.md`. Në Docker të dy skedarët ruhen në volumin
`crawl-data`. Faqet e rezultateve dhe listave të studentëve përjashtohen me pattern-et
`rezultatet`, `rezultati`, `listat`, `lista` dhe `liste`; lidhjet me Google Drive raportohen,
por nuk ndiqen.

Për t'i mbajtur të dhënat të freskëta, përsëritni të njëjtën komandë çdo muaj ose vendoseni
në një cron job mujor. Kontrolloni gjithmonë raportin, sidomos dështimet dhe PDF-të e reja që
kanë kaluar nëpër OCR.

`crawl.json` përjashton edhe dokumentet e seksionit "Dokumentet e shfuqizuara" të faqes së
rregulloreve dhe dokumentet e brendshme për stafin. Crawler-i nuk fshin dokumente që janë
ngarkuar më parë, prandaj pas ndryshimit të rregullave pastrojeni bazën:

```bash
# 1. Shiko listën e dokumenteve që do të fshiheshin
docker compose exec backend python -m app.cli prune-excluded --config /app/docs/universiteti/crawl.json
# 2. Nëse lista është në rregull, fshiji
docker compose exec backend python -m app.cli prune-excluded --config /app/docs/universiteti/crawl.json --apply
```

Kur universiteti e kalon një rregullore te "Dokumentet e shfuqizuara", shtoni adresën e saj te
`exclude_patterns` në `crawl.json` dhe përsëritni pastrimin.

## 4. Testet

```bash
cd backend
pytest
```

## 5. Publikimi online

Duhet një server (VPS) me të paktën 2 GB RAM, p.sh. Hetzner, DigitalOcean ose serveri i universitetit, dhe një domen.

```bash
git clone <repo-ja-jote> chatbot-uhp && cd chatbot-uhp
cp .env.example .env   # plotëso vlerat, CORS_ORIGINS=https://domeni-yt
docker compose up -d --build
docker compose exec backend python -m app.cli ingest /path/te/dokumentet   # ose nga paneli
```

Faqja del në portin 80. Për **HTTPS** (i domosdoshëm për një faqe publike), më e thjeshta është Caddy para Nginx-it ose Certbot. Mund ta shtojmë kur ta kesh serverin dhe domenin.

Mbrojtjet që janë të përfshira:
- Çelësi i DeepSeek qëndron vetëm në server, kurrë në shfletues.
- Kufizim pyetjesh për IP (`RATE_LIMIT_PER_MINUTE`), që mos të shpenzohet buxheti.
- Paneli kërkon kyçje (JWT). Ndrysho patjetër `ADMIN_PASSWORD` dhe `JWT_SECRET`.
- Baza e të dhënave nuk është e hapur në internet.
- Nuk ruhen të dhëna personale të studentëve, vetëm pyetjet anonime.

Vendos edhe një limit shpenzimesh në llogarinë e DeepSeek.

## 6. Kalimi në Ollama lokal

Kodi nuk ndryshon. Vetëm `.env`:

```bash
docker compose --profile ollama up -d
docker compose exec ollama ollama pull qwen2.5:3b
```

```
LLM_BASE_URL=http://ollama:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:3b
```

Pastaj `docker compose up -d backend`. Dokumentet nuk duhet të ngarkohen përsëri, sepse embeddings janë lokale.

Shënim: modelet 3B janë më të dobëta në shqip. Nëse serveri ka 16 GB RAM ose GPU, provo `qwen2.5:7b`. Krahasimi DeepSeek vs. Ollama me të njëjtat pyetje është material i mirë për kapitullin e testimit.

## 7. Për kapitullin e testimit

Paneli i administratës tregon:
- numrin e bisedave dhe pyetjeve,
- përqindjen e pyetjeve me përgjigje,
- vlerësimet "Po / Jo" të studentëve,
- pyetjet pa përgjigje (tregojnë cilat dokumente mungojnë),
- pyetjet më të shpeshta.

## 8. Testimi automatik për temën

Dy skripte në dosjen `scripts/` e testojnë chatbot-in që punon dhe i ruajnë rezultatet në `scripts/rezultatet/`. Përdorin vetëm Python-in standard, pa instalime shtesë.

```powershell
# Seksioni 6.3: 9 teste funksionale (rreth 3 minuta)
python scripts\testimi_funksional.py --fjalekalimi FJALEKALIMI_I_ADMINIT

# Seksioni 6.4 dhe Shtojca A: 20 pyetjet testuese (rreth 4 minuta)
python scripts\vleresimi.py --emri deepseek
```

Për modelin lokal: ndrysho tri rreshtat LLM në `.env` dhe pastaj:

```powershell
docker compose --profile ollama up -d
docker compose exec ollama ollama pull qwen2.5:3b
docker compose up -d --force-recreate backend
python scripts\vleresimi.py --emri ollama-qwen2.5-3b
```
