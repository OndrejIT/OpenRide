# OpenRide

Indoor cyklistický trenažér v prohlížeči. YouTube video jízdy se napáruje na výškový profil trasy a během přehrávání ukazuje aktuální sklon v procentech, profil před jezdcem a odpor, který by šel do trenažéru. Trasy bez videa se jezdí jako virtuální průlet nad 3D terénem.

Sklon a časování videa se počítají lokálně, bez placených služeb, z jednoho ze tří zdrojů:

| Zdroj | Kdy | Výsledek |
|---|---|---|
| **overlay** | video má v obraze cyklopočítač (km, rychlost, výška nebo sklon) | profil a časování přímo z OCR overlaye; zvládá i stříhaná videa; bez mapy |
| **GPX** | máš GPX trasy (Strava, plánovač) | GPX se napáruje na video podle zatáček; profil z GPX, mapa a 3D průlet |
| **obraz** | nic z toho | sklon odhadnutý z obrazu (GeoCalib + SfM); nepřesné, jen orientační |

Fáze 1 je prototyp: bez uživatelů a bez napojení na skutečný trenažér (odpor se jen zobrazuje). Zadání je v [SPEC.md](SPEC.md).

## Architektura

```
              ┌──────────────┐  /api/routes/ (veřejné, jen čtení)
 prohlížeč ──▶│ frontend Vue │──────────────────────────────┐
              │ (Vite / dist)│  /api/manage/ (správce)      ▼
              └──────────────┘                     ┌────────────────┐     ┌──────────┐
                     │  YouTube IFrame player      │ web: Django+DRF│────▶│ Postgres │
                     ▼                             │ admin, API     │     └──────────┘
                  YouTube                          └───────┬────────┘
                                                           │ Dramatiq úloha
                                                     ┌─────▼─────┐   ┌────────────────────────┐
                                                     │   Redis   │──▶│ worker: pipeline/      │
                                                     └───────────┘   │ yt-dlp, OpenCV, OCR,   │
                                                                     │ GeoCalib, SfM          │
                                                                     └────────────────────────┘
```

| Část | Technologie |
|---|---|
| Backend | Django 5, Django REST Framework, django-environ, WhiteNoise |
| Fronta | django-dramatiq + Redis; worker zpracovává jedno video naráz |
| Databáze | PostgreSQL 16 |
| Zpracování (`pipeline/`) | čistý Python bez Djanga: OpenCV, NumPy/SciPy, RapidOCR (ONNX), yt-dlp + deno, GeoCalib (PyTorch), pycolmap |
| Frontend | Vue 3, Vite, TypeScript, Vue Router, Leaflet, MapLibre GL; balíčky přes bun |
| Nástroje | uv (Python), ruff, pytest; ESLint + Prettier, vue-tsc, vitest |
| Běh | Docker Compose; data v bind mountech `./.data/` (žádné Docker volumes) |

## Rychlý start

Potřebuješ Docker s Compose v2 (na macOS např. Colima).

```sh
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

| Adresa | Co tam je |
|---|---|
| http://localhost:5173/ | aplikace (Vite dev server, hot reload) |
| http://localhost:5173/manage | správa videí: přidání a zpracování |
| http://localhost:8000/admin/ | Django admin |
| http://localhost:8000/ | sestavená aplikace servírovaná Djangem |

Migrace proběhnou při startu kontejneru `web`. Všechny hodnoty v `docker-compose.yml` mají vývojové výchozí hodnoty, `.env` není potřeba (přehled proměnných níže).

## Práce s aplikací

1. Otevři **/manage** a přihlas se účtem správce (odkaz vede na přihlášení do adminu a zpět).
2. **Přidat video**: vlož URL z YouTube (název se doplní sám), zvol výpočet sklonu, případně nahraj GPX. Volitelně „URL videa pro zpracování“: jiná verze stejné jízdy, ze které se data počítají (typicky verze s overlayem cyklopočítače, zatímco přehrává se čistá verze bez něj; časový posun mezi verzemi se zjistí a ověří automaticky).
3. Nech zaškrtnuté **hned zpracovat**, nebo později klikni **Zpracovat**. V seznamu uvidíš krok, procenta a odhad zbývajícího času.
4. Po dokončení zkontroluj **verdikt kvality** (✓ / ⚠ / ✗ s tabulkou metrik) a stránku **kontrola** (`/check/<id>`: video, profil v čase a mapa vedle sebe). Pak jeď v **trenažéru** (`/ride/<id>`).

Totéž jde v Django adminu: **Videa → Přidat**, tlačítko „Uložit a zpracovat“, akce „Zpracovat vybraná videa“. **Trasy → Přidat** slouží jen pro trasy bez videa (GPX povinné). Z příkazové řádky: `docker compose exec web python manage.py process_video <id>` nebo `--pending`.

### Trenažér

| Ovládání | |
|---|---|
| mezera | start / pauza |
| ← / → | ±10 s (bez videa ±100 m) |
| ↑ / ↓ | obtížnost |

HUD ukazuje sklon a průměr dalších 500 m, odpor (simulovaný sklon = sklon × obtížnost, sjezdy ×0,5, minimum −5 %, úroveň 0–10), čas, vzdálenost, výšku, rychlost, profil dalších 500 m, profil celé trasy (kliknutím skok) a minimapu. U trasy bez videa se pozice posouvá podle rychlosti z posuvníku.

### Jak číst kvalitu výsledku

| Metrika | Zdroj | ✓ dobré | ⚠ podezřelé |
|---|---|---|---|
| korelace zatáček video × GPX | GPX | ≥ 0,6 | ≥ 0,4 |
| přečteno z overlaye (údaje, ze kterých se počítá) | overlay | ≥ 90 % | ≥ 70 % |
| měřítko rychlost × počítadlo km | overlay | odchylka ≤ 5 % | ≤ 15 % |
| odchylka od počítadla km | overlay | ≤ 50 m | ≤ 150 m |
| shoda se sklonem z overlaye | overlay | ≥ 0,8 | ≥ 0,6 |
| průměrná odchylka sklonu | overlay | ≤ 2 % | ≤ 4 % |
| shoda přehrávané a zpracované verze | 2 verze videa | ≥ 90 % minut | ≥ 80 % |
| úseky se sklonem z obrazu | obraz | ≥ 70 % | ≥ 40 % |

Když overlay nemá výškoměr a výška se integruje ze sklonu, „shoda se sklonem z overlaye“ porovnává profil se zdrojem, ze kterého vznikl, a vychází vždy dobře. Spolehlivé jsou pak metriky vzdálenosti.

Podrobný popis algoritmů: [docs/zpracovani.md](docs/zpracovani.md). API: [docs/api.md](docs/api.md).

## Vývoj

### Backend a pipeline

```sh
uv sync                          # Python 3.12, všechny skupiny závislostí (.venv)
uv run pytest                    # testy; SQLite v paměti, Redis ani Postgres nejsou potřeba
uv run ruff format && uv run ruff check
```

Testy v `tests/test_regression.py` běží na skutečných datech prototypu (adresář `../data`, cestu jde změnit `OPENRIDE_TEST_DATA`); bez nich se přeskočí.

| Skupina závislostí (`pyproject.toml`) | Obsah | Kde je potřeba |
|---|---|---|
| základní | Django, DRF, Dramatiq, NumPy, SciPy | web i worker |
| `pipeline` | OpenCV (headless), RapidOCR + onnxruntime, yt-dlp + deno | worker |
| `video` | PyTorch (CPU), GeoCalib, pycolmap | worker, jen zdroj „obraz“ |
| `dev` | pytest, pytest-django, ruff | lokálně |

### Frontend

```sh
cd frontend
bun install
bun run dev          # proxy /api, /admin a /static na Django (VITE_API_PROXY, výchozí http://localhost:8000)
bun run dev:mock     # bez backendu: API z frontend/mock/*.json
bun run lint && bun run typecheck && bun run test && bun run build
```

### Struktura

```
backend/                 Django projekt
  config/                settings (django-environ), urls
  routes/                modely Route a Video, admin, API (views.py veřejné, manage.py správa),
                         formuláře, Dramatiq úloha (tasks.py), příkaz process_video
pipeline/                zpracování videa, nezávislé na Djangu
  download.py            yt-dlp (≤ 720p, přednostně H.264)
  vo.py, flow_speed.py   vizuální odometrie, rychlost z pohybu silnice
  gpx.py, align.py       GPX → profil; napárování GPX na video
  overlay.py             OCR overlaye cyklopočítače → profil a časování
  sync.py                časový posun mezi dvěma verzemi videa
  video_grade.py         sklon z obrazu (GeoCalib + SfM)
  process.py             spojení kroků pro jednotlivé zdroje
  progress.py            hlášení průběhu do úlohy
frontend/                Vue aplikace (seznam tras, trenažér, kontrola, správa)
docker/                  Dockerfile (targety web, worker), entrypoint
tests/                   pytest
research/                výzkumné skripty z prototypu (v produkci se nespouštějí)
SPEC.md                  zadání fáze 1
```

## Konfigurace

Proměnné prostředí čte Django přes django-environ (případně ze souboru `.env` v kořeni repozitáře). `docker-compose.yml` dosazuje vývojové výchozí hodnoty.

| Proměnná | Výchozí v compose | Význam |
|---|---|---|
| `SECRET_KEY` | `dev-insecure-secret-key` | Django secret key; mimo vývoj vždy nastav |
| `DEBUG` | `true` | ladicí režim Djanga (bez compose výchozí `false`) |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1,web` | povolené hostitele |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `openride` | přístup k databázi; z nich se skládá `DATABASE_URL` |
| `DATABASE_URL` | ze tří výše | např. `postgres://user:heslo@db:5432/openride` |
| `REDIS_URL` | `redis://redis:6379/0` | broker Dramatiq |
| `FRONTEND_URL` | `http://localhost:5173` | kam vedou odkazy z adminu; zároveň důvěryhodný origin pro CSRF. Prázdné = aplikace na stejném hostu |
| `VIDEO_ASSUMED_KMH` | `25` | zdroj „obraz“: průměrná rychlost, na kterou se škáluje vzdálenost |
| `MEDIA_ROOT`, `CACHE_DIR`, `STATIC_ROOT`, `FRONTEND_DIST` | nastavené v Dockerfile | nahrané GPX, mezivýsledky zpracování, statika, sestavený frontend |
| `VITE_API_PROXY` (frontend) | `http://web:8000` | kam Vite dev server přeposílá `/api`, `/admin`, `/static` |
| `VITE_MOCK` (frontend) | – | `1` = API z `frontend/mock/` |

Data v `./.data/`: `postgres/` (databáze), `media/` (GPX), `cache/` (mezivýsledky zpracování podle YouTube ID; stažená videa se po zpracování mažou), `frontend-node_modules/`.

## Omezení

- **Zdroj „obraz“ nepoběží na ARM** (Apple Silicon, linux/aarch64): pycolmap nemá wheel pro linux/aarch64. Potřebuje amd64 worker.
- **Napárování přes GPX nezvládá střihy ve videu** (vystřižené úseky). U videí s overlayem je spolehlivější zdroj „overlay“.
- **Overlay**: jen metrické jednotky (km/h, km, m, %); výška se bere z výškoměru, jinak z integrovaného sklonu v celých procentech.
- **Fronta Dramatiq je jen v Redisu bez trvalých dat**: po `docker compose down` se ztratí a rozběhnutá nebo čekající videa zůstanou ve stavu „ve frontě“ / „zpracovává se“. Je potřeba je odeslat znovu.
- Časový limit zpracování závisí na délce videa (GPX 2×, overlay 1,5×, obraz 8× délka videa, minimálně 1 h).
- Trenažér zatím není napojený na hardware.

## Právní poznámky

Shrnutí rešerše podmínek služeb z prototypu. Nejde o právní radu.

- **Přehrávání** používá oficiální YouTube IFrame player (vložení videa YouTube povoluje). HUD trenažéru je ale zobrazený **přes** přehrávač, což odporuje požadavku YouTube na minimální funkčnost přehrávače (Required Minimum Functionality: žádné překryvy přes přehrávač, minimální velikost 200×200 px). Pro veřejný provoz je potřeba HUD přesunout mimo plochu videa.
- **Zpracování stahuje video** (yt-dlp). Podmínky YouTube stahování bez svolení zakazují (ToS; Developer Policies III.E.1.a). Pipeline je proto určená pro osobní a výzkumné použití; veřejně provozovaná služba by potřebovala svolení autorů videí nebo jiný zdroj dat.
- YouTube Developer Policies (III.F.3.a) nedovolují zpoplatnit sledování videí, aplikace je proto zdarma.
- **Data ze Stravy** (GPX exporty aktivit) jsou podle podmínek Stravy (§12) jen pro osobní použití. Nenahrávej je do veřejných repozitářů ani je nesdílej dál.
- Stažená videa, nahraná GPX a databáze jsou v `.data/`, která je v `.gitignore`.
