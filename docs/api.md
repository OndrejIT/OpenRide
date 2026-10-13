# API

REST API Djanga (`/api/`). Odpovědi jsou JSON.

## Veřejné (jen čtení, bez přihlášení)

Vrací jen trasy připravené k jízdě: mají profil a buď nemají video, nebo je video zpracované (`ready`).

### `GET /api/routes/`

```json
[
  {
    "id": 1,
    "title": "Sankt Kassian, Dolomity (MTB)",
    "distance_km": 11.63,
    "elev_gain_m": 160.0,
    "elev_loss_m": 230.0,
    "max_grade": 10.5,
    "video": { "source": "youtube", "source_id": "y_g3yfhl0bo", "duration_s": 2401 }
  }
]
```

`video` je `null` u virtuální trasy (jen GPX).

### `GET /api/routes/<id>/`

Totéž plus:

| Pole | Obsah |
|---|---|
| `profile` | `{step_m: 10, dist: [m], elev: [m], grade: [%], lat?: [], lon?: []}`; `lat`/`lon` jen s GPX |
| `segment` | `[[lat, lon], …]` zjednodušená geometrie pro mapu, nebo `null` |
| `video.timing` | `{t: [s], dist: [m]}`: pro každou sekundu přehrávaného videa vzdálenost v profilu |

## Správa (jen správce)

Přihlášení přes Django session (`/admin/login/`), uživatel musí mít `is_staff`. POST požadavky potřebují hlavičku `X-CSRFToken` s hodnotou cookie `csrftoken`. Validace je stejná jako v adminu (`backend/routes/forms.py`).

### `GET /api/manage/session/`

Bez přihlášení dostupné; nastaví CSRF cookie.

```json
{
  "user": "ondrej",
  "is_staff": true,
  "grade_sources": [{ "value": "gpx", "label": "GPX (napárování na video)" }, …]
}
```

### `GET /api/manage/videos/`

Všechna videa, nejnovější první.

| Pole | Obsah |
|---|---|
| `id`, `route_id`, `title` | video, jeho trasa a název (z YouTube) |
| `source_id`, `data_source_id` | přehrávané video; video pro zpracování (prázdné = totéž) |
| `grade_source`, `grade_source_label`, `has_gpx` | zdroj sklonu, zda trasa má GPX |
| `status`, `status_label` | `new` / `queued` / `processing` / `ready` / `failed` |
| `state` | jeden řádek pro člověka: „vizuální odometrie 35 % · zbývá ~5 min · běží 12 min“, „hotovo za 14 min“ |
| `progress` | `{step, pct, since}` během zpracování, jinak `null` |
| `error` | text chyby s krokem, ve kterém nastala |
| `quality` | `[{label, value, verdict}]`, `verdict` = `good` / `warn` / `bad` / `null` |
| `verdict` | nejhorší verdikt z `quality` |
| `duration_s`, `started_at`, `finished_at`, `admin_url` | |

### `POST /api/manage/videos/`

`multipart/form-data`:

| Pole | |
|---|---|
| `source_id` | URL videa na YouTube nebo jeho ID (povinné) |
| `data_source_id` | URL / ID jiné verze pro zpracování (volitelné) |
| `grade_source` | `overlay` / `gpx` / `video` |
| `gpx` | soubor GPX (povinný pro `gpx`) |
| `process` | `true` = hned odeslat ke zpracování |

Název trasy se doplní z YouTube (oEmbed). Neexistující, soukromé nebo nevložitelné video se odmítne.

- `201`: vytvořené video (stejný tvar jako v seznamu)
- `400`: chyby formuláře `{pole: [zprávy]}`, např. `{"source_id": ["Neplatná URL YouTube videa"], "gpx": ["Výpočet z GPX vyžaduje GPX."]}`

### `POST /api/manage/videos/<id>/process/`

Odešle video ke zpracování (i hotové nebo chybné, znovu).

- `200`: video ve stavu `queued`
- `409`: video už je ve frontě nebo se zpracovává
