# Zpracování videí

Jak OpenRide z YouTube videa a případně GPX získá výškový profil trasy a časování (každá sekunda videa → vzdálenost na trase). Kód je v `pipeline/`, nezávislý na Djangu; spouští ho Dramatiq úloha `backend/routes/tasks.py`.

## Výstup

| Data | Kde | Obsah |
|---|---|---|
| profil | `Route.profile` | po 10 m: vzdálenost, výška (vyhlazená přes ~30 m), sklon v %, u GPX i lat/lon |
| souhrny | `Route.distance_km`, `elev_gain_m`, `elev_loss_m`, `max_grade` | z profilu |
| geometrie | `Route.segment` | zjednodušená trasa pro mapu (Douglas–Peucker, 5 m); jen s GPX |
| časování | `Video.timing` | `{t: [s], dist: [m]}` pro každou sekundu přehrávaného videa |
| kvalita | `Video.quality` | metriky podle zdroje, viz README › Jak číst kvalitu výsledku |

## Průběh úlohy

```
stažení (yt-dlp, ≤ 720p, přednostně H.264)
  └─ [2 verze videa] stažení přehrávané verze (360p) → synchronizace verzí
       └─ zdroj: overlay │ GPX │ obraz
            └─ [2 verze videa] přepočet časování na přehrávané video
                 └─ uložení profilu, časování a kvality
```

- **Stav videa**: `new` → `queued` (odesláno) → `processing` → `ready` / `failed`. Video ve frontě nebo při zpracování nejde odeslat znovu.
- **Průběh**: kroky pipeline volají `progress.report(krok, hotovo, celkem)`; úloha zapisuje krok a procenta do `Video.progress` nejvýš jednou za 5 s. Admin i dashboard z toho počítají odhad zbývajícího času.
- **Časový limit**: po stažení se zjistí délka videa; limit = GPX 2×, overlay 1,5×, obraz 8× délka videa, minimálně 1 h. Překročení ukončí úlohu při nejbližším hlášení průběhu. Dramatiq `time_limit` 24 h je jen pojistka.
- **Chyba** se uloží do `Video.error` i s krokem, ve kterém nastala („stahování videa: …“).
- **Cache**: `CACHE_DIR/videos/<YouTube ID zpracovávaného videa>/` drží mezivýsledky (VO, rychlost, OCR, signály synchronizace). Opakované zpracování je proto rychlé. Stažená videa se po zpracování mažou.
- **Kodek**: wheel OpenCV pro linux/aarch64 neumí dekódovat AV1, které YouTube často posílá; stahuje se proto přednostně H.264 (`avc1`).
- **Worker** zpracovává jedno video naráz (jeden proces, jedno vlákno); úlohy vytěžují CPU.

## Zdroj „overlay“ (`pipeline/overlay.py`)

Pro videa s vypáleným overlayem cyklopočítače (Garmin apod.).

1. **OCR**: RapidOCR (ONNX, modely jsou součástí balíčku) čte celý snímek jednou za sekundu. Na 720p trvá ~0,3 s na snímek; 40min video ~14 min.
2. **Rozpoznání údajů podle jednotek**, bez konfigurace rozvržení pro každý kanál:

   | Text | Údaj |
   |---|---|
   | `12.5 km`, `2.5km` | vzdálenost (počítadlo) |
   | `18 km/h`, nebo číslo s popiskem `km/h` vedle / pod ním | rychlost |
   | `1668.2 m`, `Höhe1668.2m` | nadmořská výška |
   | `3%`, `-4%` | sklon |

   Hodnoty mimo rozumné meze se zahodí (rychlost 0–120 km/h, výška −450 až 6000 m, sklon ±35 %).
3. **Poloha údaje**: pro každý údaj se najde místo ve snímku, kde se čte nejčastěji (hustota přes vzorek až 2000 čtení, poloměr 6 % výšky snímku). Čtení jinde (jiné widgety, náhodné shody) se ignorují.
4. **Čištění**: odchylka od klouzavého mediánu přes 15 s nad tolerancí (rychlost 8 km/h, km 0,3, výška 5 m, sklon 4 %) = chybně přečtená číslice. Chyby chodí ve shlucích (odlesk za číslicemi), proto široké okno.
5. **Vzdálenost**: integrál rychlosti kalibrovaný na počítadlo km (samotné počítadlo má krok 0,1 km). Robustní fit jednoho měřítka a posunu pro každý úsek, pomalá korekce driftu (Gauss, σ 60 s) jen uvnitř úseků.
6. **Střihy**: když počítadlo mezi dvěma čteními skočí o víc než 150 m nad to, co vysvětlí rychlost, video bylo stříhané. Vzdálenost na tom snímku skočí také, takže profil pokračuje podle skutečné trasy a mezi oběma stranami střihu se výška lineárně interpoluje. Vzdálenost i výška se počítají v časech OCR snímků, aby skok výšky a vzdálenosti padl na stejný okamžik.
7. **Profil**: výška podle vzdálenosti; když výškoměr chybí (méně než 30 % čtení), výška se integruje ze sklonu (celá procenta, hrubší profil).
8. **Časování** vzniká přímo, bez napárování: sekunda videa → vzdálenost.

Kontrola kvality: shoda profilu se sklonem z overlaye (korelace, průměrná odchylka), měřítko a odchylka vůči počítadlu, pokrytí čtením.

## Zdroj „GPX“ (`pipeline/align.py`, `vo.py`, `flow_speed.py`)

GPX nemá čas, nebo jeho čas nesedí s videem; napárování proto časy z GPX nepoužívá a hledá trasu podle obsahu videa.

1. **Parametry kamery**: GeoCalib na 15 snímcích → ohnisko a zkreslení.
2. **Maska overlaye**: průměr 80 snímků přes celé video; ostré hrany v průměru = grafika pevně spojená s kamerou → maska.
3. **Vizuální odometrie** (6 fps): KLT body + esenciální matice → rotace mezi snímky. Jen horních 60 % obrazu (vzdálená scéna; dole bývají řídítka a ruce).
4. **Rychlost z obrazu**: tok bodů silnice ve spodní střední části obrazu, očištěný o rotaci, vydělený geometrií roviny silnice → hodnota úměrná rychlosti (neznámé měřítko, drift ~20 %).
5. **Signál zatáček**: rotace kolem svislé osy kamery (VO) proti křivosti GPX × rychlost.
6. **Hrubé napárování** (rigid): start kdekoli na GPX + jedno měřítko rychlosti, na prvních 300 s videa (delší úsek se jedním měřítkem nepopíše kvůli driftu).
7. **Pružné napárování** (DP): dynamické programování přes (čas × poloha na GPX) se startem v ±300 m od hrubého; shoda změn směru, rychlost jen jako měkké omezení, max. 80 km/h.
8. Profil = vyříznutý úsek GPX (vyhlazení na celém GPX, takže řez nemá okrajové efekty); časování z napárování.

Omezení: střihy ve videu (DP nemůže skočit), dlouhé rovinky bez zatáček, silnice zakrytá řídítky (rychlost z obrazu pak nefunguje).

## Zdroj „obraz“ (`pipeline/video_grade.py`)

Sklon jen z videa; pomalé (hodiny) a nepřesné.

1. **Směr gravitace** z GeoCalib pro každý snímek (1 fps).
2. **SfM** (pycolmap) v oknech 150 s s překryvem 15 s: nejdřív model OPENCV_FISHEYE na 6 fps, při špatné registraci RADIAL na 12 fps.
3. **Sklon** = trajektorie z SfM vůči směru „nahoru“ z GeoCalib, převedenému do kamery COLMAPu přes dva body horizontu (poměr ohnisek mezi modely objektivu nefunguje). Vyhlazení σ 15 s.
4. **Vzdálenost**: rychlost z obrazu škálovaná na předpokládanou průměrnou rychlost `VIDEO_ASSUMED_KMH` (absolutní měřítko z obrazu neznáme).

pycolmap nemá wheel pro linux/aarch64; na ARM hostech tento zdroj vyžaduje amd64 worker.

## Dvě verze videa (`pipeline/sync.py`)

Autor často nahraje stejnou jízdu s overlayem i bez něj. Data se počítají z verze s overlayem (`data_source_id`), přehrává se čistá verze (`source_id`).

1. **Signál pohybu** obou videí (4 Hz): průměrný rozdíl po sobě jdoucích náhledů 48×32 px ze středu obrazu (overlaye bývají u okrajů; rozlišení nevadí).
2. **Posun**: normalizovaná korelace celých signálů v rozsahu ±300 s; překryv aspoň polovina kratšího videa.
3. **Ověření**: každá minuta zpracovávaného videa se hledá sama v celém rozsahu posunů. Jisté minuty (korelace ≥ 0,5) musí aspoň z 80 % souhlasit s posunem do 0,5 s; jinak úloha skončí chybou („videa se neshodují, jinak sestříhaná?“) se seznamem posunů.
4. Časování se přepočte na sekundy přehrávaného videa: `t_přehrávané = t_zpracované + posun`.

Konstantní posun pokrývá stejný střih s jiným začátkem. Různě sestříhané verze se odmítnou.
