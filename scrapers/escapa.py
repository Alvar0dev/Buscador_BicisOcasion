"""
scrapers/escapa.py
Adaptador para Escapa / Biciescapa (escapa.com sobre BigCommerce).
Usa HTTP directo via requests (evita 403/10s de StealthyFetcher en WAF de CloudFront),
ordena por ?sort=priceasc y descarta tarjetas con botón 'Avísame'.
"""

import re
from typing import List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from bs4 import BeautifulSoup

import config as cfg
from models import Bicicleta
from scraper_base import BaseScraper, parsear_precio_euro, es_modelo_no_mtb_doble, es_unidad_test_o_demo


class EscapaScraper(BaseScraper):
    usar_requests_primero: bool = True
    MAX_PAGINAS: int = 4

    def construir_url_pagina(self, pagina: int) -> str:
        base = self.sitio.seccion_emtb
        if pagina <= 1:
            return base
        parsed = urlparse(base)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["page"] = str(pagina)
        return urlunparse(parsed._replace(query=urlencode(params)))

    def extraer_bicicletas(self) -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        vistos: Set[str] = set()
        techo_corte = getattr(cfg, "PRECIO_RESPALDO_BLACK_FRIDAY_EUR", 4000) + 400

        for pagina in range(1, self.MAX_PAGINAS + 1):
            url_listado = self.construir_url_pagina(pagina)
            soup = self.sopa(url_listado)
            if soup is None:
                break
            extraidas = self._extraer_de_sopa(soup, url_listado=url_listado)
            if not extraidas:
                break
            for b in extraidas:
                if b.bici_id not in vistos:
                    vistos.add(b.bici_id)
                    bicis.append(b)
            if max(b.precio for b in extraidas) > techo_corte:
                break

        return bicis

    def _extraer_de_sopa(self, soup: BeautifulSoup, url_listado: str = "") -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        vistos: Set[str] = set()

        for card in soup.select("article.card"):
            try:
                if self.es_tarjeta_no_disponible(card):
                    continue

                title_link = card.select_one("h4.card-title a, .card-title a, a.card-link[href]")
                card_link = card.select_one("a.card-link[href]") or title_link
                title_el = card.select_one("h4.card-title, .card-title")
                if card_link is None:
                    continue

                href = card_link.get("href", "") or (title_link.get("href", "") if title_link else "")
                if not href:
                    continue
                url = self.url_absoluta(href).split("#")[0]

                img_el = card.select_one("img.card-image[alt], img[alt]")
                titulo = (
                    self.limpiar_texto(title_el.get_text())
                    if title_el and self.limpiar_texto(title_el.get_text())
                    else (self.limpiar_texto(img_el.get("alt")) if img_el else None)
                )
                if not titulo:
                    continue

                pid_node = card.select_one("[data-product-id]")
                raw_id = pid_node.get("data-product-id") if pid_node else url.rstrip("/").split("/")[-1]
                bici_id = f"escapa-{raw_id}"
                if bici_id in vistos:
                    continue
                vistos.add(bici_id)

                precio_el = (
                    card.select_one(".price-section--withTax .price.red")
                    or card.select_one(".price-section--withTax .price.price--withTax:not(.price--non-sale)")
                    or card.select_one(".price--withoutTax:not(.price--non-sale):not(.price--rrp)")
                    or card.select_one(".price:not(.price--non-sale):not(.price--rrp)")
                )
                precio = parsear_precio_euro(precio_el.get_text()) if precio_el else 0.0
                if precio <= 0:
                    continue

                old_el = (
                    card.select_one(".old-price .price.price--non-sale")
                    or card.select_one(".price--non-sale")
                    or card.select_one(".price--rrp")
                )
                pvp_original = parsear_precio_euro(old_el.get_text()) if old_el else None
                if not pvp_original or pvp_original <= precio:
                    pvp_original = None

                ano_m = re.search(r"\b(20[12]\d)\b", titulo)
                es_no_mtbd = es_modelo_no_mtb_doble(titulo, url)
                es_demo = es_unidad_test_o_demo(titulo, url)

                bicis.append(Bicicleta(
                    sitio=self.sitio.nombre,
                    bici_id=bici_id,
                    titulo=titulo,
                    precio=precio,
                    url=url,
                    talla=None,
                    ano=int(ano_m.group(1)) if ano_m else None,
                    km=None if es_demo else 0,
                    bateria_salud_pct=None if es_demo else 100,
                    bateria_ciclos=None if es_demo else 0,
                    suspension_trasera="no" if es_no_mtbd else "si",
                    garantia_anos=self.sitio.garantia_anos,
                    pvp_original=pvp_original,
                ))
            except Exception as e:
                print(f"[Escapa] Error parseando tarjeta: {e}")
                continue

        return bicis
