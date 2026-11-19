"""
main.py
Punto de entrada del buscador de bicicletas de ocasión.

Orquesta: scrape de los 4 sitios -> filtros estrictos -> nota de oportunidad
-> enriquecimiento de campos faltantes (ficha del sitio + web)
-> seleccion de la mejor oportunidad (umbral 8.5, fallback a la mejor nota)
-> base de datos (dedup) -> notificador Telegram.
Ejecucion diaria a las 12:00 con schedule + while True (S10).
"""

import argparse
import schedule
import time
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Optional

import config as cfg
from config import SITIOS, HORA_EJECUCION, NOTA_MIN_NOTIFICAR, NOTA_MIN_AGUARDAR, TOP_N_NOTIFICAR
from db import BaseDatos, titulos_equivalentes_dedup
from evaluator import evaluar, calcular_nota_oportunidad, pasa_filtros_estrictos, prioridad_modalidad
from gemini_classifier import enriquecer_y_valorar_bici, _es_anuncio_generico_sin_modelo
from notifier import enviar, enviar_heartbeat, es_mega_chollo
from scrapers.bike_ocasion import BikeOcasionScraper
from scrapers.buhobike import BuhobikeScraper
from scrapers.upway import UpwayScraper
from scrapers.mammoth import MammothScraper
from scrapers.wallapop import WallapopScraper
from scrapers.enriquecedor_web import enriquecer_bici, _extraer_range_extender

# Mapa sitio -> clase scraper
SCRAPERS = {
    "Bike Ocasión": BikeOcasionScraper,
    "Buhobike": BuhobikeScraper,
    "Upway": UpwayScraper,
    "Mammoth": MammothScraper,
    "Wallapop": WallapopScraper,
}

# ---------------------------------------------------------------------------
# Logging: consola + archivo logs/buscador.log
# ---------------------------------------------------------------------------
LOG_DIR = cfg.BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "buscador.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
    force=True,
)
logger = logging.getLogger("buscador")


def _health_check_scrapers() -> dict:
    """
    Health check de los scrapers (tarea 10, Fase C).

    Ejecuta cada scraper y verifica que devuelva al menos 1 producto.
    Si un devuelve 0 o falla, significa que sus selectores están rotos
    (la web cambió su HTML) y se lanza una alerta por log y Telegram.

    Devuelve un dict {nombre_sitio: cantidad_productos}.
    """
    estado: dict = {}

    for sitio in SITIOS:
        clase = SCRAPERS.get(sitio.nombre)
        if clase is None:
            logger.warning(f"[Health check] No hay scraper para {sitio.nombre}.")
            estado[sitio.nombre] = 0
            continue

        try:
            scraper = clase(sitio)
            bicis = scraper.extraer_bicicletas()
            cantidad = len(bicis)
            estado[sitio.nombre] = cantidad
            if cantidad == 0:
                logger.critical(
                    f"[Health check] {sitio.nombre} devolvió 0 productos. "
                    f"POSIBLES SELECTORES ROTOS — revisar HTML de {sitio.seccion_emtb}"
                )
                _enviar_alerta_telegram(
                    f"⚠️ *Health check fallido*\n"
                    f"Sitio: {sitio.nombre}\n"
                    f"Producto: 0 bicicletas extraídas\n"
                    f"Posibles selectores rotos en {sitio.seccion_emtb}"
                )
            else:
                logger.info(f"[Health check] {sitio.nombre}: {cantidad} productos OK.")
        except Exception as e:
            logger.critical(f"[Health check] {sitio.nombre} falló: {e}")
            estado[sitio.nombre] = 0
            _enviar_alerta_telegram(
                f"⚠️ *Health check fallido*\n"
                f"Sitio: {sitio.nombre}\n"
                f"Error: {e}"
            )

    return estado


def _enviar_alerta_telegram(texto: str) -> None:
    """Envía un mensaje de alerta por Telegram si hay credenciales configuradas."""
    if not cfg.TELEGRAM_BOT_TOKEN or not cfg.TELEGRAM_CHAT_ID:
        logger.debug("[Alerta Telegram] Credenciales no configuradas. Se omite envío.")
        return

    import requests
    url = cfg.TELEGRAM_API_URL.format(token=cfg.TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": cfg.TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info("[Alerta Telegram] Enviada.")
    except requests.RequestException as e:
        logger.error(f"[Alerta Telegram] Error enviando alerta: {e}")


def clave_orden_estrictas(item: tuple) -> tuple:
    """
    Clave de ordenación por calidad real dentro de bicicletas que pasan filtros estrictos:
      1. Salud mecánica: nota >= 6.0, km verificado <= 4.000 y modelo identificable.
      2. Sin Línea Roja activa (km <= 6.000 o no descartada, peso < 21.0 kg y no genérica).
      3. Prioridad de modalidad efectiva (para bicicletas mecánicamente sanas):
         XC / Downcountry (3) > Light e-MTB (2) > Trail (1).
      4. Mayor Nota de Oportunidad del Perito Mecánico.
      5. Prioridad de modalidad como desempate.
      6. Menor peso en kg.
    """
    bici, nota = item[0], item[1]
    km = bici.km
    peso = bici.peso_kg or 20.0
    es_generico = bool(nota <= 4.5 and _es_anuncio_generico_sin_modelo(bici))
    salud_mecanica = 1 if (nota >= 6.0 and km is not None and km <= 4000 and not es_generico) else 0
    sin_linea_roja = 1 if ((km is None or km <= 6000) and peso < 21.0 and not es_generico) else 0
    mod_prio = prioridad_modalidad(bici)
    return (
        salud_mecanica,
        sin_linea_roja,
        mod_prio if salud_mecanica else 0,
        nota,
        mod_prio,
        -peso,
    )


def _scrapear_sitio(sitio: cfg.SitioObjetivo) -> list:
    """Ejecuta el scraper de un portal individual y devuelve sus bicicletas."""
    clase = SCRAPERS.get(sitio.nombre)
    if clase is None:
        logger.warning(f"No hay scraper implementado para {sitio.nombre}. Saltando.")
        return []
    try:
        scraper = clase(sitio)
        bicis = scraper.extraer_bicicletas()
        cantidad = len(bicis)
        if cantidad == 0:
            logger.critical(
                f"[Health check] {sitio.nombre} devolvió 0 productos. "
                f"POSIBLES SELECTORES ROTOS — revisar HTML de {sitio.seccion_emtb}"
            )
        else:
            logger.info(f"[{sitio.nombre}] {cantidad} bicicletas extraídas OK.")
        return bicis
    except Exception as e:
        logger.error(f"[{sitio.nombre}] Error durante el scraping: {e}")
        return []


def deduplicar_inter_portal(bicis: list) -> list:
    """
    Elimina réplicas publicadas en Wallapop cuando el mismo modelo, talla compatible
    y rango de precio (+-25 EUR) ya existe en una tienda oficial disponible
    (Bike Ocasión, Buhobike, Upway, Mammoth), priorizando la tienda oficial.
    """
    oficiales = [b for b in bicis if (b.sitio or "").lower() != "wallapop"]
    resultado = list(oficiales)

    for b_w in bicis:
        if (b_w.sitio or "").lower() != "wallapop":
            continue
        talla_w = (b_w.talla or "").strip().upper()
        clon_de = None
        for b_of in oficiales:
            if not getattr(b_of, "disponible", True):
                continue
            talla_of = (b_of.talla or "").strip().upper()
            if talla_of and talla_w and talla_of != talla_w:
                continue
            if abs(float(b_of.precio) - float(b_w.precio)) <= 25.0 and titulos_equivalentes_dedup(
                b_of.titulo, b_w.titulo
            ):
                clon_de = b_of
                break
        if clon_de is not None:
            logger.info(
                f"  [Dedup inter-portal] Omitiendo clon Wallapop '{b_w.titulo}' ({b_w.precio:.0f} €) "
                f"— ya presente en {clon_de.sitio} ({clon_de.precio:.0f} €)."
            )
            continue
        resultado.append(b_w)

    return resultado


def _recolectar_oportunidades(
    db: BaseDatos,
    forzar_envio: bool = False,
    telemetria: Optional[dict] = None,
) -> list:
    """
    Recorre los sitios objetivo en paralelo (con health check integrado),
    pre-filtra candidatas, deduplica clones inter-portal (tienda oficial vs Wallapop),
    enriquece y valora con el clasificador híbrido
    (ficha del sitio + catálogo + DuckDuckGo cacheado + Gemini Flash / motor autónomo),
    y aplica los filtros estrictos S1-S6 post-enriquecimiento.

    Devuelve una lista de (bici, nota, desglose) ordenada por relevancia:
      1. Estrictas (< 21 kg) nuevas o que bajaron de precio.
      2. Estrictas (< 21 kg) vigentes en stock (para completar Top N antes que meter >= 21 kg).
      3. Candidatas cercanas por peso nuevas.
      4. Candidatas cercanas por peso vigentes.
    """
    bicis_brutas = []
    conteo_por_portal: Dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=len(SITIOS)) as pool_sitios:
        futuros_sitios = {
            pool_sitios.submit(_scrapear_sitio, sitio): sitio
            for sitio in SITIOS
        }
        for futuro_s in as_completed(futuros_sitios):
            sitio = futuros_sitios[futuro_s]
            try:
                bicis = futuro_s.result()
                conteo_por_portal[sitio.nombre] = len(bicis)
                bicis_brutas.extend(bicis)
            except Exception as e:
                logger.error(f"[{sitio.nombre}] Excepción en worker de scraping: {e}")
                conteo_por_portal[sitio.nombre] = 0

    pre_aptas = []
    vigilancia_aptas = []

    for bici in bicis_brutas:
        if bici.range_extender_wh is None:
            ext = _extraer_range_extender(f"{bici.titulo} {bici.componentes or ''}")
            if ext:
                bici.range_extender_wh = ext
                if bici.bateria_wh is not None and bici.bateria_wh <= 600:
                    bici.bateria_wh += ext
        # Registrar en Zona de Vigilancia bicicletas aptas entre 3.301 € y 3.500 €
        if 3300.0 < bici.precio <= 3500.0:
            from dataclasses import replace
            bici_test_vig = replace(bici, precio=3000.0)
            apto_vig, _ = pasa_filtros_estrictos(bici_test_vig)
            if apto_vig:
                vigilancia_aptas.append(bici)

        # Pre-filtro rápido antes de deduplicar para que una talla L/XL oficial nunca tape una M de Wallapop
        apto_pre, motivo_pre = pasa_filtros_estrictos(bici)
        if not apto_pre:
            logger.debug(f"  DESCARTADA PRE [{bici.sitio}]: {bici.titulo} - {motivo_pre}")
            continue
        pre_aptas.append(bici)

    for b_vig in deduplicar_inter_portal(vigilancia_aptas):
        db.registrar_en_catalogo(b_vig)

    candidatas_pre = deduplicar_inter_portal(pre_aptas)
    for b_cand in candidatas_pre:
        db.registrar_en_catalogo(b_cand)

    if not candidatas_pre:
        if telemetria is not None:
            telemetria["conteo_por_portal"] = conteo_por_portal
            telemetria["total_procesadas"] = sum(conteo_por_portal.values())
            telemetria["candidatas_pre"] = 0
            telemetria["candidatas_aptas"] = 0
        return []

    logger.info(f"[IA/Enriquecedor] Analizando y completando {len(candidatas_pre)} candidatas pre-filtradas...")

    estrictas_pool = []
    respaldo_pool = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futuros = {
            executor.submit(enriquecer_y_valorar_bici, bici): bici
            for bici in candidatas_pre
        }
        for futuro in as_completed(futuros):
            bici_orig = futuros[futuro]
            try:
                bici, nota, desglose = futuro.result()
            except Exception as e:
                logger.warning(f"[IA/Enriquecedor] Error en {bici_orig.titulo}: {e}")
                nota, desglose = calcular_nota_oportunidad(bici_orig)
                bici = bici_orig

            # Verificar disponibilidad, Talla M, Doble Suspensión, Batería > 500 Wh y Precio 2.000-3.300 €
            if getattr(bici, "disponible", True) is False:
                continue
            if bici.talla and bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
                continue
            if bici.bateria_wh is not None and bici.bateria_wh <= cfg.BATERIA_MIN_WH:
                continue
            if bici.suspension_trasera is not None and str(bici.suspension_trasera).lower() in ("false", "no", "0"):
                continue
            if not (cfg.PRECIO_MIN_EUR <= bici.precio <= cfg.PRECIO_MAX_EXCEPCIONAL_EUR):
                continue

            if (bici.sitio or "").lower() == "wallapop" and db.fue_enviada_equivalente(bici):
                logger.info(
                    f"  [Dedup inter-portal] Omitiendo clon Wallapop ya notificado desde tienda oficial: '{bici.titulo}'"
                )
                continue

            es_nueva = forzar_envio or db.debe_reenviarse(bici, nota)
            apto_pre, motivo_post = pasa_filtros_estrictos(bici)

            if apto_pre:
                estrictas_pool.append((bici, nota, desglose, es_nueva))
            else:
                logger.info(f"  [Candidata cercana] {bici.titulo}: {motivo_post} (Nota {nota}/10)")
                respaldo_pool.append((bici, nota, desglose, es_nueva))

    # Ordenar estrictas (< 21 kg) por calidad real (novedad solo desempata a igualdad exacta)
    estrictas_pool.sort(key=lambda x: (clave_orden_estrictas(x[:3]), 1 if x[3] else 0), reverse=True)

    # Ordenar respaldo priorizando modelo identificable, mayor nota, XC y menor peso
    clave_orden_respaldo = lambda x: (
        1 if not (x[1] <= 4.5 and _es_anuncio_generico_sin_modelo(x[0])) else 0,
        x[1],
        prioridad_modalidad(x[0]),
        -(x[0].peso_kg or 25.0),
        1 if x[3] else 0,
    )
    respaldo_pool.sort(key=clave_orden_respaldo, reverse=True)

    seleccion = [
        (b, n, d) for (b, n, d, _) in (estrictas_pool + respaldo_pool)
    ]

    if telemetria is not None:
        telemetria["conteo_por_portal"] = conteo_por_portal
        telemetria["total_procesadas"] = sum(conteo_por_portal.values())
        telemetria["candidatas_pre"] = len(candidatas_pre)
        telemetria["candidatas_aptas"] = len(seleccion)

    return seleccion


def exportar_radar_mercado_md(
    ruta: Optional[Path] = None,
    db: Optional[BaseDatos] = None,
) -> Path:
    """
    Exporta automáticamente el informe de Radar de Mercado en Markdown (docs/radar_mercado.md).
    Incluye métricas de permanencia en stock (días), ahorro medio en rebajas y comparación vs PVP original.
    """
    db_inst = db if db is not None else BaseDatos()
    stats = db_inst.obtener_estadisticas_mercado()
    destino = Path(ruta) if ruta is not None else (cfg.BASE_DIR / "docs" / "radar_mercado.md")
    destino.parent.mkdir(parents=True, exist_ok=True)

    ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = stats.get("total", 0)
    res_global = stats.get("resumen_global", {})
    metricas_sitios = stats.get("metricas_por_sitio", {})

    dias_global = res_global.get("dias_stock_medio", 0.0)
    p_medio_global = res_global.get("precio_medio", 0.0)
    total_rebajas = res_global.get("con_rebajas", len(stats.get("con_rebajas", [])))
    ahorro_medio_rebajas = res_global.get("ahorro_medio_rebajas", 0.0)
    total_vigilancia = res_global.get("en_vigilancia", len(stats.get("en_vigilancia", [])))

    lineas = [
        "# 📡 Radar de Mercado e-MTB de Ocasión",
        "",
        f"> **Última actualización:** `{ahora}`  ",
        f"> **Total en seguimiento activo:** `{total}` unidades | **Permanencia media global:** `{dias_global:.1f} días`  ",
        f"> **Oportunidades con rebaja activa:** `{total_rebajas}` unidades (Ahorro medio: `-{ahorro_medio_rebajas:.0f} €`) | **Zona de Vigilancia:** `{total_vigilancia}` unidades",
        "",
        "---",
        "",
        "## 🏪 1. Distribución por Portal y Permanencia",
        "",
    ]

    if stats.get("por_sitio"):
        lineas.extend([
            "| Portal | Unidades | Cuota (%) | Días en Stock (medio) | Precio Medio | Ahorro Medio Rebajas |",
            "| :--- | :---: | :---: | :---: | :---: | :---: |",
        ])
        for sitio, cant in sorted(stats["por_sitio"].items(), key=lambda x: x[1], reverse=True):
            m = metricas_sitios.get(sitio, {})
            pct = m.get("cuota_pct", (cant / total * 100.0) if total > 0 else 0.0)
            dias_medio = m.get("dias_stock_medio", 0.0)
            p_med = m.get("precio_medio", 0.0)
            con_reb = m.get("con_rebajas", 0)
            ahorro_m = m.get("ahorro_medio_rebajas", 0.0)
            dto_pvp = m.get("descuento_pvp_medio_pct")

            ahorro_txt = f"-{ahorro_m:.0f} €" if con_reb > 0 else "-"
            if dto_pvp is not None:
                ahorro_txt += f" (~{dto_pvp:.0f}% vs PVP)"

            lineas.append(
                f"| **{sitio}** | {cant} | {pct:.1f}% | {dias_medio:.1f}d | {p_med:.0f} € | {ahorro_txt} |"
            )
    else:
        lineas.append("_Sin bicicletas registradas en el catálogo._")

    lineas.extend([
        "",
        "## 🎯 2. Modelos Clave de e-MTB Ligera",
        "",
    ])

    if stats.get("modelos_clave"):
        lineas.extend([
            "| Familia / Modelo | Unidades | Precio Mínimo | Precio Medio | Permanencia Media |",
            "| :--- | :---: | :---: | :---: | :---: |",
        ])
        for modelo, info in stats["modelos_clave"].items():
            p_min = f"{info['precio_min']:.0f} €" if info.get("precio_min") else "-"
            p_med = f"{info['precio_medio']:.0f} €" if info.get("precio_medio") else "-"
            d_med = f"{info.get('dias_stock_medio', 0.0):.1f}d"
            lineas.append(f"| **{modelo}** | {info['unidades']} | {p_min} | {p_med} | {d_med} |")
    else:
        lineas.append("_No hay unidades activas de las familias clave en este momento._")

    lineas.extend([
        "",
        "## 📉 3. Oportunidades con Bajada de Precio Detectada",
        "",
    ])

    if stats.get("con_rebajas"):
        lineas.extend([
            "| Bicicleta | Portal | Precio Actual | Precio Inicial | Ahorro | Días en Stock |",
            "| :--- | :---: | :---: | :---: | :---: | :---: |",
        ])
        for r in stats["con_rebajas"]:
            badge = " 🚨" if r.get("entrada_vigilancia") else ""
            lineas.append(
                f"| [{r['titulo']}]({r['url']}){badge} | {r['sitio']} | "
                f"**{r['precio_actual']:.0f} €** | ~{r['precio_inicial']:.0f} €~ | "
                f"**-{r['ahorro']:.0f} €** | {r['dias']}d |"
            )
    else:
        lineas.append("_Todavía no se han acumulado bajadas de precio respecto al registro inicial._")

    lineas.extend([
        "",
        "## 👀 4. Zona de Vigilancia (2.900 € – 3.500 € esperando rebaja)",
        "",
    ])

    if stats.get("en_vigilancia"):
        lineas.extend([
            "| Bicicleta | Portal | Precio Actual | Días en Stock |",
            "| :--- | :---: | :---: | :---: |",
        ])
        for v in stats["en_vigilancia"]:
            lineas.append(
                f"| [{v['titulo']}]({v['url']}) | {v['sitio']} | "
                f"**{v['precio']:.0f} €** | {v['dias']}d |"
            )
    else:
        lineas.append("_Sin bicicletas en la franja de vigilancia actualmente._")

    lineas.append("")
    destino.write_text("\n".join(lineas), encoding="utf-8")
    return destino


def seleccionar_por_portal(
    oportunidades: list,
    ultimo_analisis: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Selecciona exactamente 1 bicicleta por cada página con candidatas disponibles,
    aplicando rotación ping-pong diaria por página (#1 -> #2 -> #1) si su #1 no cambió:
      - Día 1 (o #1 nuevo): envía #1 real de esa página.
      - Día 2 (misma #1 que ayer y >= 2 candidatas válidas): envía #2 con aviso.
      - Día 3 (sigue misma #1 tras alternar al #2): vuelve a #1 confirmando liderazgo.
    """
    orden_sitios = [s.nombre for s in SITIOS]
    for b, _, _ in oportunidades:
        if b.sitio not in orden_sitios:
            orden_sitios.append(b.sitio)

    estado_previo = (ultimo_analisis or {}).get("estado_portales") or {}
    nuevo_estado_portales: Dict[str, Dict[str, Any]] = {}
    seleccionados_raw = []
    top1_ids_por_portal = []

    for sitio in orden_sitios:
        vistos_sitio = set()
        items_sitio = []
        for op in oportunidades:
            if op[0].sitio == sitio and op[0].bici_id not in vistos_sitio:
                vistos_sitio.add(op[0].bici_id)
                items_sitio.append(op)
        if not items_sitio:
            continue

        estrictas_sitio = [op for op in items_sitio if pasa_filtros_estrictos(op[0])[0]]
        estrictas_no_gen = [
            op for op in estrictas_sitio
            if op[1] > 4.5 or not _es_anuncio_generico_sin_modelo(op[0])
        ]
        respaldo_sitio = [op for op in items_sitio if not pasa_filtros_estrictos(op[0])[0]]

        if estrictas_no_gen:
            pool_sitio = estrictas_no_gen
            es_estricta_pool = True
        elif estrictas_sitio:
            pool_sitio = estrictas_sitio[:1]
            es_estricta_pool = False
        elif respaldo_sitio:
            pool_sitio = respaldo_sitio[:1]
            es_estricta_pool = False
        else:
            continue

        top1_item = pool_sitio[0]
        top1_id = top1_item[0].bici_id
        top1_ids_por_portal.append(top1_id)

        prev = estado_previo.get(sitio)
        if prev and prev.get("top1_id") == top1_id:
            if prev.get("enviado_id") == top1_id and len(pool_sitio) >= 2 and es_estricta_pool:
                elegido = pool_sitio[1]
                pos = 2
                es_rot2 = True
                retorno_top1 = False
            else:
                elegido = top1_item
                pos = 1
                es_rot2 = False
                retorno_top1 = bool(prev.get("enviado_id") != top1_id and len(pool_sitio) >= 2)
        else:
            elegido = top1_item
            pos = 1
            es_rot2 = False
            retorno_top1 = False

        nuevo_estado_portales[sitio] = {
            "top1_id": top1_id,
            "enviado_id": elegido[0].bici_id,
            "posicion": pos,
        }
        seleccionados_raw.append({
            "sitio": sitio,
            "item": elegido,
            "posicion": pos,
            "es_rot2": es_rot2,
            "retorno_top1": retorno_top1,
            "es_estricta": es_estricta_pool,
        })

    # Ordenar envíos: portales con opciones válidas <21 kg primero, luego por calidad real
    seleccionados_raw.sort(
        key=lambda x: (1 if x["es_estricta"] else 0, clave_orden_estrictas(x["item"])),
        reverse=True,
    )

    return {
        "seleccionados": seleccionados_raw,
        "estado_portales": nuevo_estado_portales,
        "top1_ids": top1_ids_por_portal,
        "portales_rotados": [x["sitio"] for x in seleccionados_raw if x["es_rot2"]],
        "portales_retorno_top1": [x["sitio"] for x in seleccionados_raw if x["retorno_top1"]],
    }


def ejecutar_busqueda(forzar_envio: bool = False) -> None:
    """Ejecuta una pasada completa de búsqueda, valoración pericial y entrega 1 opción por página."""
    t_inicio = time.time()
    logger.info(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando búsqueda de e-MTB...")

    db = BaseDatos()
    telemetria_ejecucion: Dict[str, Any] = {}
    oportunidades = _recolectar_oportunidades(db, forzar_envio=forzar_envio, telemetria=telemetria_ejecucion)

    try:
        ruta_md = exportar_radar_mercado_md(db=db)
        logger.info(f"[Radar] Informe de mercado actualizado en {ruta_md}")
    except Exception as e:
        logger.warning(f"[Radar] No se pudo exportar docs/radar_mercado.md: {e}")

    total_notificadas = 0
    mega_chollos_count = 0
    aviso_top_repetido = False
    portales_rotados = []
    portales_retorno_top1 = []

    ultimo_analisis = db.obtener_ultimo_analisis()
    estado_portales_previo = (ultimo_analisis or {}).get("estado_portales") or {}

    if oportunidades:
        for op in oportunidades:
            b_op, n_op = op[0], op[1]
            if es_mega_chollo(b_op, n_op):
                mega_chollos_count += 1

        plan = seleccionar_por_portal(oportunidades, ultimo_analisis=ultimo_analisis)
        seleccionados = plan["seleccionados"]
        nuevo_estado_portales = plan["estado_portales"]
        top1_ids_por_portal = plan["top1_ids"]

        mejor_nota = max((x["item"][1] for x in seleccionados), default=0.0)
        logger.info(
            f"[main] Seleccionada(s) {len(seleccionados)} bici(s) (1 por página con stock) "
            f"| mejor nota: {mejor_nota}/10 | Mega Chollos en pool: {mega_chollos_count} "
            f"| rotación #2 prevista: {plan['portales_rotados'] or 'ninguna'} "
            f"| retorno #1 previsto: {plan['portales_retorno_top1'] or 'ninguno'}."
        )

        enviados_ids = []
        estado_portales_confirmado = dict(estado_portales_previo)
        for entry in seleccionados:
            sitio_entry = entry["sitio"]
            bici, nota, desglose = entry["item"]
            pos_portal = entry["posicion"]
            es_rot2 = entry["es_rot2"]
            ret_top1 = entry["retorno_top1"]
            precio_anterior = db.precio_previo(bici.bici_id)
            seguimiento = db.obtener_seguimiento(bici.bici_id)
            es_mega = es_mega_chollo(bici, nota)
            tag_mega = " [💥 MEGA CHOLLO]" if es_mega else ""

            if enviar(
                bici,
                nota,
                desglose,
                precio_anterior=precio_anterior,
                seguimiento=seguimiento,
                aviso_top_repetido=es_rot2,
                ranking_posicion=pos_portal,
                es_rotacion_portal=es_rot2,
                aviso_retorno_top1=ret_top1,
            ):
                db.registrar(bici, nota, precio_anterior=precio_anterior)
                enviados_ids.append(bici.bici_id)
                estado_portales_confirmado[sitio_entry] = nuevo_estado_portales[sitio_entry]
                if es_rot2:
                    portales_rotados.append(sitio_entry)
                elif ret_top1:
                    portales_retorno_top1.append(sitio_entry)
                total_notificadas += 1
                estado_tag = " (rot #2)" if es_rot2 else (" (retorno #1)" if ret_top1 else " (#1)")
                logger.info(
                    f"  NOTIFICADA [{bici.sitio}{estado_tag}]: {bici.titulo} "
                    f"({bici.peso_kg} kg) - Nota {nota}/10{tag_mega}"
                )

        aviso_top_repetido = bool(portales_rotados)
        db.registrar_analisis(
            top3_ids=top1_ids_por_portal,
            enviados_ids=enviados_ids,
            offset_usado=0,
            repetido=aviso_top_repetido,
            estado_portales=estado_portales_confirmado,
        )
    else:
        logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                    "No se encontraron bicis aptas en ninguno de los sitios.\n")
        db.registrar_analisis(
            top3_ids=[],
            enviados_ids=[],
            offset_usado=0,
            repetido=False,
            estado_portales=estado_portales_previo,
        )

    duracion_seg = round(time.time() - t_inicio, 1)
    stats_radar = db.obtener_estadisticas_mercado()

    # Heartbeat a Telegram: si está configurado, o si se forzó la búsqueda
    if cfg.TELEGRAM_HEARTBEAT or forzar_envio:
        resumen_hb = {
            "fecha_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duracion_seg": duracion_seg,
            "conteo_por_portal": telemetria_ejecucion.get("conteo_por_portal", {}),
            "total_procesadas": telemetria_ejecucion.get("total_procesadas", 0),
            "candidatas_aptas": len(oportunidades),
            "notificadas": total_notificadas,
            "mega_chollos": mega_chollos_count,
            "top_repetido": aviso_top_repetido,
            "offset_usado": 0,
            "portales_rotados": portales_rotados,
            "portales_retorno_top1": portales_retorno_top1,
            "total_en_catalogo": stats_radar.get("total", 0),
            "total_en_vigilancia": len(stats_radar.get("en_vigilancia", [])),
            "estado": "🟢 Runner operativo" if telemetria_ejecucion.get("total_procesadas", 0) > 0 else "⚠️ Sin bicicletas procesadas",
        }
        enviar_heartbeat(resumen_hb)

    logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Finalizado en {duracion_seg}s. "
                f"{len(oportunidades)} candidatas aptas, {total_notificadas} notificadas.\n")


def mostrar_radar_mercado() -> None:
    """Imprime la radiografía del mercado de e-MTB basada en el catálogo rastreado (TODO 3)."""
    db = BaseDatos()
    stats = db.obtener_estadisticas_mercado()
    ruta_md = exportar_radar_mercado_md(db=db)
    res_global = stats.get("resumen_global", {})
    metricas_sitios = stats.get("metricas_por_sitio", {})

    print("\n" + "=" * 70)
    print(" 📡 RADAR DE MERCADO e-MTB DE OCASIÓN (ESTADÍSTICAS)")
    print("=" * 70)
    print(f"Total bicicletas en seguimiento activo: {stats['total']}")
    print(f"Permanencia media global en stock: {res_global.get('dias_stock_medio', 0.0):.1f} días")
    print(f"Precio medio global de catálogo: {res_global.get('precio_medio', 0.0):.0f} €")
    print(f"Informe Markdown exportado en: {ruta_md}")

    if stats["por_sitio"]:
        print("\n🏪 Distribución y permanencia por portal:")
        print(f"  {'Portal':16} | {'Uds':4} | {'Días Stock':10} | {'P. Medio':9} | {'Ahorro Rebajas':14}")
        print("  " + "-" * 62)
        for sitio, cant in sorted(stats["por_sitio"].items(), key=lambda x: x[1], reverse=True):
            m = metricas_sitios.get(sitio, {})
            d_med = f"{m.get('dias_stock_medio', 0.0):.1f}d"
            p_med = f"{m.get('precio_medio', 0.0):.0f} €"
            ahorro_m = f"-{m.get('ahorro_medio_rebajas', 0.0):.0f} €" if m.get("con_rebajas", 0) > 0 else "-"
            print(f"  {sitio:16} | {cant:4} | {d_med:>10} | {p_med:>9} | {ahorro_m:>14}")

    if stats["modelos_clave"]:
        print("\n🎯 Modelos Clave de e-MTB Ligera:")
        print(f"  {'Modelo':22} | {'Uds':4} | {'Mínimo':9} | {'P. Medio':10} | {'Días Stock':10}")
        print("  " + "-" * 65)
        for modelo, info in stats["modelos_clave"].items():
            p_min = f"{info['precio_min']:.0f} €" if info['precio_min'] else "-"
            p_med = f"{info['precio_medio']:.0f} €" if info['precio_medio'] else "-"
            d_med = f"{info.get('dias_stock_medio', 0.0):.1f}d"
            print(f"  {modelo:22} | {info['unidades']:4} | {p_min:>9} | {p_med:>10} | {d_med:>10}")

    if stats["con_rebajas"]:
        print(f"\n📉 Oportunidades con Bajada de Precio ({len(stats['con_rebajas'])} detectadas):")
        for r in stats["con_rebajas"][:5]:
            print(f"  • {r['titulo']} ({r['sitio']})")
            print(f"    Precio: {r['precio_actual']:.0f} € (Antes: {r['precio_inicial']:.0f} € | Ahorro: -{r['ahorro']:.0f} € | {r['dias']} días en stock)")

    if stats["en_vigilancia"]:
        print(f"\n👀 Zona de Vigilancia (2.900 € - 3.500 € esperando rebaja, {len(stats['en_vigilancia'])} unidades):")
        for v in stats["en_vigilancia"][:5]:
            print(f"  • {v['titulo']} — {v['precio']:.0f} € ({v['sitio']}) [{v['dias']} días en stock]")

    print("=" * 70 + "\n")


def main() -> None:
    """Punto de entrada CLI: soporta ejecución única (--once), radar (--stats) o bucle diario a las 12:00 (S10)."""
    parser = argparse.ArgumentParser(description="Buscador de e-MTB de Ocasión")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Ejecuta una sola búsqueda inmediatamente y termina (ideal para Task Scheduler).",
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Fuerza el envío del Top 3 aunque ya figuren en bicis_enviadas.db.",
    )
    parser.add_argument(
        "--stats",
        "--radar",
        action="store_true",
        dest="stats",
        help="Muestra informe de radar de mercado a partir del historial de catálogo.",
    )
    parser.add_argument(
        "--heartbeat",
        action="store_true",
        help="Envía un heartbeat de prueba con el estado del runner y del radar a Telegram.",
    )
    args = parser.parse_args()

    if args.heartbeat:
        db = BaseDatos()
        stats = db.obtener_estadisticas_mercado()
        resumen_hb = {
            "fecha_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duracion_seg": 0.0,
            "conteo_por_portal": stats.get("por_sitio", {}),
            "total_procesadas": stats.get("total", 0),
            "candidatas_aptas": len(stats.get("con_rebajas", [])),
            "notificadas": 0,
            "total_en_catalogo": stats.get("total", 0),
            "total_en_vigilancia": len(stats.get("en_vigilancia", [])),
            "estado": "🟢 Test manual de Heartbeat",
        }
        enviar_heartbeat(resumen_hb)
        return

    if args.stats:
        mostrar_radar_mercado()
        return

    if args.once:
        ejecutar_busqueda(forzar_envio=args.forzar)
        return

    logger.info(f"Buscador de e-MTB iniciado. Ejecucion diaria a las {HORA_EJECUCION}.")
    logger.info("Presiona Ctrl+C para detener.")

    ejecutar_busqueda(forzar_envio=args.forzar)
    schedule.every().day.at(HORA_EJECUCION).do(ejecutar_busqueda)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
