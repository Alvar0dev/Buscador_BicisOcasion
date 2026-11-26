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
import os
import schedule
import time
import logging
from contextlib import contextmanager
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Optional

LOCK_FILE_PATH: Path = Path(__file__).resolve().parent / "cache" / "buscador.lock"


@contextmanager
def _adquirir_lock_ejecucion(
    lock_path: Optional[Path] = None,
    stale_seg: Optional[int] = None,
):
    """
    Evita ejecuciones concurrentes (p. ej. tarea diaria 12:00 vs --modo-caza cada 2h)
    mediante creación atómica de fichero lock con expiración segura para locks huérfanos.
    """
    ruta = Path(lock_path) if lock_path is not None else LOCK_FILE_PATH
    timeout_stale = int(stale_seg if stale_seg is not None else getattr(cfg, "BUSCADOR_LOCK_STALE_SEG", 15 * 60))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    adquirido = False

    for intento in range(2):
        try:
            fd = os.open(str(ruta), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"{os.getpid()}|{int(time.time())}".encode("utf-8"))
            finally:
                os.close(fd)
            adquirido = True
            break
        except FileExistsError:
            try:
                edad_seg = time.time() - ruta.stat().st_mtime
                if edad_seg > timeout_stale and intento == 0:
                    logger.warning(
                        f"[Lock] Lock huérfano expirado ({edad_seg:.0f}s > {timeout_stale}s) en {ruta}; limpiando."
                    )
                    ruta.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            logger.warning(f"[Lock] Otra instancia en ejecución ({ruta}); abortando pasada para evitar colisión.")
            break

    try:
        yield adquirido
    finally:
        if adquirido:
            try:
                ruta.unlink(missing_ok=True)
            except OSError:
                pass

import config as cfg
from config import SITIOS, HORA_EJECUCION, NOTA_MIN_NOTIFICAR, NOTA_MIN_AGUARDAR, TOP_N_NOTIFICAR
from db import BaseDatos, titulos_equivalentes_dedup
from dataclasses import replace
from evaluator import (
    evaluar,
    calcular_nota_oportunidad,
    pasa_filtros_estrictos,
    prioridad_modalidad,
    prioridad_marca,
    pasa_prefiltro_black_friday,
    evaluar_oportunidad_black_friday,
    pasa_prefiltro_respaldo_black_friday,
    evaluar_respaldo_black_friday,
    evaluar_chollo_sniper,
    calcular_descuento_pvp_pct,
    es_bici_bh,
    es_bh_irrechazable,
    es_bici_de_ocasion,
    es_modalidad_mtb_doble_valida,
    es_modalidad_xc,
    es_modelo_trail_o_enduro,
    es_unicornio_xc,
)
from gemini_classifier import (
    enriquecer_y_valorar_bici,
    completar_con_catalogo,
    _es_anuncio_generico_sin_modelo,
)
from notifier import (
    enviar,
    enviar_black_friday,
    enviar_informe_respaldo_black_friday,
    enviar_alerta_sniper,
    enviar_heartbeat,
    enviar_heartbeat_black_friday,
    es_mega_chollo,
)
from scrapers.bike_ocasion import BikeOcasionScraper
from scrapers.buhobike import BuhobikeScraper
from scrapers.upway import UpwayScraper
from scrapers.mammoth import MammothScraper
from scrapers.wallapop import WallapopScraper
from scrapers.sanferbike import SanferbikeScraper
from scrapers.bicimarket import BicimarketScraper
from scrapers.escapa import EscapaScraper
from scrapers.fabregues import FabreguesScraper
from scrapers.enriquecedor_web import enriquecer_bici, _extraer_range_extender

# Mapa sitio -> clase scraper
SCRAPERS = {
    "Bike Ocasión": BikeOcasionScraper,
    "Buhobike": BuhobikeScraper,
    "Upway": UpwayScraper,
    "Mammoth": MammothScraper,
    "Wallapop": WallapopScraper,
    "Sanferbike": SanferbikeScraper,
    "Bicimarket": BicimarketScraper,
    "Escapa": EscapaScraper,
    "Fabregues": FabreguesScraper,
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
        prioridad_marca(bici),
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
            diff_precio = float(b_w.precio) - float(b_of.precio)
            mismo_km_clon = (
                b_of.km is not None
                and b_w.km is not None
                and b_of.km > 0
                and b_of.km == b_w.km
                and 0.0 <= diff_precio <= 160.0
            )
            if (abs(diff_precio) <= 25.0 or mismo_km_clon) and titulos_equivalentes_dedup(
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
    bf_extra_pre = []
    bf_respaldo_pre = []
    vigilancia_aptas = []
    sniper_ocasion_pre = []

    for bici in bicis_brutas:
        if bici.range_extender_wh is None:
            ext = _extraer_range_extender(f"{bici.titulo} {bici.componentes or ''}")
            if ext:
                bici.range_extender_wh = ext
                if bici.bateria_wh is not None and bici.bateria_wh <= 600:
                    bici.bateria_wh += ext
        b_pre = completar_con_catalogo(replace(bici), aplicar_heuristica_peso=False)
        es_ocasion_o_wallapop_pre = es_bici_de_ocasion(b_pre) or (b_pre.sitio or "").lower() == "wallapop"
        # Registrar en Zona de Vigilancia bicicletas XC aptas entre 3.301 € y 3.500 €
        # y capturar para Sniper Light e-MTB de ocasión en esa banda sin alterar el techo diario 3.300 €.
        if 3300.0 < bici.precio <= 3500.0:
            bici_test_vig = replace(b_pre, precio=3000.0)
            apto_vig, _ = pasa_filtros_estrictos(bici_test_vig)
            if apto_vig:
                vigilancia_aptas.append(bici)
            elif getattr(cfg, "SNIPER_ACTIVO", True) and es_ocasion_o_wallapop_pre:
                apto_sn_pre, _ = pasa_filtros_estrictos(bici_test_vig, permitir_trail_respaldo=True)
                if apto_sn_pre and prioridad_modalidad(b_pre) >= 2:
                    sniper_ocasion_pre.append(bici)

        # Pre-filtro rápido usando catálogo local antes de deduplicar o enriquecer:
        # En portales de ocasión/segunda mano y Wallapop admite también Trail ligera / MTB (< 21 kg, > 500 Wh)
        # ordenadas por clave_orden_estrictas (XC [3] > Trail ligera [2] > MTB [1]).
        apto_pre, motivo_pre = pasa_filtros_estrictos(
            b_pre, permitir_trail_respaldo=es_ocasion_o_wallapop_pre
        )
        if apto_pre:
            pre_aptas.append(bici)
            continue

        apto_bf_pre, _ = pasa_prefiltro_black_friday(b_pre)
        if apto_bf_pre:
            bf_extra_pre.append(bici)
            continue

        apto_resp_pre, _ = pasa_prefiltro_respaldo_black_friday(b_pre)
        if apto_resp_pre:
            bf_respaldo_pre.append(bici)
            continue

        logger.debug(f"  DESCARTADA PRE [{bici.sitio}]: {bici.titulo} - {motivo_pre}")

    vigilancia_dedup = deduplicar_inter_portal(vigilancia_aptas)
    vigilancia_ids = {b.bici_id for b in vigilancia_dedup}

    # Deduplicar por separado flujo diario y extras exclusivos BF para que un modelo
    # >3.300 EUR o 500 Wh de tienda nunca suprima un Wallapop elegible en flujo diario.
    pre_aptas_dedup = deduplicar_inter_portal(pre_aptas)
    ids_pre_dedup = {b.bici_id for b in pre_aptas_dedup}
    bf_extra_dedup = deduplicar_inter_portal(bf_extra_pre)
    bf_extra_unicas = [b for b in bf_extra_dedup if b.bici_id not in ids_pre_dedup]
    candidatas_pre = pre_aptas_dedup + bf_extra_unicas
    ids_catalogo_base = {b.bici_id for b in candidatas_pre}

    bf_respaldo_dedup = deduplicar_inter_portal(bf_respaldo_pre)
    bf_respaldo_unicas = [b for b in bf_respaldo_dedup if b.bici_id not in ids_catalogo_base]
    ids_enriquecer = ids_catalogo_base | {b.bici_id for b in bf_respaldo_unicas}
    vigilancia_extra = [b for b in vigilancia_dedup if b.bici_id not in ids_enriquecer]
    ids_enriquecer = ids_enriquecer | {b.bici_id for b in vigilancia_extra}
    sniper_dedup = deduplicar_inter_portal(sniper_ocasion_pre)
    sniper_unicas = [b for b in sniper_dedup if b.bici_id not in ids_enriquecer]
    todos_enriquecer = candidatas_pre + bf_respaldo_unicas + vigilancia_extra + sniper_unicas

    if not todos_enriquecer:
        if telemetria is not None:
            telemetria["conteo_por_portal"] = conteo_por_portal
            telemetria["total_procesadas"] = sum(conteo_por_portal.values())
            telemetria["candidatas_pre"] = 0
            telemetria["candidatas_aptas"] = 0
            telemetria["black_friday_pool"] = []
            telemetria["black_friday_respaldo_pool"] = []
            telemetria["black_friday_suplemento_pool"] = []
            telemetria["sniper_pool"] = []
        return []

    logger.info(
        f"[IA/Enriquecedor] Analizando y completando {len(todos_enriquecer)} candidatas pre-filtradas "
        f"({len(bf_respaldo_unicas)} extra fuera de tope para respaldo Top 3)..."
    )

    estrictas_pool = []
    respaldo_pool = []
    black_friday_pool = []
    black_friday_respaldo_pool = []
    black_friday_suplemento_pool = []
    sniper_pool = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        futuros = {
            executor.submit(enriquecer_y_valorar_bici, bici): bici
            for bici in todos_enriquecer
        }
        for futuro in as_completed(futuros):
            bici_orig = futuros[futuro]
            try:
                bici, nota, desglose = futuro.result()
            except Exception as e:
                logger.warning(f"[IA/Enriquecedor] Error en {bici_orig.titulo}: {e}")
                nota, desglose = calcular_nota_oportunidad(bici_orig)
                bici = bici_orig

            # Verificar disponibilidad, Talla M y Doble Suspensión
            if getattr(bici, "disponible", True) is False:
                continue
            if bici.talla and bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
                continue
            if bici.suspension_trasera is not None and str(bici.suspension_trasera).lower() in ("false", "no", "0"):
                continue

            # Leer precio previo ANTES de actualizar historial_catalogo en este barrido
            precio_previo_sniper = (
                db.obtener_precio_previo_global(bici.bici_id)
                if hasattr(db, "obtener_precio_previo_global")
                else None
            )
            if getattr(cfg, "SNIPER_ACTIVO", True):
                ok_sn, mot_sn = evaluar_chollo_sniper(bici, nota, precio_previo=precio_previo_sniper)
                if ok_sn:
                    sniper_pool.append((bici, nota, mot_sn, precio_previo_sniper))

            # Evaluar elegibilidad Black Bike Beast (nuevas y seminuevas <= 3.500 €, respaldo <= 4.000 €,
            # batería > 500 Wh, < 21 kg, doble suspensión; prioriza XC y como respaldo Trail ligera / MTB)
            es_bf, nota_bf, dto_bf, etiq_bf, desglose_bf = evaluar_oportunidad_black_friday(bici, nota_perito=nota)
            if es_bf:
                black_friday_pool.append((bici, nota_bf, dto_bf, etiq_bf, desglose_bf))
            else:
                ok_resp, dto_r, nota_r, mot_r, clave_r = evaluar_respaldo_black_friday(bici, nota_perito=nota)
                if ok_resp:
                    black_friday_respaldo_pool.append((bici, dto_r, nota_r, mot_r, clave_r))
                else:
                    ok_sup, dto_s, nota_s, mot_s, clave_s = evaluar_respaldo_black_friday(
                        bici, nota_perito=nota, requerir_descuento_pvp=False
                    )
                    if ok_sup:
                        black_friday_suplemento_pool.append((bici, dto_s, nota_s, mot_s, clave_s))

            es_ocasion_o_wallapop = es_bici_de_ocasion(bici) or (bici.sitio or "").lower() == "wallapop"
            if es_ocasion_o_wallapop:
                if not es_modalidad_mtb_doble_valida(bici) or (
                    bici.recorrido_mm is not None and bici.recorrido_mm > 165
                ):
                    logger.info(
                        f"  [Descarte Modalidad/Recorrido Diario] {bici.titulo}: modalidad={bici.modalidad}, "
                        f"recorrido={bici.recorrido_mm} mm (fuera de XC/Trail ligera/MTB <= 165 mm)"
                    )
                    continue
            elif (
                es_modelo_trail_o_enduro(bici)
                or not es_modalidad_xc(bici.modalidad)
                or (bici.recorrido_mm is not None and bici.recorrido_mm > cfg.RECORRIDO_MAX_XC_MM)
            ):
                logger.info(
                    f"  [Descarte Trail/Enduro Diario] {bici.titulo}: modalidad={bici.modalidad}, "
                    f"recorrido={bici.recorrido_mm} mm (tiendas nuevas no-XC van a Beast)"
                )
                continue

            if (bici.bici_id in ids_catalogo_base or bici.bici_id in vigilancia_ids) and (
                bici.peso_kg is None or bici.peso_kg < cfg.PESO_DESCARTE_KG
            ):
                db.registrar_en_catalogo(bici)

            en_flujo_diario = (
                bici.bici_id in ids_catalogo_base
                or (bici.bici_id in vigilancia_ids and es_unicornio_xc(bici))
            )
            if not en_flujo_diario:
                continue

            # Flujo diario: Batería > 500 Wh y Precio 2.000-3.300 € (hasta 3.500 € en Unicornios XC >=600 Wh, <=500 km)
            if bici.bateria_wh is not None and bici.bateria_wh <= cfg.BATERIA_MIN_WH:
                continue
            precio_techo_diario = (
                getattr(cfg, "PRECIO_MAX_UNICORNIO_XC_EUR", cfg.PRECIO_MAX_EXCEPCIONAL_EUR)
                if es_unicornio_xc(bici)
                else cfg.PRECIO_MAX_EXCEPCIONAL_EUR
            )
            if not (cfg.PRECIO_MIN_EUR <= bici.precio <= precio_techo_diario):
                continue

            if (bici.sitio or "").lower() == "wallapop" and db.fue_enviada_equivalente(bici):
                logger.info(
                    f"  [Dedup inter-portal] Omitiendo clon Wallapop ya notificado desde tienda oficial: '{bici.titulo}'"
                )
                continue

            es_nueva = forzar_envio or db.debe_reenviarse(bici, nota)
            apto_pre, motivo_post = pasa_filtros_estrictos(
                bici, permitir_trail_respaldo=es_ocasion_o_wallapop
            )

            if apto_pre:
                estrictas_pool.append((bici, nota, desglose, es_nueva))
            else:
                es_rechazo_duro = (
                    (bici.peso_kg is not None and bici.peso_kg >= cfg.PESO_DESCARTE_KG)
                    or (bici.bateria_wh is not None and bici.bateria_wh <= cfg.BATERIA_MIN_WH)
                    or "Full Power" in motivo_post
                    or "pesado" in motivo_post
                )
                if not es_rechazo_duro:
                    logger.info(f"  [Candidata cercana] {bici.titulo}: {motivo_post} (Nota {nota}/10)")
                    respaldo_pool.append((bici, nota, desglose, es_nueva))

    # Ordenar estrictas (< 21 kg) por calidad real (novedad solo desempata a igualdad exacta)
    estrictas_pool.sort(key=lambda x: (clave_orden_estrictas(x[:3]), 1 if x[3] else 0), reverse=True)

    # Ordenar respaldo priorizando marca objetivo, modelo identificable, mayor nota, XC y menor peso
    clave_orden_respaldo = lambda x: (
        prioridad_marca(x[0]),
        1 if not (x[1] <= 4.5 and _es_anuncio_generico_sin_modelo(x[0])) else 0,
        x[1],
        prioridad_modalidad(x[0]),
        -(x[0].peso_kg or 25.0),
        1 if x[3] else 0,
    )
    respaldo_pool.sort(key=clave_orden_respaldo, reverse=True)

    black_friday_pool.sort(
        key=lambda x: (
            prioridad_marca(x[0], dto_pvp=x[2]),
            1 if float(x[0].precio) <= float(cfg.PRECIO_MAX_BLACK_FRIDAY_EUR) else 0,
            prioridad_modalidad(x[0]),
            x[1],
            x[2] or 0.0,
            -(x[0].peso_kg or 21.0),
        ),
        reverse=True,
    )
    black_friday_respaldo_pool.sort(key=lambda x: x[4], reverse=True)
    black_friday_suplemento_pool.sort(key=lambda x: x[4], reverse=True)
    sniper_pool.sort(
        key=lambda x: (
            0 if (x[0].sitio or "").lower() == "wallapop" else 1,
            1 if cfg.es_sitio_tienda_nueva(x[0].sitio, x[0].url, x[0].titulo) else 0,
            prioridad_marca(x[0]),
            prioridad_modalidad(x[0]),
            calcular_descuento_pvp_pct(x[0]) or 0.0,
            x[1],
            -(x[0].peso_kg or 21.0),
            -float(x[0].precio),
        ),
        reverse=True,
    )

    seleccion = [
        (b, n, d) for (b, n, d, _) in (estrictas_pool + respaldo_pool)
    ]

    if telemetria is not None:
        telemetria["conteo_por_portal"] = conteo_por_portal
        telemetria["total_procesadas"] = sum(conteo_por_portal.values())
        telemetria["candidatas_pre"] = len(candidatas_pre)
        telemetria["candidatas_aptas"] = len(seleccion)
        telemetria["black_friday_pool"] = black_friday_pool
        telemetria["black_friday_respaldo_pool"] = [
            x[:4] for x in black_friday_respaldo_pool
        ]
        telemetria["black_friday_suplemento_pool"] = [
            x[:4] for x in black_friday_suplemento_pool
        ]
        telemetria["sniper_pool"] = sniper_pool

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
        f"> **Última actualización:** `{ahora}` | **Criterio activo:** `XC / Downcountry <= {cfg.RECORRIDO_MAX_XC_MM} mm`, Talla `{cfg.TALLA_OBJETIVO}`, `< {cfg.PESO_DESCARTE_KG:.1f} kg`  ",
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

        estrictas_sitio = [
            op for op in items_sitio
            if pasa_filtros_estrictos(
                op[0],
                permitir_trail_respaldo=(
                    es_bici_de_ocasion(op[0]) or (op[0].sitio or "").lower() == "wallapop"
                ),
            )[0]
        ]
        estrictas_no_gen = [
            op for op in estrictas_sitio
            if op[1] > 4.5 or not _es_anuncio_generico_sin_modelo(op[0])
        ]
        respaldo_sitio = [
            op for op in items_sitio
            if not pasa_filtros_estrictos(
                op[0],
                permitir_trail_respaldo=(
                    es_bici_de_ocasion(op[0]) or (op[0].sitio or "").lower() == "wallapop"
                ),
            )[0]
        ]

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


def _encontrar_equivalente_idx(bici, lista_bicis: list) -> int:
    """
    Devuelve el índice en lista_bicis si existe otro portal con el mismo modelo y precio +-25 EUR,
    o una variante de color / clon del mismo modelo en el mismo portal (en tiendas oficiales o mismo km/precio).
    Devuelve -1 si no existe equivalente.
    """
    t_b = (bici.titulo or "").strip().lower()
    s_b = (bici.sitio or "").strip().lower()
    talla_b = (bici.talla or "").strip().upper()
    es_tienda_nueva_b = cfg.es_sitio_tienda_nueva(bici.sitio, bici.url, bici.titulo) and not es_bici_de_ocasion(bici)
    for idx, s in enumerate(lista_bicis):
        s_s = (s.sitio or "").strip().lower()
        t_s = (s.titulo or "").strip().lower()
        if s_s != s_b:
            if abs(float(s.precio) - float(bici.precio)) <= 25.0 and titulos_equivalentes_dedup(s.titulo, bici.titulo):
                return idx
        elif s.bici_id != bici.bici_id:
            talla_s = (s.talla or "").strip().upper()
            misma_talla = (not talla_s or not talla_b or talla_s == talla_b)
            if (
                misma_talla
                and es_tienda_nueva_b
                and (t_s == t_b or titulos_equivalentes_dedup(s.titulo, bici.titulo))
            ):
                return idx
            if t_s == t_b and abs(float(s.precio) - float(bici.precio)) <= 1.0:
                return idx
    return -1


def _es_equivalente_en_lista(bici, lista_bicis: list) -> bool:
    """True si existe un equivalente/variante en lista_bicis."""
    return _encontrar_equivalente_idx(bici, lista_bicis) >= 0


def seleccionar_siguientes_sin_repetir(
    oportunidades: list,
    ids_omitir_todos: set,
    ids_omitir_hoy: set,
    limite: int = 3,
) -> list:
    """
    Selecciona las siguientes opciones más interesantes (< 21 kg, > 500 Wh, sin genéricas)
    omitiendo las ya enviadas anteriormente:
      1. Primero candidatas estrictas nunca notificadas (fuera de ids_omitir_todos).
      2. Si hay menos de `limite`, completa con estrictas no notificadas hoy (fuera de ids_omitir_hoy).
    Nunca rellena con bicicletas >= 21 kg.
    """
    estrictas_validas = []
    vistos = set()
    for op in oportunidades:
        bici, nota = op[0], op[1]
        if bici.bici_id in vistos:
            continue
        es_oc_w = es_bici_de_ocasion(bici) or (bici.sitio or "").lower() == "wallapop"
        if not pasa_filtros_estrictos(bici, permitir_trail_respaldo=es_oc_w)[0]:
            continue
        if nota <= 4.5 and _es_anuncio_generico_sin_modelo(bici):
            continue
        vistos.add(bici.bici_id)
        estrictas_validas.append(op)

    nunca_vistas = [
        (idx + 1, op)
        for idx, op in enumerate(estrictas_validas)
        if op[0].bici_id not in ids_omitir_todos
    ]
    no_vistas_hoy = [
        (idx + 1, op)
        for idx, op in enumerate(estrictas_validas)
        if op[0].bici_id in ids_omitir_todos and op[0].bici_id not in ids_omitir_hoy
    ]

    seleccion = []
    ids_sel = set()
    for pos, op in nunca_vistas + no_vistas_hoy:
        if len(seleccion) >= limite:
            break
        if op[0].bici_id in ids_sel:
            continue
        ids_sel.add(op[0].bici_id)
        seleccion.append({
            "sitio": op[0].sitio,
            "item": op,
            "posicion": pos,
            "es_rot2": True,
            "retorno_top1": False,
            "es_estricta": True,
        })
    return seleccion


def _despachar_alertas_sniper(
    db: BaseDatos,
    sniper_pool: list,
    forzar_envio: bool = False,
) -> int:
    """
    Despacha alertas sonoras inmediatas para todos los chollos Sniper detectados,
    saltándose el tope de 1-por-portal y rotación, con dedup por (bici_id, precio >= -50 €)
    y evitando clones Wallapop equivalentes dentro del mismo lote.
    """
    if not sniper_pool or not getattr(cfg, "SNIPER_ACTIVO", True):
        return 0

    enviadas = 0
    vistos_lote = []
    for item in sniper_pool:
        bici, nota, motivo_sniper, precio_previo = item
        es_clon_lote = any(
            (eq.sitio or "").lower() != (bici.sitio or "").lower()
            and abs(float(eq.precio) - float(bici.precio)) <= 25.0
            and titulos_equivalentes_dedup(eq.titulo, bici.titulo)
            for eq in vistos_lote
        )
        vistos_lote.append(bici)
        if es_clon_lote:
            continue
        if (
            not forzar_envio
            and (bici.sitio or "").lower() == "wallapop"
            and hasattr(db, "fue_enviada_sniper_equivalente")
            and db.fue_enviada_sniper_equivalente(bici)
        ):
            continue
        if not forzar_envio and hasattr(db, "debe_enviar_sniper") and not db.debe_enviar_sniper(bici):
            continue

        es_beast = (not es_bici_de_ocasion(bici)) and (
            (bici.km is not None and bici.km <= cfg.KM_MAX_SEMINUEVA_BLACK_FRIDAY)
            or cfg.es_sitio_tienda_nueva(bici.sitio, bici.url, bici.titulo)
        )
        if enviar_alerta_sniper(
            bici=bici,
            nota=nota,
            motivo_sniper=motivo_sniper,
            precio_anterior=precio_previo,
            es_beast=es_beast,
        ):
            if hasattr(db, "marcar_sniper_enviada"):
                db.marcar_sniper_enviada(bici, motivo_sniper)
            enviadas += 1
            logger.info(
                f"  🎯🔥 SNIPER [{bici.sitio}]: {bici.titulo} ({bici.precio:.0f} €, {bici.peso_kg} kg) -> {motivo_sniper}"
            )
    return enviadas


def _despachar_alertas_black_friday(
    db: BaseDatos,
    bf_pool: list,
    forzar_envio: bool = False,
    bf_respaldo_pool: Optional[list] = None,
    bf_suplemento_pool: Optional[list] = None,
    estado_beast_previo: Optional[dict] = None,
    estado_extra: Optional[dict] = None,
    omitir_enviadas: bool = False,
    modo_caza: bool = False,
) -> int:
    """
    Envía las mejores nuevas y seminuevas (hasta 3 por defecto) al bot Black Bike Beast:
    - Si hay opciones nuevas/rebajadas o el pool cambió, prioriza novedades y completa hasta 3.
    - Si la búsqueda actual es idéntica a la anterior, rota hacia las siguientes en importancia
      (o reordena el Top <= 3) enviando hasta 3 resultados en lugar de quedar vacío.
    """
    if not getattr(cfg, "TELEGRAM_BOT_TOKEN_BLACK_FRIDAY", ""):
        if bf_pool or bf_respaldo_pool or bf_suplemento_pool:
            logger.info(
                "[Black Friday] Ofertas detectadas, pero TELEGRAM_BOT_TOKEN_BLACK_FRIDAY no está configurado."
            )
        return 0

    pool_beast = []
    vistos_pool = set()
    bicis_pool = []

    def _agregar_item_beast(kind: str, bici, nota, dto, etiqueta=None, desglose=None, motivo=None):
        if bici.bici_id in vistos_pool:
            return
        idx_eq = _encontrar_equivalente_idx(bici, bicis_pool)
        if idx_eq >= 0:
            prev_item = pool_beast[idx_eq]
            mismo_portal = (prev_item["bici"].sitio or "").strip().lower() == (bici.sitio or "").strip().lower()
            if (
                mismo_portal
                and prev_item["kind"] == kind
                and float(bici.precio) < float(prev_item["bici"].precio)
            ):
                vistos_pool.discard(prev_item["bici"].bici_id)
                vistos_pool.add(bici.bici_id)
                bicis_pool[idx_eq] = bici
                pool_beast[idx_eq] = {
                    "kind": kind,
                    "bici": bici,
                    "nota": nota,
                    "dto": dto,
                    "etiqueta": etiqueta,
                    "desglose": desglose,
                    "motivo": motivo,
                }
            return
        vistos_pool.add(bici.bici_id)
        bicis_pool.append(bici)
        pool_beast.append({
            "kind": kind,
            "bici": bici,
            "nota": nota,
            "dto": dto,
            "etiqueta": etiqueta,
            "desglose": desglose,
            "motivo": motivo,
        })

    for bici, nota_bf, dto_pct, etiqueta, desglose_bf in bf_pool:
        _agregar_item_beast("strict", bici, nota_bf, dto_pct, etiqueta=etiqueta, desglose=desglose_bf)
    for bici, dto_r, nota_r, mot_r in (bf_respaldo_pool or []):
        _agregar_item_beast("resp", bici, nota_r, dto_r, motivo=mot_r)
    for bici, dto_s, nota_s, mot_s in (bf_suplemento_pool or []):
        _agregar_item_beast("sup", bici, nota_s, dto_s, motivo=mot_s)

    n_total = len(pool_beast)
    if n_total == 0:
        return 0

    # Garantizar prioridad de marcas objetivo (no-BH o BH irrechazable) por delante de BH ordinaria,
    # luego candidatas <= 3.500 € antes del respaldo 3.501-4.000 €, XC (3) > Trail ligera (2) > MTB (1),
    # preservando strict > resp > sup y el orden previo de dto/nota mediante sort estable.
    pool_beast.sort(
        key=lambda item: (
            prioridad_marca(item["bici"], dto_pvp=item.get("dto")),
            1 if float(item["bici"].precio) <= float(cfg.PRECIO_MAX_BLACK_FRIDAY_EUR) else 0,
            prioridad_modalidad(item["bici"]),
            2 if item["kind"] == "strict" else (1 if item["kind"] == "resp" else 0),
        ),
        reverse=True,
    )

    max_envios = max(1, int(getattr(cfg, "BLACK_FRIDAY_TOP_N", 5)))
    objetivo_top = max(1, int(getattr(cfg, "BLACK_FRIDAY_FALLBACK_TOP_N", 3)))
    k_objetivo = min(objetivo_top, n_total)
    pool_ids = [item["bici"].bici_id for item in pool_beast]

    prev_beast = estado_beast_previo or {}
    prev_pool_ids = prev_beast.get("pool_ids") or []
    prev_enviados_ids = set(prev_beast.get("enviados_ids") or [])
    prev_offset = int(prev_beast.get("offset", 0) or 0)
    misma_busqueda = (not forzar_envio) and bool(prev_pool_ids) and (pool_ids == prev_pool_ids)

    def _ya_mostrada(b) -> bool:
        return (
            not db.debe_reenviarse_black_friday(b)
            or not db.debe_reenviarse_black_friday(replace(b, bici_id=f"respaldo:{b.bici_id}"))
            or db.fue_enviada_black_friday_equivalente(b)
        )

    nuevas_items_caza = [x for x in pool_beast if not _ya_mostrada(x["bici"])]
    def _bajada_beast_50(b) -> bool:
        for bid in (b.bici_id, f"respaldo:{b.bici_id}"):
            prev_p = db.precio_previo_black_friday(bid)
            if prev_p is not None and float(b.precio) <= float(prev_p) - 50.0:
                return True
        return False

    hay_bajada_50 = any(_bajada_beast_50(x["bici"]) for x in pool_beast)
    hay_estricta_nueva = any(
        x["kind"] == "strict"
        and db.debe_reenviarse_black_friday(x["bici"])
        and not db.fue_enviada_black_friday_equivalente(x["bici"])
        for x in pool_beast
    )
    hay_entrada_nueva = (
        bool(set(pool_ids) - set(prev_pool_ids))
        if prev_pool_ids
        else bool(nuevas_items_caza or hay_estricta_nueva)
    )
    if modo_caza and not forzar_envio and not (hay_estricta_nueva or hay_entrada_nueva or hay_bajada_50):
        logger.info("[Modo Caza] Beast sin novedades ni bajadas >= 50 €; se omite rotación y spam.")
        if estado_extra is not None:
            estado_extra["estrictas_enviadas"] = 0
            estado_extra["respaldo_enviado"] = False
            estado_extra["respaldo_count"] = 0
            estado_extra["misma_busqueda"] = True
        return 0

    sin_novedades_rotacion = misma_busqueda and not (modo_caza and (hay_bajada_50 or hay_estricta_nueva))
    seleccion_beast = []
    if sin_novedades_rotacion or omitir_enviadas:
        paso = objetivo_top if n_total > objetivo_top else 1
        inicio_rot = (prev_offset + paso) % n_total
        ids_sel = set()
        # 1. Priorizar candidatas del pool NO enviadas en la pasada anterior (evita repetir el mismo trío)
        if prev_enviados_ids:
            orden_circular = [pool_beast[(prev_offset + i) % n_total] for i in range(n_total)]
            for x in orden_circular:
                if len(seleccion_beast) >= k_objetivo:
                    break
                if x["bici"].bici_id not in prev_enviados_ids and x["bici"].bici_id not in ids_sel:
                    seleccion_beast.append(x)
                    ids_sel.add(x["bici"].bici_id)
        # 2. Completar huecos restantes siguiendo el avance cíclico desde inicio_rot
        for i in range(n_total):
            if len(seleccion_beast) >= k_objetivo:
                break
            x = pool_beast[(inicio_rot + i) % n_total]
            if x["bici"].bici_id not in ids_sel:
                seleccion_beast.append(x)
                ids_sel.add(x["bici"].bici_id)
        offset_sel = pool_ids.index(seleccion_beast[0]["bici"].bici_id) if seleccion_beast else inicio_rot
    elif forzar_envio:
        offset_sel = 0
        estrictas_all = [x for x in pool_beast if x["kind"] == "strict"][:max_envios]
        if len(estrictas_all) >= k_objetivo:
            seleccion_beast = estrictas_all
        else:
            seleccion_beast = list(pool_beast[:k_objetivo])
    else:
        nuevas_items = [x for x in pool_beast if not _ya_mostrada(x["bici"])]
        estrictas_nuevas_cand = [x for x in nuevas_items if x["kind"] == "strict"][:max_envios]
        if len(estrictas_nuevas_cand) >= k_objetivo:
            seleccion_beast = estrictas_nuevas_cand
        else:
            ids_sel = set()
            for x in nuevas_items:
                if len(seleccion_beast) >= k_objetivo:
                    break
                seleccion_beast.append(x)
                ids_sel.add(x["bici"].bici_id)
            for x in pool_beast:
                if len(seleccion_beast) >= k_objetivo:
                    break
                if x["bici"].bici_id not in ids_sel:
                    seleccion_beast.append(x)
                    ids_sel.add(x["bici"].bici_id)
        offset_sel = pool_ids.index(seleccion_beast[0]["bici"].bici_id) if seleccion_beast else 0

    estrictas_enviadas = 0
    informe_items = []
    informe_sources = []

    for item in seleccion_beast:
        bici = item["bici"]
        if item["kind"] == "strict" and (
            forzar_envio
            or (db.debe_reenviarse_black_friday(bici) and not db.fue_enviada_black_friday_equivalente(bici))
        ):
            precio_anterior = db.precio_previo_black_friday(bici.bici_id)
            if enviar_black_friday(
                bici=bici,
                nota_bf=item["nota"],
                descuento_pct=item["dto"],
                etiqueta_estado=item["etiqueta"],
                desglose=item["desglose"],
                precio_anterior=precio_anterior,
            ):
                db.registrar_black_friday(
                    bici=bici,
                    nota_bf=item["nota"],
                    descuento_pct=item["dto"],
                    precio_anterior=precio_anterior,
                )
                estrictas_enviadas += 1
                dto_txt = f"-{item['dto']:.0f}%" if item["dto"] is not None else "n/a"
                logger.info(
                    f"  ⚡ NOTIFICADA [Black Friday / {item['etiqueta']}]: {bici.titulo} "
                    f"({bici.precio:.0f} €, {dto_txt}, {bici.peso_kg} kg) - BF {item['nota']}/10"
                )
        else:
            motivo_final = (
                "Cumple 100% Black Friday (Top vigente ya avisado)"
                if item["kind"] == "strict"
                else item["motivo"]
            )
            informe_items.append((bici, item["dto"], item["nota"], motivo_final))
            informe_sources.append(item)

    respaldo_enviado = False
    if informe_items:
        subtitulo_resp = None
        if omitir_enviadas:
            subtitulo_resp = (
                f"Doble suspensión, Talla {cfg.TALLA_OBJETIVO}, < 21 kg, batería > {cfg.BATERIA_MIN_WH} Wh, "
                f"hasta {cfg.PRECIO_MAX_BLACK_FRIDAY_EUR} € (respaldo hasta {getattr(cfg, 'PRECIO_RESPALDO_BLACK_FRIDAY_EUR', 4000)} €), "
                f"priorizando XC y luego Trail ligera / MTB. "
                f"Búsqueda omitiendo resultados ya mostrados — siguientes {len(informe_items)} más interesantes:"
            )
        elif sin_novedades_rotacion:
            subtitulo_resp = (
                f"Doble suspensión, Talla {cfg.TALLA_OBJETIVO}, < 21 kg, batería > {cfg.BATERIA_MIN_WH} Wh, "
                f"hasta {cfg.PRECIO_MAX_BLACK_FRIDAY_EUR} € (respaldo hasta {getattr(cfg, 'PRECIO_RESPALDO_BLACK_FRIDAY_EUR', 4000)} €), "
                f"priorizando XC y luego Trail ligera / MTB. "
                f"Búsqueda sin novedades respecto a la anterior — rotando las {len(informe_items)} siguientes en importancia:"
            )
        elif bf_pool:
            subtitulo_resp = (
                f"Doble suspensión, Talla {cfg.TALLA_OBJETIVO}, < 21 kg, batería > {cfg.BATERIA_MIN_WH} Wh, "
                f"hasta {cfg.PRECIO_MAX_BLACK_FRIDAY_EUR} € (respaldo hasta {getattr(cfg, 'PRECIO_RESPALDO_BLACK_FRIDAY_EUR', 4000)} €), "
                f"priorizando XC y luego Trail ligera / MTB. "
                f"Top {len(informe_items)} nuevas/seminuevas (sin bicis de ocasión):"
            )

        if enviar_informe_respaldo_black_friday(
            informe_items,
            silencioso=(sin_novedades_rotacion and not omitir_enviadas),
            subtitulo=subtitulo_resp,
        ):
            respaldo_enviado = True
            for src, (b, dto_r, nota_r, _) in zip(informe_sources, informe_items):
                if src["kind"] != "strict":
                    b_mark = replace(b, bici_id=f"respaldo:{b.bici_id}")
                    prev_r = db.precio_previo_black_friday(b_mark.bici_id)
                    db.registrar_black_friday(b_mark, nota_r, dto_r, precio_anterior=prev_r)
            logger.info(
                f"  📊⚡ INFORME TOP {len(informe_items)} [Black Friday Respaldo/Complemento]: enviado a Black Bike Beast."
            )

    if estado_extra is not None:
        estado_extra["estrictas_enviadas"] = estrictas_enviadas
        estado_extra["respaldo_enviado"] = respaldo_enviado
        estado_extra["respaldo_count"] = len(informe_items) if respaldo_enviado else 0
        estado_extra["misma_busqueda"] = misma_busqueda
        if estrictas_enviadas > 0 or respaldo_enviado:
            estado_extra["beast_estado"] = {
                "pool_ids": pool_ids,
                "offset": offset_sel,
                "enviados_ids": [x["bici"].bici_id for x in seleccion_beast],
            }

    return estrictas_enviadas + (len(informe_items) if respaldo_enviado else 0)


def ejecutar_busqueda(
    forzar_envio: bool = False,
    omitir_enviadas: bool = False,
    modo_caza: Optional[bool] = None,
) -> None:
    """Ejecuta una pasada completa de búsqueda, valoración pericial y entrega 1 opción por página."""
    modo_caza_activo = bool(modo_caza) if modo_caza is not None else bool(getattr(cfg, "MODO_CAZA_BF", False))
    modo_caza_prev = getattr(cfg, "MODO_CAZA_BF", False)
    with _adquirir_lock_ejecucion() as lock_ok:
        if not lock_ok:
            return
        cfg.MODO_CAZA_BF = modo_caza_activo
        try:
            _ejecutar_busqueda_interna(
                forzar_envio=forzar_envio,
                omitir_enviadas=omitir_enviadas,
                modo_caza_activo=modo_caza_activo,
            )
        finally:
            cfg.MODO_CAZA_BF = modo_caza_prev


def _ejecutar_busqueda_interna(
    forzar_envio: bool = False,
    omitir_enviadas: bool = False,
    modo_caza_activo: bool = False,
) -> None:
    """Núcleo protegido por lock de ejecución de una pasada completa del buscador."""
    t_inicio = time.time()
    modo_label = " [MODO CAZA]" if modo_caza_activo else ""
    logger.info(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando búsqueda de e-MTB{modo_label}...")

    db = BaseDatos()
    telemetria_ejecucion: Dict[str, Any] = {}
    oportunidades = _recolectar_oportunidades(db, forzar_envio=forzar_envio, telemetria=telemetria_ejecucion)

    try:
        ruta_md = exportar_radar_mercado_md(db=db)
        logger.info(f"[Radar] Informe de mercado actualizado en {ruta_md}")
    except Exception as e:
        logger.warning(f"[Radar] No se pudo exportar docs/radar_mercado.md: {e}")

    sniper_pool = telemetria_ejecucion.get("sniper_pool") or []
    sniper_notificadas = _despachar_alertas_sniper(db, sniper_pool, forzar_envio=forzar_envio)

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

        if omitir_enviadas:
            ids_omitir_todos = db.obtener_ids_enviadas(solo_hoy=False)
            ids_omitir_hoy = db.obtener_ids_enviadas(solo_hoy=True)
            seleccionados = seleccionar_siguientes_sin_repetir(
                oportunidades,
                ids_omitir_todos=ids_omitir_todos,
                ids_omitir_hoy=ids_omitir_hoy,
                limite=TOP_N_NOTIFICAR,
            )
            nuevo_estado_portales = dict(estado_portales_previo)
            top1_ids_por_portal = [x["item"][0].bici_id for x in seleccionados]
            mejor_nota = max((x["item"][1] for x in seleccionados), default=0.0)
            logger.info(
                f"[main] Modo --omitir-enviadas: seleccionada(s) {len(seleccionados)} bici(s) siguientes "
                f"(< 21 kg, > 500 Wh) | mejor nota: {mejor_nota}/10."
            )
        else:
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
            if modo_caza_activo and not forzar_envio:
                prev_portal = estado_portales_previo.get(sitio_entry)
                es_bajada_real = db.ya_enviada(bici.bici_id) and db.debe_reenviarse(bici, nota)
                es_entrada_vig = (
                    bool(seguimiento and seguimiento.get("entrada_desde_vigilancia"))
                    and db.debe_reenviarse(bici, nota)
                )
                supera_top1_previo = (
                    not es_rot2
                    and not ret_top1
                    and (
                        prev_portal is None
                        or (prev_portal.get("top1_id") != bici.bici_id and db.debe_reenviarse(bici, nota))
                    )
                )
                if not (supera_top1_previo or es_entrada_vig or es_bajada_real):
                    continue
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
                es_rotacion_portal=(es_rot2 and not omitir_enviadas),
                aviso_retorno_top1=ret_top1,
            ):
                db.registrar(bici, nota, precio_anterior=precio_anterior)
                enviados_ids.append(bici.bici_id)
                if not omitir_enviadas and sitio_entry in nuevo_estado_portales:
                    estado_portales_confirmado[sitio_entry] = nuevo_estado_portales[sitio_entry]
                if es_rot2:
                    portales_rotados.append(sitio_entry)
                elif ret_top1:
                    portales_retorno_top1.append(sitio_entry)
                total_notificadas += 1
                estado_tag = f" (sig #{pos_portal})" if omitir_enviadas else (" (rot #2)" if es_rot2 else (" (retorno #1)" if ret_top1 else " (#1)"))
                logger.info(
                    f"  NOTIFICADA [{bici.sitio}{estado_tag}]: {bici.titulo} "
                    f"({bici.peso_kg} kg) - Nota {nota}/10{tag_mega}"
                )

        aviso_top_repetido = bool(portales_rotados)
    else:
        logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                    "No se encontraron bicis aptas en ninguno de los sitios.\n")
        top1_ids_por_portal = []
        enviados_ids = []
        estado_portales_confirmado = dict(estado_portales_previo)

    duracion_seg = round(time.time() - t_inicio, 1)
    bf_pool = telemetria_ejecucion.get("black_friday_pool") or []
    bf_respaldo_pool = telemetria_ejecucion.get("black_friday_respaldo_pool") or []
    bf_suplemento_pool = telemetria_ejecucion.get("black_friday_suplemento_pool") or []
    bf_estado_envio: Dict[str, Any] = {}
    bf_notificadas = _despachar_alertas_black_friday(
        db,
        bf_pool,
        forzar_envio=forzar_envio,
        bf_respaldo_pool=bf_respaldo_pool,
        bf_suplemento_pool=bf_suplemento_pool,
        estado_beast_previo=estado_portales_previo.get("__beast__"),
        estado_extra=bf_estado_envio,
        omitir_enviadas=omitir_enviadas,
        modo_caza=modo_caza_activo,
    )
    if "beast_estado" in bf_estado_envio:
        estado_portales_confirmado["__beast__"] = bf_estado_envio["beast_estado"]
    if (not modo_caza_activo) or enviados_ids or ("beast_estado" in bf_estado_envio):
        db.registrar_analisis(
            top3_ids=top1_ids_por_portal,
            enviados_ids=enviados_ids,
            offset_usado=0,
            repetido=aviso_top_repetido,
            estado_portales=estado_portales_confirmado,
        )
    stats_radar = db.obtener_estadisticas_mercado()

    # Heartbeat a Telegram: omitido en --modo-caza para evitar ruido cada 2h (se envía a las 12:00 o --forzar)
    if (not modo_caza_activo and cfg.TELEGRAM_HEARTBEAT) or forzar_envio:
        resumen_hb = {
            "fecha_hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duracion_seg": duracion_seg,
            "conteo_por_portal": telemetria_ejecucion.get("conteo_por_portal", {}),
            "total_procesadas": telemetria_ejecucion.get("total_procesadas", 0),
            "candidatas_aptas": len(oportunidades),
            "notificadas": total_notificadas,
            "mega_chollos": mega_chollos_count,
            "black_friday_encontradas": len(bf_pool),
            "black_friday_notificadas": bf_estado_envio.get("estrictas_enviadas", 0)
            if bf_estado_envio.get("respaldo_enviado")
            else bf_notificadas,
            "black_friday_respaldo_enviado": bool(bf_estado_envio.get("respaldo_enviado")),
            "black_friday_respaldo_count": bf_estado_envio.get("respaldo_count", 0),
            "top_repetido": aviso_top_repetido,
            "offset_usado": 0,
            "portales_rotados": portales_rotados,
            "portales_retorno_top1": portales_retorno_top1,
            "total_en_catalogo": stats_radar.get("total", 0),
            "total_en_vigilancia": len(stats_radar.get("en_vigilancia", [])),
            "sniper_notificadas": sniper_notificadas,
            "estado": "🟢 Runner operativo" if telemetria_ejecucion.get("total_procesadas", 0) > 0 else "⚠️ Sin bicicletas procesadas",
        }
        enviar_heartbeat(resumen_hb)
        if getattr(cfg, "TELEGRAM_BOT_TOKEN_BLACK_FRIDAY", ""):
            enviar_heartbeat_black_friday(resumen_hb)

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
        "--omitir-enviadas",
        action="store_true",
        help="Omite los resultados ya enviados y notifica las siguientes opciones más interesantes (< 21 kg, > 500 Wh).",
    )
    parser.add_argument(
        "--modo-caza",
        action="store_true",
        help="Modo caza Black Friday/Cyber Monday: caché fresca 45 min, cero rotaciones/Heartbeats repetidos y alertas inmediatas ante novedades/bajadas.",
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
            "black_friday_encontradas": 0,
            "black_friday_notificadas": 0,
            "total_en_catalogo": stats.get("total", 0),
            "total_en_vigilancia": len(stats.get("en_vigilancia", [])),
            "estado": "🟢 Test manual de Heartbeat",
        }
        enviar_heartbeat(resumen_hb)
        if getattr(cfg, "TELEGRAM_BOT_TOKEN_BLACK_FRIDAY", ""):
            enviar_heartbeat_black_friday(resumen_hb)
        return

    if args.stats:
        mostrar_radar_mercado()
        return

    if args.once:
        ejecutar_busqueda(
            forzar_envio=args.forzar,
            omitir_enviadas=args.omitir_enviadas,
            modo_caza=True if args.modo_caza else None,
        )
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
