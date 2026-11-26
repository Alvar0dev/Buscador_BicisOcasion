# Operación Caza Black Friday & Cyber Monday (`--modo-caza`, BH en 2º plano y Detector Sniper)
Objetivo: Modificar el buscador para priorizar marcas objetivo frente a BH (salvo oferta irrechazable), capturar cualquier chollo nuevo, seminuevo o de ocasión premium mediante un detector Sniper transversal con alerta sonora garantizada, habilitar barridos cada 2 horas sin spam (`--modo-caza`) y ampliar cobertura en los 9 portales sin relajar ningún blindaje mecánico.
Rama: `feat/modo-caza-black-friday` (desde `main` `736b7d4`) | Runner: `python test_buscador.py` | Estado: Pendiente de ejecución por Gemini Hydrogen XHigh

## Specs

- **S1 — Requisito verbatim del usuario y aprobación**:
  - Solicitud original: `"Mañana Black Friday y el lunes Cyber Monday estoy intentando encontrar la oferta de mi guida en la bici que quiero con esas características. La verdad que las bh no me interesan, deberían de ser en segundo plano, a no ser que una oferta sea la reostia. Y quiero que me caces el modelo nuevo o semi-nuvo. o de ocasión que haya estos días y no se te pase como podemos planificar la modificación del buscador para que encuentre ese chullo que tanto estoy buscando hazme la planificación pormenorizada Para que el modelo Hidrogen X High la pueda llevar a cabo."`
  - Aprobación de umbrales: `"me parece bien asi dejaselo todo preparado al siguiente modelo para ejecutar"`
  - Invariantes no negociables (se conservan intactos en todos los canales): `Talla M`, doble suspensión real, batería `> 500 Wh`, peso `< 21.0 kg`, cero Full Power / Enduro (`> 165 mm`) / e-Gravel / SUV / rígidas (`Upway` incluido), Wallapop estrictamente `<= 50 km` desde Fuenlabrada, y compatibilidad 100% con toda la suite existente en `test_buscador.py`.

- **S2 — Prioridad de marca (`BH` en segundo plano + excepción `es_bh_irrechazable`)**:
  - Constantes configurables en `config.py`:
    - `BH_EN_SEGUNDO_PLANO: bool = True`
    - `BH_IRRECHAZABLE_PRECIO_MAX_NUEVA_EUR: float = 2900.0`
    - `BH_IRRECHAZABLE_DTO_MIN_NUEVA_PCT: float = 45.0`
    - `BH_IRRECHAZABLE_PRECIO_MAX_ALT_NUEVA_EUR: float = 3100.0`
    - `BH_IRRECHAZABLE_DTO_MIN_ALT_NUEVA_PCT: float = 50.0`
    - `BH_IRRECHAZABLE_PRECIO_MAX_OCASION_EUR: float = 2300.0`
    - `BH_IRRECHAZABLE_KM_MAX_OCASION: int = 1200`
    - `BH_IRRECHAZABLE_PESO_MAX_KG: float = 19.0`
  - En `evaluator.py`:
    - `es_bh_irrechazable(bici, dto_pvp=None) -> bool`: exige `es_bici_bh(bici)`, `bateria_wh > 500`, `peso_kg is not None and peso_kg <= 19.0`, cuadro de carbono; y en nueva/seminueva (`km <= 500` o `es_sitio_tienda_nueva`) `(precio <= 2900 and dto >= 45.0) or (precio <= 3100 and dto >= 50.0)`; o en ocasión `precio <= 2300 and km <= 1200 and (dto is None or dto >= 50.0) and prioridad_modalidad(bici) >= 2`.
    - `prioridad_marca(bici, dto_pvp=None) -> int`: devuelve `1` si `not BH_EN_SEGUNDO_PLANO`, si `not es_bici_bh(bici)` o si `es_bh_irrechazable(bici, dto_pvp)`; en otro caso devuelve `0`.
  - Integración de `prioridad_marca` en:
    - `evaluar_respaldo_black_friday` (`evaluator.py:1013-1022`) como primer criterio del `sort_key` (antes de `precio <= 3500`).
    - `pool_beast.sort` (`main.py:944-951`): `(prioridad_marca, precio <= 3500, prioridad_modalidad, kind[strict:2, resp:1, sup:0], dto, nota)`.
    - `clave_orden_estrictas` (`main.py:166-191`): insertar `prioridad_marca` justo después de `sin_linea_roja` y antes de `mod_prio` y `nota`, para que en el mismo portal ninguna BH ordinaria desplace a una no-BH sana (manteniendo la BH como respaldo si no hay no-BH en ese portal).
  - Etiqueta visual en `notifier.py`: `[2º plano BH]` para BH ordinaria en informes y `[🔥 BH IRRECHAZABLE]` cuando pase por excepción.

- **S3 — Detector Sniper Transversal (Nueva + Seminueva + Ocasión) y Fix de `es_mega_chollo`**:
  - Constantes configurables en `config.py`:
    - `SNIPER_ACTIVO: bool = True`
    - `SNIPER_PRECIO_MAX_NUEVA_EUR: float = 3600.0`
    - `SNIPER_PRECIO_MAX_OCASION_EUR: float = 3500.0`
    - `SNIPER_KM_MAX_OCASION: int = 2500`
    - `SNIPER_PESO_MAX_KG: float = 20.5`
    - `SNIPER_DTO_MIN_NUEVA_PCT: float = 40.0`
    - `SNIPER_DTO_MIN_OCASION_PCT: float = 42.0`
    - `SNIPER_PRECIO_ROMPEDOR_CARBONO_EUR: float = 2850.0`
    - `SNIPER_BAJADA_FLASH_MIN_EUR: float = 150.0`
  - En `evaluator.py`, crear `evaluar_chollo_sniper(bici, nota, precio_previo=None) -> tuple[bool, str]`:
    - Barreras duras: `disponible`, `talla == "M"` confirmada, doble suspensión confirmada, `not es_full_power_o_pesada`, `not es_modelo_no_mtb_doble`, `prioridad_modalidad >= 2` (XC o Light Trail, nunca Enduro `>150 mm`), `bateria_wh > 500`, `peso_kg is not None and peso_kg <= 20.5` (en tiendas nuevas `0 km` aceptar peso exacto de `CATALOGO_EMTB`).
    - Regla BH: si `es_bici_bh(bici)` y `not es_bh_irrechazable(bici)` -> `(False, "BH en segundo plano")`.
    - Disparadores (basta uno):
      - `T1` (Nueva/Seminueva `<= 500 km`): `(precio <= 3500 and dto >= 40%)` OR `(precio <= 3600 and dto >= 45%)` OR `(cuadro carbono and precio <= 3100)`.
      - `T2` (Ocasión Premium `501–2.500 km`, incluye `Bike Ocasión` y `Upway`): `(precio <= 3500 and dto >= 42% and peso_kg <= 20.0)` OR `(cuadro carbono and precio <= 2850 and km <= 2000)`.
      - `T3` (Bajada Flash): `precio_previo is not None and (precio_previo - bici.precio) >= 150.0 and precio <= 3500 and (km is None or km <= 2500)`.
  - Pre-filtro en `main.py:311-336`: cuando `SNIPER_ACTIVO` sea `True`, incluir un bucket `sniper_ocasion_pre` para capturar Light e-MTB (`prioridad_modalidad >= 2`, `not es_full_power_o_pesada`, `talla M` o `None`) en `3300 < precio <= 3500` **sin modificar** `PRECIO_MAX_EXCEPCIONAL_EUR = 3300` del canal diario ordinario (preservar `test_descarta_precio_fuera_rango`).
  - Persistencia en `db.py`: tabla `alertas_sniper_enviadas(bici_id TEXT PRIMARY KEY, precio REAL, fecha TEXT, motivo TEXT)` con `debe_enviar_sniper(bici)` (reenvía solo si es nueva o si `bici.precio <= precio_previo - 50.0`) y `marcar_sniper_enviada(bici, motivo)`.
  - Despacho en `main.py`: ejecutar despacho Sniper sobre todas las candidatas enriquecidas **antes** de aplicar el tope de 1-por-portal (Daily) y la rotación Top 3 (Beast), consultando `precio_previo` en `historial_catalogo` / `bicis_enviadas` / `bicis_black_friday_enviadas`.
  - Notificación en `notifier.py`:
    - Corregir `es_mega_chollo` (`notifier.py:12-24`): devolver `True` si `(pct_dto >= 50.0 and nota >= 7.5)` OR `(pct_dto >= 40.0 and nota >= 8.5)` OR `nota >= 9.0` (resuelve el bug por penalización `-2.0` en `> 3150 €` que dejaba mudos todos los chollos `3.200–3.500 €`).
    - Añadir `enviar_alerta_sniper(bici, nota, motivo_sniper, precio_anterior=None, es_beast=False) -> bool` siempre con `silencioso=False` (`disable_notification=False`) y cabecera `🎯🔥 ALERTA SNIPER BLACK FRIDAY`.

- **S4 — Modo Caza (`--modo-caza` / `MODO_CAZA_BF`), Caché Fresca `45 min` y Lock de Concurrencia**:
  - Flag CLI `--modo-caza` en `main.py:1335-1362` (y override opcional por env `MODO_CAZA_BF=true`, default `False`).
  - Caché fresca en `scrapers/enriquecedor_web.py:42, 371-377`: cuando `modo_caza=True`, usar `FICHA_TIENDA_TTL_CAZA_SEG = 45 * 60` (`45 min`) y re-consultar también fichas cuya tarjeta en listado muestre un precio distinto al `cache_precio` almacenado.
  - Invalidación de caché IA en `gemini_classifier.py:1610-1631`: invalidar también si cambia `int(bici.pvp_original or 0)`.
  - Política anti-spam en `--modo-caza`:
    - Sniper: envía siempre con sonido cuando `debe_enviar_sniper(bici)` sea `True`.
    - Beast: envía solo si hay bici estricta nueva, alguna entrada nueva en el pool no vista antes (`nuevas_items`), o bajada de precio `>= 50 €`; si `misma_busqueda` sin cambios, **no rota ni envía informe ni Heartbeat**.
    - Daily: envía solo si hay una bici nueva que mejore el `#1` previo del portal, una entrada desde Zona de Vigilancia o una bajada real (`debe_reenviarse`); si no hay cambios, **no rota ni envía Heartbeat**.
    - Modo estándar (`main.py --once`, usado a las `12:00`): comportamiento 100% intacto (resumen completo + rotación + Heartbeat).
  - Lock de concurrencia en `main.py`: file lock `cache/buscador.lock` con stale-timeout de `15 min` para impedir colisiones SQLite/JSON entre la tarea diaria `12:00` y las corridas cada 2h de `--modo-caza`.

- **S5 — Ampliación Quirúrgica de Cobertura en los 9 Portales y `CATALOGO_EMTB`**:
  - `scrapers/upway.py`: añadir paginación `?page=1..4` con corte temprano si una página devuelve `0` tarjetas o todos sus `bici_id` ya fueron vistos, preservando la guardia `es_modelo_no_mtb_doble` (`Haibike AllTrack`).
  - `scrapers/sanferbike.py`: `MAX_PAGINAS = 4` con corte temprano cuando el precio mínimo de la página supere `4.200 €`.
  - `scrapers/escapa.py`: `MAX_PAGINAS = 4` (manteniendo `techo_corte = PRECIO_RESPALDO_BLACK_FRIDAY_EUR + 400`).
  - `scrapers/buhobike.py`: añadir página 2 en categoría XC (`3229`) con corte temprano si no hay nuevos productos.
  - `scrapers/mammoth.py`: subir `precioMaximo` de `4200` a `4400`.
  - `config.py` (`WALLAPOP_UNICORN_QUERIES`): ampliar bajo radio estricto `<= 50 km` con `"Specialized Levo SL"`, `"Trek Fuel EXe"`, `"Mondraker Neat"`, `"Lapierre E-Zesty"`, `"Cube AMS Hybrid"`, `"MMR Kaizen"`, `"Amflow PL"`, dejando `"BH iLynx Race"` / `"BH iLynx Trail"` al final.
  - `gemini_classifier.py` (`CATALOGO_EMTB`): auditar y completar entradas faltantes de peso/batería/recorrido para modelos objetivo 2024–2026 (`Orbea Rise SL M/H 2025/2026`, `Scott Lumen eRIDE 900/910`, `Cannondale Moterra SL 1/2 / Neo SL`, `Specialized Turbo Levo SL`, `Trek Fuel EXe`, `Mondraker Neat`, `Wilier Urta Hybrid`, `Focus VAM2 SL`, `Lapierre E-Zesty`, `Cube AMS Hybrid ONE44`, `KTM Macina Scarp SX`, `MMR Kaizen`, `Amflow PL Carbon`).

- **S6 — Programación Temporal Windows Task Scheduler (Solo tras verificación en vivo y confirmación final)**:
  - Documentar en `CRON.md` y `README.md` la tarea paralela reversible `BuscadorBiciOcasion_BlackFriday`:
    - Acción: `python.exe "G:\Proyectos OpenCode\Buscador BiciOcasion\main.py" --once --modo-caza`
    - Trigger: inicio `2026-11-26T23:55:00`, repetición cada `2 horas`, `EndBoundary = 2026-12-01T01:00:00`, `MultipleInstances = IgnoreNew`, `WakeToRun = True`.
    - No modificar ni deshabilitar `BuscadorBiciOcasion` (tarea diaria de las `12:00`).
  - **Nota de seguridad**: antes de registrar la tarea en Windows Task Scheduler, confirmar con el usuario tras mostrar el resultado del smoke test `--once` y `--once --modo-caza`.

## Tasks

- [x] **T1** | `S1, S2` | Route: `inline` | Risk: `item 3 (shared ranking in evaluator.py, main.py, notifier.py)` | Commit: `fc09cf2` (`feat(ranking): relega BH a segundo plano salvo excepcion irrechazable`) | Añadir constantes `BH_*` en `config.py`, `es_bh_irrechazable` y `prioridad_marca` en `evaluator.py`, integrar en `evaluar_respaldo_black_friday`, `clave_orden_estrictas` y `pool_beast.sort` (`main.py`), etiquetas en `notifier.py` y test TDD `test_bh_segundo_plano_y_excepcion_irrechazable` en `test_buscador.py`.
- [x] **T2** | `S1, S3` | Route: `inline` | Risk: `item 1 + item 3 (new SQLite table alertas_sniper_enviadas + shared notifier/evaluator/main)` | Commit: `24c6d14` (`feat(sniper): detector transversal Black Friday y fix alerta sonora mega-chollo`) | Añadir constantes `SNIPER_*` en `config.py`, `evaluar_chollo_sniper` en `evaluator.py`, tabla y métodos `alertas_sniper_enviadas` en `db.py`, fix de `es_mega_chollo` + `enviar_alerta_sniper` en `notifier.py`, bucket `sniper_ocasion_pre` + despacho Sniper previo a caps en `main.py`, y tests TDD `test_sniper_rescata_ocasion_premium_y_bloquea_bh_ordinaria` y `test_es_mega_chollo_no_silencia_rango_3200_3500`.
- [x] **T3** | `S1, S4` | Route: `inline` | Risk: `item 3 + item 4 (cache TTL/invalidation + file lock concurrency)` | Commit: `d505a0b` (`feat(caza): modo --modo-caza anti-spam con cache 45m y lock de concurrencia`) | Añadir `--modo-caza` / `MODO_CAZA_BF`, TTL `45 min` y chequeo de `cache_precio` en `enriquecedor_web.py`, invalidación por cambio de `pvp_original` en `gemini_classifier.py`, silencio anti-spam en Daily/Beast cuando no haya novedades, file lock `cache/buscador.lock` (15 min stale timeout) en `main.py`, y tests TDD `test_modo_caza_sin_cambios_no_envia_spam_ni_heartbeat` y `test_modo_caza_dispara_al_instante_en_reposicion_o_bajada`.
- [x] **T4** | `S1, S5` | Route: `inline` | Risk: `none` | Commit: `e445b85` (`feat(scrapers): paginacion Upway, mas cobertura tiendas y queries Wallapop Light e-MTB`) | Paginación `1..4` con corte temprano en `scrapers/upway.py`, `MAX_PAGINAS=4` con corte por techo en `sanferbike.py` y `escapa.py`, pág. 2 XC en `buhobike.py`, `precioMaximo=4400` en `mammoth.py`, ampliación `WALLAPOP_UNICORN_QUERIES` en `config.py`, auditoría de `CATALOGO_EMTB` en `gemini_classifier.py`, y tests TDD `test_upway_paginacion_y_corte_temprano` + `test_corte_temprano_sanferbike_escapa_por_techo_precio`.
- [x] **T5** | `S1-S5` | Route: `independent verifier` | Risk: `high-risk items in T1-T3` | Commit: `0e8d320` (`fix(caza): corrige spam vigilancia, bajadas Beast y dedup Sniper cross-bucket`) | Ejecutar suite completa `python test_buscador.py` (`exit 0`), verificador independiente `736b7d4..HEAD` (`T1-T3`: corregidos 3 blockers `B1-B3` + Advisories `#2-#3` y re-validado `MET` con regresiones TDD en `0e8d320`), y smoke tests en vivo consecutivos (`--once` `49.7s` -> `--once --modo-caza` `49.8s` detectando reposición `bicimarket-54682` TTL 45m -> 2.ª pasada `--once --modo-caza` `46.6s` con `0 notificadas` y `[Modo Caza] Beast sin novedades ni bajadas >= 50 €`, ranking no-BH delante de BH).
- [ ] **T6** | `S6` | Route: `inline` | Risk: `item 5 (Windows Task Scheduler delivery — requiere confirmación final)` | Commit: `pendiente docs/confirmación` (`docs: documentar modo caza Black Friday/Cyber Monday y tarea programada`) | Documentar cambios, dificultades y configuración en `README.md` y `CRON.md`, guardar decisión en Engram (`mem_save`), y tras aprobación del usuario registrar `BuscadorBiciOcasion_BlackFriday` en Windows Task Scheduler y mergear/pushear a `main`.

## Log

- **L1 (2026-11-26)**: Solicitud original del usuario verbatim: `"Mañana Black Friday y el lunes Cyber Monday estoy intentando encontrar la oferta de mi guida en la bici que quiero con esas características. La verdad que las bh no me interesan, deberían de ser en segundo plano, a no ser que una oferta sea la reostia. Y quiero que me caces el modelo nuevo o semi-nuvo. o de ocasión que haya estos días y no se te pase como podemos planificar la modificación del buscador para que encuentre ese chullo que tanto estoy buscando hazme la planificación pormenorizada Para que el modelo Hidrogen X High la pueda llevar a cabo."`
- **L2 (2026-11-26)**: Aprobación del usuario verbatim: `"me parece bien asi dejaselo todo preparado al siguiente modelo para ejecutar"`. Se congelan los umbrales de `S2`, `S3` y `S4`, se crea la rama `feat/modo-caza-black-friday` desde `main` (`736b7d4`, `python test_buscador.py` GREEN), y se registra este documento + espejo Engram `odd/modo-caza-black-friday/tasks` para ejecución directa por Gemini Hydrogen XHigh.
- **L3 (2026-11-26 — Evidencia de línea base verificada)**:
  - `main.py:944-951`: `pool_beast.sort` carece de `prioridad_marca`; `main.py:166-191`: `clave_orden_estrictas` carece de `prioridad_marca`; `gemini_classifier.py:1147-1485`: `auditar_perito_mecanico` penaliza `-2.0` a `> 3150 €` (máx `8.0/10`), haciendo matemáticamente inalcanzable `es_mega_chollo` (`notifier.py:12-24`: `pct_dto >= 50%` y `nota >= 9.0`) en el tramo `3.200–3.500 €`.
  - `scrapers/enriquecedor_web.py:42`: `FICHA_TIENDA_TTL_SEG = 6 * 3600`; `scrapers/upway.py:22-26`: página 1 fija; `scrapers/sanferbike.py:16`: `MAX_PAGINAS=2`; `scrapers/escapa.py:20`: `MAX_PAGINAS=2`; `scrapers/mammoth.py:77-78`: `precioMaximo=4200`.
  - Windows Task Scheduler: `BuscadorBiciOcasion` corre `DaysInterval: 1` a las `12:00:00` (`python.exe "G:\Proyectos OpenCode\Buscador BiciOcasion\main.py" --once`).

- **L4 (`26/11 11:36`) — Verificación independiente `odd-verifier` (`b53ddb96`) y resolución `0e8d320`**: Primera pasada confirmó `S1, S2, S5` y reportó 3 blockers reales (`B1`: entrada desde Vigilancia en `--modo-caza` sin `db.debe_reenviarse`; `B2`: `misma_busqueda` en Beast ocultando bajadas `>= 50 €` en pools `>= 6`; `B3`: duplicado Wallapop Sniper cross-bucket en Run 2) + Advisories `#2` (redondeo `44.97% -> 45%` en insignia BH) y `#3` (leak atributo `cache_precio`). Corregidos en `0e8d320` con sus tests de regresión TDD; re-chequeo acotado del verificador devolvió **MET (`RC=0`)** en `S3` y `S4`. Nota contractual sobre `S3`: `es_mega_chollo` aplica la regla flexible `(pct_dto >= 50.0 and nota >= 7.5) or (pct_dto >= 40.0 and nota >= 8.0)` exclusivamente cuando `precio > 3150.0`, preservando `pct_dto >= 50.0 and nota >= 9.0` en `<= 3150.0` por compatibilidad `S1`.
- **L5 (`26/11 11:51 - 11:54`) — Validación en vivo `--once` + `--modo-caza`**:
  1. `python main.py --once` (`49.7s`, exit `0`): 9 portales scrapeados (`179` Bike Ocasión, `112` Buhobike, `141` Mammoth, `96` Fabregues, `72` Sanferbike, `55` Bicimarket, `36` Escapa, `21` Upway, `537` Wallapop); Wallapop #1 `Orbea Rise H10 2023/24 540w Talla M` (`2.200 €`, `7.0/10`) adelantó a BH (`7.5/10`), junto con `BH ILYNX RACE CARBON LT 7.6 T-M 2022` (`Buhobike rot #2`) y `Orbea Rise H15 XT` (`Bike Ocasión #1`), más Top 3 Beast y Heartbeats.
  2. `python main.py --once --modo-caza` (pasada 1, `49.8s`, exit `0`): TTL `45m` refrescó fichas de `10:33` y detectó reposición real en talla M de `bicimarket-54682` (`BH iLynx Trail Carbon 8.8`), actualizando Top 3 Beast (`Orbea Rise H10`, `Escapa Orbea Rise SL H30 2026`, `Bicimarket BH 8.7`) con no-BH por delante de BH ordinaria, manteniendo `0 notificadas` y `0` Heartbeats en Diario.
  3. `python main.py --once --modo-caza` (pasada 2 sin cambios, `46.6s`, exit `0`): `[Modo Caza] Beast sin novedades ni bajadas >= 50 €; se omite rotación y spam` y `0 notificadas` (`0` alertas y `0` heartbeats en ambos canales).
- **L6 (`26/11 11:56`) — Documentación `T6` en rama `feat/modo-caza-black-friday` y puerta de confirmación**: Actualizados `CRON.md`, `README.md` y `docs/radar_mercado.md`. Parada explícita previa a registrar `BuscadorBiciOcasion_BlackFriday` en Windows Task Scheduler y mergear/pushear a `main`, esperando confirmación final del usuario.
