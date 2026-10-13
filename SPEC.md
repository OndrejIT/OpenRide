# OpenRide – zadání (fáze 1)

Indoor cyklistický trenažér v prohlížeči: trasy s výškovým profilem, volitelně YouTube video napárované na trasu.
Fáze 1: seznam tras, trenažér (bez napojení na hardware), zpracování videí. Bez uživatelů.

## Stack

| Oblast | Volba |
|---|---|
| Backend | Django + Django REST Framework (API jen pro čtení) |
| DB | PostgreSQL 16 |
| Fronta | django-dramatiq + Redis 7 |
| Konfigurace | django-environ (`.env`, vzor `.env.example`) |
| Python balíčky | uv (`pyproject.toml` + `uv.lock`), Python 3.12 |
| Lint/format Python | ruff (`format` + `check`, pravidla E, F, I, B, UP, DJ) |
| Frontend | Vue 3 + Vite + TypeScript + Vue Router, bun; ESLint + Prettier |
| Mapa | Leaflet (minimapa), MapLibre GL (virtuální průlet) |
| Testy | pytest + pytest-django; frontend `vue-tsc` + build |
| Běh | Docker Compose; produkce Gunicorn + WhiteNoise |

## Struktura

```
openride/
  backend/                 # Django projekt
    config/                # settings (django-environ), urls, wsgi
    routes/                # app: models, admin, serializers, views, tasks (dramatiq), management/commands
  pipeline/                # čistý Python bez Djanga – produkční zpracování
    gpx.py                 # načtení GPX, převzorkování, profil podle vzdálenosti, souhrny
    vo.py                  # vizuální odometrie (rotace mezi snímky)
    flow_speed.py          # relativní rychlost z pohybu silnice
    align.py               # napárování GPX na video (rigid → dp kolem nalezeného startu)
    video_grade.py         # sklon jen z obrazu (GeoCalib + SfM) – zdroj „video“
    overlay.py             # rychlost, km, výška a sklon z overlaye cyklopočítače (OCR) – zdroj „overlay“
    sync.py                # časový posun mezi dvěma verzemi stejné jízdy (zpracovávaná × přehrávaná)
    download.py            # yt-dlp
  research/                # výzkumné skripty z prototypu (nespouští se v produkci)
  frontend/                # Vue aplikace
  docker/                  # Dockerfile (targety web, worker), entrypointy
  docker-compose.yml
  .data/                   # bind mounty (mimo git): postgres/, media/, cache/
```

## Datový model

**Route** (trasa)
- `title` (char)
- `gpx` (FileField, volitelné)
- `profile` (JSON, podle vzdálenosti, krok 10 m): `{"step_m": 10, "dist": [m], "elev": [m], "grade": [%], "lat": [], "lon": []}` – `lat/lon` jen pokud je GPX
- `distance_km`, `elev_gain_m`, `elev_loss_m`, `max_grade` (float, null do zpracování)
- `segment` (JSON `[[lat, lon], …]`, zjednodušená geometrie pro mapu, null bez GPX)

Route bez videa = virtuální trasa (vyžaduje GPX; profil se počítá při uložení v adminu).

**Video** (volitelné, OneToOne → Route)
- `source` (choice: `youtube`)
- `source_id` (char; unique spolu se `source`) – přehrávané video; admin zadává URL, ID se vyparsuje
- `data_source_id` (char, volitelné) – jiná verze stejné jízdy, ze které se počítá (např. s overlayem cyklopočítače); prázdné = `source_id`
- `duration_s` (int, null do zpracování)
- `grade_source` (choice: `gpx` | `video` | `overlay`) – `gpx` vyžaduje GPX u trasy (validace v adminu)
- `status` (choice: `new` | `queued` | `processing` | `ready` | `failed`), `error` (text, s krokem, ve kterém zpracování spadlo)
- `progress` (JSON `{step, pct, since}` během zpracování), `started_at`, `finished_at`
- `timing` (JSON): `{"t": [s], "dist": [m]}` po sekundách videa – převod čas videa → vzdálenost na trase
- `quality` (JSON): metriky napárování (`turn_corr`, `method`, `start_m`, …)

Žádná data o autorovi, licenci ani datu nahrání.

## Zpracování

- Admin: **Videa → Přidat** (URL z YouTube, volitelně URL pro zpracování a GPX, zdroj výpočtu) – trasa se založí sama s názvem z YouTube (oEmbed; neexistující / nevložitelné video se odmítne). **Trasy → Přidat** jen pro trasy bez videa (GPX povinné). Video vznikne se `status=new`, nic se nespouští automaticky.
- Spuštění: tlačítko „Uložit a zpracovat“ v detailu videa / trasy, akce „Zpracovat vybraná…“ v seznamech, nebo `python manage.py process_video <id>` / `--pending` → `queued`, Dramatiq úloha `process_video(video_id)`; worker nastaví `processing` a hlásí krok + procenta (zápis do DB nejvýš po 5 s), po dokončení `ready` (nebo `failed` + `error`). Video ve frontě / při zpracování se znovu neodešle.
- Admin během zpracování: sloupec stav „krok xx % · zbývá ~N min · běží M min“, seznam i detail se samy obnovují po 10 s; kvalita výsledku jako tabulka s verdiktem (dobré / podezřelé / špatné), náhled profilu a odkazy na kontrolu a trenažér v detailu videa i trasy.
- Úloha: stáhne zpracovávané video (`data_source_id` nebo `source_id`) (yt-dlp, ≤720p, přednostně H.264 – OpenCV na linux/aarch64 neumí AV1) do `/cache/videos/<id>/` → VO (6 fps) → rychlost z obrazu →
  - `grade_source=gpx`: napárování GPX (rigid hledání startu přes celé GPX, pak dp jen v okolí ±300 m startu); `Route.profile` z GPX; `Video.timing` z napárování.
  - `grade_source=video`: GeoCalib + SfM okna → sklon(t); vzdálenost z rychlosti obrazu se škálováním na předpokládanou průměrnou rychlost (nastavení `VIDEO_ASSUMED_KMH`, výchozí 25) – známé omezení: absolutní měřítko z obrazu neznáme; `Route.profile` (bez lat/lon) z integrovaného sklonu.
  - `grade_source=overlay`: video s vypáleným overlayem cyklopočítače (Garmin apod.). RapidOCR (ONNX, modely jsou součástí balíčku) čte celý snímek 1× za sekundu; hodnoty se poznají podle jednotek (`km/h`, `km`, `m`, `%`), místo každého údaje = nejčastější poloha jeho čtení. Vzdálenost = integrál rychlosti kalibrovaný na počítadlo km, profil z výšky podle vzdálenosti (bez výšky z integrovaného sklonu), `timing` přímo bez napárování. Bez lat/lon (žádná mapa). Jen metrické jednotky.
- Dvě verze videa (`data_source_id` ≠ `source_id`): stáhne se i přehrávané video (360p) a nejdřív se ověří, že jde o stejný střih – „energie pohybu“ středu obrazu (4 Hz) obou videí, posun z korelace celých signálů, pak každá minuta zvlášť v celém rozsahu posunů; ≥ 80 % jistých minut musí souhlasit, jinak úloha selže (jinak sestříhané verze). `timing` se přepočte na sekundy přehrávaného videa, posun a shoda v `quality.sync`.
- Cache mezivýsledků `/cache/videos/<YouTube ID zpracovávaného videa>/`.
- Limity: `max_retries=0`; časový limit podle délky videa (zjistí se po stažení): 2× (gpx) / 1,5× (overlay) / 8× (video) délka videa, min. 1 h; Dramatiq `time_limit` 24 h jen jako pojistka. Velká stažená videa se po zpracování mažou, malé mezivýsledky v cache zůstávají.

## API (DRF, jen čtení, bez autentizace)

```
GET /api/routes/        [{id, title, distance_km, elev_gain_m, elev_loss_m, max_grade,
                          video: null | {source, source_id, duration_s}}]   – jen trasy s profilem a (bez videa nebo video ready)
GET /api/routes/<id>/   {…výše, segment, profile, video: null | {…, timing}}
```

Správa (jen přihlášený správce přes Django session, POST s CSRF tokenem; validace = formuláře adminu `routes/forms.py`):

```
GET  /api/manage/session/              {user, is_staff, grade_sources}; nastaví CSRF cookie
GET  /api/manage/videos/               [{id, route_id, title, source_id, data_source_id, grade_source, has_gpx,
                                         status, state, progress, error, quality: [{label, value, verdict}], verdict, …}]
POST /api/manage/videos/               multipart: source_id (URL), data_source_id, grade_source, gpx, process
POST /api/manage/videos/<id>/process/  409, když je ve frontě / zpracovává se
```

## Frontend

- `/` – seznam tras (dlaždice: náhled z `i.ytimg.com` nebo minimapa, km, převýšení, max. sklon).
- `/ride/:id` – trenažér:
  - pozice = vzdálenost; u videa z `timing` podle času přehrávání, bez videa z rychlosti (posuvník km/h, protože trenažér zatím není napojený),
  - HUD přes video: sklon v % + STOUPÁNÍ/KLESÁNÍ/ROVINA, průměr dalších 500 m, odpor (simulovaný sklon = sklon × obtížnost, sjezdy ×0,5, min −5 %, úroveň 0–10, posuvník obtížnosti), čas/vzdálenost/výška/rychlost, profil dalších 500 m, profil celé trasy (klik = skok), minimapa (Leaflet),
  - bez videa: MapLibre GL průlet po trase s 3D terénem (AWS Terrain Tiles – terrarium, bez klíče; podklad OSM rastr), kamera za jezdcem ve směru jízdy,
  - klávesy: mezera start/pauza, ←/→ ±10 s (bez videa ±100 m), ↑/↓ obtížnost.
- `/check/:id` – ladění: video + profil po čase + mapa (pro kontrolu napárování).
- `/manage` – správa videí místo Django adminu: přidání videa (URL, URL pro zpracování, zdroj sklonu, GPX, „hned zpracovat“), seznam se stavem a průběhem (obnovuje se po 5 s při zpracování, jinak po 30 s), verdikt a tabulka kvality, „Zpracovat (znovu)“, odkazy na trenažér / kontrolu / admin. Nepřihlášenému nabídne přihlášení v adminu (`/admin/login/?next=/manage`); Vite dev server proto proxuje i `/admin` a `/static`.
- Komponenty: `YoutubePlayer`, `VirtualScene`, `GradeHud`, `ResistancePanel`, `AheadProfile`, `RouteProfile`, `RouteMap`; composable `useRide` (profil, pozice, odvozené hodnoty).
- Dev: Vite dev server proxy `/api` → Django. Produkce: `bun run build` → statika servírovaná Djangem (WhiteNoise), SPA fallback na `index.html`.

## Docker

- `docker/Dockerfile` – stage `base` (python:3.12-slim + uv + kód), `web` (základní závislosti + build frontendu), `worker` (+ ffmpeg, skupiny `pipeline` a `video`: opencv-python-headless, numpy, scipy, yt-dlp, torch CPU, GeoCalib, pycolmap).
- `docker-compose.yml`: `db`, `redis`, `web` (migrace + runserver v dev), `worker` (`rundramatiq`), `frontend` (bun + Vite dev server).
- Bind mounty (žádné Docker volumes): `./.data/postgres`, `./.data/media` (web + worker), `./.data/cache` (worker; i váhy modelů).

## Hotovo, když

1. `docker compose up` nastartuje vše, `/admin` funguje, migrace proběhnou.
2. Trasa s GPX + YouTube video (`grade_source=gpx`) se zpracuje příkazem a trenažér ji přehraje se synchronním sklonem; ověřeno na Deer Creek (`4Mmx8soDJ6s`, GPX z prototypu) – start napárování ~km 85,2, korelace zatáček ≥ 0,5.
3. Trasa jen s GPX se přehraje jako virtuální průlet.
4. `ruff check`, `ruff format --check`, `pytest`, `vue-tsc`, `bun run build` projdou.
