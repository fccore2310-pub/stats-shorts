# Football Core playbook — what I (Claude) have learned

_Living document. Each Claude session should read this before making strategic
decisions, and update it when a pattern becomes clear. Keep it short and opinionated._

## Current hypotheses being tested

- **H1 — Instagram is the breakout channel.** IG Reels outperforms YT/X for this
  niche. Action: bumped IG to 4 posts/day (10:00, 14:00, 18:00, 22:00 Madrid).
  Validate by week-over-week views delta in journal.
- **H2 — Minimalist captions beat clickbait.** "football core ⚽" style captions
  from `metadata_generator.py` track the niche convention. If views flatline,
  A/B test slightly longer captions.
- **H3 — The 45s TikTok version converts better than 75s long-form on Reels.**
  Unvalidated. Needs at least 14 days of data.

## Rules of thumb

- Always run Vision QA before publishing. Only `good`/`okay` + no FROZEN/CORRUPT.
- Black separators with "football core."/"fc.core." text are *intentional*, not
  bugs. Don't let QA prompt drift back into flagging them.
- Never schedule more than 7 days out — platform algorithms prefer fresh uploads.
- TikTok via Upload-Post is disabled until warm-up ends (target: 2026-04-21).

## Decisions log

- 2026-04-18 — Switched from `undetected-chromedriver` to plain Selenium (arm64).
- 2026-04-18 — IG cadence 2/day → 4/day.
- 2026-04-18 — Analytics routine installed (this system).
- 2026-04-18 — **Baseline D0:** IG 855 views / 63 likes / 699 reach / 2 followers
  on day 1. YouTube 0 across the board. X 4 impressions / 2 likes. Confirms H1
  (IG is the breakout channel) before even a full week. Keep IG at 4/day.

## Open questions for future-me

- Which hashtag pool has the highest CTR? Need per-post tagging in metadata.
- Does posting at 22:00 actually add reach, or cannibalize the 18:00 slot?
- Is YouTube Shorts worth the effort if Δ7d on views stays under IG by >5x?


## 2026-04-18 — IG token invalidation on password change
Meta invalida el token al cambiar contraseña pero Upload-Post **no** marca `reauth_required: true` hasta que un upload falla. `list_users` miente. La señal real: `get_history` con `error_message` que contiene "session has been invalidated".
**Regla:** siempre que el usuario cambie contraseña de IG/FB → reconectar en app.upload-post.com/manage-users. Verificar publicando 1 post a IG-only vía `publisher.publish_post(..., platforms_override=["instagram"])`.


## 2026-04-19 — YouTube title duplication kills reach
Observación: de 9 YT posts, **8 tenían título idéntico** ("football core • beautiful game") y 0 views cada uno; el único con título distinto ("Most Insane Football Goals 2025 🔥⚽") pilló 1.1k views.
**Regla:** YT Shorts penaliza duplicados. IG/TT quieren low-key; YT quiere clickbait-SEO (keywords + año + emojis + under 60 chars).
**Fix aplicado:**  ahora genera YT title+description con prompt separado, rotando entre 18 seeds (Most Insane/Incredible/Wild/etc.). Description keyword-rich para búsqueda. IG/TT/X siguen minimalistas.
**Hipótesis H4:** YT Shorts es canal viable si corregimos esto. Revisar en 7 días (2026-04-26) — si algún post nuevo pasa de 500 views, queda validado.


## 2026-04-19 — TikTok manual upload breaks the 0-view floor
Post manual https://www.tiktok.com/@fc.core.23.10/video/7630562576790818070 con caption "pov: you understand football core 🔥" → **349 views en primeras horas** (los 3 previos vía API: 0 views cada uno).
**Hipótesis H5:** la cuenta @fc.core.23.10 NO estaba shadowbanned — lo que la mataba era 1 de estos 3 factores (o combo): (a) caption genérica "football core ⚽", (b) uploads vía API sin trending sound, (c) falta de text overlay/hook en 2s.
**Próximo test:** subir manual otro mañana con mismo estilo para confirmar. Si también pasa de 300 → queda claro que TT funciona solo manual con hook agresivo + trending sound. API upload queda en banquillo para TT.


## 2026-04-21 — CORRECCIÓN IMPORTANTE al diagnóstico del 19-abr
El diagnóstico anterior ("títulos duplicados matan reach en YT") era **incorrecto**. Evidencia real de YT Studio el 21-abr:
- 4 posts con título literal "football core • beautiful game" → views: **8.6k, 4.2k, 1.4k, 12**
- 1 post "pure skill" → 1.4k
- 1 post "Most Insane Football Goals 2025 🔥⚽" → 1.1k (no era el winner, era mid)
Mismo título, varía 700×. El driver NO es el título — es el contenido del clip + thumbnail.
**Upload-Post API subestima views masivamente**: reportaba 1,115 impressions cuando YT Studio mostraba ~17k. Nunca confiar en la API para YT; leer YT Studio directamente.
**Nueva H6 (reemplaza H4):** YT Shorts reach correlaciona con "momento WTF visible en el thumbnail". Los que pegan tienen acción clara y alta compresión visual (portero saltando, aglomeración, pegada potente). Los que fallan son aesthetic-smooth (botín-flotando tipo anuncio).
**Lever a testar:** en el compilador, priorizar clips cuyo primer frame tenga composición "impactante" (movimiento extremo, grupo de gente, salto). Thumbnail = primer frame. Hay que añadir una heurística a la selección de clips para poner el más visualmente fuerte en posición 0.
**El fix de títulos clickbait se queda** (no hace daño, puede ayudar al margen en CTR de search) pero no era la cura que yo pensaba.


## 🏁 Deberes para la próxima sesión (anotado 2026-04-21)
Cuando el usuario vuelva, hay que:
1. **Conectar TikTok** a Upload-Post profile FCCore-23 (sigue desconectado desde el principio — actualmente publica 0 a TT vía API; el test manual del 19-abr dio 349 y murió).
2. **Ingerir nuevos sources de football core** — el usuario traerá más URLs. Ejecutar 
Adding: URL1
WARNING  Download failed for URL1: ERROR: [generic] 'URL1' is not a valid URL   
                                                                                
  ✗ download_failed

Adding: URL2
WARNING  Download failed for URL2: ERROR: [generic] 'URL2' is not a valid URL   
                                                                                
  ✗ download_failed

Adding: ...
WARNING  Download failed for ...: ERROR: [generic] '...' is not a valid URL     
                                                                                
  ✗ download_failed

Library stats:
  Sources:   24
  Segments:  109
  Duration:  10.7 min para descargar, splittear e ingestar. Luego generar batch con .
3. Opcional: decidir si activar la heurística "best-thumbnail-first" en el compilador (ver entrada de hoy 21-abr sobre H6).


## 2026-04-21 02:00 — Session wrap: TT + batch masivo programado
1. TikTok reconectado y activo en config (`platforms = [yt, ig, x, tiktok]`).
2. Ingeridas 11 nuevas sources football core → library 35 sources / 159 segments / 15.3 min.
3. Scheduled 14 posts multi-platform + 4 YT-extra. Cobertura hasta 2026-04-27. Total 59 slots en cola FCCore-23.
4. **Fix importante en `metadata_generator._generate_youtube`:** ahora consulta títulos ya programados y en historial reciente vía Upload-Post, pasa lista negra a Claude, reintenta hasta 3 veces, y fallback con sufijo único. Resuelve el bug de "Claude colapsa a 1 variante favorita" detectado hoy (5/14 idénticos antes del fix).
5. Pre-morning state verificado: 14/14 títulos YT únicos, todas plataformas en cada slot, 0 dups.

**Para próxima sesión:** monitorear 48h y ver cómo rinden los primeros TT vía API (primer slot: 2026-04-21 10:00 Madrid). Si TT API genera 0 views reproduciendo el patrón del manual, probar subida manual con trending sound como backup.


## 2026-04-24 — Session: queue cleanup + first-clip uniqueness + publisher fixes

**Estado al cerrar sesión:**
- Cola limpia (todos los huérfanos cancelados).
- 6 slots completos programados (hoy 18:00 → lun 10:00, 4 plataformas cada uno).
- 1 post publicado inmediatamente (15:57) en las 4 redes.
- Batch para rellenar lun 18:00 → vie 01 may pendiente de lanzar.

**Fix implementado: first-clip uniqueness (`src/library.py`)**
- `generate_post()` ahora consulta `data/analytics/used_first_clips.json` (ventana de 12).
- Rota el pool para que el primer segmento no repita aperturas recientes.
- Persiste el clip elegido tras cada post.
- Soluciona: "que no se repita la foto inicial en los vídeos en la misma plataforma".

**Fix implementado: caption diversity TT/IG/X (sesión anterior)**
- `metadata_generator.generate()` ahora pasa lista negra de captions ya usados por plataforma.
- 3 reintentos + fallback con sufijo único. Resuelve colapso "pure football core 👑" ×10.

**Fix caffeinate:** lanzar siempre con `caffeinate -i python3 scripts/schedule_batch.py N` para evitar que el Mac duerma y corte uploads largos (BrokenPipe era sleep, no red).

**Regla nueva:** después de cada batch, verificar que no hay slots huérfanos (< 4 plataformas). Script de comprobación:
```python
by_slot = defaultdict(list)
for s in fc: by_slot[s['scheduled_date']].extend(s['platforms'])
orphans = {k:v for k,v in by_slot.items() if len(v) < 4}
```


## 2026-04-25 — Hipótesis H6 corregida (de nuevo)

**Resultado:** un Short del 19 abr llegó a **1.4M views, 31k likes, +485 subs en 24h**.
Crucé los **1.000 subs** (1.418 actualmente).

**Análisis fallido (mío) post-viral:**
- Bajé el thumbnail max-res, identifiqué patrones (mid-action freeze, 3 capas profundidad,
  jugador único central, contraste alto) y propuse "engineer this in clip-0".
- **El usuario me corrigió correctamente:** los Shorts se consumen en el feed con
  autoplay, NO desde el perfil. El thumbnail estático es marginal. El driver real es
  (a) los primeros 0.5-1s del vídeo + (b) decisión algorítmica de a quién impulsar
  inicialmente, que es **mayoritariamente aleatoria**.

**Hipótesis válida (H7 reemplaza H6):**
- El algoritmo de Shorts elige un % pequeño de vídeos para "test push". El factor que
  decide entre los que reciben push es **retention en los primeros 1-2s**.
- Optimizar el thumbnail estático es overfit con N=1 — descartar.
- Optimizar el FIRST FRAME (que es lo que ve el viewer al landing en feed) sigue
  siendo válido pero su impacto es solo en el sub-conjunto que ya recibió push.
- **Mejor lever: volumen sostenido + diversidad del library** = más tiros, más probabilidad
  de que el algoritmo elija uno tuyo para el push masivo.

**Decisión:**
- NO tocar la lógica de thumbnail engineering.
- Mantener cadence 2 Shorts/día × 4 plataformas.
- Priorizar ingerir más fuentes nuevas (diversidad).
- El user fue claro: "no te líes con el thumbnail".
