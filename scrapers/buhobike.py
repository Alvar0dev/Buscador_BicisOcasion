"""
scrapers/buhobike.py
Adaptador para Buhobike (buhobike.com).
Selectores CSS ajustados tras inspección real de la web (S14, S11).
Categorías objetivo:
  - Segunda mano e-MTB (/9448-segunda-mano-montana-electricas)
  - e-MTB trail doble suspensión ordenadas por precio (/3230-electricas-trail-dobles?order=product.price.asc)
"""

from typing import List, Optional, Set
from bs4 import BeautifulSoup
from models import Bicicleta
from scraper_base import BaseScraper
import config as cfg
import re


class BuhobikeScraper(BaseScraper):
    # Buhobike bloquea siempre peticiones HTTP simples con 503 de Cloudflare;
    # usar StealthyFetcher directamente ahorra ~7 segundos de reintentos fallidos por página.
    usar_stealth_directo: bool = True

    URLS_ADICIONALES: List[str] = [
        "https://www.buhobike.com/9448-segunda-mano-montana-electricas",
    ]

    def extraer_bicicletas(self) -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        vistos: Set[str] = set()

        urls = [self.sitio.seccion_emtb]
        for u in self.URLS_ADICIONALES:
            if u not in urls:
                urls.append(u)

        for url_listado in urls:
            soup = self.sopa(url_listado)
            if soup is None:
                continue
            for bici in self._extraer_de_sopa(soup, url_listado=url_listado):
                if bici.bici_id not in vistos:
                    vistos.add(bici.bici_id)
                    bicis.append(bici)

        return bicis

    def _extraer_de_sopa(self, soup: BeautifulSoup, url_listado: str = "") -> List[Bicicleta]:
        bicis: List[Bicicleta] = []
        productos = soup.select(
            "article.product-miniature, article.js-product-miniature, "
            "article.product, .product-item, .product-grid-item, .product-card, "
            "div.product, .producto, .item-producto"
        )

        for p in productos:
            try:
                # 1. Enlace y elemento de título: priorizar el bloque de título real
                # para no capturar etiquetas de descuento ni enlaces vacíos.
                titulo_el = p.select_one(
                    "p.product-title a, .product-title a, h3.product-title a, "
                    "h2.product-title a, h3 a, h2 a"
                )
                if titulo_el is None:
                    for a in p.select("a[href]"):
                        href = a.get("href", "")
                        t = self.limpiar_texto(a.get_text())
                        if (
                            t
                            and href != "#"
                            and not re.search(r"dto\b|descuento", t, re.IGNORECASE)
                            and t.lower() not in ("", "añadir al carrito", "ver rápido", "vista rápida")
                        ):
                            titulo_el = a
                            break

                # 2. Precio actual (evitando .discount-percentage / .regular-price)
                precio_el = p.select_one(
                    "span.price.current-price-discount, .product-price-and-shipping .price, "
                    ".price, .current-price, .product-price, [class*='precio']"
                )

                link_el = titulo_el if titulo_el else p.select_one("a.product-thumbnail[href], a[href]")
                if not (precio_el and link_el):
                    continue

                # 3. Título completo sin truncar: si la miniatura tiene <img class="thumbnail-img" alt="...">,
                # contiene el título completo sin "..." al final; si no, usamos el texto de titulo_el.
                img_el = p.select_one("img.thumbnail-img[alt], a.product-thumbnail img[alt]")
                titulo_alt = self.limpiar_texto(img_el.get("alt")) if img_el else None
                titulo_txt = self.limpiar_texto(titulo_el.get_text()) if titulo_el else None
                titulo = titulo_alt if (titulo_alt and len(titulo_alt) >= len(titulo_txt or "")) else titulo_txt

                precio = self._parsear_precio(precio_el.get_text())
                url = self.url_absoluta(link_el.get("href", ""))
                bici_id = p.get("data-id-product") or self._extraer_id_url(url)

                if not titulo or precio <= 0:
                    continue

                # 4. Extraer especificaciones directamente desde la tarjeta (URL, SKU, título)
                talla = self._extraer_talla_tarjeta(url, titulo)
                ano = self._extraer_ano_texto(titulo)

                sku_el = p.select_one("meta[itemprop='sku']")
                sku = sku_el.get("content", "") if sku_el else ""
                km = self._extraer_km_tarjeta(sku, url, url_listado)

                es_doble = (
                    "trail-dobles" in url.lower()
                    or "trail-dobles" in url_listado.lower()
                    or "doble-suspension" in url.lower()
                    or any(k in titulo.lower() for k in ["ilynx", "lynx", "rise", "strike", "zesty", "overvolt tr", "crafty", "thron", "jam", "stereo", "lt "])
                )

                bicis.append(Bicicleta(
                    sitio=self.sitio.nombre,
                    bici_id=str(bici_id),
                    titulo=titulo,
                    precio=precio,
                    url=url,
                    talla=talla,
                    ano=ano,
                    km=km,
                    suspension_trasera="si" if es_doble else None,
                    garantia_anos=self.sitio.garantia_anos,
                ))
            except Exception as e:
                print(f"[Buhobike] Error parseando producto: {e}")
                continue

        return bicis

    @staticmethod
    def _extraer_talla_tarjeta(url: str, titulo: str) -> Optional[str]:
        """
        Extrae la talla desde el fragmento de URL de PrestaShop (ej. '#/16856-talla-m', '#/17675-talla-l_43')
        o desde el propio título ('T-M', 'TALLA M').
        """
        match_url = re.search(r"talla-([a-z]{1,3})(?:[_\-/]|$)", url, re.IGNORECASE)
        if match_url:
            talla = match_url.group(1).upper()
            if talla in ("XS", "S", "M", "L", "XL", "XXL", "SM", "ML", "MD", "LG"):
                return "M" if talla == "MD" else ("L" if talla == "LG" else talla)

        match_tit = re.search(r"\b(?:TALLA|T)[\s\-:]+(XS|S|M|L|XL|SM|ML)\b", titulo, re.IGNORECASE)
        if match_tit:
            return match_tit.group(1).upper()

        return None

    @staticmethod
    def _extraer_ano_texto(titulo: str) -> Optional[int]:
        match = re.search(r"\b(20[12]\d)\b", titulo)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extraer_km_tarjeta(sku: str, url: str, url_listado: str) -> Optional[int]:
        """
        En Buhobike segunda mano el SKU codifica el kilometraje aproximado (ej. 'BSM32910KM5000A' -> 5000 km).
        En bicicletas nuevas/liquidación (fuera de segunda mano), km = 0.
        """
        if sku:
            match_sku = re.search(r"KM(\d{2,5})", sku, re.IGNORECASE)
            if match_sku:
                return int(match_sku.group(1))
        es_segunda_mano = "segunda-mano" in url.lower() or "segunda-mano" in url_listado.lower()
        if not es_segunda_mano:
            return 0
        return None

    def _parsear_precio(self, texto: str) -> float:
        """Extrae el primer número de precio del texto (ej. '5.999,00 €' o '3.599,00 € 3.599,00 €')."""
        match = re.search(r"([\d\.\s,\u00A0]+)\s*€", texto)
        if not match:
            return 0.0
        digitos = match.group(1)
        digitos = "".join(c for c in digitos if c.isdigit() or c in ".,")
        digitos = digitos.replace(".", "").replace(",", ".")
        try:
            return float(digitos)
        except ValueError:
            return 0.0

    def _extraer_id_url(self, url: str) -> str:
        """Extrae el ID numérico de la URL de producto de Buhobike.
        URL ejemplo: /electricas-trail-dobles/25574-127079-scott-strike-10-2027-...html
        """
        partes = url.rstrip("/").split("/")
        slug = partes[-1] if partes else ""
        # El ID suele ser el primer segmento numérico del slug
        match = re.match(r"(\d+)", slug)
        return match.group(1) if match else slug
