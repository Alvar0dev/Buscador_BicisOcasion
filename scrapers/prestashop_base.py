"""
scrapers/prestashop_base.py
Base reutilizable para tiendas españolas sobre PrestaShop (Sanferbike, Bicimarket, Fabregues).
Centraliza paginación, extracción de tarjetas article.product-miniature, precios/PVP y guardas.
"""

import re
from typing import List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from bs4 import BeautifulSoup

import config as cfg
from models import Bicicleta
from scraper_base import BaseScraper

_PATRONES_NO_MTBD = (
    "carretera", "gravel", "gravelx", "urbana", "paseo",
    "trekking", "plegable", "rigida", "rígida", "hardtail",
    "infantil", "junior", "kids", "24\"", "24''", "rookie",
    "gain", "e-sensium", "esensium", "keram", "marlin+",
    "aspect", "scale", "talon", "ebig", "bignine", "alltrack",
    "reach ht", "reach-ht", "overvolt ht", "overvolt-ht",
)


class PrestaShopBaseScraper(BaseScraper):
    """Adaptador base para listados PrestaShop (article.product-miniature)."""

    PREFIJO_ID: str = "ps"
    MAX_PAGINAS: int = 3
    RESPETAR_TALLA_URL: bool = False
    LIMPIAR_FRAGMENTO_URL: bool = True

    def construir_url_pagina(self, pagina: int) -> str:
        """Conserva los parámetros actuales de orden/faceta y actualiza page=N."""
        base = self.sitio.seccion_emtb
        if pagina <= 1:
            return base
        parsed = urlparse(base)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["page"] = str(pagina)
        return urlunparse(parsed._replace(query=urlencode(params)))

    def extraer_bicicletas(self) -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        por_id: dict = {}

        for pagina in range(1, self.MAX_PAGINAS + 1):
            url_listado = self.construir_url_pagina(pagina)
            soup = self.sopa(url_listado)
            if soup is None:
                break
            cards = self._seleccionar_tarjetas(soup)
            if not cards:
                break

            extraidas = self._extraer_de_sopa(soup, url_listado=url_listado)
            for bici in extraidas:
                idx = por_id.get(bici.bici_id)
                if idx is None:
                    por_id[bici.bici_id] = len(bicis)
                    bicis.append(bici)
                elif 0 < bici.precio < bicis[idx].precio:
                    bicis[idx] = bici

        return bicis

    def _seleccionar_tarjetas(self, soup: BeautifulSoup) -> list:
        return soup.select("article.product-miniature, article.js-product-miniature")

    def _tiene_stock_tarjeta(self, card) -> bool:
        return not self.es_tarjeta_no_disponible(card)

    def _extraer_de_sopa(self, soup: BeautifulSoup, url_listado: str = "") -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        vistos_pag: Set[str] = set()

        for card in self._seleccionar_tarjetas(soup):
            try:
                if not self._tiene_stock_tarjeta(card):
                    continue

                titulo, url_raw = self._extraer_titulo_y_url(card)
                if not titulo or not url_raw:
                    continue

                precio, pvp_original = self._extraer_precios(card)
                if precio <= 0:
                    continue

                url = self.url_absoluta(url_raw)
                raw_id = card.get("data-id-product") or self._extraer_id_url(url)
                bici_id = f"{self.PREFIJO_ID}-{raw_id}"
                if bici_id in vistos_pag:
                    continue
                vistos_pag.add(bici_id)

                talla = self._extraer_talla_tarjeta(card, url, titulo)
                url_limpia = url.split("#")[0] if self.LIMPIAR_FRAGMENTO_URL else url

                es_test = self._es_test_ride(titulo, url_limpia)
                ano = self._extraer_ano_texto(titulo)
                es_no_mtbd = self._es_no_mtb_doble(titulo, url_limpia)

                bicis.append(Bicicleta(
                    sitio=self.sitio.nombre,
                    bici_id=bici_id,
                    titulo=titulo,
                    precio=precio,
                    url=url_limpia,
                    talla=talla,
                    ano=ano,
                    km=None if es_test else 0,
                    bateria_salud_pct=None if es_test else 100,
                    bateria_ciclos=None if es_test else 0,
                    suspension_trasera="no" if es_no_mtbd else "si",
                    garantia_anos=self.sitio.garantia_anos,
                    pvp_original=pvp_original,
                ))
            except Exception as e:
                print(f"[{self.sitio.nombre}] Error parseando tarjeta: {e}")
                continue

        return bicis

    def _extraer_titulo_y_url(self, card) -> Tuple[Optional[str], str]:
        link_el = card.select_one(
            ".product-title a, h2.product-title a, h3.product-title a, "
            "p.product-title a, h2 a, h3 a"
        )
        if link_el is None:
            for a in card.select("a[href]"):
                href = a.get("href", "")
                if href and href != "#" and not re.search(r"\bver\b|añadir|favorit", a.get_text(" ", strip=True), re.I):
                    link_el = a
                    break
        if link_el is None:
            return None, ""

        href = link_el.get("href", "")
        if not href:
            thumb = card.select_one("a.product-thumbnail[href], a.thumbnail[href]")
            href = thumb.get("href", "") if thumb else ""

        img_el = card.select_one("img[alt]")
        txt_a = self.limpiar_texto(link_el.get_text()) or ""
        txt_title = self.limpiar_texto(link_el.get("title")) or ""
        txt_img = self.limpiar_texto(img_el.get("alt")) if img_el else ""

        candidatos = [t for t in (txt_title, txt_a, txt_img) if t and not t.endswith("...")]
        if candidatos:
            titulo = max(candidatos, key=len)
        else:
            titulo = txt_title or txt_a or (txt_img or None)
        return titulo, href

    def _extraer_precios(self, card) -> Tuple[float, Optional[float]]:
        precio_el = (
            card.select_one(".product-price-and-shipping .product-price")
            or card.select_one("span.product-price")
            or card.select_one(".product-price-and-shipping .price")
            or card.select_one(".product-price, .price")
        )
        precio = 0.0
        if precio_el is not None:
            content_val = precio_el.get("content")
            if content_val:
                try:
                    precio = float(str(content_val).replace(",", "."))
                except ValueError:
                    precio = 0.0
            if precio <= 0:
                precio = self._parsear_precio(precio_el.get_text())

        old_el = card.select_one(".regular-price, del, .old-price, .price-before-discount")
        pvp_original = self._parsear_precio(old_el.get_text()) if old_el else None
        if not pvp_original or pvp_original <= precio:
            pvp_original = None
        return precio, pvp_original

    def _extraer_talla_tarjeta(self, card, url: str, titulo: str) -> Optional[str]:
        if self.RESPETAR_TALLA_URL:
            m_url = re.search(r"tallas?-([a-z0-9_]+)(?:[_\-/]|$)", url, re.IGNORECASE)
            if m_url:
                t_norm = cfg.normalizar_codigo_talla(m_url.group(1).replace("_", "/"))
                if t_norm:
                    return t_norm
        m_tit = re.search(r"\b(?:TALLA|T)[\s\-:]+(XXL|XL|XS|SM|ML|MD|LA|LG|S/M|M/L|S|M|L)\b", titulo, re.IGNORECASE)
        if m_tit:
            return cfg.normalizar_codigo_talla(m_tit.group(1))
        return None

    @staticmethod
    def _es_test_ride(titulo: str, url: str) -> bool:
        txt = f"{titulo} {url}".lower()
        return "test ride" in txt or "test-ride" in txt

    @staticmethod
    def _es_no_mtb_doble(titulo: str, url: str) -> bool:
        txt = f"{titulo} {url}".lower()
        return any(k in txt for k in _PATRONES_NO_MTBD) or (
            "powerfly" in txt and "fs" not in txt and "+" not in txt
        )

    @staticmethod
    def _parsear_precio(texto: str) -> float:
        match = re.search(r"(\d[\d\.\s,\u00A0]*\d|\d+)", (texto or "").strip())
        if not match:
            return 0.0
        digitos = "".join(c for c in match.group(1) if c.isdigit() or c in ".,")
        if "," in digitos:
            digitos = digitos.replace(".", "").replace(",", ".")
        elif digitos.count(".") >= 1 and all(len(p) == 3 for p in digitos.split(".")[1:]):
            digitos = digitos.replace(".", "")
        try:
            return float(digitos)
        except ValueError:
            return 0.0

    @staticmethod
    def _extraer_ano_texto(titulo: str) -> Optional[int]:
        match = re.search(r"\b(20[12]\d)\b", titulo)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extraer_id_url(url: str) -> str:
        slug = url.split("#")[0].rstrip("/").split("/")[-1]
        match = re.match(r"(\d+)", slug)
        return match.group(1) if match else slug
