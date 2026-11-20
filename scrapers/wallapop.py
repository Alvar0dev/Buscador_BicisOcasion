"""
scrapers/wallapop.py
Adaptador para anuncios de bicicletas eléctricas de montaña en Wallapop,
geolocalizados en un radio configurable alrededor de Fuenlabrada (50 km).

Consulta la API pública de búsqueda de Wallapop (/api/v3/search) filtrando
por categoría Bicicletas (17000) y subcategoría Eléctricas (10215), aplica
verificación matemática de distancia (Haversine <= WALLAPOP_RADIO_KM) para
bloquear anuncios patrocinados remotos y reutiliza los extractores NLP/regex
de enriquecedor_web.py sobre título y descripción.
"""

import logging
import math
import random
from typing import Any, Dict, List, Optional
import re

import requests

import config as cfg
from models import Bicicleta
from scraper_base import BaseScraper
from scrapers.enriquecedor_web import (
    PALABRAS_EXCLUSION_EXTENDER,
    _detectar_suspension_trasera,
    _extraer_ano,
    _extraer_bateria,
    _extraer_componentes,
    _extraer_cuadro,
    _extraer_km,
    _extraer_modalidad,
    _extraer_motor,
    _extraer_peso,
    _extraer_range_extender,
    _extraer_recorrido,
    _extraer_salud_bateria,
    _extraer_talla,
)

log = logging.getLogger("buscador.wallapop")

WALLAPOP_CATEGORIA_BICIS = "17000"
WALLAPOP_SUBCATEGORIA_ELECTRICAS = "10215"

# Palabras en título/anuncio que identifican modalidades o artículos ajenos a e-MTB
_PATRONES_NO_EMTB_TITULO = (
    "gravel",
    "carretera",
    "urbana",
    "paseo",
    "plegable",
    "fat bike",
    "fatbike",
    "cargo",
    "triciclo",
    "handbike",
    "patinete",
    "scooter",
    "silla movilidad",
    "silla eléctrica",
    "e-suv",
    "trekking",
    "estatica",
    "estática",
    "rodillo",
    "turbo creo",
    "e-edr",
    "roadmachine",
    "kemen",
    "precede",
    "escultura",
    "dusty",
    "kansas",
    "winora tria",
    "allant",
    "macina style",
    "cento 10",
    "axis eride",
    "rayvolt",
    "exploro",
    "riese muller",
    "riese & muller",
    "charger 4",
    "turbo tero",
    "orbea diem",
    "e-teru",
    "2 bicicletas",
    "dos bicicletas",
    "alquiler",
    "se alquila",
    "busco ",
    "compro ",
    "despiece",
)

_MODELOS_DOBLE_RE = re.compile(
    r"\b(?:"
    r"doble\b(?!\s+(?:pared|plato|altura|bater[ií]a|piso|capa|junta)\b)"
    r"|full[\s\-]+suspension"
    r"|rise|wild|i?lynx|atomx|xtep|levo|kenevo"
    r"|wilier[\s\-]+urta|urta(?:\s+hybrid)?|fourstroke(?:\s+amp)?|macina\s+scarp"
    r"|fuel[\s\-]+ex(?:[\-\s]*e)?|rail|stereo[\s\-]+hybrid"
    r"|crafty|dusk|neat|trance|reign|stance"
    r"|moterra|habit[\s\-]+neo|lumen|strike|patron"
    r"|jam\s*2|thron(?:\s*2)?|vam(?:\s*2|\s*8\.|\s*9\.)|sam\s*2"
    r"|allmtn|alltrail|e[\-\s]?zesty|zesty|overvolt"
    r"|spectral|neuron|mako|e[\-\s]?asx|e[\-\s]?riot|riot[\s\-]+am"
    r"|meta[\s\-]+power|e[\-\s]?feel|niner[\s\-]+rip|e[\-\s]?stream|sonic[\s\-]+evo"
    r"|powerplay|samedi|intrigue|t[\-\s]?tronik|kapoho|shuttle"
    r"|heckler|bullit|lt2|fullseven"
    r")\b"
)

_UNICORNIOS_NACIONALES_PATRONES = {
    "bh ilynx race": re.compile(r"\bi[\-\s]?lynx\s+race\b", re.IGNORECASE),
    "wilier urta hybrid": re.compile(r"\bwilier\s+urta\b|\burta\s+hybrid\b", re.IGNORECASE),
    "scott lumen": re.compile(r"\bscott\s+lumen\b", re.IGNORECASE),
    "focus vam2": re.compile(r"\bfocus\s+vam\s*2?(?:\s*sl|\s*8\.|\s*9\.)?\b", re.IGNORECASE),
    "bmc fourstroke amp": re.compile(r"\bbmc\s+fourstroke\b|\bfourstroke\s+amp\b", re.IGNORECASE),
}


def _extraer_pvp_wallapop(texto: str, precio: float) -> Optional[float]:
    """Extrae el PVP original si el vendedor lo declara explícitamente en el texto."""
    m = re.search(
        r"\bp\.?v\.?p\.?(?:\s+en\s+20\d{2}|\s+original|\s+nuevo|\s+de|\s+aprox\.?)?\s*[:\-]?\s*"
        r"(?:de\s+)?(\d{1,2}[.,]\d{3}|\d{4,5})(?:[.,]\d{2})?\s*(?:€|eur|euros)?\b",
        texto or "",
        re.IGNORECASE,
    )
    if not m:
        return None
    raw = m.group(1)
    if re.match(r"^\d{1,2}[.,]\d{3}$", raw):
        raw = raw.replace(".", "").replace(",", "")
    try:
        pvp = float(raw)
    except ValueError:
        return None
    if pvp > precio * 1.05 and pvp <= 20000.0:
        return pvp
    return None

_PATRONES_DESPIECE_TITULO = re.compile(
    r"^(?:bater[ií]a|cargador|horquilla|amortiguador|motor|rueda|ruedas|cuadro|extender)\b",
    re.IGNORECASE,
)


def distancia_haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcula la distancia geodésica en kilómetros entre dos coordenadas (WGS84)."""
    r_tierra_km = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return r_tierra_km * c


def _es_descartable_no_emtb(titulo: str, descripcion: str) -> bool:
    """Descarta anuncios que claramente no son bicicletas e-MTB completas en venta."""
    t_lower = (titulo or "").strip().lower()
    if any(p in t_lower for p in _PATRONES_NO_EMTB_TITULO):
        return True
    if _PATRONES_DESPIECE_TITULO.search(t_lower):
        return True

    d_lower = (descripcion or "").lower()
    if re.search(r"\b(?:se alquila|solo venta por piezas|despiece completo)\b", d_lower):
        return True
    if re.search(r"\b(?:bicicleta\s+de\s+(?:gravel|carretera|paseo|ciudad|trekking)|urban\s+bike)\b", d_lower):
        return True
    return False


def _extraer_talla_wallapop(titulo: str, descripcion: str) -> str:
    """
    Extrae la talla del título/descripción de Wallapop.
    Si no figura explícitamente en el anuncio, devuelve 'No indicada' para que
    pasa_filtros_estrictos descarte en pre-filtro y no consuma cuota de enriquecimiento
    ni mezcle bicis L/S/XL sin confirmar.
    """
    texto = f"{titulo}\n{descripcion}"
    talla = _extraer_talla(texto)
    if talla:
        return talla

    # Fallback frecuente en títulos de Wallapop: "Haibike AllMtn 7 M – ...", "FOCUS VAM2 SL 8.7 2024 XL"
    # Evita capturar guiones de modelo como "M-Team" o "M-LTD".
    m_titulo = re.search(
        r"(?:^|\s)(XXL|XL|XS)\b|\s(M)(?=\s|$|[–.,](?:\s|$))",
        titulo or "",
    )
    if m_titulo:
        return (m_titulo.group(1) or m_titulo.group(2)).upper()

    # Rango de estatura habitual en M (exige separador '1m'/'1,'/'1.' y descarta recorridos '170-180 mm')
    m_alt = re.search(
        r"\b1(?:m|[.,])\s*(6[6-9]|7[0-8])\s*(?:m|cm)?\s*(?:a|-)\s*1(?:m|[.,])\s*(7[4-9]|8[0-2])(?:\s*(?:m|cm))?\b(?!\s*mm\b)",
        texto,
        re.IGNORECASE,
    )
    if m_alt:
        return "M"

    return "No indicada"


class WallapopScraper(BaseScraper):
    """Scraper geolocalizado para anuncios de e-MTB en Wallapop."""

    def _headers_api(self) -> Dict[str, str]:
        return {
            "User-Agent": random.choice(cfg.USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "es-ES,es;q=0.9",
            "X-DeviceOS": "0",
        }

    def _obtener_pagina_api(self, params: Dict[str, Any], timeout: int = 20) -> Optional[dict]:
        """Consulta el endpoint JSON de Wallapop respetando la configuración opcional de proxies."""
        proxies_req = None
        if cfg.PROXY_LIST:
            idx = random.randrange(len(cfg.PROXY_LIST)) if cfg.PROXY_ROTATION in ("random", "aleatorio") else 0
            proxy_url = cfg.PROXY_LIST[idx]
            proxies_req = {"http": proxy_url, "https": proxy_url}

        try:
            resp = requests.get(
                self.sitio.seccion_emtb,
                params=params,
                headers=self._headers_api(),
                proxies=proxies_req,
                timeout=timeout,
            )
            self._ultimo_status_http = resp.status_code
            if resp.status_code != 200:
                log.warning(f"[Wallapop] HTTP {resp.status_code} consultando API.")
                return None
            return resp.json()
        except Exception as e:
            log.warning(f"[Wallapop] Error consultando API de búsqueda: {e}")
            return None

    def extraer_bicicletas(self, max_paginas: int = 30) -> List[Bicicleta]:
        """Extrae anuncios únicos de bicicletas eléctricas dentro del radio configurado."""
        bicis: List[Bicicleta] = []
        ids_vistos = set()

        params: Optional[Dict[str, Any]] = {
            "source": "quick_filters",
            "category_id": WALLAPOP_CATEGORIA_BICIS,
            "subcategory_ids": WALLAPOP_SUBCATEGORIA_ELECTRICAS,
            "latitude": cfg.WALLAPOP_LAT,
            "longitude": cfg.WALLAPOP_LON,
            "distance_in_km": cfg.WALLAPOP_RADIO_KM,
            "min_sale_price": cfg.PRECIO_MIN_EUR,
            "max_sale_price": 3500,  # Incluye Zona de Vigilancia (3.301-3.500 €)
        }

        pagina = 0
        vacias_consecutivas = 0
        while params and pagina < max_paginas:
            if pagina > 0:
                import time
                time.sleep(random.uniform(0.25, 0.55))

            data = self._obtener_pagina_api(params)
            if not data:
                break

            pagina += 1
            payload_sec = (
                ((data.get("data") or {}).get("section") or {}).get("payload") or {}
            )
            items = payload_sec.get("items") or []
            if not items:
                vacias_consecutivas += 1
            else:
                vacias_consecutivas = 0

            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "").strip()
                if not item_id or item_id in ids_vistos:
                    continue
                ids_vistos.add(item_id)

                try:
                    bici = self._parsear_item(item)
                except Exception as e:
                    log.warning(f"[Wallapop] Error parseando item {item_id}: {e}")
                    continue
                if bici is not None:
                    bicis.append(bici)

            next_page = (data.get("meta") or {}).get("next_page")
            if not next_page or vacias_consecutivas >= 5:
                break
            params = {"next_page": next_page, "source": "quick_filters"}

        extra = self._buscar_unicornios_nacionales(ids_vistos, bicis)
        return bicis + extra

    def _buscar_unicornios_nacionales(
        self, ids_vistos: set, bicis_locales: List[Bicicleta]
    ) -> List[Bicicleta]:
        """Busca unicornios XC específicos en toda España deduplicando clones multi-ciudad."""
        queries = getattr(cfg, "WALLAPOP_UNICORN_QUERIES", [])
        if not queries:
            return []

        from db import titulos_equivalentes_dedup

        locales_norm = [
            (b.titulo, float(b.precio), (b.talla or "").strip().upper())
            for b in bicis_locales
        ]
        nacionales_por_clave: Dict[int, tuple] = {}
        orden_claves: List[int] = []
        seq = 0

        for kw in queries:
            regex_modelo = _UNICORNIOS_NACIONALES_PATRONES.get(kw.lower())
            tokens_req = tuple(t for t in kw.lower().split() if len(t) >= 3)
            params_q = {
                "source": "search_box",
                "category_id": WALLAPOP_CATEGORIA_BICIS,
                "subcategory_ids": WALLAPOP_SUBCATEGORIA_ELECTRICAS,
                "keywords": kw,
                "min_sale_price": cfg.PRECIO_MIN_EUR,
                "max_sale_price": cfg.PRECIO_MAX_BLACK_FRIDAY_EUR,
                "latitude": cfg.WALLAPOP_LAT,
                "longitude": cfg.WALLAPOP_LON,
            }
            data = self._obtener_pagina_api(params_q)
            if not data:
                continue
            items = (((data.get("data") or {}).get("section") or {}).get("payload") or {}).get("items") or []
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "").strip()
                if not item_id or item_id in ids_vistos:
                    continue

                txt_low = f"{item.get('title', '')} {item.get('description', '')}".lower().replace("²", "2")
                if regex_modelo is not None:
                    if not regex_modelo.search(txt_low):
                        continue
                elif not all(tok in txt_low for tok in tokens_req):
                    continue

                ids_vistos.add(item_id)

                try:
                    bici = self._parsear_item(item, permitir_nacional=True)
                except Exception:
                    continue
                if bici is None:
                    continue

                talla_b = (bici.talla or "").strip().upper()
                # Si ya existe idéntico (mismo modelo, precio y talla) en búsqueda local <= 50 km, no duplicar
                if any(
                    tl == talla_b
                    and abs(p - bici.precio) <= 10.0
                    and titulos_equivalentes_dedup(t, bici.titulo)
                    for t, p, tl in locales_norm
                ):
                    continue

                loc = item.get("location") or {}
                dist_act = distancia_haversine_km(
                    cfg.WALLAPOP_LAT, cfg.WALLAPOP_LON, float(loc.get("latitude")), float(loc.get("longitude"))
                )
                match_idx = None
                for k, (prev_b, prev_d) in nacionales_por_clave.items():
                    prev_talla = (prev_b.talla or "").strip().upper()
                    if (
                        prev_talla == talla_b
                        and abs(prev_b.precio - bici.precio) <= 10.0
                        and titulos_equivalentes_dedup(prev_b.titulo, bici.titulo)
                    ):
                        match_idx = k
                        if dist_act < prev_d:
                            nacionales_por_clave[k] = (bici, dist_act)
                        break
                if match_idx is None:
                    nacionales_por_clave[seq] = (bici, dist_act)
                    orden_claves.append(seq)
                    seq += 1

        return [nacionales_por_clave[k][0] for k in orden_claves]

    def _parsear_item(self, item: dict, permitir_nacional: bool = False) -> Optional[Bicicleta]:
        """Convierte un ítem JSON de Wallapop en Bicicleta aplicando geo-filtro y extractores."""
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            return None

        if (item.get("reserved") or {}).get("flag"):
            return None

        cat_id = item.get("category_id")
        if cat_id is not None and str(cat_id) != WALLAPOP_CATEGORIA_BICIS:
            return None

        precio_raw = (item.get("price") or {}).get("amount")
        try:
            precio = float(precio_raw)
        except (TypeError, ValueError):
            return None
        if precio <= 0:
            return None

        # Verificación geográfica estricta (bloquea anuncios promocionados tipo 'bump: country' o sin coordenadas válidas)
        loc = item.get("location") or {}
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        if lat is None or lon is None:
            return None
        try:
            dist_km = distancia_haversine_km(
                cfg.WALLAPOP_LAT,
                cfg.WALLAPOP_LON,
                float(lat),
                float(lon),
            )
        except (TypeError, ValueError):
            return None
        if not permitir_nacional and dist_km > float(cfg.WALLAPOP_RADIO_KM):
            return None

        titulo = self.limpiar_texto(item.get("title") or "") or ""
        descripcion = self.limpiar_texto(item.get("description") or "") or ""
        if not titulo or _es_descartable_no_emtb(titulo, descripcion):
            return None

        slug = item.get("web_slug") or item_id
        url = f"{self.sitio.base_url.rstrip('/')}/item/{slug.lstrip('/')}"

        texto_completo = f"{titulo}\n{descripcion}"
        talla = _extraer_talla_wallapop(titulo, descripcion)
        modalidad = _extraer_modalidad(texto_completo)
        recorrido_mm = _extraer_recorrido(texto_completo)
        bateria_wh = _extraer_bateria(texto_completo)
        if bateria_wh is None:
            m_bat_w = re.search(
                r"\b(?:bater[ií]a|bat\.?|pila)\s*[:\-]?\s*(360|400|420|430|480|500|504|520|530|540|600|625|630|700|720|750|800|900)\s*w\b",
                texto_completo,
                re.IGNORECASE,
            )
            if m_bat_w:
                pref_bat = re.split(r"[,.;\n]", texto_completo[max(0, m_bat_w.start() - 25):m_bat_w.start()])[-1]
                suf_bat = re.split(r"[,.;\n]", texto_completo[m_bat_w.end():min(len(texto_completo), m_bat_w.end() + 15)])[0]
                ctx_bat = f"{pref_bat} {m_bat_w.group(0)} {suf_bat}".lower()
                if not re.search(r"\b(?:motor|potencia|pico)\b", ctx_bat):
                    bateria_wh = int(m_bat_w.group(1))
        range_extender_wh = _extraer_range_extender(texto_completo)
        if range_extender_wh is None:
            m_ext_w = re.search(
                r"(?:extender|segunda\s+bater[ií]a)[^.,;\n]{0,25}?\b(160|180|210|250|252|360)\s*w\b",
                texto_completo,
                re.IGNORECASE,
            )
            if m_ext_w:
                pref_ext = re.split(r"[,.;\n]", texto_completo[max(0, m_ext_w.start() - 40):m_ext_w.start()])[-1]
                suf_ext = re.split(r"[,.;\n]", texto_completo[m_ext_w.end():min(len(texto_completo), m_ext_w.end() + 40)])[0]
                ctx_ext = f"{pref_ext} {m_ext_w.group(0)} {suf_ext}".lower()
                if not any(exc in ctx_ext for exc in PALABRAS_EXCLUSION_EXTENDER) and not re.search(r"\b(?:motor|potencia|pico)\b", ctx_ext):
                    range_extender_wh = int(m_ext_w.group(1))
        if range_extender_wh and bateria_wh is not None and bateria_wh <= 600:
            bateria_wh += range_extender_wh

        salud_pct, ciclos_bat = _extraer_salud_bateria(texto_completo)
        km = _extraer_km(texto_completo)
        if km is None and re.search(r"\bkm\.?\s*0\b", texto_completo, re.IGNORECASE):
            km = 0
        if km is None:
            for m_est in re.finditer(
                r"\b(?:sin\s+estrenar|nueva\s+a\s+estrenar|a\s+estrenar)\b",
                texto_completo,
                re.IGNORECASE,
            ):
                ctx_est = texto_completo[max(0, m_est.start() - 35):min(len(texto_completo), m_est.end() + 20)].lower()
                if not re.search(
                    r"\b(?:cadena|cubierta|cubiertas|neum[aá]ticos?|cassette|pastillas|frenos|bater[ií]a|sill[ií]n|pu[ñn]os|horquilla|ruedas?|discos?|motor|cambio|tija)\b",
                    ctx_est,
                ):
                    km = 0
                    break

        ano = _extraer_ano(texto_completo)
        peso_kg = _extraer_peso(texto_completo)
        motor = _extraer_motor(texto_completo)
        cuadro_material = _extraer_cuadro(texto_completo)
        componentes = _extraer_componentes(texto_completo)

        susp = _detectar_suspension_trasera(texto_completo)
        suspension_trasera = "si" if susp is True else ("no" if susp is False else None)

        # Exigir doble suspensión explícita o mención de gama e-MTB doble conocida
        # para evitar títulos ambiguos de particulares (ej. 'Bicicleta Eléctrica BH 237 km').
        if suspension_trasera != "si":
            tl_comp = texto_completo.lower().replace("²", "2")
            if not _MODELOS_DOBLE_RE.search(tl_comp):
                return None

        tiene_garantia_verificada = bool(
            (item.get("has_warranty") or {}).get("flag")
            or (item.get("is_refurbished") or {}).get("flag")
        )
        garantia_anos = 1 if tiene_garantia_verificada else self.sitio.garantia_anos
        tl_fact = texto_completo.lower()
        tiene_factura = bool(
            re.search(r"\bfactura\b", tl_fact)
            and not re.search(r"\b(?:sin|no\s+tengo|no\s+hay|no\s+dispongo\s+de)\s+factura\b", tl_fact)
        )

        ciudad = loc.get("city") or ""
        if ciudad and dist_km is not None:
            sufijo = " - envío España" if dist_km > float(cfg.WALLAPOP_RADIO_KM) else ""
            ubicacion = f"{ciudad} ({dist_km:.0f} km{sufijo})" if dist_km > float(cfg.WALLAPOP_RADIO_KM) else f"{ciudad} ({dist_km:.1f} km)"
        elif dist_km is not None:
            ubicacion = f"A {dist_km:.1f} km de Fuenlabrada"
        elif ciudad:
            ubicacion = str(ciudad)
        else:
            ubicacion = None

        pvp_original = _extraer_pvp_wallapop(texto_completo, precio)

        imagenes: List[str] = []
        for img in (item.get("images") or [])[:8]:
            if isinstance(img, dict):
                urls_img = img.get("urls") or {}
                img_u = urls_img.get("big") or urls_img.get("medium") or urls_img.get("small")
                if img_u:
                    imagenes.append(str(img_u))

        return Bicicleta(
            sitio=self.sitio.nombre,
            bici_id=f"wallapop-{item_id}",
            titulo=titulo,
            precio=precio,
            url=url,
            talla=talla,
            modalidad=modalidad,
            peso_kg=peso_kg,
            bateria_wh=bateria_wh,
            range_extender_wh=range_extender_wh,
            bateria_salud_pct=salud_pct,
            bateria_ciclos=ciclos_bat,
            cuadro_material=cuadro_material,
            motor=motor,
            km=km,
            ano=ano,
            componentes=componentes,
            suspension_trasera=suspension_trasera,
            recorrido_mm=recorrido_mm,
            garantia_anos=garantia_anos,
            disponible=True,
            pvp_original=pvp_original,
            ubicacion=ubicacion,
            imagenes=imagenes or None,
            tiene_factura=tiene_factura,
        )
