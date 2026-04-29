# Shorts-Reels — Football Core Pipeline

Sistema automatizado para generar y publicar compilaciones de football core en TikTok, YouTube Shorts, Instagram Reels y X/Twitter.

---

## Quickstart (Mac nuevo — setup en 10 min)

```bash
cd Shorts-Reels

# 1. Homebrew deps (si no estan)
brew install ffmpeg python@3.13

# 2. Crear virtualenv e instalar deps Python
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .

# 3. Verificar que tienes las API keys en config/config.toml
cat config/config.toml

# 4. Comprobar que todo sigue conectado
python scripts/library.py stats
```

Si `stats` devuelve `19 sources, 80 segments`, todo funciona.

---

## Arquitectura en 30 segundos

**Input:** URLs de TikTok (videos de football core de otras cuentas)
**Proceso:** Descarga → detecta separadores negros (ffmpeg + Claude Vision) → guarda segmentos individuales
**Output:** Posts nuevos con segmentos mezclados + captions unicos por plataforma → scheduled en Upload-Post (cloud)

```
data/library/sources/    ← videos originales descargados
data/library/segments/   ← clips individuales (normalizados 1080x1920)
data/library/metadata/   ← JSON por source y segmento
data/outputs/            ← posts generados (vacio tras schedule — ya estan en cloud)
data/branding/           ← logos
```

---

## Flujo diario del usuario

### Añadir URLs nuevas a la biblioteca (semanal)
```bash
source .venv/bin/activate
python scripts/library.py add \
  "https://vm.tiktok.com/URL1/" \
  "https://vm.tiktok.com/URL2/" \
  "https://vm.tiktok.com/URL3/"
```
Cada URL se descarga, splitea por pantallas negras (validadas con Claude Vision), y añade ~2-6 segmentos limpios a la biblioteca.

### Programar N posts para los proximos dias
```bash
python scripts/schedule_batch.py 6      # 6 posts = 3 dias de contenido (10:00 + 18:00)
python scripts/schedule_batch.py 14     # 14 posts = 7 dias
```
Los posts se generan localmente, se suben a **Upload-Post servers** con `scheduled_date`, y se publican automaticamente. **El Mac puede estar apagado**.

### Ver posts programados
```bash
source .venv/bin/activate
python3 -c "
from upload_post import UploadPostClient
from src.utils.config import load_config
client = UploadPostClient(api_key=load_config()['upload_post']['api_key'])
import json
print(json.dumps(client.list_scheduled(), indent=2, default=str)[:2000])
"
```

### Ver stats de la biblioteca
```bash
python scripts/library.py stats   # sources, segments, duracion total
python scripts/library.py list    # tabla completa
```

---

## Cuentas

| Plataforma | Handle | Login |
|---|---|---|
| TikTok | `@fc.core.23.10` | (warm-up hasta ~21 abril 2026 — NO publicar aun) |
| YouTube | `@FCCore-23` | via OAuth en Upload-Post |
| Instagram | `@fc.core.23.10` | via OAuth en Upload-Post |
| X/Twitter | `@Fc_Core_23` | via OAuth en Upload-Post |
| Upload-Post | `fc.core.23.10@gmail.com` (plan Basic mensual $26) | JWT API key en config |

Foto de perfil en las 4: `data/branding/logo_512.png` (logo negro "fc.core.")

---

## Comandos CLI disponibles

```bash
python scripts/library.py add URL1 URL2...   # Descargar + splitear + guardar en library
python scripts/library.py hunt               # Auto-descubrir + validar + ingerir (opcional)
python scripts/library.py stats              # Estado de la biblioteca
python scripts/library.py list               # Tabla de segmentos
python scripts/library.py post               # Generar 1 post (TikTok 45s + Long 75s)
python scripts/library.py show POST_ID       # Ver captions + abrir carpeta
python scripts/library.py publish POST_ID    # Publicar AHORA en todas las plataformas habilitadas
python scripts/library.py publish POST_ID x  # Publicar AHORA solo en X
python scripts/library.py tiktok-post POST_ID  # Publicar AHORA en TikTok via Selenium
python scripts/library.py clear              # Borrar TODA la biblioteca (cuidado)

python scripts/schedule_batch.py N           # Generar + programar N posts en Upload-Post
python scripts/schedule_batch.py N --start 2h   # Primer slot 2h desde ahora
```

---

## Config (config/config.toml)

```toml
[claude]
api_key = "sk-ant-api03-..."            # Anthropic API key
model = "claude-haiku-4-5-20251001"

[upload_post]
api_key = "eyJhbGciOi..."                # JWT Upload-Post API key
username = "FCCore-23"                   # Nombre del profile en Upload-Post
platforms = ["youtube", "instagram", "x"]  # TikTok anadir cuando warm-up acabe
```

---

## Componentes clave

### src/library.py
Clase `SegmentLibrary`. Gestiona todo:
- `add_source(url)` — descarga + splitea + guarda
- `hunt(...)` — automatizado: busca candidatos + valida + ingiere
- `generate_post()` — crea un post (2 videos + metadata JSON)
- `generate_mix(duration)` — genera solo 1 mix (sin 2 versiones)

### src/services/hybrid_splitter.py
Detecta pantallas negras con ffmpeg blackdetect (milisegundos de precision) → Claude Vision valida cuales son separadores reales vs falsos positivos → corta exactamente al final de cada separador validado.

### src/services/metadata_generator.py
Claude genera captions minimalistas estilo football core real ("football core ⚽", "football core • grassroots") para cada plataforma. Rota hashtags del pool para evitar duplicados.

### src/services/uploadpost_publisher.py
Sube via Upload-Post SDK oficial. Soporta `scheduled_date` + `timezone` → programacion cloud. El Mac no necesita estar encendido despues de programar.

### src/services/vision_qa.py
Claude Vision revisa el output final: detecta frozen frames, black frames extendidos, cortes abruptos. Se usa opcionalmente en `mix`.

### src/services/hunter.py / validator.py
Auto-descubrimiento: busca videos en cuentas conocidas (@hopecore.video, @football.1.hub...) → Claude Vision valida si son football core real → añade automaticamente. Uso opcional via `hunt` CLI.

---

## Estado actual (18 abril 2026)

### Scheduled en Upload-Post
- **21 posts programados** desde hoy 18:00 hasta el 21 abril 10:00
- Distribuidos en YouTube + Instagram + X (3 posts × 7 slots)
- Proximos slots: 18 Apr 18:00, 19 Apr 10:00 y 18:00, 20 Apr 10:00 y 18:00, 21 Apr 10:00

### Biblioteca
- **19 sources** (videos TikTok descargados)
- **80 segmentos** (clips individuales normalizados)
- ~8 minutos de material

### TikTok warm-up
Hasta el **21 abril**: no publicar via Upload-Post. La usuaria debe:
- 10-15 min/dia en TikTok usando `@fc.core.23.10`: FYP, likes, comentarios en football core, seguir cuentas del nicho
- 1 video al dia subido manualmente desde la app de TikTok del movil

Despues del 21 de abril: dar "I Understand, Connect" en Upload-Post y añadir `"tiktok"` a `platforms` en config.toml. Al siguiente `schedule_batch.py` empezara a publicar tambien en TikTok.

### Auto-upload a TikTok via Selenium (durante warm-up)

Durante el warm-up se usa Selenium para publicar en TikTok (no hay API). Hay un launchd que dispara a las 10:00 y 18:00:

```bash
# Instalar (una vez)
bash scripts/launchd/install.sh

# Desinstalar cuando TikTok API esté conectada
bash scripts/launchd/uninstall.sh
```

Primera vez que se ejecute abrirá Chrome y esperará hasta 5 min a que hagas login. Después la sesión queda guardada en `~/.shorts_pipeline/chrome_profile/`.

Manual: `python3 scripts/library.py tiktok-post POST_ID`

---

## Costes mensuales

| Servicio | Coste | Nota |
|---|---|---|
| Claude API (Haiku) | ~$1/mes | Por ~60 posts + validaciones |
| Upload-Post Basic | $26/mes (mensual) o $16 (anual) | Publish ilimitado cloud |
| **Total** | **~$27/mes** | |

---

## Decisiones importantes tomadas

1. **Splitter hibrido (ffmpeg + Claude Vision)**: usar solo blackdetect produce falsos positivos; solo Claude es impreciso. Combinar los dos da precision milisegundo + validacion semantica.

2. **Captions minimalistas**: captions "Most Insane Goals 2025" no encajan con el nicho. Los posts exitosos usan captions de 2-6 palabras ("football core ⚽", "hopecore football video . . . ."). El `metadata_generator.py` fue reescrito para clonar ese estilo.

3. **Upload-Post > Publer > Buffer**: Buffer free plan solo da tokens OIDC (no API). Publer requiere reescribir publisher. Upload-Post Basic ($26 mensual) ya tiene API oficial de TikTok aprobada — ahorra semanas de verificacion.

4. **Scheduling cloud > launchd local**: el Mac encendido era inviable. Upload-Post permite `scheduled_date` en el upload — los servidores publican, el Mac puede estar apagado.

5. **TikTok warm-up**: Upload-Post avisa que cuentas nuevas sin warm-up pueden ser shadow-banned. 3-5 dias de uso organico antes de conectar API.

---

## Troubleshooting

### "Upload failed: Username required"
El SDK oficial usa el parametro `user`, no `username`. Ya arreglado en `uploadpost_publisher.py`.

### Videos se reproducen con pantalla congelada
Segmentos con diferentes SAR/fps. Ya resuelto: `_concat` normaliza todo a 1080x1920 30fps antes de concatenar.

### "No hay suficientes segmentos"
Añade URLs nuevas: `python scripts/library.py add URL1 URL2...`

### Limite de Upload-Post
Plan Basic = ilimitado. Si ves errores de limite, verifica que el plan no se haya vuelto free.

---

## Mejoras futuras pendientes

- **Nichos adicionales**: el pipeline esta hardcoded a football core. Migrar a config multi-nicho para `fails`, `satisfying`, etc.
- **Hunter automatico semanal**: cron que ejecute `hunt` cada domingo para añadir URLs nuevas sin intervencion.
- **Analytics**: conectar con Upload-Post `get_analytics` para medir views/engagement por plataforma y decidir que formatos amplificar.
- **Monetizacion**: desde 10K followers → activar TikTok Creator Rewards, YouTube Shorts Fund, X Premium para revenue sharing. Coste marginal 0€.
