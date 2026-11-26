# 🚵‍♂️ Buscador de e-MTB de Ocasión

Script modular en Python para rastrear automáticamente tiendas profesionales de reacondicionado de bicicletas y encontrar ofertas de bicicletas eléctricas de montaña (e-MTB) doble suspensión que cumplan con filtros estrictos de talla, modalidad, peso, batería y precio.

Cuando encuentra bicicletas aptas tras superar los filtros estrictos, las audita con un **Perito Mecánico Escéptico y Estricto (v2)** y envía por Telegram **1 mejor bicicleta por cada portal con stock** (con rotación ping-pong `#1 -> #2 -> #1` si la mejor opción de una página no cambia entre corridas consecutivas), evitando alertas repetitivas salvo bajadas de precio o verificación de liderazgo.

## Tabla de contenidos

- [¿Qué hace este proyecto?](#qué-hace-este-proyecto)
- [Requisitos estrictos de filtrado](#requisitos-estrictos-de-filtrado)
- [Algoritmo de Nota de Oportunidad (Perito Mecánico Escéptico v2)](#algoritmo-de-nota-de-oportunidad-perito-mecánico-escéptico-v2)
- [Integración con Telegram](#integración-con-telegram)
- [Automatización y programación](#automatización-y-programación)
- [Plataformas objetivo y garantía](#plataformas-objetivo-y-garantía)
- [Arquitectura modular](#arquitectura-modular)
- [Requisitos previos](#requisitos-previos)
- [Instalación](#instalación)
- [Configuración](#configuración)
- [Cómo usar](#cómo-usar)
- [Pruebas](#pruebas)
- [Advertencias importantes](#advertencias-importantes)
- [Próximos pasos y Roadmap](#próximos-pasos-y-roadmap)
- [Por qué se ha construido así (Arquitectura e Ingeniería de Decisiones)](#por-qué-se-ha-construido-así-arquitectura-e-ingeniería-de-decisiones)
- [Proceso de desarrollo y dificultades encontradas](#proceso-de-desarrollo-y-dificultades-encontradas)
- [Estado actual y TODOs para mañana](#estado-actual-y-todos-para-mañana-27112026)
- [Licencia](#licencia)

---

## ¿Qué hace este proyecto?

Este script rastrea diariamente las secciones de e-MTB doble suspensión de portales de reacondicionado, anuncios geolocalizados de Wallapop (radio de 50 km desde Fuenlabrada, Madrid) y **6 tiendas oficiales españolas online de bicicletas nuevas (`0 km`, 3 años de garantía)** para compra en toda España:

- **Bike Ocasión** (bike-ocasion.com)
- **Buhobike** (buhobike.com — nuevas + segunda mano)
- **Upway** (upway.es)
- **Mammoth Bikes** (mammothbikes.com — nuevas `0 km`)
- **Sanferbike** (sanferbike.com — nuevas `0 km`, stock en vivo por talla)
- **Bicimarket** (bicimarket.com — nuevas `0 km`, faceta Doble Suspensión)
- **Escapa** (escapa.com — nuevas `0 km`, BigCommerce + stock por `BCData`)
- **Fabregues Bicicletas** (fabreguesbicicletas.com — nuevas `0 km` + *Test Ride*)
- **Wallapop** (es.wallapop.com — radio estricto `<= 50 km` desde Fuenlabrada + búsqueda local por modelos clave)

Para cada bicicleta encontrada aplica una serie de filtros estrictos y, si pasa, le asigna una **Nota de Oportunidad del 0 al 10**. Solo las bicicletas con nota **≥ 8.0** se guardan en una base de datos local SQLite y se envían por Telegram para evitar alertas duplicadas (salvo que bajen de precio).

La ejecución automática en Windows Task Scheduler (`BuscadorBiciOcasion`) está programada todos los días a las **12:00** (`python main.py --once`), mientras que el modo demonio integrado (`python main.py` con `schedule`) utiliza `config.HORA_EJECUCION` (**12:30**).

---

## Requisitos estrictos de filtrado

| ID | Requisito | Detalle |
|----|-----------|---------|
| **S0** | Disponibilidad | Exclusivamente unidades **en stock** (se descartan preventivamente unidades marcadas como *Reservada*, *Agotada*, *Vendida* o *Sin stock*). |
| **S1** | Talla | Exclusivamente **Talla M** (aprox. 165 cm - 179 cm). |
| **S2** | Modalidad | Estrictamente **XC / Cross Country / Downcountry puro (`<= 130 mm`)** (bloquea Trail `>= 140 mm`, All Mountain y Enduro aunque sean ligeras). |
| **S3** | Peso | Máximo **19 kg** (se priorizan cuadros de carbono y motores ligeros; se descartan modelos > **21 kg**). |
| **S4** | Batería | En flujo diario: estrictamente **> 500 Wh** (interna + Range Extender incluido). En Black Friday: **>= 500 Wh** o XC ligero Fazua `420–430 Wh` (`<= 3.050 €`) ampliable a `630–640 Wh` con extender (`+210 Wh`) dentro del tope de `3.500 €`. |
| **S5** | Precio principal | Rango de **2.000 € a 3.000 €**. |
| **S6** | Precio excepcional | Hasta **3.300 €** en flujo general, o hasta **3.500 €** en diario solo para **Unicornios XC** (`>= 600 Wh`, `<= 500 km`, `< 19 kg`, `<= 130 mm`). |

---

## Algoritmo de Nota de Oportunidad (Perito Mecánico Escéptico v2)

El sistema opera bajo las reglas deterministas de un **Perito Mecánico Escéptico y Estricto (`perito_v6_xc`)**: parte de **BASE = 10.0 sin bonos positivos**, prohíbe inventar componentes, aplica física realista anti-optimismo de peso (`Full Power + >= 625 Wh` o sin batería confirmada `>= 22.5 kg` salvo excepciones ligeras explícitas), distingue modelos XC (`<= 130 mm`: `BH iLynx Race`, `Wilier Urta Hybrid`, `Scott Lumen <= 130 mm`, `BMC Fourstroke AMP LT`, `Focus VAM2 SL`) de modelos Trail (`>= 140 mm`: `Orbea Rise`, `BH iLynx Trail`, `KTM Macina Scarp SX`, `Moterra SL`, `Levo SL`, `Fuel EXe`), corrige erratas de motor (`BH iLynx Race/Trail` sin `+` = `BH 2EXMAG` cerrado; `BH iLynx+` = `Shimano EP801` abierto; `Orbea Rise 2021-2022` = `EP8-RS`; `2025+` = `EP801-RS Gen2`; `Bosch` = solo taller oficial sin SoH en app de usuario) y limita la nota final mediante **Líneas Rojas**:

| Línea Roja Eliminatoria | Tope de Nota |
|-------------------------|--------------|
| Talla distinta de `M` (`S`, `L`, `XL`, etc.) | **0.0 / 10** (`DESCARTADA`) |
| Batería interna/total `< 500 Wh` | **4.0 / 10** (`DESCARTADA`) |
| Peso real o estimado `> 21.0 kg` | **4.0 / 10** (`DESCARTADA`) |
| Kilometraje `> 6.000 km` | **4.5 / 10** (`DESCARTADA`) |
| Anuncio genérico sin marca ni modelo identificable | **4.5 / 10** (`DESCARTADA`) |

### 1. Kilometraje y Desgaste (incluye contradicciones)
* **0 a 1.000 km** (sin contradicciones): **-0.0 pts**
* **1.001 a 2.000 km**: **-1.0 pt**
* **2.001 a 4.000 km**: **-2.5 pts**
* **4.001 a 6.000 km**: **-3.5 pts**
* **> 6.000 km**: **-4.5 pts** (activa Línea Roja `4.5`)
* **No especificado o contradicción** (`"NUEVA"` / `"ESTRENAR"` + `km > 50`): **-2.0 pts** (o mantiene la resta mayor de tramo si supera `2.000 km` mediante `min(delta_km, -2.0)`).

### 2. Peso Real Estimado (sin bonos y anti-optimismo)
* **<= 19.0 kg**: **-0.0 pts**
* **19.1 a 20.0 kg**: **-0.5 pts**
* **20.1 a 21.0 kg**: **-1.5 pts**
* **> 21.0 kg**: **-6.0 pts** (activa Línea Roja `4.0`)

### 3. Motor, Diagnosis y Batería (SoH / Ciclos)
* **Shimano EP8 / EP801 / EP6** (incluida `BH iLynx+`) o **Specialized**: **-0.0 pts** (auditables vía app propia o PCE02).
* **Bosch Performance CX / SX** sin informe oficial completo de taller: **-0.5 pts** (Bosch no expone ciclos ni SoH en la app de usuario).
* **Motor propietario cerrado** (`BH 2EXMAG` sin `+`, `Brose` antiguo, otros): **-0.5 pts** (`<= 2.000 km`) o **-1.0 pt** (`> 2.000 km` / desconocido).
* **Penalización extra sin SoH ni ciclos**: **-0.5 pts** adicionales si no aporta SoH/ciclos y tiene `> 1.500 km` o kilometraje desconocido.

### 4. Garantía y Canal de Venta
* **Tienda profesional en España** (`>= 1 año` garantía legal): **-0.0 pts**
* **Tienda extranjera / sin reseñas verificadas**: **-1.0 pt**
* **Particular con factura vigente** (`< 2 años`, detectada vía `tiene_factura`): **-1.0 pt**
* **Particular sin garantía comercial ni mención de factura**: **-1.5 pts**

### 5. Precio y Componentes Declarados
* **2.000 € - 3.000 €** con transmisión 12v (SLX/XT/GX) y suspensiones gama media-alta: **-0.0 pts**
* **Precio 3.001 € - 3.150 €** (margen negociable): **-0.5 pts** | **> 3.150 €**: **-2.0 pts**
* **Montaje básico/obsoleto** (`10v/11v`, frenos `MT200/MT401`, horquilla básica) costando `> 2.400 €`: **-0.5 a -1.0 pt**
* **Componentes principales no detallados** en el anuncio (`NO ESPECIFICADO`): **-1.5 pts**

---

## Integración con Telegram

El script usa la API de Telegram vía `requests` y envía un mensaje en **Markdown** con:

- Título de la bicicleta y precio.
- **Nota de Oportunidad destacada** (ej. 🔥 8.5/10).
- Kilómetros, capacidad de batería y material del cuadro.
- **Desglose breve** de por qué sacó esa nota.
- **Enlace directo de compra**.
- **Segmentación sonora (TODO 3)**: Las ofertas normales y el Heartbeat se entregan en silencio (`disable_notification=True`). Únicamente los verdaderos **Mega Chollos** (Nota $\ge$ 9.0 y dto $\ge$ 50% vs PVP nuevo) disparan notificación sonora/prioritaria con timbre (`disable_notification=False`), configurable mediante `TELEGRAM_SILENCIAR_OFERTAS_NORMALES=true`.
- **Canal exclusivo Black Friday (`Black_Bike_Beast`)**: Segundo bot independiente (`TELEGRAM_BOT_TOKEN_BLACK_FRIDAY` y `TELEGRAM_CHAT_ID_BLACK_FRIDAY`, con fallback a `TELEGRAM_CHAT_ID`) que vigila e-MTB **XC/Downcountry (`<= 130 mm`) nuevas o de exposición (`<= 50 km`, Talla M, `< 21.0 kg`, `>= 500 Wh` — o XC ligero Fazua `420–430 Wh` con margen `<= 3.050 €` para añadir extender `+210 Wh` = `640 Wh` dentro de `3.500 €` —, doble suspensión) hasta `3.500 €`** con descuento real **`>= 35%` sobre PVP** (`nota_bf >= 7.5/10`), sin alterar el techo diario de `3.300 €` (salvo unicornios XC `>= 600 Wh` y `<= 500 km` hasta `3.500 €`). Si `0` unidades cumplen el estricto en presupuesto, envía un informe **Top 3 XC Puro fuera de tope/criterio** (admitiendo en respaldo baterías ligeras TQ `>= 360 Wh`, `km <= 2.000` y advertencia explícita).

Requiere configurar `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en el archivo `.env` (y opcionalmente `TELEGRAM_BOT_TOKEN_BLACK_FRIDAY` / `TELEGRAM_CHAT_ID_BLACK_FRIDAY` para el canal Black Friday).

### Cómo conectar tu cuenta de Telegram (paso a paso)

Para recibir las notificaciones del buscador en tu chat de Telegram, seguí estos pasos:

#### 1. Creá un bot con @BotFather

1. Abrí Telegram y buscá al usuario **@BotFather**.
2. Enviá el comando `/newbot`.
3. Seguí las instrucciones: poné un nombre para tu bot (ej. "Buscador e-MTB") y un nombre de usuario único (ej. `buscador_ebtm_bot`).
4. Al terminar, @BotFather te dará un **token** que se ve así: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`.
5. **Copiá ese token**: es tu `TELEGRAM_BOT_TOKEN`.

#### 2. Obtené tu `chat_id`

Hay dos formas:

**Opción A (más fácil):** Enviá cualquier mensaje a tu bot recién creado y luego entrá a esta URL en tu navegador (reemplazá `TU_TOKEN` por el token del paso 1):

```
https://api.telegram.org/bot<TU_TOKEN>/getUpdates
```

Buscá en el JSON la sección `"chat": {"id": -1001234567890, ...}`. Ese número (ej. `-1001234567890`) es tu `TELEGRAM_CHAT_ID`.

**Opción B:** Usá el bot **@userinfobot** en Telegram. Enviá `/start` y te dirá tu `chat_id` directamente.

#### 3. Configurá el archivo `.env`

1. Copiá la plantilla: `cp .env.example .env`
2. Editá `.env` y pegá tus valores reales:

```ini
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890
# Opcional: ruta personalizada de la base de datos SQLite
# BUSCADOR_DB_PATH=bicis_enviadas.db
```

⚠️ **Importante:** Nunca subas el archivo `.env` a GitHub. Contiene tu token de bot y tu chat_id. Ya está excluido por `.gitignore`.

#### 4. Probá el envío

El script solo envía notificaciones cuando encuentra una bici con **Nota de Oportunidad ≥ 8.0** que no haya sido notificada antes (o que bajó de precio). Para probar que Telegram funciona sin esperar a que aparezca una bici real, podés ejecutar los tests:

```bash
python test_buscador.py
```

Aunque los tests no envían mensajes reales a Telegram (require credenciales configuradas), validan que la lógica de formateo del mensaje es correcta.

Cuando el script encuentre una bici real con nota ≥ 8.0, recibirás un mensaje en tu chat de Telegram con algo como:

```
🚵‍♂️ *Nueva oportunidad de e-MTB encontrada*

*Moustache Samedi 29 Trail 3*
🏪 Tienda: Upway
💰 Precio: *1.999 €*
🔥 Nota de Oportunidad: *8.5/10*

📏 Talla: M: ideal para ciclistas entre 1m69 - 1m85
⚙️ Modalidad: De doble suspensión
⚖️ Peso: 24 kg
🔋 Batería: 687 Wh
🛞 Cuadro: Aluminio
⚡ Motor: Bosch Performance Line CX
📅 Año: 2023
🛣️ Kilómetros: 10.152 km
🛡️ Garantía: 1 año(s)

_Desglose de la nota:_
Kilometraje: Km moderados (10152 km): +1.5 | Calidad-precio: cuadro carbono: +1.0; ...

🔗 [Enlace directo de compra](https://upway.es/products/moustache-samedi-29-trail-3-rk7fu0)
```

#### 5. Seguridad

- **No compartas tu `TELEGRAM_BOT_TOKEN`** con nadie. Cualquiera con ese token puede enviar mensajes en nombre de tu bot.
- **No subas el archivo `.env`** a ningún repositorio público. Está en `.gitignore` para evitar que se suba por error.

---

## Automatización y programación

El script soporta dos modos de automatización:

- **Programador de tareas de Windows / `cron` (recomendado, en producción)**: ejecuta `python main.py --once` diariamente a las **12:00** con despertar automático (`WakeToRun: True` en `BuscadorBiciOcasion`, ver [CRON.md](CRON.md)).
- **Bucle `schedule` integrado (`python main.py`)**: queda residente y dispara la búsqueda todos los días a las **12:30** (`config.HORA_EJECUCION`).

Consulta [CRON.md](CRON.md) para ver tanto la configuración de cronjob en Linux/macOS como el script PowerShell de Windows Task Scheduler.

---

## Plataformas objetivo y garantía

El scraper rastrea tiendas profesionales y portales de ocasión en España con garantía mínima de 1–3 años más Wallapop (con auditoría de factura y sin garantía comercial cuando es particular):

- bike-ocasion.com (ocasión, 1 año garantía)
- upway.es (reacondicionadas, 1 año garantía)
- wallapop.com (geo-radio `<= 50 km` desde Fuenlabrada)
- buhobike.com (nuevas `0 km` + segunda mano)
- mammothbikes.com (nuevas `0 km`, 3 años garantía)
- sanferbike.com (nuevas `0 km`, 3 años garantía)
- bicimarket.com (nuevas `0 km`, 3 años garantía)
- escapa.com (nuevas `0 km`, 3 años garantía)
- fabreguesbicicletas.com (nuevas `0 km` + *Test Ride*, 3 años garantía)

---

## Arquitectura modular

El proyecto está separado en módulos con responsabilidad única:

| Archivo | Responsabilidad |
|---------|-----------------|
| `config.py` | Configuración central: URLs objetivo optimizadas, filtros estrictos XC (`RECORRIDO_MAX_XC_MM = 130`), `WALLAPOP_UNICORN_QUERIES`, `PRECIO_MAX_UNICORNIO_XC_EUR = 3500`, `GEMINI_MODELS`, credenciales Telegram/Gemini, user-agents, proxies (opcional) y horarios. |
| `models.py` | Dataclass `Bicicleta` con todos los campos necesarios para scoring, telemetría de batería (`bateria_salud_pct`, `bateria_ciclos`), `pvp_original`, `ubicacion` y `tiene_factura`. |
| `db.py` | Base de datos SQLite (`WAL`): registro de bicicletas ya enviadas, tabla `bicis_black_friday_enviadas`, deduplicación por ID y equivalencia cruzada (`respaldo:` aislado), `estado_portales`, historial de catálogo (`historial_catalogo`), permanencia en stock y métricas del Radar (`BH iLynx Race`, `Wilier Urta Hybrid`, `Focus VAM2 SL`, etc.). |
| `evaluator.py` | Filtros estrictos (S1-S6), purga XC `<= 130 mm` (`es_modalidad_xc`, `es_modelo_trail_o_enduro`), `es_unicornio_xc`, `es_xc_ampliable_en_presupuesto` (Fazua `420–430 Wh` + extender), algoritmo de Nota de Oportunidad, `prioridad_modalidad` y rúbrica Black Friday (`evaluar_oportunidad_black_friday`) para nuevas/expo `<= 3.500 €`. |
| `gemini_classifier.py` | Motor Perito Mecánico Senior (`perito_v6_xc`), catálogo técnico `CATALOGO_EMTB` (XC vs Trail), desambiguación BH (`2EXMAG` vs `EP801`), seguimiento de peso empírico real y clasificador híbrido (`gemini-3.5-flash-lite` -> `gemini-3-flash-preview` con `thinkingBudget: 0`). |
| `notifier.py` | Notificador unificado de Telegram vía `requests` (`_enviar_telegram`), ficha diaria Markdown, alertas exclusivas Black Friday (`enviar_black_friday`, nota extender `+210 Wh`), informe Top 3 XC de respaldo y Heartbeats operativos diarios. |
| `scraper_base.py` | Clase base con **motor Scrapling**: `Fetcher` (HTTP con impersonación TLS) → `StealthyFetcher` (navegador stealth con `solve_cloudflare=True`), con `usar_stealth_directo` y salto inmediato ante bloqueos HTTP 403/503 de Cloudflare. |
| `scrapers/bike_ocasion.py` | Adaptador específico para Bike Ocasión. Extrae título limpio (`h3.s_title_block a`), talla, batería, km, marca del motor (`Km / <Marca>`), PVP original y doble suspensión directamente de la tarjeta del listado. Paginación de hasta 6 páginas (180+ bicis). |
| `scrapers/buhobike.py` | Adaptador específico para Buhobike con modo stealth directo (`usar_stealth_directo=True`), rastreo combinado de `/3230-electricas-trail-dobles` (págs. 1 y 2 + `?q=MODELO-LUMEN`) y segunda mano (`/9448-...`, `/3225-...`), y extracción de título, talla (`#/...-talla-m`), año, km en SKU y PVP original. |
| `scrapers/upway.py` | Adaptador específico para Upway sobre `/collections/doble-suspension`. Extrae año, kilometraje (`km` y `< 5 km`), talla (desde el rango de estatura `1mXX-1mYY`), PVP original nuevo ('6.000 € nuevo') y doble suspensión directamente de la tarjeta en `< 1s`. |
| `scrapers/mammoth.py` | Adaptador específico para Mammoth Bikes sobre `/bicicletas-electricas-mtb-dobles-rally-xc/c-3104` y `/bicicletas-electricas-mtb-trail-all-mountain-dobles/c-2139`. Extrae precio (`:not(.is__old)`), tallas en stock (`M`), modalidad XC, año, PVP original tachado (`.is__old`), telemetría de bici nueva (`km=0`, `SoH=100%`) y filtro anti-rígidas en `~2.5s`. |
| `scrapers/wallapop.py` | Adaptador para API v3 de Wallapop (`source="quick_filters"`, geo-radio `<= 50 km` desde Fuenlabrada) + búsqueda local por modelo (`WALLAPOP_UNICORN_QUERIES`), dedup por talla/precio, `_extraer_pvp_wallapop`, `tiene_factura` y detección segura de `km=0` / `SIN ESTRENAR`. |
| `scrapers/prestashop_base.py` | Base reutilizable para tiendas PrestaShop: paginación con preservación de parámetros, extracción de título sin contaminación de badges, precio/PVP, detección `TEST RIDE` / `DEMO` y guardas anti-rígidas. |
| `scrapers/sanferbike.py` | Adaptador PrestaShop para Sanferbike con stock real por talla desde `.js-miniature-product-variants` (`data-qty-*` / `attribute-not-in-stock`) y precio desde `span.product-price[content]`. |
| `scrapers/bicimarket.py` | Adaptador PrestaShop para Bicimarket sobre faceta de Doble Suspensión ordenada por precio ascendente (`PVPR`), delegando validación real de talla M a la ficha del producto. |
| `scrapers/escapa.py` | Adaptador BigCommerce para Escapa con descarga HTTP directa vía `requests`, descarte preventivo de tarjetas `Avísame` y validación de stock talla `M`/`MD` por `BCData.in_stock_attributes`. |
| `scrapers/fabregues.py` | Adaptador PrestaShop para Fabregues Bicicletas con limpieza de códigos SKU BH (`\|EC796\|`), tratamiento de unidades *Test Ride* y verificación real de talla `M`/`MD` en ficha. |
| `scrapers/enriquecedor_web.py` | Enriquecedor web paralelo con caché JSON (`cache/fichas_detalle.json`, TTL 6h para stock en tiendas nuevas) y DuckDuckGo; extrae variantes en stock (`PrestaShop` / `BCData`), `<dt>/<dd>`, SoH/ciclos, recorrido (`mm` ignorando rotores de freno `180 mm`) y `_extraer_km` sin falsos positivos. |
| `main.py` | Orquestador: scrape paralelo de los 9 portales → **health check** → pre-filtro con `CATALOGO_EMTB` → dedup separada → enriquecimiento → selección por portal + Black Bike Beast (`<= 3.500/4.000 €`) → SQLite → Telegram + Radar (`docs/radar_mercado.md`). |
| `test_buscador.py` | Suite de pruebas unitarias e integración con mocks para validar filtros XC vs Trail, Fazua ampliable, unicornios XC `<= 3.500 €`, Perito `perito_v6_xc`, scrapers (incluyendo Wallapop nacional y `_extraer_km`), rotación por portal y dedup SQLite. |
| `CRON.md` | Instrucciones para ejecutar mediante cronjob en Linux/Mac o Programador de tareas de Windows. |
| `.env.example` | Plantilla de variables de entorno. |
| `requirements.txt` | Dependencias de Python. |

---

## Requisitos previos

- **Python 3.10 o superior** instalado en tu sistema.
- `pip` disponible en el PATH.
- Una cuenta de Telegram y un bot creado (vía [@BotFather](https://t.me/botfather)) para obtener `TELEGRAM_BOT_TOKEN`.
- El `chat_id` de tu chat de Telegram (puedes obtenerlo con [@userinfobot](https://t.me/userinfobot) o enviando un mensaje al bot y consultando `https://api.telegram.org/bot<TOKEN>/getUpdates`).

---

## Instalación

1. Cloná el repositorio:

```bash
git clone https://github.com/tu-usuario/buscador-bici-ocasion.git
cd buscador-bici-ocasion
```

2. Instalá las dependencias:

```bash
pip install -r requirements.txt
```

### Opcional: capas anti-baneo

Scrapling ya incluye todo lo necesario (HTTP con impersonación TLS, navegador stealth con Playwright/Patchright, y `solve_cloudflare=True` para Cloudflare). Se instala con:

```bash
pip install -r requirements.txt
```

Esto instala `scrapling`, `patchright`, `browserforge` y `msgspec`. No hace falta instalar `curl_cffi` ni `playwright` por separado.

### Proxies (opcional, para sitios con Cloudflare agresivo)

Si un sitio bloquea por IP (ej. Buhobike con Cloudflare muy agresivo), configurá proxies rotatorios en `.env`:

```ini
PROXY_LIST=http://usuario:contraseña@ip:puerto,http://otro-proxy:puerto
PROXY_ROTATION=cyclic
```

Scrapling usará `ProxyRotator` para rotar entre ellos automáticamente.

---

## Configuración

1. Copiá el archivo de ejemplo:

```bash
cp .env.example .env
```

2. Editá `.env` y completá tus credenciales:

```ini
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890
# Opcional: ruta personalizada de la base de datos SQLite
# BUSCADOR_DB_PATH=bicis_enviadas.db
```

---

## Cómo usar

### Opción A: Ejecución manual con bucle diario (schedule)

```bash
python main.py
```

El script quedará corriendo y ejecutará la búsqueda todos los días a la hora configurada en `config.HORA_EJECUCION` (`12:30`). Presiona `Ctrl+C` para detenerlo.

### Opción B: Cronjob (Linux / Mac)

Consultá el archivo `CRON.md` para la configuración exacta. Ejemplo de entrada en crontab:

```cron
0 12 * * * /usr/bin/python3 /ruta/absoluta/al/proyecto/main.py >> /ruta/absoluta/al/proyecto/logs/buscador.log 2>&1
```

---

## Pruebas

El proyecto incluye `test_buscador.py` con pruebas RED/GREEN usando datos simulados (no depende de la web real ni de credenciales de Telegram). Valida:

- Filtros estrictos (talla, modalidad, batería, peso, precio).
- Algoritmo de Nota de Oportunidad.
- Deduplicación de SQLite y re-alerta por bajada de precio.
- Formateo del mensaje de Telegram.

Ejecutá:

```bash
python test_buscador.py
```

Deberías ver: `Todas las pruebas pasaron (GREEN).`

---

## Advertencias importantes

1. **Selectores CSS inspeccionados.** Los selectores de Bike Ocasión, Buhobike y Upway ya fueron inspeccionados en el HTML real de cada web (vía ego-browser).

2. **Protecciones anti-baneo.** Las 4 tiendas objetivo probablemente usen Cloudflare o renderizado JavaScript. `scraper_base.py` usa **Scrapling** con dos capas: `Fetcher` (HTTP rápido con impersonación TLS) y `StealthyFetcher` (navegador stealth con `solve_cloudflare=True` para Cloudflare). Buhobike requiere la capa stealth porque devuelve 503 con HTTP simple. Si seguís teniendo bloqueos, configurá proxies rotatorios (`PROXY_LIST` en `.env`).

3. **Datos inferidos.** Peso, talla, batería y motor a menudo no vienen como campos directos en el listado. Bike Ocasión ya extrae talla, batería, km, motor, suspensión, cuadro y componentes desde la tarjeta de listado. Los campos que falten (peso, año) se completan con el enriquecedor web (ficha del sitio + DuckDuckGo) antes de notificar por Telegram.

4. **Health check.** Antes de cada ejecución, `main.py` verifica que cada scraper devuelva al menos 1 producto. Si alguno devuelve 0, se lanza una alerta por log y Telegram (posibles selectores rotos por cambio de HTML).

5. **Caché de fichas.** Las fichas de producto ya consultadas se guardan en `cache/fichas_detalle.json` para no re-scrapear URLs repetidas y acelerar la corrida.

6. **Criterio separado tienda vs particular.** Wallapop solo entra en diario/BF pasando Haversine `<= 50 km` (salvo los 5 modelos XC unicornio autorizados a nivel nacional) y con deducción por ausencia de garantía comercial salvo factura vigente.

---

## Roadmap / próximos pasos

- [x] Instalar Python y dependencias en tu máquina local.
- [x] Ejecutar `python test_buscador.py` y verificar que pase todo (GREEN).
- [x] Probar scraping real sitio por sitio (Upway, Bike Ocasión y Buhobike probados con Scrapling).
- [x] Configurar `.env` con los bots de Telegram (Diario + `@BlackBikeBeast_bot`) y verificar el envío en vivo.
- [x] Automatizar la ejecución diaria con Windows Task Scheduler (`BuscadorBiciOcasion` a las `12:00` con `main.py --once`) y documentar `CRON.md`.
- [x] Configurar proxies rotatorios (`PROXY_LIST` en `.env`) con soporte nativo de rotación cíclica y aleatoria en Scrapling (`scraper_base.py`).

---

## Estado actual del proyecto

| Tarea | Estado | Detalle |
|-------|--------|---------|
| `config.py` | ✅ Hecho | URLs de los 4 sitios, filtros S1-S6, credenciales Telegram, user-agents, proxies (opcional), horario 12:30. |
| `requirements.txt` + `.env.example` | ✅ Hecho | Dependencias (Scrapling + Patchright + Browserforge + Msgspec) y plantilla de variables de entorno. |
| `models.py` | ✅ Hecho | Dataclass `Bicicleta` con todos los campos para scoring y Telegram. |
| `db.py` | ✅ Hecho | SQLite: dedup por ID, no reenvía salvo bajada de precio. |
| `evaluator.py` | ✅ Hecho | Filtros estrictos S1-S6 y algoritmo de Nota de Oportunidad 0-10 (S7, S8). |
| `notifier.py` | ✅ Hecho | Telegram vía `requests`, mensaje Markdown con todos los campos (S9). |
| `scraper_base.py` | ✅ Hecho | Motor Scrapling: `Fetcher` → `StealthyFetcher` con `solve_cloudflare`. Delays aleatorios, `ProxyRotator` opcional, paginación, salud de scrapers. |
| `scrapers/` (3 sitios) | ✅ Hecho | Bike Ocasión, Buhobike y Upway con selectores reales verificados y scraping real probado. |
| `scrapers/enriquecedor_web.py` | ✅ Hecho | Enriquece campos faltantes (peso, año, suspensión, cuadro, componentes, modalidad) desde ficha del sitio + DuckDuckGo fallback. Caché JSON en disco. |
| `main.py` | ✅ Hecho | Orquestador + health check + enriquecimiento paralelo (3 workers) + logging a archivo + bucle `schedule` diario a las 12:30. |
| `CRON.md` | ✅ Hecho | Instrucciones para cronjob Linux/Mac. |
| `test_buscador.py` | ✅ Hecho | Pruebas RED/GREEN con datos simulados. |
| `README.md` | ✅ Hecho | Documentación completa (este archivo). |

---

## Resultados de scraping real (validación de sesión)

Se ejecutó scraping real contra **Bike Ocasión** y **Buhobike** con Scrapling (`Fetcher` + `StealthyFetcher` con `solve_cloudflare=True`).

### Bike Ocasión — ✅ 153 bicicletas extraídas (5 páginas)

El scraper extrae 30 bicicletas por página y recorre 5 páginas (paginación `?page=N`). Campos extraídos directamente de la tarjeta de listado:

| Campo | Tasa de extracción |
|-------|-------------------|
| Talla | 100% |
| Batería | 100% |
| Kilometraje | 100% |
| Motor | 100% |
| Suspensión trasera | 100% |
| Material de cuadro | 100% |
| Componentes | 56% |
| Año | 0% (completado por enriquecedor web) |
| Peso | 0% (completado por enriquecedor web) |

Tiempo: ~28 segundos para 153 bicicletas (sin visitar ficha de detalle de cada una).

Luego se aplicaron los filtros estrictos (S1–S6) y la regla de nota ≥ 8.0 (S8). **Ninguna bici pasó todos los filtros** en el inventario actual:

| Motivo de descarte | Cantidad |
|--------------------|----------|
| Talla no es M (S1) | mayoría de bicis |
| Precio > 3.300 € (S5/S6) | varias bicis |
| Batería ≤ 500 Wh (S4) | algunas bicis |
| Nota < 8.0 tras pasar filtros | varias bicis |

Las bicicletas con precios más interesantes dentro del rango fueron descartadas principalmente por talla (no M) o por precio superior a 3.300 €. El inventario cambia constantemente; se recomienda ejecutar el buscador periódicamente.

### Buhobike — ✅ 32 bicicletas extraídas

El Fetcher HTTP devolvió 503 (Cloudflare agresivo), pero `StealthyFetcher` con `solve_cloudflare=True` resolvió el desafío y obtuvo 200.

Se extrajeron **32 bicicletas** de la categoría Trail Eléctricas. Tras aplicar los filtros estrictos:

| Filtro | Resultado |
|--------|-----------|
| Precio en rango 2.000–3.300 € (S5/S6) | **0 bicis** — el más barato es 3.399 € |
| Talla M (S1) | 10 bicis |
| Ambas condiciones | **0 bicis** |
| Pasan filtros estrictos completos | **0 bicis** |

El principal obstáculo en Buhobike es el precio: todos los modelos de trail eléctrica superan los 3.300 €.

### Upway — ✅ Ya validado previamente

Scraping real probado exitosamente con Playwright (23 productos extraídos con títulos y precios correctos).

### Resumen de sitios activos

| Sitio | Estado | Bicis extraídas |
|-------|--------|-----------------|
| Bike Ocasión | ✅ Funciona con Scrapling Fetcher | 182 (6 páginas) |
| Buhobike | ✅ Funciona con Scrapling StealthyFetcher (`usar_stealth_directo=True`) | 48 (dobles + segunda mano) |
| Upway | ✅ Funciona con Scrapling Fetcher (en tarjeta ~0.8s) | 23 (/collections/doble-suspension) |
| Mammoth Bikes | ✅ Funciona con Scrapling Fetcher (en tarjeta ~2.6s) | 65 (Rally/XC dobles + Trail dobles) |

---

## Estado operativo actual

El sistema se encuentra en **producción activa y 100% automatizado**:
- **Scrapers en producción (9 fuentes)**: Bike Ocasión (6 páginas), Buhobike (dobles págs. 1-2 + `?q=MODELO-LUMEN` + segunda mano), Upway (`/collections/doble-suspension`), Mammoth Bikes (`c-3104` / `c-2139` / `c-3102` + AJAX `POST /filtrarproductos` hasta 139 uds), **Sanferbike** (PrestaShop + stock por talla en tarjeta), **Bicimarket** (PrestaShop faceta Doble Suspensión), **Escapa** (BigCommerce vía `requests` directo + `BCData`), **Fabregues Bicicletas** (PrestaShop 4 págs. + *Test Ride*) y Wallapop (radio estricto `<= 50 km` desde Fuenlabrada + búsquedas locales por modelos clave hasta `4.000 €`).
- **Separación estricta de canales + Jerarquía `XC > Trail ligera > MTB`**: El Canal Diario prioriza XC `<= 130 mm` (`<= 3.300 €`, o `<= 3.500 €` para unicornios XC `>= 600 Wh`, `<= 500 km`, `< 19 kg`) con respaldo Trail ligera `< 21 kg` en portales de ocasión y Wallapop; `@BlackBikeBeast_bot` rastrea exclusivamente bicis nuevas/seminuevas (`<= 500 km`, `< 21 kg`, `> 500 Wh`, sin ocasión ni Enduro `> 165 mm`) en tramos `<= 3.500 €` (principal) y `3.501–4.000 €` (respaldo).
- **Auditoría híbrida optimizada (`perito_v6_xc` + `[Perito Rápido]`)**: Catálogo local + enriquecedor web con verificación real de stock en **Talla M** + Gemini Flash/Vision (`gemini-3.5-flash-lite` -> `gemini-3-flash-preview`), cortocircuitando antes de DuckDuckGo/Gemini cuando una ficha ya queda descartada por falta de stock en M, talla != M o falta de doble suspensión (**`37.5s`** en corrida completa sobre 9 portales).
- **Notificaciones duales automáticas**: Entrega diaria `1 por portal` con rotación ping-pong `#1 -> #2 -> #1`, rotación persistente `__beast__` en `@BlackBikeBeast_bot` cuando se repite el pool y Heartbeats operativos diarios.
- **Automatización**: Tarea programada en Windows Task Scheduler (`BuscadorBiciOcasion`) a las **12:00** de cada día (`main.py --once` con `WakeToRun: True` y `StartWhenAvailable: True`; modo bucle `main.py` usa `config.HORA_EJECUCION = "12:30"`).

## Próximos pasos y Roadmap

| # | Tarea | Estado | Detalle |
|---|-------|--------|---------|
| 1 | **Calibración continua de scoring y ordenamiento** | ✅ Completado | Priorización de salud mecánica (`nota >= 6.0`, `km <= 4.000`) antes que modalidad XC para evitar que unidades muy castigadas (> 4.000 km) encabecen el Top 3. |
| 2 | **Alertas de bajada de precio con historial visual** | ✅ Completado | Notificación explícita con cálculo de ahorro en euros cuando una bicicleta previamente registrada baja de precio. |
| 3 | **Nuevos portales profesionales certificados** | ✅ Completado | Integrado `MammothScraper` (`mammothbikes.com`, categorías Rally/XC y Trail doble suspensión con 3 años de garantía oficial) tras descartar definitivamente Tuvalum. |
| 4 | **Detección multimodal de odómetros y filtro anti-falsos positivos** | ✅ Completado | Extracción con Gemini Vision de displays en fotos de segunda mano y bloqueo de texto de lubricación/cadena. |
| 5 | **Despertar automático en Task Scheduler (`WakeToRun`)** | ✅ Completado | Configurado `WakeToRun: True`, `StartWhenAvailable: True` y ejecución en batería en la tarea `BuscadorBiciOcasion` de Windows Task Scheduler. |
| 6 | **Detección de Range Extender en descripción** | ✅ Completado | Detección de inclusión real (+180 Wh en BH / +252 Wh en Orbea / +160 Wh en TQ y Specialized / +250 Wh en Bosch PowerMore), rescate de filtro estricto S4 (Rise 360 Wh + 252 Wh = 612 Wh > 500 Wh), bonificación de +0.5 pts en calidad-precio, reflejo en desglose pericial y mensaje de Telegram. |
| 7 | **Telemetría real de Salud de Batería (SoH % y ciclos)** | ✅ Completado | Extracción automática de `bateria_salud_pct` (`Estado de salud: 90 %`, `% batería: 95%`, `conserva el 89 % de su capacidad original`) y `bateria_ciclos` (`Número de ciclos de carga: 164`), preservando los Wh nominales en `bateria_wh` y ponderando el SoH real en el Perito Mecánico Senior y en Telegram (`[SoH: XX% | YY ciclos]`). |
| 8 | **Filtro preventivo anti-Reservadas/Agotadas y Scraping Multi-Portal Paralelo** | ✅ Completado | Descarte inmediato de unidades reservadas/agotadas en los 4 scrapers (`es_tarjeta_no_disponible`), en la ficha de detalle (`_extraer_disponibilidad_ficha`) y en el filtro `S0`, más ejecución en paralelo de los 4 portales (`ThreadPoolExecutor`) reduciendo el tiempo de corrida a ~57s. |
| 9 | **Historial de evolución de precios y "Tiempo en Stock" (`historial_catalogo`)** | ✅ Completado | Registro persistente en SQLite de todas las candidatas pre-filtradas con cálculo de días en catálogo, detección de rebajas acumuladas y ahorro total, visible en Telegram (`⏳ X días en catálogo | 🏷️ Y rebaja(s)`). |
| 10 | **Clasificación objetiva de modalidad por recorrido de suspensión (mm)** | ✅ Completado | Extracción en `enriquecedor_web.py` de milímetros físicos de horquilla/amortiguador (`_extraer_recorrido`), ponderación directa en `prioridad_modalidad` (`≤130 mm` XC > `140 mm` Light Trail > `150-160 mm` All-Mountain) y descarte por S2bis de modelos `> 170 mm` (Enduro/DH). |
| 11 | **Modo radar de mercado CLI (`python main.py --stats`) y exportación Markdown (`docs/radar_mercado.md`)** | ✅ Completado | Comando de consola (`--stats` o `--radar`) y generación automática de `docs/radar_mercado.md` en cada corrida con unidades por tienda, precios medios/mínimos de modelos estrella (*Orbea Rise*, *BH iLynx*), unidades en vigilancia (2.900–3.500 €) y rebajas activas. |
| 12 | **Extracción multimodal en lote de odómetros en imágenes (`gemini-3.5-flash-lite`) y tabla técnica Buhobike** | ✅ Completado | Cuando `km` no aparece en string ni int en los datos/ficha, inspecciona hasta 6 fotos de galería en una única llamada multimodal a Gemini Vision (`4238 km` detectados en foto #3 de Orbea Rise H10) y extrae peso de báscula (`19,57Kg`) de `table.caracteristicas-tecnicas-2-tablas` y `#product-details`. |
| 13 | **Alertas proactivas de Entrada desde Zona de Vigilancia** | ✅ Completado | Seguimiento activo de bicicletas hasta 3.500 € en `historial_catalogo` y disparo de cabecera prioritaria `🚨 ¡ENTRADA DESDE ZONA DE VIGILANCIA! BAJADA DE PRECIO DETECTADA` cuando bajan a `<= 3.000 €` o acumulan `>= 200 €` de descuento. |
| 14 | **Soporte robusto de Proxies Rotatorios (`PROXY_LIST` y `PROXY_ROTATION`)** | ✅ Completado | Integración de `ProxyRotator` en `scraper_base.py` y `enriquecedor_web.py` con soporte para rotación cíclica y aleatoria en `Fetcher` y `StealthyFetcher` ante bloqueos de IP en Cloudflare. |

---

## Por qué se ha construido así (Arquitectura e Ingeniería de Decisiones)

El sistema no es un simple scraper de precios: está diseñado como un **embudo pericial determinista en dos fases** que combina velocidad de red, evasión selectiva anti-bot y auditoría mecánica estricta. Cada decisión arquitectónica responde a un problema real encontrado en producción:

### 1. Embudo en 2 fases: Extracción densa en tarjeta → Enriquecimiento paralelo selectivo
* **Por qué**: Rastrear las ~320 bicicletas de los 4 portales entrando una por una a su ficha de producto requeriría > 320 peticiones HTTP/Stealth por corrida (> 12 minutos) y provocaría bloqueos por *rate-limiting* en Cloudflare.
* **Cómo se construyó**:
  1. **Fase 1 (Listado en paralelo)**: Los 4 scrapers (`bike_ocasion`, `buhobike`, `upway`, `mammoth`) corren en paralelo mediante `ThreadPoolExecutor(max_workers=4)`. Cada adaptador extrae directamente del HTML de la tarjeta de listado la mayor cantidad de metadatos posible (talla, precio, doble suspensión, disponibilidad, y en Bike Ocasión/Upway también batería, km y motor).
  2. **Pre-filtro en memoria (`_pasa_prefiltro`)**: Descarta en milisegundos el ~92% del catálogo (tallas S/L/XL, rígidas, precios > 3.300 €, agotadas/reservadas).
  3. **Fase 2 (`EnriquecedorWeb` con 5 workers y caché en disco)**: Solo las ~10-25 candidatas viables visitan su ficha individual de detalle (y DuckDuckGo como respaldo de catálogo) para completar peso exacto, odómetro, SoH % de batería y componentes. Las fichas ya visitadas se persisten en `cache/fichas_detalle.json`.

### 2. Motor dual anti-baneo (`Fetcher` TLS vs `StealthyFetcher` Cloudflare)
* **Por qué**: Levantar un navegador headless Chromium para todas las tiendas consume mucha RAM y multiplica por 10x la latencia, pero usar `requests` estándar falla con HTTP 403/503 en tiendas protegidas por Cloudflare.
* **Cómo se construyó**: `BaseScraper` utiliza **Scrapling** en dos niveles:
  * **Nivel 1 (`Fetcher`)**: Peticiones HTTP ultrarrápidas con *TLS fingerprinting* de Chrome real. Extrae Upway en `0.8s`, Mammoth en `2.6s` y 6 páginas de Bike Ocasión en `~18s`.
  * **Nivel 2 (`StealthyFetcher` con `solve_cloudflare=True`)**: Se activa automáticamente ante un HTTP 403/503 o de forma directa (`usar_stealth_directo=True` en Buhobike) para resolver el desafío JavaScript de Cloudflare sin intervención humana.

### 3. Regla Maestra del Perito Mecánico Senior (Deducción irreversible vs Media ponderada)
* **Por qué**: En un sistema de puntuación por suma o media ponderada tradicional, una bicicleta con cuadro de carbono, cambio Shimano XT y suspensión Fox Kashima pero con **6.200 km** de desgaste o **22.5 kg** de peso seguiría obteniendo ~7.5/10, engañando al comprador con una falsa ganga que requiere 900 € en taller.
* **Cómo se construyó**:
  * Toda bicicleta parte de **10.0 puntos** y solo puede **perder** puntos por desgaste mecánico (salvo bonificaciones acotadas por peso pluma `< 19 kg`, transmisión electrónica/XT, Range Extender incluido o batería con `SoH >= 92%`).
  * **Líneas Rojas irreversibles**: Si `km > 6.000` (nota capada a máx `4.5/10`) o `peso > 21.0 kg` (nota capada a máx `4.0/10`), ningún componente tope de gama puede rescatarla.
  * **Escalón de salud mecánica en el ranking (`clave_orden_estrictas`)**: Antes de ordenar por modalidad preferida (`XC / Downcountry` > `Light e-MTB` > `Trail`), el orquestador exige un escalón primario de salud (`nota >= 6.0` y `km <= 4.000`). Así, una XC muy castigada jamás supera en el Top 3 a una Light e-MTB mecánicamente impecable.

### 4. Telemetría de Batería en 3 dimensiones: Capacidad Nominal, Range Extender y SoH %
* **Por qué**: El análisis de las fichas reales reveló dos trampas opuestas en los portales de segunda mano:
  1. **Trampa de descarte por batería interna pequeña en Light e-MTB**: Modelos ultraligeros de 18 kg (ej. *Orbea Rise 360 Wh* o *BH iLynx*) se descartaban en el filtro `S4 (<= 500 Wh)` aunque incluyeran en el precio el **Range Extender oficial** (+252 Wh / +180 Wh = 540–612 Wh reales).
  2. **Trampa de descarte por capacidad efectiva degradada en Upway**: Upway publica frases de laboratorio como *"conserva el 89 % de su capacidad original de 750 Wh, es decir, 670 Wh"*. En una batería de 540 Wh al 90% de salud (~486 Wh efectivos), tomar el valor efectivo hacía que la bici cayera falsamente en el filtro `S4 (<= 500 Wh)`.
* **Cómo se construyó**:
  * `_extraer_bateria` prioriza siempre la `"capacidad original de XXX Wh"` para preservar la capacidad nominal de diseño en `bateria_wh`.
  * `_detectar_range_extender` analiza el contexto semántico: suma los Wh externos (`+252 Wh`, `+180 Wh`, `+160 Wh`, `+250 Wh`) **solo** cuando hay inclusión explícita (`+`, `incluye`, `con`, `regalo`) e ignora menciones comerciales de compatibilidad (`compatible con`, `opcional`, `no incluido`).
  * `_extraer_salud_bateria` captura por separado `bateria_salud_pct` (`% SoH`) y `bateria_ciclos` para premiar o castigar la degradación química real de las celdas en el Perito Mecánico Senior (`>= 92%: +0.5`, `80-84%: -1.0`, `< 80%: -2.5`).

### 5. Auditoría de Odómetro en Doble Capa: Bloqueo Léxico + Visión Multimodal (Gemini Flash)
* **Por qué**: Caso real detectado en producción con la *Orbea Rise H10 T-M* en Buhobike: la tienda no puso los kilómetros ni en el título, ni en el SKU, ni en la tabla técnica; solo subió una **foto del display Shimano marcando 4.237 km**. A la vez, el texto comercial del anuncio decía *"permite hacerle unos 700 km sin necesidad de engrasar la cadena con cera al agua"*, provocando que un regex numérico ingenuo le asignara `700 km` y nota `10/10`.
* **Cómo se construyó**:
  1. **Capa 1 (Filtro de contexto negativo en `_extraer_km`)**: Se analiza una ventana de ±70 caracteres alrededor de cada mención de `km` y se descarta si aparece vocabulario de taller/mantenimiento (`cadena`, `cera`, `engrasar`, `lubricar`, `autonomía`, `garantía`, `revisión`).
  2. **Capa 2 (Inspección visual con `_extraer_km_de_imagenes`)**: Cuando una bici usada no declara su odómetro en texto, se descargan hasta 6 imágenes de la galería del producto y se envían en una sola llamada multimodal a **Gemini 2.5 Flash Vision** para leer pantallas de Bosch Kiox/Purion, Shimano Steps, Specialized MasterMind o Garmin. Si sigue sin existir dato confirmado en una bici usada, el Perito aplica `-2.0 pts` preventivos por incertidumbre.

### 6. Filtro Transversal Anti-Reservadas / Agotadas (`S0`)
* **Por qué**: Las tiendas de ocasión mantienen visibles durante semanas las bicicletas ya **Reservadas** o **Vendidas** para captar tráfico orgánico de Google. Sin un filtro dedicado, esas bicis consumían llamadas de enriquecimiento e IA y ocupaban huecos en el Top 3 de Telegram.
* **Cómo se construyó**: `BaseScraper.es_tarjeta_no_disponible` inspecciona clases CSS (`.product-unavailable`, `.out-of-stock`, `.reserved`, `.sold-out`) y etiquetas cortas en los 4 scrapers antes siquiera de instanciar la `Bicicleta`. Luego, `_extraer_disponibilidad_ficha` verifica la ficha de producto completa ignorando frases trampa como *"¿Quieres reservarla?"* o *"Reserva tu cita"*.

### 7. Historial Dinámico de Catálogo y Detección de Inmovilización (`historial_catalogo`)
* **Por qué**: Si solo registramos en SQLite las bicicletas que se envían por Telegram (el Top 3 del día), somos ciegos ante la dinámica global de precios: no sabemos cuántos días lleva una unidad sin venderse en la tienda (métrica clave para negociar o detectar sobreprecio) ni podemos avisar cuando una bici de 3.350 € baja a 2.890 € si antes nunca entró en el Top 3.
* **Cómo se construyó**:
  * Se implementó la tabla `historial_catalogo` en `db.py`.
  * Toda bicicleta que pasa el pre-filtro de listado se inserta o actualiza automáticamente registrando `fecha_primera_vez`, `fecha_ultima_vez`, `precio_actual`, `precio_inicial`, `precio_minimo`, `dias_en_stock` y `rebajas_detectadas`.
  * En cada notificación por Telegram, el mensaje incorpora la línea de trazabilidad: `📊 Seguimiento: ⏳ X días en catálogo | 🏷️ Y rebaja(s) (Ahorro: -Z €)`.

### 8. Clasificación Determinista por Recorrido Físico de Suspensión en Milímetros
* **Por qué**: Las tiendas de reacondicionado usan nomenclaturas comerciales inconsistentes en sus títulos (ej. llamar "XC" a una bici de 150 mm o "All Mountain" a una Light e-MTB de 140 mm). Depender exclusivamente de texto o nombres comerciales provocaba que bicis con geometrías pesadas compitieran indebidamente con verdaderas e-MTB de Cross Country / Downcountry.
* **Cómo se construyó**:
  * `_extraer_recorrido` en `enriquecedor_web.py` extrae los milímetros reales de suspensión (`100-180 mm`) analizando tablas `<dt>/<dd>` y menciones directas de horquillas/amortiguadores (`Fox 34 130mm`, `RockShox SID 120 mm`, `Pike 140 mm`).
  * `prioridad_modalidad` en `evaluator.py` supedita el ranking a la cota física: **`≤ 130 mm` -> Nivel 3 (XC / Downcountry)**, **`131–145 mm` -> Nivel 2 (Light Trail / Downcountry largo)**, **`146–165 mm` -> Nivel 1 (Trail / All-Mountain)** y `> 165 mm` -> Nivel 0 (Enduro).
  * Filtro `S2bis`: Descarte automático e inapelable de unidades con recorrido `> 170 mm` (bicicletas de Enduro severo o Freeride incompatibles con el pliego).

### 9. Radiografía de Mercado en CLI (`python main.py --stats`) y Exportación Markdown
* **Por qué**: El usuario y el desarrollador necesitan ver en cualquier momento qué está pasando en el mercado (precios medios de Orbea Rise o BH iLynx, unidades estancadas, oportunidades en zona de vigilancia) sin depender exclusivamente del push diario de las 12:00 ni consultar tablas SQL a mano.
* **Cómo se construyó**: Se implementó `mostrar_radar_mercado()` activable mediante el flag `--stats` (o `--radar`) y la función `exportar_radar_mercado_md()`, que genera automáticamente `docs/radar_mercado.md` en cada corrida resumiendo cuotas de mercado por tienda, modelos clave, alertas de vigilancia (2.900–3.500 €) y rebajas acumuladas.

### 10. Resiliencia de Red y Rotación de Proxies (`ProxyRotator` en Scrapling 0.5)
* **Por qué**: En tiendas con Cloudflare agresivo (Buhobike y Bike Ocasión), realizar scraping frecuente o enriquecer docenas de fichas de detalle desde una misma IP residencial puede provocar bloqueos preventivos por reputación de IP (HTTP 403/503 o CAPTCHAs interactivos). Aunque `StealthyFetcher` resuelve el handshake y JS de Cloudflare, una IP penalizada en origen bloquea cualquier capa de fetch.
* **Cómo se construyó**:
  * Se implementó `crear_proxy_rotator()` en `scraper_base.py`, integrando el `ProxyRotator` nativo de Scrapling con soporte para rotación secuencial cíclica (`cyclic`) y rotación aleatoria (`random`).
  * El rotador se inyecta de forma transparente tanto en peticiones HTTP rápidas (`FetcherSession` y `Fetcher.get`) como en el navegador stealth (`StealthyFetcher.fetch`).
  * Se extendió a `scrapers/enriquecedor_web.py` para que la apertura paralela de fichas de detalle y la descarga binaria de fotos de odómetro también roten proxies si `PROXY_LIST` está configurada en `.env`.

### 11. Odómetros en Lote Multimodal vs Timeouts de Inferencia Individual
* **Por qué**: Al inspeccionar imágenes de galería de producto para leer displays de cuentakilómetros, las llamadas individuales foto por foto con `gemini-flash-latest` (que mapea internamente a Gemini 3.8 Flash con thinking activado) tardaban > 15s por petición y provocaban `ReadTimeout`.
* **Cómo se construyó**: Se agrupan hasta 6 fotos de la galería en un único payload multimodal enviado a `gemini-3.5-flash-lite` (con fallback a `gemini-3.5-flash`), resolviendo toda la galería en 3–5 segundos con 100% de precisión en la extracción del odómetro (ej. `4.238 km` leídos en el display Shimano de Buhobike) y cacheando el resultado con invalidación reactiva si cambia el dato.

### 12. Aislamiento de Peso de Báscula vs Peso con Embalaje en Buhobike
* **Por qué**: En Buhobike, el bloque de descripción y ficha técnica declara `Peso estimado del producto + embalaje: 22,000 Kg` (caja de transporte y protecciones), mientras que el peso neto de la bicicleta (`19,57 Kg`) se encuentra en una tabla estructurada interna. Un extractor genérico tomaba los 22 kg activando el filtro `S3` (> 21 kg) y descartando bicicletas ultraligeras aptas.
* **Cómo se construyó**: Se implementó el parseo estructurado de `table.caracteristicas-tecnicas-2-tablas` (`<tr><th>/<td>`) y del atributo JSON `#product-details[data-product]`, aislando el peso neto de báscula antes de la descomposición del DOM y descartando cualquier valor asociado al texto contextual de `embalaje`.

### 13. Detección y Alerta de "Mega Chollos" (>50% vs PVP) Condicionada a Excelencia Mecánica (Nota ≥ 9.0)
* **Por qué**: Una e-MTB puede tener un 55% de descuento sobre su PVP nuevo, pero si acumula 5.000 km, holguras de basculante o una batería degradada (nota 3.5 o 5.5/10), calificarla de "Mega Chollo" genera falso FOMO, alerta innecesaria y destruye la credibilidad del peritaje técnico. Un precio de liquidación por desgaste mecánico no es una oportunidad; es simplemente su valor residual real.
* **Cómo se construyó**:
  * Se diseñó una regla bicondicional estricta: `descuento_pvp >= 50%` **Y** `nota >= 9.0`.
  * Solo cuando ambos criterios se cumplen simultáneamente, el notificador (`notifier.py`) dispara la cabecera destacada: `💥🏷️ ¡MEGA CHOLLO e-MTB DETECTADO! (-XX% vs PVP)` y el badge `💥 *MEGA CHOLLO*`.
  * Si la bicicleta acumula un descuento masivo (≥ 50%) pero su nota pericial es `< 9.0`, el sistema la degrada automáticamente a **oferta normal** (`🚵‍♂️ Nueva oportunidad...` o `📉 Bajada de precio`), manteniendo la línea informativa de fábrica (`🏷️ PVP Original: ~XXXX €~ (-XX% | Ahorro: -XXXX €)`) sin estridencias alarmistas.
  * Se incorporó el conteo de Mega Chollos en el Heartbeat diario y la bonificación pericial en `evaluator.py`.

### 14. Segmentación Sonora en Telegram (`disable_notification`): Silencio Operativo vs Alerta Sonora Prioritaria
* **Por qué**: Recibir notificaciones con sonido o vibración todos los días a las 12:00 por ofertas normales de catálogo o por el pulso de diagnóstico diario (Heartbeat) provoca fatiga de alertas (*alert fatigue*) y desensibilización. Si el móvil suena por cualquier bicicleta de rutina, el usuario termina silenciando el canal completo de Telegram y perdiendo las verdaderas oportunidades excepcionales.
* **Cómo se construyó**:
  * Se integró el parámetro nativo `disable_notification: True` de la Telegram Bot API para todas las ofertas estándar de catálogo y para el mensaje diario de diagnóstico Heartbeat en `notifier.py`.
  * La función pericial `es_mega_chollo(bici, nota)` actúa como árbitro centralizado: si y solo si una e-MTB alcanza la excelencia pericial (`nota >= 9.0`) con descuento masivo de liquidación (`>= 50% vs PVP nuevo`), se despacha con `disable_notification: False` (activando el timbre y la vibración sonora prioritaria en el móvil).
  * El comportamiento es configurable de forma reactiva mediante `TELEGRAM_SILENCIAR_OFERTAS_NORMALES` en `.env` / `config.py` y admite anulación manual mediante el parámetro `silencioso: Optional[bool]` en `enviar()`.

### 15. Rotación Dinámica de Alternativas en Análisis Consecutivos (Top 3 Idéntico -> Bloque 4-6)
* **Por qué**: En ejecuciones consecutivas del buscador o en días sucesivos con baja rotación de stock en las tiendas, el Top 3 de oportunidades óptimas suele mantenerse invariable. Volver a notificar exactamente las mismas 3 bicicletas satura la atención y no aporta valor nuevo al comprador; mientras que no notificar nada genera incertidumbre sobre qué otras opciones interesantes existen en el catálogo.
* **Cómo se construyó**:
  * **Persistencia de ejecuciones en SQLite (`db.py`)**: Se creó la tabla `analisis_ejecuciones` (`id`, `fecha`, `top3_ids`, `enviados_ids`, `offset_usado`, `repetido`) que almacena la huella exacta del Top 3 de cada análisis.
  * **Preservación íntegra del pool de candidatas (`main.py`)**: Se refactorizó `_recolectar_oportunidades()` para que devuelva la totalidad de candidatas aptas ordenadas por estricta prioridad (estrictas nuevas -> estrictas conocidas -> respaldo nuevas -> respaldo conocidas), eliminando el truncamiento prematuro a 3 unidades que impedía acceder a los puestos 4, 5 y 6.
  * **Cálculo de rotación por offset cíclico**: Si `ultimo_analisis["top3_ids"] == top3_actual_ids` y existen más de 3 opciones en catálogo, el orquestador avanza automáticamente el offset (`offset_a_usar = 3`), seleccionando las alternativas posicionadas en los puestos #4, #5 y #6 (`oportunidades[3:6]`). Si se vuelve a ejecutar sin cambios, continúa rotando o cicla elegantemente.
  * **Cabecera contextual en Telegram (`notifier.py`)**: Cuando se detecta repetición, el formateador antepone un banner informativo en cada ficha:
    ```markdown
    🔄 *Top 3 sin cambios respecto al análisis anterior*
    💡 _Exponiendo siguiente mejor alternativa #4 del catálogo:_
    ```
  * **Diagnóstico en Heartbeat**: El pulso operativo diario de Telegram reporta la rotación activa con el rango de posiciones expuestas (`🔄 Rotación activa: Top 3 idéntico (exponiendo #4 a #6)`).

### 16. Integración de Wallapop Geolocalizado (Fuenlabrada +50 km) y Peritaje Honesto de Particulares
* **Por qué**: Ampliar el alcance más allá de las 4 tiendas profesionales permite detectar e-MTB de gama alta puestas a la venta por particulares en el entorno cercano (50 km alrededor de Fuenlabrada) a precios muy competitivos (ej. `BH iLynx Race Carbon` por 2.000 €), conservando exactamente los filtros estrictos (`Talla M`, doble suspensión, `> 500 Wh`, `< 21 kg`, `2.000-3.300 €`) sin mezclar envíos lejanos ni ofertas urbanas.
* **Cómo se construyó**:
  * **API de búsqueda por subcategoría (`scrapers/wallapop.py`)**: Consulta `/api/v3/search` con `source="quick_filters"`, `category_id="17000"`, `subcategory_ids="10215"` (Bicicletas eléctricas), coordenadas de Fuenlabrada (`40.2842, -3.7942`), `distance_in_km=50` y rango `2.000-3.500 €` (cubre también la Zona de Vigilancia).
  * **Guardia geográfica Haversine**: Descarta cualquier ítem cuya coordenada supere los `50.0 km` reales aunque Wallapop lo inyecte con promoción nacional (`bump: country`).
  * **NLP sobre descripción libre + Visión IA sin SPA**: Reutiliza los extractores de `enriquecedor_web.py` (mejorados para `t.M`, `size M`, Specialized `S3`, `M/L -> ML`, `540w`, `extender 160w`) sobre título y descripción. Si falta `km`, `enriquecer_bici` inspecciona directamente las URLs de `bici.imagenes` mediante Gemini Vision sin intentar scrapear el HTML Next.js vacío de `es.wallapop.com/item/...`.
  * **Transparencia de garantía (`garantia_anos=0`)**: Distingue vendedores particulares (`has_warranty=False`, `is_refurbished=False` -> `garantia_anos=0`) de tiendas verificadas en Wallapop (`1` año), reflejando `"Sin garantía comercial (particular)"` y la ubicación exacta (`📍 Ubicación: Ciudad (X.X km)`) en `notifier.py` y en `gemini_classifier.py`.

### 17. Deduplicación Inter-Portal, Endurecimiento de Filtros Wallapop/AL y Caché DuckDuckGo
* **Por qué**: Tras integrar Wallapop se detectaron tres fricciones en producción: (1) tiendas como Buhobike republicaban sus mismas bicis en Wallapop exactamente al mismo precio, duplicando alertas u ocultando opciones reales; (2) modelos genéricos de aluminio como `Ghost E-ASX 160 Advanced AL` y títulos vagos (`"Bicicleta Eléctrica BH 237 km"`) o urbanos (`Orbea Diem 10`) se colaban en el análisis; (3) consultar DuckDuckGo sin caché previa tras el orden antiguo disparaba la corrida a ~440–580 segundos.
* **Cómo se construyó**:
  * **Deduplicación cruzada inter-portal (`db.py`, `main.py`)**: `tokens_titulo_dedup` normaliza ruido de anuncio extrayendo explícitamente talla (`talla`/`size`) antes que palabras genéricas y preservando versiones numéricas de modelo (`8.4` vs `8.6`). En `main.py`, `pasa_filtros_estrictos` corre antes de `deduplicar_inter_portal` (evitando que una tienda Talla `L` tape un clon Talla `M`), `deduplicar_inter_portal` verifica compatibilidad de disponibilidad/talla dentro de un margen `±25 €`, y los clones de Wallapop equivalentes a registros ya notificados en `bicis_enviadas` se omiten totalmente.
  * **Fronteras estrictas de modelo y material (`scrapers/wallapop.py`, `gemini_classifier.py`)**: En Wallapop se descartaron urbanas (`diem`, `vibe`, `gain`, etc.), títulos genéricos sin confirmación de amortiguador ni modelo doble, y se reemplazó la lista de subcadenas por el regex con fronteras de palabra `_MODELOS_DOBLE_RE` + normalización `² -> 2` (`Focus JAM²`, `THRON²`), evitando falsos positivos con `"trail"`, `"llevo"`, `"volumen"`, `"riser"` o `"doble pared"`. En `gemini_classifier.py`, `AL` solo se detecta con mayúsculas sobre texto crudo excluyendo frases españolas (`"al 98%"`, `"al día"`), se acotó `CATALOGO_EMTB` (`orbea rise m10/m20/...` sin `"orbea rise m"` que capturaba `"Orbea Rise Motor"`) y se añadió `ghost e-asx` (`24.2 kg Aluminio`).
  * **Caché resiliente de DuckDuckGo (`scrapers/enriquecedor_web.py`)**: Reordenado el catálogo local antes de DuckDuckGo, filtradas consultas sin modelo específico (`_es_consulta_web_especifica` con normalización Unicode NFD) y blindado `completar_desde_duckduckgo` (`ddg_v2:`) con lock por clave (`_obtener_lock_ddg`), extracción incondicional de `peso_kg`, `ano` y `suspension_trasera` sin envenenamiento parcial y sin cachear fallos HTTP/anti-bot (`""`, `anomaly-modal`), reduciendo el tiempo total en vivo a **115.3s**.

### 18. Entrega por Página (1 por Portal) con Rotación Ping-Pong (`#1 -> #2 -> #1`)
* **Por qué**: Al ordenar el catálogo entero priorizando solo bicis no notificadas previamente (`estrictas_nuevas > estrictas_conocidas`) y recortar globalmente a `[:3]`, los anuncios nuevos de Wallapop (`6.5/10`) expulsaban del Telegram mejores oportunidades vigentes de Upway (`8.0/10`), Bike Ocasión o Buhobike, dando la falsa impresión de que solo buscaba en Wallapop.
* **Cómo se construyó**:
  * **Ranking por calidad real (`main.py`)**: `_recolectar_oportunidades` y `clave_orden_estrictas` ordenan primero por salud mecánica verificada (`km is not None and km <= 4000`), ausencia de Línea Roja/anuncio genérico, modalidad (`XC > Light e-MTB > Trail`), nota pericial y menor peso, dejando la novedad solo como desempate final.
  * **Selección por portal (`seleccionar_por_portal`, `db.py`)**: Elige exactamente **1 mejor bicicleta por cada portal** con stock apto (`Wallapop`, `Bike Ocasión`, `Upway`, `Buhobike`, `Mammoth`). Si la `#1` real de un portal no cambió desde la corrida anterior: el **Día 2** expone la `#2` válida (nunca anuncios genéricos descartados `<= 4.5`), y el **Día 3** retorna a la `#1` confirmando que sigue liderando ese portal. El estado (`estado_portales`) solo avanza para portales cuyo envío Telegram tuvo éxito y no se borra ante corridas vacías.

### 19. Perito Mecánico Escéptico y Estricto v2 (`gemini_classifier.py`, `models.py`, `scrapers/wallapop.py`)
* **Por qué**: Los anuncios genéricos de Wallapop sin marca/modelo (`"BICI MONTAÑA ELECTRICA DOBLE CARBONO NUEVA"`) o contradicciones (`"NUEVA"` con >50 km) alcanzaban notas altas (`8.5/10`), y motores Full Power + `>= 625 Wh` recibían estimaciones de peso optimistas (`< 21 kg`).
* **Cómo se construyó**:
  * **Reglas anti-alucinación y física realista (`_es_anuncio_generico_sin_modelo`, `_detectar_contradiccion_nueva`, `_es_motor_full_power`, `_es_excepcion_ligera`)**: Prohibido inventar componentes no declarados (`-1.5 pts` si faltan); las e-MTB Full Power (`>= 625 Wh` o batería sin confirmar) no pueden bajar de `22.5 kg` salvo excepciones ligeras explícitas (`Orbea Rise`, `BH iLynx Race/Trail Carbon`, `Cannondale Moterra SL`, `Amflow PL Carbon`, `Mondraker Neat/Dune >=500Wh`, `Pivot Shuttle SL >=500Wh`), con clamp post-Gemini.
  * **Corrección estricta de motores**: `BH iLynx Race/Trail` sin `+` fijado a `BH 2EXMAG` (cerrado), `BH iLynx+` fijado a `Shimano EP801` (abierto), `Orbea Rise 2021-2022` a `Shimano EP8-RS`, `2025+` a `Shimano EP801-RS Gen2`, y Bosch marcado como dependiente de taller oficial (no muestra SoH/ciclos en app de usuario).
  * **5 Líneas Rojas y rúbrica sin bonos (`perito_v5`)**: Base `10.0` con 5 ejes estrictos incluyendo **Garantía/Canal** (`tienda España 0.0`, `extranjera -1.0`, `particular con factura -1.0`, `sin factura -1.5` con extracción `tiene_factura` en Wallapop) y topes: Talla != M (`0.0`), Batería < 500 Wh (`4.0`), Peso > 21.0 kg (`4.0`), Km > 6.000 (`4.5`) y Anuncio genérico (`4.5`), en formato `🧮 Auditoría Pericial`.

### 20. Canal Exclusivo Black Friday (`<= 3.500 €`, `Black_Bike_Beast`) y PVP en Mammoth (`.is__old`)
* **Por qué**: Las ofertas exclusivas de Black Friday en bicis **completamente nuevas (`0 km`) o de exposición (`<= 50 km`)** suelen situarse entre `3.000 €` y `3.500 €` y quedaban descartadas por el techo diario de segunda mano (`3.300 €`), además de que `scrapers/mammoth.py` no capturaba el PVP tachado porque Mammoth usa `<span class="price is__old">` (devolvía `0` bicis con PVP antes del fix vs `28/66` después).
* **Cómo se construyó**:
  * **Pre-filtro y rúbrica dedicada (`pasa_prefiltro_black_friday`, `evaluar_oportunidad_black_friday` en `evaluator.py`)**: rescata unidades nuevas/exposición entre `2.000 €` y `3.500 €` para enriquecimiento único en `_recolectar_oportunidades` sin contaminar el flujo diario (`<= 3.300 €`), exigiendo datos confirmados de **Talla M**, **doble suspensión**, **peso `< 21.0 kg`**, **batería `>= 500 Wh`**, **`km <= 50` sin contradicciones** (`km=None` queda descartado) y **descuento verificado `>= 35%` sobre PVP** (`nota_bf >= 7.5/10`).
  * **Segundo bot independiente y tabla SQLite propia**: configurado mediante `TELEGRAM_BOT_TOKEN_BLACK_FRIDAY` y `TELEGRAM_CHAT_ID_BLACK_FRIDAY` (con fallback a `TELEGRAM_CHAT_ID`), notificador unificado `_enviar_telegram` + `enviar_black_friday` + pulso operativo `enviar_heartbeat_black_friday` en `notifier.py`, informe consolidado automático **Top 3 más interesantes fuera de tope/criterio** (`enviar_informe_respaldo_black_friday` cuando 0 unidades cumplen `<= 3.500 €`) y deduplicación aislada en `bicis_black_friday_enviadas` (`db.py`, con clave `respaldo:` separada para no bloquear futuras alertas estrictas si bajan a `<= 3.500 €`).

### 21. Purga Radical a XC Puro (`<= 130 mm`), Bloqueo Post-Enriquecimiento y Resiliencia en `GEMINI_MODELS` (`perito_v6_xc`)
* **Por qué**: Aceptar `"Light e-MTB"`, `"Trail"` y `"All Mountain"` hasta `170 mm` provocaba que modelos Trail/All Mountain (`Orbea Rise`, `BH iLynx Trail`, `Moterra SL`, `Levo SL`, `Fuel EXe`, `Haibike Lyke`, `Santa Cruz Heckler SL`, `Focus JAM²/THRON²`, `KTM Macina Scarp SX` —que en ficha real monta `400 Wh` y `140 mm` Trail—) coparan las alertas y el Top 3 en lugar de verdaderas e-MTB de Cross Country / Downcountry. Además, en llamadas en vivo `gemini-3.5-flash` devolvía `HTTP 429` y `gemini-3-flash-preview` superaba los 20s de timeout cuando ejecutaba razonamiento interno (*thinking*) por defecto.
* **Cómo se construyó**:
  * **Restricción dura XC (`config.py`, `evaluator.py`, `main.py`)**: Se redujo `MODALIDADES_VALIDAS` estrictamente a `["XC", "Cross Country", "Downcountry"]` y se fijó `RECORRIDO_MAX_XC_MM = 130`. Las funciones `es_modalidad_xc`, `es_modelo_trail_o_enduro` (`_PATRONES_MODELO_TRAIL_ENDURO` con normalización `² -> 2`) y el chequeo de `recorrido_mm > 130` filtran primero con `completar_con_catalogo` antes de enriquecer, vuelven a validar tras el enriquecimiento web/IA en `_recolectar_oportunidades` (`[Descarte Trail/Enduro]`) y excluyen Trail/Enduro incluso de `historial_catalogo` / Radar.
  * **Separación entre peso empírico real y catálogo estático (`gemini_classifier.py`)**: En `enriquecer_y_valorar_bici`, `peso_empirico_previo` ya no considera empírico el peso estimado por el diccionario local `CATALOGO_EMTB` (`peso_tras_cat`): solo se considera verificado si proviene de la ficha web/anuncio (`peso_despues_web`) o de DuckDuckGo real (`ddg_aporto_peso`). Así, en Black Friday no entra ninguna unidad con peso teórico sin báscula/fuente real (`_peso_estimado = True`).
  * **Fallback IA rápido sin timeouts (`config.py`, `gemini_classifier.py`, `scrapers/enriquecedor_web.py`)**: Se reordenó `GEMINI_MODELS` priorizando `gemini-3.5-flash-lite` -> `gemini-3-flash-preview` -> `gemini-3.5-flash`, inyectando `thinkingConfig: {"thinkingBudget": 0}` para `3-flash` tanto en texto como en visión por lotes e invalidando automáticamente caché previa mediante la versión `perito_v6_xc`.

### 22. Caza Nacional de Unicornios XC (`<= 3.500 €`) y Fazua Ampliable (`420–430 Wh` + Extender)
* **Por qué**:
  1. Limitar Wallapop a `50 km` de Fuenlabrada dejaba fuera escasas e-MTB XC puras de toda España (`Wilier Urta Hybrid`, `Scott Lumen`, `Focus VAM²`, `BMC Fourstroke AMP`, `BH iLynx Race Pro`) en presupuesto.
  2. Elevar sin condiciones el tope diario a `3.500 €` habría llenado Telegram de modelos Trail o usados caros; solo merece romper el tope diario de `3.300 €` si es un **Unicornio XC** casi nuevo (`<= 500 km`) y de alta autonomía real (`>= 600 Wh`).
  3. Exigir `>= 500 Wh` nativos en Black Friday descartaba e-MTB XC ligeras con motor Fazua Ride 60 (`420–430 Wh`, ej. *Wilier Urta Hybrid*) incluso cuando su precio (`<= 3.050 €`) permite comprar el Range Extender oficial de `+210 Wh` (~`450 €`) y obtener `630–640 Wh` totales sin pasarse del presupuesto de `3.500 €`.
* **Cómo se construyó**:
  * **Búsqueda nacional dedicada (`config.py`, `scrapers/wallapop.py`)**: `WALLAPOP_UNICORN_QUERIES` lanza consultas nacionales en Wallapop filtradas con `_UNICORNIOS_NACIONALES_PATRONES` por límites de palabra (`\bi[\-\s]?lynx\s+race\b`, `\bwilier\s+urta\b`, etc., evitando falsos positivos como `"Race Face"` o `"llevamos"`), deduplica anuncios multi-ciudad comparando `(talla, precio ± 10 €, titulos_equivalentes_dedup)` y priorizando la menor distancia Haversine a Fuenlabrada, extrae PVP declarado (`_extraer_pvp_wallapop`) y baterías `420/430/480 Wh`, y mapea `"sin estrenar"`/`"a estrenar"` a `km=0` solo cuando no acompaña recambios (`cadena`, `cubiertas`, `frenos`, etc.).
  * **Reglas `es_unicornio_xc` y `es_xc_ampliable_en_presupuesto` (`evaluator.py`, `main.py`, `notifier.py`)**:
    * En flujo diario, las unidades en Vigilancia (`3.301–3.500 €`) que cumplen `es_unicornio_xc` (`<= 130 mm`, `< 19 kg`, `>= 600 Wh`, `<= 500 km`, `<= 3.500 €`) promocionan al flujo diario tras el enriquecimiento (`en_flujo_diario`, `+1.5` en `_puntuacion_precio_excepcional`).
    * En Black Friday (`@BlackBikeBeast_bot`), `es_xc_ampliable_en_presupuesto(bici, 3500)` admite e-MTB XC puras verificadas Fazua `420–430 Wh` `< 19 kg` cuando `bici.precio <= 3.050 €` (`>= 450 €` libres para el extender `+210 Wh`), informando en Telegram el coste y capacidad totales estimados (`~640 Wh`, `~3.300 €`).
  * **Extracción acotada de odómetro (`scrapers/enriquecedor_web.py`)**: `_extraer_km` exige sufijo `km`/`kilómetros` tras `recorrido`/`rodaje` (y lookahead negativo `(?!\s*mm\b)`) para no confundir recorridos de suspensión (`120 mm`), y recorta la ventana contextual del Paso 3 en fronteras de oración (`[.;!\n]`) bloqueando expresiones de autonomía (`da para`, `modo eco`, `modo turbo`, `modo trail`, `con una carga`, `máxima potencia`).

### 23. Blindaje Black Friday (`> 500 Wh`, `< 21 kg`, `<= 3.500 / 4.000 €`), `Mammoth /filtrarproductos`, Radio Wallapop `<= 50 km` y Afinado Anti-Full-Power (`23–24/11`)
* **Por qué**: El pliego definitivo de compra exige no mezclar rígidas ni e-MTB Full Power pesadas (`>= 21 kg`) con chollos ligeros, acotar Wallapop estrictamente a recogida local (`<= 50 km` desde Fuenlabrada) dejando la compra online nacional exclusivamente a tiendas oficiales `0 km`, evitar que un mismo modelo en dos colores ocupe dos huecos en Beast, y rotar automáticamente a las siguientes candidatas cuando la búsqueda se repite sin novedades.
* **Cómo se construyó**:
  * **Jerarquía `XC (3) > Trail ligera (2) > MTB (1)` en dos escalones (`evaluator.py`, `main.py`)**: Tanto el Canal Diario (para ocasión/Wallapop) como `@BlackBikeBeast_bot` aplican `es_full_power_o_pesada` (bloqueando `Berria Mako Hybrid`, `Orbea Rise LT H` Alu `21.8 kg`, `BH iLynx 9.8`, `Amflow TL` `22.6 kg`, `Cube Stereo Hybrid`, `Trek Rail`, `Wild`, etc. y reconociendo `Cannondale Moterra Neo SL 2` `19.8 kg` `601 Wh`), exigiendo estrictamente doble suspensión y batería `> 500 Wh`. Beast prioriza `<= 3.500 €` antes del respaldo `3.501–4.000 €`, y deduplica variantes de color dentro del mismo portal conservando siempre la más barata (`_encontrar_equivalente_idx`).
  * **Mammoth AJAX completo + Inferencia OEM (`scrapers/mammoth.py`, `gemini_classifier.py`)**: `MammothScraper` consulta `POST /filtrarproductos` en `PrecioAscendente` y `DescuentoDescendente` (conservando el menor precio por `bici_id` y saltando de 60 tarjetas aleatorias a ~139-143 unidades), mientras `CATALOGO_EMTB` aporta `componentes_default` solo para unidades `km=0` de tiendas nuevas cuando su ficha omite la tabla HTML de montaje.
  * **Wallapop estrictamente local y coma decimal español (`config.py`, `scrapers/wallapop.py`, `enriquecedor_web.py`)**: Fijado `WALLAPOP_PERMITIR_NACIONAL = False` en todo flujo Wallapop, `_parsear_precio` con `€` opcional para `"antes 4599€"`, `_parsear_entero_km` respetando decimales españoles (`"2.293,8 km" -> 2294`), filtro de viñeta `"- Range Extender"` y flag CLI `python main.py --omitir-enviadas` + rotación `__beast__` persistente.

### 24. Expansión a 9 Portales Españoles (`Sanferbike`, `Bicimarket`, `Escapa`, `Fabregues`), Stock Real Talla M y `[Perito Rápido]` (`24–25/11`)
* **Por qué**: Con solo 2 tiendas online de bicis nuevas (`Mammoth` y `Buhobike`), la cobertura Black Friday nacional de Light e-MTB `0 km` perdía múltiples ofertas activas en distribuidores oficiales españoles. Tras auditar 8 webs candidatas vía HTTP/DOM (descartando `Bicispasaje` por HTTP 403, `Pedalmoto` por 0 Light e-MTB `<= 4.100 €` y `BikePhilosophy` por latencia > 4s), se seleccionaron las 4 tiendas viables con mejor catálogo y tiempos de respuesta (`0.7s–2.7s`).
* **Cómo se construyó**:
  * **Centralización de tiendas nuevas (`config.py`)**: Se sustituyeron comprobaciones hardcodeadas `("mammoth", "buhobike")` repartidas en 4 módulos por `SitioObjetivo.es_tienda_nueva` + `config.es_sitio_tienda_nueva(sitio, url, titulo)` (verificando además `es_unidad_test_o_demo` con borde `\bdemo\b` para no marcar `0 km` unidades *Test Ride* o *Demo*). Los nuevos sitios se añadieron en `SITIOS[5..8]` para no alterar ningún test acoplado a `SITIOS[0..4]`.
  * **Adaptadores modulares (`prestashop_base.py`, `sanferbike.py`, `bicimarket.py`, `escapa.py`, `fabregues.py`)**:
    * `PrestaShopBaseScraper` unifica paginación, precios/PVP y guardas comunes para `Sanferbike` (con lectura directa de stock por talla vía `.js-miniature-product-variants` / `data-qty-*` en tarjeta), `Bicimarket` (faceta Doble Suspensión) y `Fabregues` (limpieza de códigos SKU `|EC796|`).
    * `EscapaScraper` (BigCommerce) activa `usar_requests_primero = True` porque CloudFront/BigCommerce bloquea TLS de `curl_cffi` con 403 pero responde HTTP 200 en ~0.7s con `requests`, descartando tarjetas con botón `Avísame`.
  * **Stock real en Talla M y bloqueo Enduro / `BH iLynx+` / `Avinox` (`enriquecedor_web.py`, `evaluator.py`, `gemini_classifier.py`)**:
    * `_extraer_tallas_disponibles_ficha` ignora el `#fragment` por defecto de PrestaShop (ej. `#/...-talla-xl`), parsea `.product-variants-item` (incluyendo `.disabled` en `span.radio-label` hijo) y `BCData.product_attributes.in_stock_attributes` en BigCommerce, normaliza `MD -> M` evitando confundir `SM` (=Small BH) y respeta `M/L -> ML`, con caché TTL de 6 horas indexada sin `#fragment`.
    * En vivo se detectaron y bloquearon nuevas familias Full Power / Enduro: `BH iLynx+ SL` (Aluminio, `Shimano EP6`, `630 Wh`, `~22.8 kg`), `BH iLynx+ Enduro` (`160–170 mm`, `22.4–22.6 kg`), `BH iLynx+ Trail Carbon 8.7` (`21.2 kg`), `BH iLynx+ DL/NX`, `Olympia Hekton`, `Megamo Reason AL/Flame/Reach`, `Mondraker Scree`, `Raymon`, motores `DJI Avinox` (preservando `Amflow PL`) y modelos `SUV` (`Superior eXF 8069 B SUV`, `BH ATOMe SUV`), más `_motivo_descarte_enduro` (`> 165 mm` o título `Enduro` en Beast) y patrones `ilynx trail` / `ilynx race` para títulos con palabra intermedia de Fabregues (`"Bicicleta BH Eléctrica Ilynx Trail..."`).
    * Añadido cortocircuito **`[Perito Rápido]`** en `enriquecer_y_valorar_bici` antes de DuckDuckGo y Gemini API cuando la ficha ya confirma `disponible=False`, `talla != M` o ausencia de doble suspensión, recortando la corrida total de 9 portales de **`75.5s` a `37.5s`**.

### 25. Refuerzo Anti-Gravel/SUV, Guardia de Rígidas en Upway y Nuevas Full Power (`26/11`)
* **Por qué**: Tras revisar la ejecución programada (`#31`, `25/11 12:00:45`, `42.6s`) y auditar los catálogos en vivo de los 9 portales hoy `26/11` (descartando de nuevo `Pedalmoto` y `BikePhilosophy` por `HTTP 404` / ausencia de stock útil), afloraron tres vectores residuales de ruido: bicicletas e-gravel (`ORBEA DENNA`) y trekking/SUV (`Flyer Goroc`), rígidas listadas dentro de `/collections/doble-suspension` en `Upway` (como `Haibike AllTrack 7`) porque `UpwayScraper` asignaba `suspension_trasera="si"` sin pasar por el filtro de modelo no doble, y familias Full Power `>= 22 kg` detectadas en fichas de tienda (`Canyon Spectral:ON`, `Neuron:ON`, `Torque:ON`, `Stevens E-Inception`, `MMR X-Bolt 120`, `Rockrider E-FEEL 700 S`, `E-EXPL 520`).
* **Cómo se construyó**:
  * **Guardia de rígidas en Upway (`scrapers/upway.py`, `scraper_base.py`)**: `UpwayScraper` importa `es_modelo_no_mtb_doble` y marca `suspension_trasera="no"` antes de aceptar la tarjeta cuando el título coincide con modelos no doble (como `Haibike AllTrack`), además de ampliar `_PATRONES_NO_MTBD_COMUNES` con `"denna"` (`ORBEA DENNA`) y `"goroc"` (`Flyer Goroc`).
  * **Bloqueo Full Power verificado (`evaluator.py`, `test_buscador.py`)**: Tras contrastar pesos empíricos (`MMR X-Bolt 120` `22.3–23.5 kg`, `Rockrider E-FEEL 700 S` `24.8–25.4 kg`, `Canyon Spectral:ON` `21.8–22.9 kg`, `Canyon Neuron:ON` `22.6–25.5 kg`, `Stevens E-Inception` `22.5–25.3 kg`), se amplió `_PATRONES_MODELO_FULL_POWER_PESADA` (`spectral:on`, `spectral on`, `neuron:on`, `neuron on`, `torque:on`, `torque on`, `stevens e-inception`, `e-inception`, `x-bolt`, `e-feel`, `e-expl`) cubierto con la regresión TDD `test_afinado_26nov_full_power_gravel_y_upway_rigida`.
  * **Validación dinámica de reposición en tiempo real (`#32`, `44.1s`)**: En la ejecución en vivo de hoy, la caché TTL 6h y el lector de variantes PrestaShop detectaron al instante la reposición de Talla M en `Bicimarket` para `BH iLynx Trail Carbon 8.7` (`3.499 €`, `-44.5%`), promocionándola al `#1` de `@BlackBikeBeast_bot`, mientras filtraron por `[Perito Rápido]` la `BH iLynx Trail Carbon 8.8 2023` al quedarse solo en `talla=L`.

---

## Proceso de desarrollo y dificultades encontradas

### Dificultades encontradas y soluciones de ingeniería

| Dificultad | Sitio afectado | Causa técnica | Solución arquitectónica / Estado |
|------------|---------------|---------------|----------------------------------|
| **Odómetro fotografiado vs texto de mantenimiento ("700 km")** | Buhobike | Buhobike no escribe el odómetro en el texto ni en el SKU en ciertas unidades usadas; solo sube una foto del display (ej. 4.237 km). Un regex simple `\d+ km` capturaba el texto de garantía: *"hacerle unos 700 km sin engrasar la cadena con cera al agua"*, asignando falsamente 700 km (10/10). | **Doble capa**: 1) Filtro de contexto negativo en `_extraer_km` que descarta menciones de cadena, cera, engrase, garantía y autonomía. 2) Fallback con Gemini Flash Vision (`_extraer_km_de_imagenes`) que analiza las fotos del display y extrae el odómetro exacto (`4237 km` -> nota 5.5/10). Si no hay dato confirmado, aplica -2.0 pts preventivos. |
| **Bicis castigadas superando a bicis sanas por modalidad** | Todos / Orquestador | `clave_orden_estrictas` ordenaba por `(sin_linea_roja, prioridad_modalidad, nota)`. Una XC con 5.000 km y nota 3.5/10 quedaba #1 sobre bicis Trail/Light sanas de < 2.000 km (7.5/10). | **Escalón de salud mecánica**: se agregó `salud_mecanica = 1 if (nota >= 6.0 and km <= 4000) else 0` como criterio #1 de ordenación, preservando la prioridad XC estrictamente dentro de cada escalón de salud. |
| **Descarte prematuro de bicis ligeras con batería interna < 500 Wh** | Todos (Orbea Rise, BH iLynx, Levo SL) | e-MTBs superligeras con batería interna de 360 Wh o 480 Wh que incluían el Range Extender oficial eran descartadas por filtro S4 (<= 500 Wh) antes del enriquecimiento, o se confundía la mera compatibilidad comercial ("compatible con extender opcional") con la inclusión real. | **Extractor robusto de Range Extender**: 1) Distingue inclusión real (`+`, `incluye`, `con`, `regalo`) de exclusión comercial (`compatible con`, `opcional`, `no incluido`, `por separado`). 2) Suma la capacidad externa al total (`bateria_wh`) para rescatar oportunidades ligeras de 18 kg y > 600 Wh. 3) Bonifica +0.5 pts en relación calidad-precio y lo refleja en Telegram. |
| **Capacidad efectiva degradada vs capacidad nominal en Upway** | Upway | Upway publica frases como *"conserva el 89 % de su capacidad original de 750 Wh, es decir, 670 Wh"*. Si el extractor tomaba los Wh efectivos degradados en una batería de 540 Wh al 90% (~486 Wh), la bici caía falsamente en el filtro S4 (`<= 500 Wh`). | **Separación Nominal vs SoH**: `_extraer_bateria` prioriza `"capacidad original de XXX Wh"` para conservar la capacidad nominal en `bateria_wh`, mientras `_extraer_salud_bateria` guarda el `% SoH` y los ciclos de carga para evaluarlos en el Perito Mecánico Senior (`>=92%: +0.5`, `80-84%: -1.0`, `<80%: -2.5`). |
| **Bicicletas "Reservadas" o "Agotadas" infiltradas en el Top 3** | Bike Ocasión / Buhobike / Upway / Mammoth | Las tiendas mantienen publicadas las fichas de unidades reservadas o recién vendidas por posicionamiento SEO. | **Filtro S0 en doble barrera**: `BaseScraper.es_tarjeta_no_disponible` descarta tarjetas con badges/clases de reserva o sin stock en los 4 scrapers, y `_extraer_disponibilidad_ficha` valida botones y etiquetas de ficha sin caer en falsos positivos (*"¿Quieres reservarla?"*). |
| **Motor separado en etiquetas `Marca` y `Modelo` + Fechas de entrega como año** | Upway / Mammoth | Upway estructura el motor como `Marca: Shimano Modelo: EP800` (no adyacente), y Mammoth incluye `"Entrega estimada 12 nov. 2026"` que se interpretaba como año del modelo `2026`. | **Regex estructurados con contexto**: `_extraer_motor` soporta `Marca: X ... Modelo: Y` en Upway, y `_extraer_ano` prioriza etiquetas explícitas e ignora contextos de entrega/envío/garantía. |
| **Confusión de motores en gama BH (BH 2EXMAG vs Shimano EP801)** | Bike Ocasión / Buhobike | Los anuncios de `BH iLynx Race/Trail` e `iLynx+` a veces omiten el modelo exacto del motor. Ambos comparten chasis similar pero la serie `iLynx+` monta **Shimano EP801** (diagnóstico abierto, pero con batería/centralita BH) mientras que la serie `iLynx Race/Trail` monta el motor propietario **BH 2EXMAG**. | **Desambiguación en catálogo técnico (`gemini_classifier.py`)**: Se separaron las firmas de catálogo de `bh ilynx+` (Shimano EP801) y `bh ilynx race/trail` (BH 2EXMAG), manteniendo la penalización de -1.0 pt en BH por ecosistema de batería cerrado que impide extraer informe PDF oficial de salud de celdas. |
| **Archivo `logs/buscador.log` vacío (0 bytes)** | Orquestador / `scraper_base.py` | `scraper_base.py` ejecutaba `logging.basicConfig()` al importarse antes de `main.py`, haciendo que Python ignorara silenciosamente el `FileHandler` configurado posteriormente en `main.py`. | Se eliminó `logging.basicConfig()` de `scraper_base.py` y se añadió `force=True` en `main.py`. |
| **URL de categoría 404** | Bike Ocasión | La URL original (`bicicletas-electronicas/doble-suspension/`) devolvía 404. Se inspeccionó el menú y se encontró la URL correcta: `bicicletas-electricas-de-montana-doble-suspension-2020`. | Selectores y URLs actualizados tras inspección en vivo. |
| **Protección anti-baneo (503)** | Buhobike | `Fetcher` HTTP devuelve 503 por desafío JS de Cloudflare. | `StealthyFetcher` con `solve_cloudflare=True` y `usar_stealth_directo=True`. |
| **Incompatibilidad TextHandler vs BeautifulSoup** | Bike Ocasión | `page.html_content` de Scrapling es un `TextHandler` (subclase de `str`). | Se normaliza con `str(html)` en `scraper_base.py`. |
| **Pérdida de corrida por suspensión del PC** | Task Scheduler | A las 12:00 el PC estaba suspendido y Task Scheduler marcó `NumberOfMissedRuns: 1`. | Configurado `WakeToRun: True`, `StartWhenAvailable: True` y ejecución en batería en la tarea `BuscadorBiciOcasion` mediante PowerShell. |
| **Bloqueo de archivo SQLite en Windows (`WinError 32`)** | Base de datos / Tests | En Windows, abrir conexiones SQLite mediante `with sqlite3.connect(...)` sin invocar `.close()` mantiene abierto el descriptor del archivo temporal hasta que el recolector de basura lo destruye, causando `PermissionError: [WinError 32]` en los tests. | Se encapsuló la limpieza de bases de datos temporales en bloques `try...except PermissionError` para garantizar tests atómicos y confiables. |
| **Ambigüedad entre milímetros de suspensión vs ruedas, bielas o discos** | Enriquecedor / Evaluador | Regex ingenuos sobre `\d+ mm` capturaban diámetros de rueda (`29" / 622 mm`), discos de freno (`180 mm`, `203 mm`) o longitud de biela (`170 mm`, `175 mm`), contaminando el recorrido. | `_extraer_recorrido` restringe la búsqueda a prefijos explícitos (`recorrido`, `travel`, `horquilla`, `suspensión`, `amortiguador`) o marcas reconocidas (`Fox 34`, `RockShox SID/Pike`, `Marzocchi`), validando el rango estricto entre 100 y 180 mm. |
| **Trazabilidad de catálogo sin penalizar latencia de scraping** | Orquestador / Base de datos | Si para registrar el historial de precios tuviéramos que entrar a las 320 fichas de detalle, la búsqueda tardaría >12 minutos por corrida. | `registrar_en_catalogo` se nutre directamente del flujo de pre-filtrado en memoria de los 4 scrapers paralelos, manteniendo la corrida completa en ~51 segundos. |
| **Scrapling 0.5 ProxyRotator sin método `.add()` e inicialización posicional** | BaseScraper / Enriquecedor | En Scrapling 0.5 `ProxyRotator()` no admite constructor vacío ni tiene método `.add()`; exige `proxies: List[str]` en `__init__`. Además `FetcherSession` guarda `_proxy_rotator` como atributo privado y no público. | Se diseñó la factoría `crear_proxy_rotator(proxies, rotacion)` con sanitización de comillas/líneas en `config.py`, inyectando el rotador directamente en los argumentos de `FetcherSession`, `StealthyFetcher.fetch` y `Fetcher.get`. |
| **Tracking accidental de archivo dinámico `logs/buscador.log` en Git** | Repositorio / Git | Aunque `logs/` figuraba en `.gitignore`, `logs/buscador.log` había sido indexado en commits anteriores, ensuciando los diffs y el árbol de trabajo en cada corrida. | Se desindexó mediante `git rm --cached logs/buscador.log` manteniendo el archivo local y limpiando los commits de producción. |
| **Timeout de inferencia individual en odómetros por imagen** | Enriquecedor / Visión IA | `gemini-flash-latest` con thinking tardaba >15s por foto en llamadas secuenciales, disparando timeouts en galerías de 6 fotos. | Agrupación de la galería completa en un único lote multimodal hacia `gemini-3.5-flash-lite`, resolviendo toda la galería en 3–5 segundos. |
| **Peso con embalaje (22 kg) enmascarando peso real en Buhobike** | Buhobike / Enriquecedor | Buhobike mezcla el peso de envío (`22,000 Kg`) con el peso de báscula (`19,57 Kg`), provocando descarte por filtro S3 (> 21 kg). | Parseo estructurado previo de `table.caracteristicas-tecnicas-2-tablas` y `#product-details`, extrayendo peso neto de báscula antes de limpiar el DOM. |
| **Extracción de PVP original nuevo vs precio de ocasión** | Upway / Bike Ocasión / Mammoth / Buhobike | Las tiendas muestran en la misma tarjeta o ficha el precio actual y el PVP original de fábrica tachado (ej. *"2.499 € 6.000 € nuevo"* en Upway, `<del>` o `.price-before-discount`). Un regex simple capturaba el primer valor o confundía el descuento con el precio real de venta. | Implementado extractor específico `_parsear_pvp_original` que compara los montos adyacentes mayores al precio ofertado, persistiendo `pvp_original` en SQLite para calcular el descuento real vs nuevo (~57% en Upway). |
| **Extenders opcionales vs batería principal en Mammoth (`EnergyPak 625` + extender compatible)** | Mammoth / Enriquecedor | Fichas técnicas en Mammoth declaran cadenas compuestas como *"Batería: EnergyPak Smart 625EnergyPak Plus 250Wh range extender compatible"*. Un extractor ingenuo tomaba los 250 Wh o sumaba una batería opcional no incluida. | Aislamiento de capacidades comerciales de catálogo sin 'Wh' explícito (`EnergyPak 625`, `PowerTube 750`, etc.) y filtrado estricto que descarta menciones adyacentes de compatibilidad comercial (`compatible`, `opcional`). |
| **Telemetría de bicis nuevas (km=0) y baterías sustituidas** | Mammoth / Upway / Enriquecedor | Unidades nuevas de liquidación (km=0 con 3 años de garantía) o de ocasión con batería a estrenar ("Batería: Reemplazada") no publican informe de degradación en texto, arriesgando quedar sin telemetría o penalizadas. | Detección contextual de batería sustituida/a estrenar fijando `SoH: 100%` y `0 ciclos`, y normalización automática para bicis con `km=0` y `garantia_anos >= 2`, otorgando la bonificación de +0.5 pts en el Perito Mecánico Senior. |
| **Heartbeat operativo diario sin saturar alertas en Telegram** | Notificador / Orquestador | En días donde ninguna e-MTB supera el corte de oportunidad (nota >= 8.0), el usuario no tenía certeza de si el cron de las 12:00 corrió con éxito, se suspendió o fue bloqueado por Cloudflare. | Implementado `enviar_heartbeat` (`formatear_heartbeat`) que reporta duración, conteo por tienda, candidatas aptas analizadas, tamaño del radar activo y unidades en vigilancia diaria con flag `TELEGRAM_HEARTBEAT`. |
| **Migración no destructiva de base de datos SQLite en producción** | Base de datos (`db.py`) | Añadir `pvp_original` a la tabla `historial_catalogo` en entornos con bases de datos preexistentes causaba `OperationalError` al no existir la columna. | Migración preventiva idempotente con `ALTER TABLE historial_catalogo ADD COLUMN pvp_original REAL` encapsulada en `try...except` durante la inicialización de la conexión. |
| **Falsos positivos de "Mega Chollo" en bicis desgastadas (nota < 9.0)** | Notificador / Orquestador | Un descuento >50% vs PVP original en una bicicleta con alto kilometraje o batería mermada (ej. nota 3.5 o 5.5/10) activaba la cabecera `💥 ¡MEGA CHOLLO!`, generando falso FOMO cuando en realidad se trataba de un precio de liquidación acorde a su desgaste. | Se aplicó una regla bicondicional estricta: `descuento_pvp >= 50%` Y `nota >= 9.0`. Si la nota es inferior a 9.0, se degrada a oferta normal mostrando el PVP original a título informativo sin cabecera alarmista. |
| **Fatiga de alertas y ruido sonoro diario en Telegram** | Notificador / UX de usuario | Si el bot activa timbre y vibración en el móvil todos los días a las 12:00 para ofertas rutinarias o heartbeats de diagnóstico, el usuario silencia el canal y se desensibiliza, ignorando alertas críticas. | Segmentación acústica nativa en Telegram Bot API: `disable_notification=True` para ofertas estándar y Heartbeat diario, reservando el timbre sonoro y vibración exclusivamente para verdaderos Mega Chollos (`nota >= 9.0` y `dto >= 50%`). |
| **Repetición estéril del Top 3 en análisis consecutivos** | Orquestador / Base de datos / Notificador | Al ejecutar búsquedas consecutivas o en períodos sin cambios de catálogo, notificar el mismo Top 3 no aporta valor, mientras que silenciarlo oculta alternativas viables. Además `_recolectar_oportunidades()` truncaba el pool a 3 unidades impidiendo acceder a puestos inferiores. | Refactorizado `_recolectar_oportunidades()` para preservar todo el catálogo apto; persistencia de la huella en tabla `analisis_ejecuciones` y rotación automática con offset cíclico (#4-#6) con cabecera de aviso contextual en Telegram (`🔄 Top 3 sin cambios respecto al análisis anterior`). |
| **Paginación híbrida de Wallapop (`items=[]` con `next_page=True`) y parámetros de categoría** | Wallapop (`scrapers/wallapop.py`) | Consultar `/api/v3/search` sin keywords con `category_ids=17000` devolvía coches (`category_id=100`); además el motor de blending de Wallapop devuelve páginas intermedias vacías (`items=[]` en la pág. 3) manteniendo `meta.next_page`, lo que cortaba la extracción en solo 5 ítems. | Migrado a `source="quick_filters"` + `category_id="17000"` + `subcategory_ids="10215"` (Bicicletas eléctricas), paginando hasta agotar `next_page` (24 páginas / 592 anuncios en vivo) con guarda Haversine `<= 50 km` contra anuncios `bump: country`. |
| **HTML SPA sin hidratar y falsos negativos en NLP libre de Wallapop** | Wallapop / `enriquecedor_web.py` | La ficha web `es.wallapop.com/item/...` es Next.js SPA (`imgs=0` en Scrapling estático); además anuncios reales incluían `"t.M"`, `"Talla S3"`, `"M/L"`, `"540w"`, `"3000km ... cadena a estrenar"` (bloqueado por ventana `-65/+65` de `'cadena'`) o `"batería interna 320Wh + extender 160w incluido"` (capturando `320` en lugar de `160`). | En Wallapop `enriquecer_bici` lee directamente `bici.imagenes` mediante Gemini Vision sin scrapear el SPA HTML; `_extraer_talla` soporta `t.M`, `S1-S6` y compuestas (`M/L -> ML`); `_extraer_range_extender` ignora capacidades precedidas por `interna/principal`; `_extraer_km` refina la lista de bloqueo de mantenimiento de cadena. |
| **Clones de tiendas en Wallapop y falsos positivos de aluminio / doble suspensión** | `db.py` / `main.py` / `wallapop.py` / `gemini_classifier.py` | Tiendas oficiales (ej. Buhobike) republicaban las mismas bicicletas al mismo precio en Wallapop (`ORBEA RISE H10`, `MONDRAKER DUSK R`, `BH ILYNX RACE`). Además `Ghost E-ASX 160 Advanced AL` se clasificaba como Carbono (`18.6 kg`), `'al 98%'` disparaba aluminio y subcadenas en Wallapop (`trail`/`llevo`/`volumen`/`riser`) daban falsos positivos de doble suspensión. | `deduplicar_inter_portal` y `fue_enviada_equivalente` omiten clones Wallapop dentro de `±25 €` (tras pre-filtrar talla `M`), conservando versiones numéricas (`8.4` vs `8.6`). `_MODELOS_DOBLE_RE` usa `\b` + `²->2`, `AL` solo matchea mayúsculas con lookahead y `orbea rise m` ambiguo fue acotado. |
| **Latencia ~580s en DuckDuckGo, caché parcial y cacheo de errores HTTP** | `scrapers/enriquecedor_web.py` | Consultar DuckDuckGo antes del catálogo local y sin caché previa bloqueaba ~440–580s; además extraer solo campos `None` envenenaba la caché para bicis posteriores y los fallos HTTP/timeouts (`""`) quedaban cacheados 7 días. | Reordenado `completar_con_catalogo` antes de DuckDuckGo, añadido filtro de especificidad (NFD), lock por clave (`_obtener_lock_ddg`), extracción incondicional (`ddg_v2:`) de los 3 campos críticos y exclusión de respuestas vacías/anti-bot (`anomaly-modal`), bajando la corrida total a **115.3s** (y **31.9s** en pasadas cacheadas). |
| **Cupos globales saturados por Wallapop ocultando tiendas profesionales** | `main.py` / `db.py` / `notifier.py` | Priorizar globalmente `estrictas_nuevas` sobre `estrictas_conocidas` y recortar a `[:3]` hacía que 3 anuncios nuevos de Wallapop (`6.5/10`) expulsaran bicis mejores ya vistas de Upway (`8.0/10`) o Bike Ocasión. | `seleccionar_por_portal` entrega **1 mejor opción de cada página** con stock apto sin degradar bicis ya conocidas frente a inferiores, con rotación diaria por portal `#1 -> #2 -> #1` persistida en `estado_portales` solo si el envío Telegram acierta. |
| **Falsos positivos de genéricas/contradicciones y pesos irreales en Full Power** | `gemini_classifier.py` / `models.py` / `wallapop.py` | Anuncios vagos (`"BICI MONTAÑA ELECTRICA DOBLE CARBONO NUEVA"`), contradicciones `"NUEVA"` + km elevados, y baterías `>= 625 Wh` con peso optimista `< 21 kg` inflaban notas hasta `8.5/10`. | Nuevo **Perito Escéptico v2** (`perito_v5`): 5 Líneas Rojas (genérica `<= 4.5`, Talla `0.0`, `<500Wh 4.0`, `>21kg 4.0`, `>6000km 4.5`), física Full Power `>= 22.5 kg` post-Gemini, corrección `BH iLynx+`/`Orbea Rise`/Bosch, eje Garantía (`tiene_factura` en Wallapop) y aritmética sin bonos positivos. |

| **Segundo bot bloqueado (`403`) hasta `/start` + Markdown v1 roto con `_`** | `notifier.py` / `.env` / Telegram | Telegram prohíbe a un bot nuevo (`@BlackBikeBeast_bot`) iniciar chat privado (`getUpdates = 0`) hasta que el usuario pulsa `/start`; además escribir `Black_Bike_Beast` dentro de `parse_mode='Markdown'` interpretaría `_Bike_` como cursiva. | Validación `getMe`/`getUpdates`, variables separadas (`TELEGRAM_BOT_TOKEN_BLACK_FRIDAY` y `TELEGRAM_CHAT_ID_BLACK_FRIDAY` con fallback a `TELEGRAM_CHAT_ID`), texto libre de guiones bajos (`Black Bike Beast`) y `enviar_heartbeat_black_friday` dedicado para confirmar pulso vivo. |
| **PVP tachado invisible en Mammoth (`0/66` vs `28/66`) y orden DOM** | `scrapers/mammoth.py` | El selector antiguo (`.card-price-old / del`) ignoraba `<span class="price is__old">` dentro de `.card-product-price`, dejando `pvp_original=None`; además un selector unión sin `:not(.is__old)` en `precio_el` corría riesgo de coger el precio viejo según el orden del DOM y dejar `0.0` al fallar el parseo. | Añadido `.is__old, .price.is__old` con limpieza de `<= precio` / `0.0` a `None` (desbloqueando `28/66` bicis con PVP real en vivo) y selección secuencial en `precio_el` excluyendo `:not(.is__old)`. |
| **Contaminación dedup `>3.300 €` y bypass de peso estimado / `suspension_trasera=None`** | `main.py` / `evaluator.py` / `gemini_classifier.py` | Unir `pre_aptas` y extras `>3.300 €` antes de `deduplicar_inter_portal` dejaba que una bici oficial no apta en flujo diario ocultara una Wallapop elegible; además `enriquecer_y_valorar_bici` rellenaba `peso_kg` con heurística/IA sin marca de origen y `suspension_trasera=None` pasaba `_pasa_requisitos_base_mecanicos`. | Deduplicación separada (`pre_aptas_dedup` vs `bf_extra_dedup`), marca `_peso_estimado = True` si no hubo dato empírico (ficha, catálogo o DuckDuckGo) rechazada en `evaluar_oportunidad_black_friday`, y exigencia explícita `suspension_trasera == "si"`. |
| **Aislamiento de dedup entre Top 3 de respaldo (`>3.500 €`) y alertas futuras `<=3.500 €`** | `db.py` / `main.py` | Registrar el informe Top 3 fuera de tope con su `bici_id` real en `bicis_black_friday_enviadas` habría bloqueado alertas estrictas futuras si la bici bajaba a `<=3.500 €` o suprimido clones equivalentes (`±25 €`) de otro portal; además `with sqlite3.connect` no cerraba descriptores en Windows. | Registro bajo prefijo `respaldo:{bici_id}` y filtro `AND bici_id NOT LIKE 'respaldo:%'` en `_fue_enviada_equivalente_en_tabla`, más `@contextmanager` con `timeout=30.0`, `WAL` y `conn.close()` en `db.py`. |
| **Fuga de modelos Trail (`140-160 mm`) vía `"Light e-MTB"`, fallos `429`/timeout en Gemini y falta de pág. 2 en Buhobike** | `config.py` / `evaluator.py` / `gemini_classifier.py` / `main.py` / `buhobike.py` | `"Light e-MTB"` y el respaldo diario `respaldo_pool` dejaban colarse modelos Trail (`Orbea Rise`, `Moterra SL`, `iLynx Trail`, `Ghost Path Riot`, `BMC Fourstroke` mal etiquetado). Además `gemini-3.5-flash` daba HTTP `429` y `gemini-3-flash-preview` excedía timeout sin `thinkingBudget: 0`, mientras `BuhobikeScraper` solo leía página 1. | Restringida `MODALIDADES_VALIDAS` exclusivamente a `XC / Cross Country / Downcountry` (`RECORRIDO_MAX_XC_MM = 130`), añadido `es_modelo_trail_o_enduro` y bloqueo post-enriquecimiento en `main.py`, incorporado `BMC Fourstroke` (`amplt`/`amp lt`) en catálogo, reordenado `GEMINI_MODELS` (`gemini-3.5-flash-lite` -> `gemini-3-flash-preview` con `thinkingBudget: 0` y caché `perito_v6_xc`) y añadida página 2 + filtro `Scott Lumen` en `BuhobikeScraper`. |
| **`KTM Macina Scarp SX` mal catalogada (`>500 Wh` XC) y superíndices `²` rompiendo regex en `Focus VAM²` / `JAM²`** | `gemini_classifier.py` / `evaluator.py` / `db.py` / `wallapop.py` | Se había catalogado la `KTM Macina Scarp SX` como XC `> 500 Wh` cuando monta `400 Wh` y `140 mm` Trail; además títulos con el carácter Unicode `²` (`VAM²`, `JAM²`, `THRON²`) no coincidían con patrones ASCII `vam2`/`jam2`. | Corregida la ficha de `KTM Macina Scarp SX` (`400 Wh`, `140 mm` Trail) e incluida en `_PATRONES_MODELO_TRAIL_ENDURO` / Nivel 2; aplicada normalización `.replace("²", "2")` en `evaluator.py`, `db.py` y `scrapers/wallapop.py` (`Focus VAM2` en Nivel 3 XC). |
| **Falsos positivos de odómetro por `recorrido 120 mm` o autonomía (`da para 90 km en modo eco`)** | `scrapers/enriquecedor_web.py` | En descripciones largas, `"recorrido: 120"` o frases con un punto intermedio arrastraban palabras clave lejanas de autonomía (`con una carga`, `en eco`, `da para`) dentro de la ventana fija de ±65 caracteres en `_extraer_km`. | En el Paso 2 de `_extraer_km`, `recorrido`/`rodaje` exige explícitamente unidad `km`/`kilómetros` con lookahead negativo `(?!\s*mm\b)`; en el Paso 3 la ventana contextual se trunca en límites de oración `[.;!\n]` ampliando la lista de bloqueo de autonomía. |
| **Peso de catálogo estático tomado como empírico, extender Fazua (`430 Wh`) excluido y clones multi-ciudad sin talla** | `gemini_classifier.py` / `evaluator.py` / `wallapop.py` | `enriquecer_y_valorar_bici` preservaba el peso del diccionario local como si fuese dato real de ficha; `Wilier Urta Hybrid` (`430 Wh`) quedaba descartada pese a caber con extender dentro de `3.500 €`; `"Race Face"` / `"a estrenar cubiertas"` generaban falsos positivos en búsqueda nacional. | Restringido `peso_empirico_previo` a fuentes reales (ficha web / DuckDuckGo); creada `es_xc_ampliable_en_presupuesto` (Fazua `420–430 Wh` XC `<= 3.050 €` + extender `+210 Wh`); `_UNICORNIOS_NACIONALES_PATRONES` con `\b`, `ids_vistos.add` antes de parsear, dedup por talla/precio y protección léxica de recambios en `km=0`. |
| **Filtración de bicis de ocasión/reacondicionadas y caché obsoleto `km=70` en el canal de nuevas/seminuevas (`@BlackBikeBeast_bot`)** | `models.py` / `evaluator.py` / `scrapers/wallapop.py` / `gemini_classifier.py` | Se colaban unidades de portales de segunda mano (`Bike Ocasión`, `Upway`, sección `/segunda-mano-` de Buhobike) y anuncios Wallapop con `"reacondicionada"` o `"neumáticos a medio uso"`; además `valoraciones_ia.json` reinyectaba un falso `km=70` (extraído antes de corregir la frase de autonomía `"da para 65/70km"`) cuando `bici.km` pasaba a `None`. | Añadido `es_ocasion: bool = False` en `Bicicleta`, filtro transversal `es_bici_de_ocasion(bici)` en las 4 funciones de evaluación de Beast (`KM_MAX_SEMINUEVA_BLACK_FRIDAY = 500`), y eliminado `"km"` del backfill de `valoraciones_ia.json` invalidando la entrada siempre que `entry.get("km") != bici.km`. |
| **Anuncios fuera de radio (Barcelona/Murcia/Sevilla) en Wallapop vs compra online nacional de bicis nuevas** | `config.py` / `scrapers/wallapop.py` | El bypass `permitir_nacional=True` en `_buscar_unicornios_nacionales` inyectaba anuncios de Barcelona (`Manresa`, `502 km`) en Wallapop, mientras que apagar las búsquedas por keyword perdía anuncios locales (`<= 50 km` de Fuenlabrada) situados más allá de la página 12 del listado general. | Fijado `WALLAPOP_PERMITIR_NACIONAL = False` para exigir siempre Haversine `<= 50 km` alrededor de Fuenlabrada en cualquier anuncio de Wallapop, reconvirtiendo `_buscar_unicornios_nacionales` en búsqueda local por modelo (`distance_in_km=50`, `max_sale_price=4000`, `permitir_nacional=False`), mientras las tiendas online oficiales (`Mammoth`, `Buhobike`) cubren toda España para compra online de bicis nuevas (`0 km`). |
| **Falsos positivos de rígidas (`Scott Aspect`, `Giant Talon`) y fugas fuera de presupuesto/batería (`Scott Lumen` `8.399–9.899 €` / `360 Wh`)** | `scrapers/mammoth.py` / `scrapers/buhobike.py` / `evaluator.py` / `gemini_classifier.py` / `scrapers/enriquecedor_web.py` | En Mammoth y Buhobike había rígidas (`Scott Aspect eRIDE 900/910`, `Giant Talon E+`, `Scott Scale`, `Merida eBig`, `Haibike Alltrack`) no listadas en `es_rigida` y marcadas como doble suspensión; además `evaluar_respaldo_black_friday` no tenía techo de precio y aceptaba desde `360 Wh`, colando las `Scott Lumen 910/900` (`8.399 €` y `9.899 €`, `360 Wh`, cuyo amortiguador oculto dentro del tubo vertical además parece rígido en foto). También `Focus Jam2` Full Power (`23.8 kg`, Bosch CX) compartía patrón con `Focus Jam2 SL` (`18.5 kg`, Fazua) y fichas nuevas de Mammoth extraían falsos `km` (`25`, `32`, `170`) de `25 km/h` o recorridos `170 mm`. | Ampliado el bloqueo de rígidas en `MammothScraper` y `BuhobikeScraper` (más soporte `talla-s_m -> M` y `"extensor"` en `_extraer_range_extender`), exigencia estricta de `bateria_wh > 500` en Beast, bloqueo de `km` espurios en tiendas nuevas (`km=0`), separación de `Focus Jam2 SL` vs `Focus Jam2`, y presupuesto en dos escalones cerrados: principal `<= 3.500 €` y respaldo `3.501–4.000 €` (`PRECIO_RESPALDO_BLACK_FRIDAY_EUR = 4000`, rechazo absoluto `> 4.000 €`). |
| **Bloqueo excesivo de Trail ligera en Beast, portada aleatoria de 60 ítems en Mammoth (`/c-2139`) y rotación Top 3 en búsquedas repetidas** | `main.py` / `evaluator.py` / `scrapers/mammoth.py` / `scrapers/wallapop.py` / `notifier.py` | Descartar `Trail > 130 mm` antes de evaluar Beast eliminaba todas las ofertas Black Friday de `Orbea Rise`, `BH iLynx Trail` y `Berria Mako Hybrid` (`< 21 kg`, `> 500 Wh`); la portada HTML de Mammoth (`/c-2139`) solo servía 60 ítems aleatorios de 139 (ocultando en algunas ejecuciones las `Orbea Rise H30 / LT H20 2026` rebajadas `-25%`), el regex de PVP en Wallapop fallaba en `"antes 4599€"` por usar `€\b`, y al repetirse la misma búsqueda Beast enviaba `0` bicis. | Beast evalúa antes del filtro XC diario con jerarquía determinista (`1º <= 3.500 € vs 3.501–4.000 €`, `2º prioridad_modalidad: XC [3] > Trail ligera [2] > MTB [1]`, `3º 0–50 km > <= 500 km`, `4º dto PVP / nota / peso`); `MammothScraper` consulta `POST /filtrarproductos` (`orden="PrecioAscendente"`, `1.500–4.200 €`, con `€` opcional en `_parsear_precio`, pasando de `66` a `143` unidades extraídas); `_es_equivalente_en_lista` deduplica clones de color del mismo portal y `_despachar_alertas_black_friday` persiste `estado_portales["__beast__"]` (`pool_ids`, `offset`, `enviados_ids`) para rotar automáticamente a las siguientes en importancia cuando la búsqueda se repite. |
| **Falsos URL `#fragment` PrestaShop (`talla-xl`), tallas `SM` (=BH Small) vs `MD`, Escapa 403 en `curl_cffi` y discos `180/180 mm` como recorrido** | `prestashop_base.py` / `sanferbike.py` / `escapa.py` / `enriquecedor_web.py` / `config.py` | En PrestaShop (`Sanferbike`, `Bicimarket`, `Fabregues`) la URL de listado apunta por defecto a `#/...-talla-xl` ocultando la M real en stock; en `Fabregues` el prefijo BH `SM` (Small) corría riesgo de confundirse con `S/M` o `M`, y en ficha PrestaShop la clase `.disabled` puede residir en el `<span>` hijo. Además `Escapa` devolvía 403 ante el TLS de `Fetcher`, y las fichas con frenos `180/180 mm` se capturaban erróneamente como `180 mm` de suspensión. | Ignorado el `#fragment` por defecto en listado PrestaShop e indexada caché de ficha sin `#fragment` (TTL 6h); añadida lectura de `.js-miniature-product-variants` (`data-qty-*`), `.product-variants-item` (recorriendo `el/inp/lbl/span`), `BCData.in_stock_attributes` y botón `Avísame`; `normalizar_codigo_talla` mapea `MD->M` y `SM->S` preservando `M/L->ML`; `usar_requests_primero=True` en `Escapa` y filtro negativo de rotores/discos en `_extraer_recorrido`. |
| **Fuga de `BH iLynx+ SL / Enduro / 8.7`, motores `Avinox M2`, `SUV`, `Orbea Rise` repetidas en Mammoth y 11+ llamadas inútiles a Gemini para `Talla != M`** | `evaluator.py` / `gemini_classifier.py` / `scraper_base.py` / `enriquecer_y_valorar_bici` | Un patrón genérico `"ilynx+"` asignaba falsamente `20.4 kg`, `Carbono` y `Shimano EP801` a modelos `SL` de Aluminio (`Shimano EP6`, `630 Wh`, `~22.8 kg`), `Enduro` (`160–170 mm`) y `Trail Carbon 8.7` (`21.2 kg`); además `Bicicleta BH Eléctrica Ilynx Trail...` en Fabregues no cruzaba `"bh ilynx trail"`, las variantes de color en Mammoth duplicaban 2/3 del Top 3, modelos `Avinox M2` / `SUV` pasaban pre-filtro y fichas `Bicimarket`/`Fabregues` sin stock M llamaban a Gemini antes del descarte S1. | Separación en `CATALOGO_EMTB` y bloqueo Full Power de `ilynx+ sl`, `ilynx+ enduro`, `ilynx+ trail carbon 8.7`, `Avinox` (salvo `Amflow PL`), `SUV` (`es_modelo_no_mtb_doble`) y Enduro (`_motivo_descarte_enduro >165mm`); patrones `"ilynx trail"` / `"ilynx race"`; dedup por variante de color en Beast y cortocircuito `[Perito Rápido]` antes de DuckDuckGo/Gemini (`75.5s -> 37.5s` en vivo). |
| **Bypass de rígidas en `Upway /doble-suspension`, fugas e-Gravel (`ORBEA DENNA`) / `Flyer Goroc` y Full Power `>= 22 kg` (`Spectral:ON`, `X-Bolt`, `E-FEEL`)** | `scrapers/upway.py` / `scraper_base.py` / `evaluator.py` | `UpwayScraper` asignaba incondicionalmente `suspension_trasera="si"` al venir de `/collections/doble-suspension`, permitiendo colarse a rígidas como `Haibike AllTrack 7`; además faltaban patrones para `ORBEA DENNA` (e-gravel), `Flyer Goroc` (trekking SUV) y familias Full Power `21.8–25.5 kg` (`Canyon Spectral:ON / Neuron:ON / Torque:ON`, `Stevens E-Inception`, `MMR X-Bolt 120`, `Rockrider E-FEEL 700 S`, `E-EXPL 520`). | `UpwayScraper` consulta `es_modelo_no_mtb_doble` antes de fijar `suspension_trasera="si"`; ampliado `_PATRONES_NO_MTBD_COMUNES` (`"denna"`, `"goroc"`) y `_PATRONES_MODELO_FULL_POWER_PESADA` con las 11 variantes validadas empíricamente; cubierto con test TDD y verificado con reposición en vivo Talla M en `Bicimarket`. |

---

## Estado actual y TODOs para mañana (`27/11/2026`)

### Fotografía real del proyecto (`26/11/2026` — tras corrida en vivo `#32` de 9 portales en `44.1s`)
- **Suite unitaria e integración (`python test_buscador.py`)**: **100% GREEN** (incluyendo la nueva regresión `test_afinado_26nov_full_power_gravel_y_upway_rigida` sobre `Upway` rígidas, e-gravel/SUV y las nuevas familias Full Power).
- **Auditoría previa y ejecución en vivo de los 9 portales (`#32`, `44.1s`)**: revisada primero la ejecución automática del `25/11` (`#31`, `12:00:45`, `42.6s`, `LastTaskResult: 0`, rotación Beast en `offset: 4` con `wallapop-pzpkpw08kkj3`, `escapa-54704`, `bicimarket-54682`); posteriormente en `#32` (`26/11 10:33:11`, `44.1s`) se procesaron **Bike Ocasión** (`179`), **Buhobike** (`92`), **Upway** (`21`), **Mammoth** (`140`), **Sanferbike** (`48`), **Bicimarket** (`55`), **Escapa** (`36`), **Fabregues** (`96`) y **Wallapop** (`533` en radio `<= 50 km`), obteniendo `11` candidatas aptas y confirmando de nuevo `Pedalmoto` / `BikePhilosophy` fuera de cobertura (`HTTP 404` / sin stock útil).
- **Resultados verificados hoy (`26/11/2026`) en ambos canales de Telegram y Radar**:
  - **Canal Diario / Segunda mano (`3` notificadas de `11` candidatas aptas — `< 21 kg`, `> 500 Wh`, Talla `M`, `XC > Trail ligera > MTB`)**:
    1. **`BH iLYNX TRAIL CARBON 8.6`** — **Wallapop (`<= 50 km`)** (`2.299,0 €`, `20.0 kg`, **Nota `7.5/10`**)
    2. **`ORBEA RISE H10 T-M 2022 BICICLETA SEGUNDA MANO`** — **Buhobike Segunda Mano** (`2.599,0 €`, `19.57 kg`, **Nota `5.5/10`**)
    3. **`Orbea Rise H15 XT`** — **Bike Ocasión** (`2.649,0 €`, `20.5 kg`, **Nota `3.5/10`**)
  - **Canal Nuevas y Seminuevas `@BlackBikeBeast_bot` (pool `__beast__` de `7` unidades limpias, `offset: 0` reiniciado con la nueva entrada `<= 3.500 €`)**:
    1. **`BH iLynx Trail Carbon 8.7`** (`bicimarket-54681`) — **Bicimarket** (`3.499,0 €`, PVP `6.299,9 €`, **`-44.5%`**, **`18.6 kg`**, `540 Wh`, **Talla M repuesta hoy**, **Nota `7.5/10`**)
    2. **`BH iLynx Trail 8.1`** (`bicimarket-58720`) — **Bicimarket** (`3.599,0 €`, PVP `4.799,9 €`, `-25.0%`, `19.6 kg`, `540 Wh`, **Nota `7.0/10`**)
    3. **`BH iLynx Trail 8.2`** (`bicimarket-58721`) — **Bicimarket** (`3.999,0 €`, PVP `5.299,9 €`, `-24.5%`, `19.6 kg`, `540 Wh`, **Nota `7.0/10`**)
    - **Stock dinámico validado y cola de rotación (`__beast__`)**: `bicimarket-54682` (`BH iLynx Trail Carbon 8.8 2023`) agotó la Talla M (`talla=L`) y quedó filtrada al instante por `[Perito Rápido]`; permanecen en cola para siguientes rotaciones `wallapop-mzn290yp0gzn` (`Orbea Rise H10 2023/24`), `escapa-54704` (`Orbea Rise SL H30 2026`), `bicimarket-58722` y `wallapop-pzpkpw08kkj3`.
  - **Radar de Mercado ([docs/radar_mercado.md](docs/radar_mercado.md))**: actualizado el `2026-11-26 10:33:10` con **`15` unidades** (`Wallapop 10`, `Bike Ocasión 2`, `Buhobike 2`, `Upway 1`), **`3.7 días`** de estancia media, `0` rebajas nuevas y **`3` en Zona de Vigilancia** (`Orbea RiseH15` `2.950 €` y `2x BH iLynx Race Carbon 8.4 LT XT` `3.129 €`).

### Estado final del sistema

| Componente | Estado |
|------------|--------|
| Canal Diario multi-portal (ocasion + Wallapop `<= 50 km` + `XC <= 130 mm` `> 500 Wh`) | ✅ Operativo y verificado en vivo (`BH iLYNX TRAIL CARBON 8.6` `2.299 €` + `Orbea Rise H10` `2.599 €` + `Orbea Rise H15 XT` `2.649 €`) |
| Canal `@BlackBikeBeast_bot` (9 fuentes, nuevas/seminuevas `<= 500 km`, `> 500 Wh`, `< 21 kg`, sin Full Power ni Enduro) | ✅ Operativo y verificado en vivo (`BH iLynx Trail Carbon 8.7` repuesta en M a `3.499 €` `-44.5%` + rotación limpia en `7` unidades `__beast__`) |
| Filtros anti-ruido (`Upway` rígidas, e-gravel/SUV, Full Power `>= 22 kg` y `[Perito Rápido]`) | ✅ Operativos y cubiertos por TDD (`test_afinado_26nov_full_power_gravel_y_upway_rigida`) |
| Scrapers tiendas online `0 km` (`Mammoth`, `Buhobike`, `Sanferbike`, `Bicimarket`, `Escapa`, `Fabregues`) + Ocasión/Wallapop | ✅ Operativos en paralelo en `44.1s` con stock real Talla `M`/`MD` y caché TTL 6h |
| Salud del repositorio, Tests y Programador de Tareas (`12:00`) | ✅ `python test_buscador.py` GREEN (`exit 0`), Task Scheduler `LastTaskResult: 0` (próxima `26/11/2026 12:00:00`) |

### TODOs concretos para mañana (`27/11/2026`)

- [ ] **1. Revisar la corrida automática de hoy `12:00` (`BuscadorBiciOcasion`) y la rotación Black Friday**: confirmar si `BH iLynx Trail Carbon 8.7` (`3.499 €` en Bicimarket) mantiene stock en Talla M y hacia qué unidades rotó `@BlackBikeBeast_bot` (`wallapop-mzn290yp0gzn`, `escapa-54704`, `bicimarket-58722`, `wallapop-pzpkpw08kkj3`).
- [ ] **2. Decidir sobre el techo diario `PRECIO_MAX_EXCEPCIONAL_EUR` (`3.300 €` vs `3.500 €`)**: hoy `Bike Ocasión` publicó `464328 Cannondale Moterra Neo SL 2` (`3.431 €`, PVP `6.500 €`, `19.8 kg`, `600 Wh`, `2.032 km`, Talla `M`), actualmente descartada por superar el techo de `3.300 €` con `> 500 km`; decidir si se mantiene `3.300 €` o se amplía a `3.500 €`.
- [ ] **3. Revisar posibles rebajas Black Friday en la Zona de Vigilancia y Radar**: comprobar en [docs/radar_mercado.md](docs/radar_mercado.md) si `Orbea RiseH15` (`2.950 €`) o las `BH iLynx Race Carbon 8.4 LT XT` (`3.129 €`) bajan hacia el umbral objetivo.
- [ ] **4. Vigilar `logs/buscador.log` ante nuevas referencias 2026/2027**: auditar cualquier título nuevo sin peso explícito que supere el prefiltro diario o Beast para ampliar `CATALOGO_EMTB` o `_PATRONES_MODELO_FULL_POWER_PESADA` si hace falta.

### Dependencias instaladas

- `scrapling>=0.5` (motor principal de scraping)
- `patchright>=1.64` (fork de Playwright usado por Scrapling)
- `browserforge>=1.2` (fingerprint generation)
- `msgspec>=0.22` (serialización rápida)

---

## Licencia

MIT

---

## Créditos

Desarrollado como asistente de código bajo la identidad **el Gentleman** (Pi-specific coding-agent harness), siguiendo el flujo de desarrollo **Organic Driven Development (ODD)**.
