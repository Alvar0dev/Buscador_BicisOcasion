"""
scrapers/mammoth.py
Adaptador para Mammoth Bikes (mammothbikes.com).
Extrae bicicletas e-MTB de doble suspensión de las categorías:
  - Rally / XC Dobles (/bicicletas-electricas-mtb-dobles-rally-xc/c-3104)
  - Trail / All-Mountain Dobles (/bicicletas-electricas-mtb-trail-all-mountain-dobles/c-2139)

Optimizado para extraer precio, tallas en stock (S/M/L/XL), año, km=0 y modalidad
directamente desde las tarjetas HTML (div.card-content) en < 1 segundo.
"""

import re
from typing import List, Optional, Set
from bs4 import BeautifulSoup
import config as cfg
from models import Bicicleta
from scraper_base import BaseScraper


class MammothScraper(BaseScraper):
    URLS_ADICIONALES: List[str] = [
        "https://www.mammothbikes.com/bicicletas-electricas-mtb-trail-all-mountain-dobles/c-2139",
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
        tarjetas = soup.select("div.card-content")

        for card in tarjetas:
            try:
                link_el = card.select_one("a[href*='/p-'], a[href]")
                nombre_el = card.select_one(".card-product-name")
                precio_el = card.select_one(
                    ".card-product-price .price.is__discount, "
                    ".card-product-price .price.is__full, "
                    ".card-product-price .price"
                )
                if not (link_el and nombre_el and precio_el):
                    continue

                href = link_el.get("href", "")
                url = self.url_absoluta(href)
                bici_id = self._extraer_id_url(href)
                precio = self._parsear_precio(precio_el.get_text())
                titulo = self._limpiar_titulo_mammoth(nombre_el)

                if not titulo or precio <= 0:
                    continue

                if self.es_tarjeta_no_disponible(card):
                    continue

                talla = self._extraer_talla_disponible(card)
                ano = self._extraer_ano_texto(titulo)

                texto_bici = f"{titulo} {href}".lower()
                es_rigida = (
                    any(
                        k in texto_bici
                        for k in [
                            "marlin", "urrun", "tempt", "lurra",
                            "tero ", "rigida", "rígida",
                        ]
                    )
                    or ("powerfly" in texto_bici and "fs" not in texto_bici)
                )

                es_categoria_xc = "rally-xc" in url_listado.lower() or "c-3104" in url_listado.lower()
                modalidad = "XC / Downcountry" if (es_categoria_xc and not es_rigida) else None

                bicis.append(Bicicleta(
                    sitio=self.sitio.nombre,
                    bici_id=f"mammoth-{bici_id}",
                    titulo=titulo,
                    precio=precio,
                    url=url,
                    talla=talla,
                    modalidad=modalidad,
                    ano=ano,
                    km=0,
                    suspension_trasera="no" if es_rigida else "si",
                    garantia_anos=self.sitio.garantia_anos,
                ))
            except Exception as e:
                print(f"[Mammoth] Error parseando tarjeta: {e}")
                continue

        return bicis

    def _limpiar_titulo_mammoth(self, nombre_el) -> str:
        """
        Normaliza títulos de Mammoth como 'scott bike bicicleta scott bike lumen 910'
        o 'trek trek fuel+ ex 8 gen 2' a un nombre limpio ('Scott Lumen 910', 'Trek Fuel+ EX 8 Gen 2').
        """
        marca_el = nombre_el.select_one("strong")
        marca = self.limpiar_texto(marca_el.get_text()) if marca_el else ""
        texto_completo = self.limpiar_texto(nombre_el.get_text())

        # Eliminar el prefijo de marca inicial si está duplicado en el resto del nombre
        resto = texto_completo
        if marca and resto.lower().startswith(marca.lower()):
            resto = resto[len(marca):].strip()

        # Quitar prefijos genéricos ("ebike", "bicicleta", "bicicleta eléctrica")
        resto = re.sub(r"^(?:ebike|e-bike|bicicleta\s+el[eé]ctrica|bicicleta)\s+", "", resto, flags=re.IGNORECASE).strip()

        # Si tras quitar "ebike/bicicleta" vuelve a aparecer la marca ("scott bike lumen 910"), evitar duplicarla
        marca_limpia = re.sub(r"\s+bike$", "", marca, flags=re.IGNORECASE).strip()
        resto = re.sub(r"^scott\s+bike\b", "Scott", resto, flags=re.IGNORECASE)

        if marca_limpia and not resto.lower().startswith(marca_limpia.lower()):
            titulo = f"{marca_limpia} {resto}".strip()
        else:
            titulo = resto or texto_completo

        # Capitalizar siglas habituales manteniendo limpio el título
        palabras = []
        for w in titulo.split():
            if w.upper() in ("EX", "FS", "FS+", "SL", "LT", "XT", "GX", "XX", "X0", "XC", "EQ", "LTD", "MMR", "BH", "KTM"):
                palabras.append(w.upper())
            elif w.lower() in ("ebike", "e-bike"):
                continue
            else:
                palabras.append(w.capitalize() if w.islower() else w)
        return " ".join(palabras)

    def _extraer_talla_disponible(self, card) -> Optional[str]:
        """
        Lee la lista de tallas en stock de la tarjeta (.card--product-sizes label).
        Si la talla objetivo ('M') está disponible en stock, devuelve 'M';
        en caso contrario devuelve la primera talla disponible para que el filtro S1 descarte.
        """
        tallas: List[str] = []
        for lbl in card.select(".card--product-sizes label, .form-sizes-group label"):
            t = self.limpiar_texto(lbl.get_text()).upper()
            if t in ("XS", "S", "M", "L", "XL", "XXL", "SM", "ML", "MD", "LG", "S/M", "M/L"):
                if t in ("MD", "S/M", "M/L"):
                    t = "M"
                elif t == "LG":
                    t = "L"
                tallas.append(t)

        if not tallas:
            return None
        objetivo = cfg.TALLA_OBJETIVO.upper()
        if objetivo in tallas:
            return objetivo
        return tallas[0]

    @staticmethod
    def _extraer_ano_texto(titulo: str) -> Optional[int]:
        match = re.search(r"\b(20[12]\d)\b", titulo)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _parsear_precio(texto: str) -> float:
        match = re.search(r"([\d\.\s,\u00A0]+)\s*€", texto)
        if not match:
            return 0.0
        digitos = "".join(c for c in match.group(1) if c.isdigit() or c in ".,")
        digitos = digitos.replace(".", "").replace(",", ".")
        try:
            return float(digitos)
        except ValueError:
            return 0.0

    @staticmethod
    def _extraer_id_url(href: str) -> str:
        match = re.search(r"/p-(\d+)", href)
        if match:
            return match.group(1)
        return href.rstrip("/").split("/")[-1]
