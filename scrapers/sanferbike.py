"""
scrapers/sanferbike.py
Adaptador para Sanferbike (sanferbike.com).
Extrae bicicletas e-MTB doble suspensión ordenadas por precio ascendente y verifica
stock real por talla directamente desde .js-miniature-product-variants en cada tarjeta.
"""

import re
from typing import List, Optional, Tuple
import config as cfg
from scrapers.prestashop_base import PrestaShopBaseScraper


class SanferbikeScraper(PrestaShopBaseScraper):
    PREFIJO_ID: str = "sanferbike"
    MAX_PAGINAS: int = 2

    def _inspeccionar_tallas_tarjeta(self, card) -> Tuple[bool, List[str]]:
        """Devuelve (tiene_bloque_tallas, tallas_con_stock) leyendo data-qty-* y attribute-not-in-stock."""
        variantes = card.select_one(".js-miniature-product-variants")
        if variantes is None:
            return False, []

        tallas_stock: List[str] = []
        hay_grupo_talla = False
        for grupo in variantes.select(".product-variants-item"):
            lbl = grupo.select_one(".control-label, p")
            lbl_txt = lbl.get_text(" ", strip=True).lower() if lbl else ""
            if "color" in lbl_txt:
                continue
            items = grupo.select("ul li")
            if not items:
                continue
            es_talla = "talla" in lbl_txt or any(
                cfg.normalizar_codigo_talla(
                    (li.select_one("input").get("title", "") if li.select_one("input") else "")
                    or li.get_text(" ", strip=True)
                )
                for li in items
            )
            if not es_talla:
                continue

            hay_grupo_talla = True
            for li in items:
                inp = li.select_one("input")
                etq = li.select_one("label")
                raw = (inp.get("title", "") if inp else "") or li.get_text(" ", strip=True)
                norm = cfg.normalizar_codigo_talla(raw)
                if not norm:
                    continue

                qtys = [
                    int(v)
                    for k, v in (inp.attrs if inp else {}).items()
                    if k.startswith("data-qty-") and str(v).isdigit()
                ]
                if qtys:
                    en_stock = any(q > 0 for q in qtys)
                else:
                    clases = " ".join((li.get("class") or []) + (etq.get("class") or [] if etq else [])).lower()
                    en_stock = not any(x in clases for x in ("attribute-not-in-stock", "disabled", "not-in-stock"))

                if en_stock:
                    tallas_stock.append(norm)

        return hay_grupo_talla, tallas_stock

    def _tiene_stock_tarjeta(self, card) -> bool:
        if not super()._tiene_stock_tarjeta(card):
            return False
        hay_grupo, tallas_stock = self._inspeccionar_tallas_tarjeta(card)
        if hay_grupo and not tallas_stock:
            return False
        return True

    def _extraer_talla_tarjeta(self, card, url: str, titulo: str) -> Optional[str]:
        hay_grupo, tallas_stock = self._inspeccionar_tallas_tarjeta(card)
        if hay_grupo:
            return cfg.seleccionar_talla_disponible(tallas_stock)
        return super()._extraer_talla_tarjeta(card, url, titulo)
