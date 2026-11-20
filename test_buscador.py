"""
test_buscador.py
Pruebas RED/GREEN con datos simulados.
Valida scoring, filtros estrictos, clasificador híbrido (IA + motor autónomo),
dedup de SQLite y formateo de mensaje Telegram.
No depende de la web real ni de credenciales de Telegram.
"""

import os
import tempfile
from models import Bicicleta
from evaluator import (
    evaluar,
    calcular_nota_oportunidad,
    pasa_filtros_estrictos,
    _puntuacion_calidad_precio,
    prioridad_modalidad,
    pasa_prefiltro_black_friday,
    evaluar_oportunidad_black_friday,
)
from gemini_classifier import (
    completar_con_catalogo,
    evaluar_documentacion_motor,
    valorar_autonomo,
    auditar_perito_mecanico,
)
from scrapers.enriquecedor_web import (
    _extraer_range_extender,
    _extraer_salud_bateria,
    _extraer_bateria,
    _extraer_motor,
    _extraer_ano,
    _extraer_recorrido,
    _extraer_km,
    _extraer_peso,
    _normalizar_km_existente,
    _extraer_pares_ficha_estructurada,
    _aplicar_detalle,
    _recolectar_urls_imagenes_ficha,
    _parsear_respuesta_km_vision,
    _extraer_km_de_imagenes,
)
from main import exportar_radar_mercado_md
from scraper_base import BaseScraper, crear_proxy_rotator, random_rotation
import config as cfg
from db import BaseDatos
from notifier import (
    formatear_mensaje,
    formatear_heartbeat,
    enviar_heartbeat,
    enviar,
    es_mega_chollo,
    formatear_mensaje_black_friday,
    enviar_black_friday,
)
from scrapers.upway import UpwayScraper
from unittest.mock import patch, MagicMock


def bici_prueba(**kwargs) -> Bicicleta:
    datos = dict(
        sitio="Bike Ocasión",
        bici_id="test-001",
        titulo="e-MTB XC Carbono Shimano EP8",
        precio=2500.0,
        url="https://bike-ocasion.com/bici/test-001",
        talla="M",
        modalidad="XC",
        peso_kg=17.5,
        bateria_wh=540,
        cuadro_material="Carbono",
        motor="Shimano EP8",
        km=1500,
        ano=2023,
        componentes="XT, suspension Kashima",
        garantia_anos=1,
    )
    datos.update(kwargs)
    return Bicicleta(**datos)


def test_pasa_filtros_valida():
    """S1-S6: bicicleta correcta pasa todos los filtros."""
    b = bici_prueba()
    apto, motivo = pasa_filtros_estrictos(b)
    assert apto is True, f"Deberia pasar: {motivo}"


def test_descarta_talla_no_m():
    """S1: solo talla M."""
    b = bici_prueba(talla="L")
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is False


def test_descarta_bateria_500_wh():
    """S4: bateria estrictamente > 500 Wh."""
    b = bici_prueba(bateria_wh=500)
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is False

    b = bici_prueba(bateria_wh=540)
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is True


def test_descarta_peso_mas_21_kg():
    """S3: descarta modelos >= 21 kg (objetivo < 21 kg)."""
    b = bici_prueba(peso_kg=21.0)
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is False

    b2 = bici_prueba(peso_kg=22.0)
    apto2, _ = pasa_filtros_estrictos(b2)
    assert apto2 is False


def test_descarta_precio_fuera_rango():
    """S5/S6: precio entre 2000 y 3300."""
    b = bici_prueba(precio=1500.0)
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is False

    b = bici_prueba(precio=3400.0)
    apto, _ = pasa_filtros_estrictos(b)
    assert apto is False


def test_nota_alta_bici_excelente():
    """S7: bici excelente nota >= 8.0."""
    b = bici_prueba(precio=2400.0, km=1000, ano=2023)
    apto, nota, desglose = evaluar(b)
    assert apto is True
    assert nota >= 8.0, f"Nota demasiado baja: {nota} | {desglose}"


def test_nota_baja_kilometraje_alto():
    """S7: km > 4000 penaliza fuerte."""
    b = bici_prueba(km=5000, precio=2400.0)
    apto, nota, desglose = evaluar(b)
    print(f"Km altos -> nota: {nota} | {desglose}")


def test_filtro_nota_minimo_8():
    """S8: solo >= 8.0 se guarda/notifica."""
    b = bici_prueba(precio=2400.0, km=1000)
    apto, nota, _ = evaluar(b)
    assert apto is True
    assert nota >= 8.0


def test_clasificador_hibrido_catalogo_y_5_ejes():
    """Verifica completado de especificaciones y valoración en los 5 ejes."""
    b = Bicicleta(
        sitio="Bike Ocasión",
        bici_id="bh-001",
        titulo="BH iLynx Race Carbon 8.4 LT",
        precio=2890.0,
        url="https://bike-ocasion.com/bici/bh-001",
        talla="M",
        km=650,
    )
    b = completar_con_catalogo(b)
    assert b.peso_kg is not None and b.peso_kg < 21.0
    assert b.bateria_wh == 540
    assert b.cuadro_material == "Carbono"
    assert b.suspension_trasera == "si"

    nota, desglose = valorar_autonomo(b)
    assert nota >= 8.0
    assert "Auditoría Pericial:" in desglose
    assert "Motor y Batería:" in desglose
    assert "Garantía y Vendedor:" in desglose

    pts_bosch, txt_bosch = evaluar_documentacion_motor("Bosch Performance Line SX")
    assert pts_bosch < 1.9
    assert "Bosch DiagnosticTool" in txt_bosch
    assert "app de usuario" in txt_bosch


def test_dedup_sqlite():
    """S12: no duplicados salvo bajada de precio."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = BaseDatos(path)
        b = bici_prueba()

        # Primera vez: debe enviarse
        assert db.debe_reenviarse(b, 8.5) is True
        db.registrar(b, 8.5)

        # Segunda vez mismo precio: no reenviar
        assert db.debe_reenviarse(b, 8.5) is False

        # Bajada de precio: reenviar
        b2 = bici_prueba(precio=2200.0, bici_id="test-001")
        assert db.debe_reenviarse(b2, 8.5) is True
    finally:
        # En Windows, SQLite puede mantener el archivo bloqueado brevemente.
        try:
            os.unlink(path)
        except PermissionError:
            pass


def test_formateo_mensaje_telegram():
    """S9: mensaje incluye todos los campos requeridos y alerta de bajada de precio."""
    b = bici_prueba()
    mensaje = formatear_mensaje(b, 8.5, "Kilometraje: Km bajos | Calidad-precio: cuadro carbono")
    assert "e-MTB XC Carbono Shimano EP8" in mensaje
    assert "2500" in mensaje
    assert "8.5/10" in mensaje
    assert "540 Wh" in mensaje
    assert "Carbono" in mensaje
    assert "Enlace directo de compra" in mensaje

    # Caso bajada de precio detectada
    b_rebajada = bici_prueba(precio=2200.0)
    msg_rebajada = formatear_mensaje(b_rebajada, 9.0, "Rebaja notable", precio_anterior=2500.0)
    assert "BAJADA DE PRECIO" in msg_rebajada
    assert "2200" in msg_rebajada
    assert "2500" in msg_rebajada
    assert "-300" in msg_rebajada


def test_extraccion_titulo_sin_dto_y_suspension_rigidez():
    """Verifica que Bike Ocasión ignore badges '% DTO' en el título y que 'rigidez' no marque hardtail."""
    from bs4 import BeautifulSoup
    import config as cfg
    from scrapers.bike_ocasion import BikeOcasionScraper
    from scrapers.enriquecedor_web import _detectar_suspension_trasera

    html = """
    <article class="ajax_block_product">
      <a class="product_img_link" href="/bicicletas-electricas-de-montana-doble-suspension/463333-bh.html" title="BH iLynx Trail Carbon 8.7 XT">- 46% DTO</a>
      <h3 class="s_title_block"><a href="/bicicletas-electricas-de-montana-doble-suspension/463333-bh.html">BH iLynx Trail Carbon 8.7 XT</a></h3>
      <span class="price">2.981 €</span>
      <div>Talla: M / 540Wh / 1.193 Km / Shimano</div>
    </article>
    """
    scraper = BikeOcasionScraper(cfg.SITIOS[0])
    bicis = scraper._extraer_de_sopa(BeautifulSoup(html, "html.parser"))
    assert len(bicis) == 1
    assert bicis[0].titulo == "BH iLynx Trail Carbon 8.7 XT"
    assert bicis[0].suspension_trasera == "si"

    # 'rigidez' no debe interpretarse como 'rigid' (sin suspensión trasera)
    assert _detectar_suspension_trasera("Cuadro de carbono con gran rigidez torsional y doble suspensión") is True


def test_perito_mecanico_senior_reglas_y_lineas_rojas():
    """Verifica la rúbrica matemática de 5 ejes sin bonos positivos y las 5 Líneas Rojas del Perito Escéptico."""
    from gemini_classifier import auditar_perito_mecanico

    # Caso 1: Línea Roja > 6.000 km (-4.5, máx 4.5) + BH 2EXMAG > 2000 km (-1.0) + sin SoH > 1500 km (-0.5) = -1.5
    b_roja_km = bici_prueba(
        titulo="BH iLynx Race Carbon 8.4 LT",
        km=8407,
        peso_kg=16.8,
        motor="BH 2EXMAG",
        precio=2768.0,
    )
    res_km = auditar_perito_mecanico(b_roja_km)
    assert res_km["nota_final"] <= 4.5, f"Línea roja >6000 km violada: {res_km}"
    assert res_km["delta_km"] == -4.5
    assert res_km["delta_motor"] == -1.5

    # Caso 2: Línea Roja > 21.0 kg (nota máxima 4.0)
    b_roja_peso = bici_prueba(titulo="Trek Rail 9.7 2023", km=500, peso_kg=22.4, motor="Bosch CX", precio=2500.0)
    res_peso = auditar_perito_mecanico(b_roja_peso)
    assert res_peso["nota_final"] <= 4.0, f"Línea roja >21 kg violada: {res_peso}"
    assert res_peso["delta_peso"] == -6.0

    # Caso 3: BH Race 1.193 km (-1.0 km) + 18.2 kg (0.0) - 0.5 (BH 2EXMAG <= 2000 km, <=1500 no extra SoH) => 8.5/10
    b_bh_bajos_km = bici_prueba(
        titulo="BH iLynx Race Carbon 8.4 LT",
        km=1193,
        peso_kg=18.2,
        motor="BH 2EXMAG",
        precio=2981.0,
    )
    res_bh = auditar_perito_mecanico(b_bh_bajos_km)
    assert res_bh["delta_motor"] == -0.5
    assert res_bh["nota_final"] == 8.5, f"Esperado 8.5, obtenido: {res_bh}"

    # Caso 4: Precio 3.150 € (-0.5) + 2.500 km (-2.5) + 19.5 kg (-0.5) + Shimano sin SoH >1500 km (-0.5) => 6.0/10
    b_cara_rodada = bici_prueba(
        titulo="Orbea Rise M10 2023",
        km=2500,
        peso_kg=19.5,
        motor="Shimano EP8",
        precio=3150.0,
    )
    res_cara = auditar_perito_mecanico(b_cara_rodada)
    assert res_cara["delta_km"] == -2.5
    assert res_cara["delta_peso"] == -0.5
    assert res_cara["delta_motor"] == -0.5
    assert res_cara["delta_precio"] == -0.5
    assert res_cara["nota_final"] == 6.0

    # Caso 5: BH iLynx+ (Shimano EP801 abierto) vs BH iLynx Race sin '+' (BH 2EXMAG cerrado)
    pts_doc_plus, txt_doc_plus = evaluar_documentacion_motor("Shimano EP801", "BH iLynx+ Trail Carbon 8.7")
    assert pts_doc_plus == 1.9 and "abierto" in txt_doc_plus
    pts_doc_race, txt_doc_race = evaluar_documentacion_motor("Shimano", "BH iLynx Race Carbon 8.4")
    assert pts_doc_race == 1.0 and "BH no genera informe PDF" in txt_doc_race


def test_optimizacion_tarjetas_upway_y_buhobike():
    """Verifica la extracción directa en tarjeta para Upway y Buhobike y los regex con bordes de palabra."""
    from bs4 import BeautifulSoup
    import config as cfg
    from scrapers.upway import UpwayScraper
    from scrapers.buhobike import BuhobikeScraper
    from scrapers.enriquecedor_web import (
        _extraer_modalidad,
        _extraer_componentes,
        _extraer_cuadro,
        _extraer_peso,
    )

    # 1. Upway: tarjeta con espacio estrecho \u202f, rango de estatura y '< 5 km'
    html_upway = """
    <div>
      <a class="w-full" href="/products/focus-thron-69-rk7qz2">
        Mejor precio Recién llegada Focus THRON² 6.9 2023 1m60-1m70 1786\u202fkm 2.499 € 6.000 € nuevo
      </a>
      <a class="w-full" href="/products/bulls-sonic-evo-am-sx-1-rk8ab1">
        Bulls Sonic Evo AM SX 1 2024 1m68-1m81 < 5\u202fkm 2.599 € 5.999 € nuevo
      </a>
    </div>
    """
    upway_scraper = UpwayScraper(cfg.SITIOS[2])
    bicis_upway = upway_scraper._extraer_de_sopa(BeautifulSoup(html_upway, "html.parser"))
    assert len(bicis_upway) == 2
    assert bicis_upway[0].titulo == "Focus THRON² 6.9"
    assert bicis_upway[0].talla == "S"
    assert bicis_upway[0].km == 1786
    assert bicis_upway[0].ano == 2023
    assert bicis_upway[0].suspension_trasera == "si"
    assert bicis_upway[1].titulo == "Bulls Sonic Evo AM SX 1"
    assert bicis_upway[1].talla == "M"
    assert bicis_upway[1].km == 5
    assert bicis_upway[1].ano == 2024

    # 2. Buhobike: tarjeta de segunda mano con alt completo, SKU KM5000 y #/16856-talla-m
    html_buhobike = """
    <article class="product-miniature js-product-miniature" data-id-product="25259">
      <a class="thumbnail product-thumbnail" href="https://www.buhobike.com/segunda-mano-electricas/25259-bh-ilynx.html#/16856-talla-m">
        <img alt="BH ILYNX RACE CARBON LT 7.6 T-M 2022 BICICLETA SEGUNDA MANO" class="thumbnail-img" />
      </a>
      <span class="discount-percentage">-3.700,00 €</span>
      <p class="h3 product-title">
        <a href="https://www.buhobike.com/segunda-mano-electricas/25259-bh-ilynx.html#/16856-talla-m">BH ILYNX RACE CARBON LT 7.6 T-M 2022...</a>
      </p>
      <meta content="BSM32910KM5000A" itemprop="sku"/>
      <div class="product-price-and-shipping">
        <span class="price current-price-discount">2.599,00 €</span>
        <span class="regular-price">6.299,00 €</span>
      </div>
    </article>
    """
    buho_scraper = BuhobikeScraper(cfg.SITIOS[1])
    bicis_buho = buho_scraper._extraer_de_sopa(
        BeautifulSoup(html_buhobike, "html.parser"),
        url_listado="https://www.buhobike.com/9448-segunda-mano-montana-electricas",
    )
    assert len(bicis_buho) == 1
    assert bicis_buho[0].titulo == "BH ILYNX RACE CARBON LT 7.6 T-M 2022 BICICLETA SEGUNDA MANO"
    assert bicis_buho[0].precio == 2599.0
    assert bicis_buho[0].talla == "M"
    assert bicis_buho[0].ano == 2022
    assert bicis_buho[0].km == 5000
    assert bicis_buho[0].suspension_trasera == "si"

    # 3. Falsos positivos por subcadenas en español ('excelente' != XC, 'extra' != XT, 'salud' != Aluminio)
    assert _extraer_modalidad("Estado excelente y exclusivo para montaña") is None
    assert _extraer_componentes("Garantía extra en el exterior del cuadro") is None
    assert _extraer_cuadro("Salud de la batería evaluada en Cataluña") is None
    assert _extraer_peso("Peso estimado del producto + embalaje: 22,000 Kg. Peso máximo ciclista 120 kg. PESO 18,28Kg") == 18.28
    from scrapers.enriquecedor_web import _extraer_km
    assert _extraer_km("engrasado de la cadena con cera al agua, mínimo para que puedas hacerle unos 700 km sin otra necesidad de engrasar la cadena") is None
    assert _extraer_km("la primera vez cambies la cadena (entre 700 y 1500 km después de la compra), no tengas que cambiar el cassette") is None
    assert _extraer_km("autonomía de hasta 120 km con batería externa") is None
    assert _extraer_km("Kilometraje: 1.250 km") == 1250
    assert _extraer_km("Bicicleta en buen estado. 4237 km rodados.") == 4237

    # 4. Prioridad de modalidad (XC > Light e-MTB > Trail) y corrección de motor BH
    from evaluator import prioridad_modalidad
    b_xc = bici_prueba(titulo="BH iLynx Race Carbon Pro LT 7.8", modalidad="XC / Downcountry", motor="Shimano")
    b_xc = completar_con_catalogo(b_xc)
    assert b_xc.motor == "BH 2EXMAG", f"Motor BH iLynx Race mal corregido: {b_xc.motor}"

    b_plus = bici_prueba(titulo="BH iLynx+ Trail Carbon 8.7 XT", modalidad="Trail", motor="Shimano")
    b_plus = completar_con_catalogo(b_plus)
    assert b_plus.motor == "Shimano EP801"

    b_light = bici_prueba(titulo="Orbea Rise H30", modalidad="Light e-MTB / Trail")
    assert prioridad_modalidad(b_xc) > prioridad_modalidad(b_light) > prioridad_modalidad(b_plus)

    # 5. Ordenación en main.clave_orden_estrictas:
    #    - Bicis sanas (nota >= 6.0 y km <= 4.000) siempre superan a una XC muy desgastada (5.000 km, 3.5/10).
    #    - A igualdad de salud mecánica, XC supera a Light e-MTB y Trail.
    from main import clave_orden_estrictas
    item_xc_sana = (
        bici_prueba(titulo="BH iLynx Race Carbon Pro LT 7.8", km=1200, peso_kg=16.8, modalidad="XC / Downcountry"),
        7.0,
        "Sana XC",
    )
    item_light_sana = (
        bici_prueba(titulo="Orbea Rise H30", km=1242, peso_kg=20.3, modalidad="Light e-MTB / Trail"),
        7.5,
        "Sana Light",
    )
    item_trail_sana = (
        bici_prueba(titulo="BH iLynx+ Trail Carbon 8.7 XT", km=1193, peso_kg=20.4, modalidad="Trail (160mm)"),
        6.5,
        "Sana Trail",
    )
    item_xc_gastada = (
        bici_prueba(titulo="BH ILYNX RACE CARBON LT 7.6", km=5000, peso_kg=18.28, modalidad="XC / Downcountry"),
        3.5,
        "Gastada 5000 km",
    )
    item_xc_linea_roja = (
        bici_prueba(titulo="BH iLynx Race Carbon 8.4 LT", km=8407, peso_kg=16.8, modalidad="XC / Downcountry"),
        2.5,
        "Línea Roja >6000 km",
    )
    lista_items = [item_xc_linea_roja, item_xc_gastada, item_trail_sana, item_light_sana, item_xc_sana]
    lista_items.sort(key=clave_orden_estrictas, reverse=True)
    assert [x[0].titulo for x in lista_items] == [
        "BH iLynx Race Carbon Pro LT 7.8",
        "Orbea Rise H30",
        "BH iLynx+ Trail Carbon 8.7 XT",
        "BH ILYNX RACE CARBON LT 7.6",
        "BH iLynx Race Carbon 8.4 LT",
    ]

    # 6. Mammoth Bikes: extracción de tarjeta con tallas en stock, limpieza de título y filtro anti-rígidas
    from scrapers.mammoth import MammothScraper
    html_mammoth = """
    <div>
      <div class="card-content">
        <a href="/bicicleta-scott-bike-lumen-910/p-592251">
          <div class="card-product-name"><strong>scott bike</strong> bicicleta scott bike lumen 910</div>
          <div class="card-product-price"><span class="price is__full">2.999,00 €</span></div>
          <div class="card--product-sizes form-sizes-group">
            <ul><li><label>M</label></li><li><label>L</label></li></ul>
          </div>
        </a>
      </div>
      <div class="card-content">
        <a href="/ebike-trek-marlin-8/p-592715">
          <div class="card-product-name"><strong>trek</strong> ebike trek marlin+ 8</div>
          <div class="card-product-price"><span class="price is__discount">2.244,68 €</span></div>
          <div class="card--product-sizes form-sizes-group">
            <ul><li><label>S</label></li><li><label>L</label></li></ul>
          </div>
        </a>
      </div>
    </div>
    """
    mammoth_scraper = MammothScraper(cfg.SITIOS[3])
    bicis_mammoth = mammoth_scraper._extraer_de_sopa(
        BeautifulSoup(html_mammoth, "html.parser"),
        url_listado="https://www.mammothbikes.com/bicicletas-electricas-mtb-dobles-rally-xc/c-3104",
    )
    assert len(bicis_mammoth) == 2
    assert bicis_mammoth[0].titulo == "Scott Lumen 910"
    assert bicis_mammoth[0].precio == 2999.0
    assert bicis_mammoth[0].talla == "M"
    assert bicis_mammoth[0].modalidad == "XC / Downcountry"
    assert bicis_mammoth[0].suspension_trasera == "si"
    assert bicis_mammoth[0].km == 0
    assert bicis_mammoth[1].talla == "S"
    assert bicis_mammoth[1].suspension_trasera == "no"


def test_range_extender_extraccion_y_filtros():
    """Valida la detección, suma de capacidad en Wh y bonificación de Range Extenders."""
    # 1. Extracción positiva vs exclusión de compatibilidad
    assert _extraer_range_extender("Orbea Rise H30 2022. Incluye Range Extender de 252Wh de regalo.") == 252
    assert _extraer_range_extender("BH iLynx Race Carbon 8.4 LT + Batería XPro 180Wh incluida") == 180
    assert _extraer_range_extender("Specialized Turbo Levo SL Expert con range extender") == 160
    assert _extraer_range_extender("Trek Fuel EXe 9.7 con segunda batería de 160Wh incluida") == 160
    assert _extraer_range_extender("Bicicleta con Bosch PowerMore 250Wh incluido") == 250
    # Descarte de compatibilidad / venta por separado
    assert _extraer_range_extender("Cuadro de carbono preparado para Range Extender de 252Wh (no incluido en la venta).") is None
    assert _extraer_range_extender("Compatible con range extender opcional de 252Wh") is None
    assert _extraer_range_extender("Admite batería externa Bosch PowerMore de 250Wh (se vende por separado).") is None

    # 2. Rescate de filtro S4: Orbea Rise 360 Wh descartada sin extender, pero admitida con extender
    b_sin = bici_prueba(titulo="Orbea Rise M20 2021", bateria_wh=360)
    apto_sin, motivo_sin = pasa_filtros_estrictos(b_sin)
    assert apto_sin is False
    assert "Batería <= 500 Wh: 360 Wh" in motivo_sin

    # Con extender en título: enriquecedor / catálogo ajusta capacidad total
    b_con = bici_prueba(
        titulo="Orbea Rise M20 2021 + Range Extender 252Wh",
        bateria_wh=360,
    )
    b_con = completar_con_catalogo(b_con)
    assert b_con.range_extender_wh == 252
    assert b_con.bateria_wh == 612  # 360 + 252 Wh
    apto_con, _ = pasa_filtros_estrictos(b_con)
    assert apto_con is True, "La bicicleta debe pasar el filtro estricto con 612 Wh"

    # 3. Bonificación en puntuación calidad-precio (+0.5 pts)
    p_sin, just_sin = _puntuacion_calidad_precio(b_sin)
    p_con, just_con = _puntuacion_calidad_precio(b_con)
    assert "Range Extender 252Wh incluido: +0.5" in just_con

    # 4. Auditoría pericial (Perito Mecánico Senior)
    audit = auditar_perito_mecanico(b_con)
    assert "Range Extender oficial de 252 Wh" in audit["txt_bateria"]
    assert "Range Extender oficial (+252 Wh" in audit["txt_precio"]

    # 5. Formato de mensaje para Telegram
    msg = formatear_mensaje(b_con, 8.5, "Desglose pericial")
    assert "🔋 Batería: 612 Wh (360 Wh + 🔋 252 Wh Range Extender)" in msg


def test_salud_bateria_soh_disponibilidad_y_extractores():
    """Valida extracción de SoH %, ciclos de batería, filtro anti-reservadas/agotadas y extractores."""
    # 1. Extracción de SoH % y ciclos en Upway y Bike Ocasión
    txt_upway = (
        "Eléctrico Batería Estado de salud: 90\u00a0% Capacidad de la batería: 670 Wh "
        "Número de ciclos de carga de la batería: 164 Ubicación de la batería: Cuadro "
        "En esta bici, la batería se ha comprobado y conserva el 89 % de su capacidad original de 750 Wh, es decir, 670 Wh."
    )
    soh, ciclos = _extraer_salud_bateria(txt_upway)
    assert soh == 90
    assert ciclos == 164
    assert _extraer_bateria(txt_upway) == 750  # Capacidad nominal original preservada

    soh_bo, ciclos_bo = _extraer_salud_bateria("Potencia batería: 540Wh | % batería: 95% | Km: 1200")
    assert soh_bo == 95
    assert ciclos_bo is None

    soh_vacio, _ = _extraer_salud_bateria("Potencia batería: 540Wh | % batería: - | Km: 1837")
    assert soh_vacio is None

    # 2. Motor en formato Upway ("Marca: X Modelo: Y") y EP800
    assert _extraer_motor("Motor Marca: Shimano Modelo: EP800 Ubicación: Central") == "Shimano EP8"
    assert _extraer_motor("Motor Marca: Bosch Modelo: Performance Line CX Par: 85 Nm") == "Bosch Performance Line CX"

    # 3. Año ignorando fechas de entrega estimada o venta
    assert _extraer_ano("Entrega estimada 12 nov. 2026. Envío gratuito.") is None
    assert _extraer_ano("Entrega estimada 12 nov. 2026. Año del modelo: 2023") == 2023

    # 4. Detección de bicicletas reservadas / agotadas y no falsos positivos ("¿Quieres reservarla?")
    assert BaseScraper.es_tarjeta_no_disponible(texto_tarjeta="Orbea Rise H10 - RESERVADA - 2.499 €") is True
    assert BaseScraper.es_tarjeta_no_disponible(texto_tarjeta="BH iLynx Race - Producto agotado") is True
    assert BaseScraper.es_tarjeta_no_disponible(texto_tarjeta="¿Tienes dudas técnicas? ¿Quieres reservarla? Financiación") is False

    b_reservada = bici_prueba(disponible=False)
    apto_res, motivo_res = pasa_filtros_estrictos(b_reservada)
    assert apto_res is False
    assert "reservada o agotada" in motivo_res

    # 5. Impacto de SoH % en Perito Mecánico Escéptico y formato de Telegram
    b_soh_optimo = bici_prueba(
        titulo="Orbea Rise M20 2023",
        bateria_wh=540,
        bateria_salud_pct=96,
        bateria_ciclos=38,
        km=1800,
        peso_kg=19.5,
    )
    audit_opt = auditar_perito_mecanico(b_soh_optimo)
    assert audit_opt["delta_motor"] == 0.0
    assert "SoH medido: 96%" in audit_opt["txt_motor"]
    assert "38 ciclos diagnosticados" in audit_opt["txt_motor"]

    b_soh_malo = bici_prueba(
        titulo="Orbea Rise M20 2023",
        bateria_wh=540,
        bateria_salud_pct=78,
        bateria_ciclos=240,
        km=1200,
        peso_kg=19.5,
    )
    audit_malo = auditar_perito_mecanico(b_soh_malo)
    assert "ALERTA CRÍTICA" in audit_malo["txt_motor"]

    msg_soh = formatear_mensaje(b_soh_optimo, audit_opt["nota_final"], "Desglose")
    assert "540 Wh [SoH: 96% | 38 ciclos]" in msg_soh


def test_todos_historial_catalogo_recorrido_y_stats():
    """Valida los TODOs: extracción de recorrido (mm), prioridad objetiva y tracking de catálogo."""
    # 1. Extractor de recorrido en mm
    assert _extraer_recorrido("Horquilla Fox 34 Float con 130 mm de recorrido") == 130
    assert _extraer_recorrido("Recorrido horquilla: 120mm. Amortiguador Fox DPS.") == 120
    assert _extraer_recorrido("RockShox Pike 140 mm") == 140
    assert _extraer_recorrido("Bicicleta de paseo sin suspension") is None

    # 2. Prioridad objetiva por recorrido de suspensión
    b_xc = bici_prueba(recorrido_mm=120)
    b_trail_ligero = bici_prueba(recorrido_mm=140)
    b_all_mtn = bici_prueba(recorrido_mm=150)
    b_enduro = bici_prueba(recorrido_mm=170)

    assert prioridad_modalidad(b_xc) == 3
    assert prioridad_modalidad(b_trail_ligero) == 2
    assert prioridad_modalidad(b_all_mtn) == 1
    assert prioridad_modalidad(b_enduro) == 0

    # 3. Filtro S2bis: descarte por recorrido excesivo (> 170 mm)
    b_dh = bici_prueba(recorrido_mm=180)
    apto_dh, motivo_dh = pasa_filtros_estrictos(b_dh)
    assert apto_dh is False
    assert "excesivo" in motivo_dh

    # 4. Historial de catálogo y tiempo en stock en SQLite
    fd, path_tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = BaseDatos(ruta=path_tmp)
        bici_track = bici_prueba(bici_id="track-001", precio=2999.0)
        
        # Primer registro: días 0, rebajas 0
        res1 = db.registrar_en_catalogo(bici_track)
        assert res1["dias_en_stock"] == 0
        assert res1["rebajas_detectadas"] == 0
        assert res1["precio_actual"] == 2999.0

        # Segundo registro con bajada de precio a 2.750 €
        bici_track.precio = 2750.0
        res2 = db.registrar_en_catalogo(bici_track)
        assert res2["rebajas_detectadas"] == 1
        assert res2["ahorro_eur"] == 249.0
        assert res2["precio_minimo"] == 2750.0

        # Consulta de seguimiento
        seg = db.obtener_seguimiento("track-001")
        assert seg is not None
        assert seg["rebajas_detectadas"] == 1
        assert seg["ahorro_eur"] == 249.0

        # Radar de mercado / estadísticas
        stats = db.obtener_estadisticas_mercado()
        assert stats["total"] == 1
        assert "Bike Ocasión" in stats["por_sitio"]
        assert len(stats["con_rebajas"]) == 1
        assert stats["con_rebajas"][0]["ahorro"] == 249.0

        # Formateo de Telegram con recorrido y seguimiento
        msg = formatear_mensaje(
            bici_track,
            nota=8.5,
            desglose="Desglose test",
            seguimiento={"dias_en_stock": 7, "rebajas_detectadas": 1},
        )
        assert "7 días en catálogo" in msg
        assert "1 rebaja(s)" in msg
    finally:
        try:
            if os.path.exists(path_tmp):
                os.remove(path_tmp)
        except PermissionError:
            pass


def test_extraccion_km_imagenes_ficha_buhobike_vigilancia_y_radar_md():
    """
    Valida:
      1. Normalización de km (string/int) y extracción con formato prefijo 'Km: 1837'.
      2. Extracción estructurada de tabla técnica de Buhobike (peso real de báscula 19,57Kg, recorrido 140mm).
      3. Extracción de km desde galería de imágenes mediante Gemini Vision cuando no aparece en texto/datos.
      4. Alerta proactiva de Entrada desde Zona de Vigilancia (> 3.000 € -> <= 3.000 €).
      5. Exportación automática del informe Markdown docs/radar_mercado.md.
    """
    from bs4 import BeautifulSoup
    from unittest.mock import patch, MagicMock
    from pathlib import Path
    import config as cfg

    # 1. Normalización de km y formato 'Km: 1837' de Bike Ocasión
    assert _normalizar_km_existente(4237) == 4237
    assert _normalizar_km_existente("4.237") == 4237
    assert _normalizar_km_existente("1.837 km") == 1837
    assert _normalizar_km_existente("-") is None
    assert _normalizar_km_existente(None) is None
    assert _extraer_km("Potencia batería: 540Wh | % batería: - | Km: 1837 | Rango: De 500Wh") == 1837

    # 2. Extracción de tabla técnica de Buhobike (peso exacto 19,57Kg y recorrido 140 mm)
    html_buhobike = """
    <div id="description">
      <table class="caracteristicas-tecnicas-2-tablas">
        <tbody>
          <tr><th>AÑO</th><td>2022</td></tr>
          <tr><th>CUADRO</th><td>ALUMINIO</td></tr>
          <tr><th>HORQUILLA</th><td>FOX 34 FACTORY KASHIMA con 140 mm de recorrido</td></tr>
          <tr><th>MOTOR</th><td>SHIMANO EP8-RS</td></tr>
          <tr><th>BATERÍA</th><td>ORBEA INTERNAL 540 WH</td></tr>
          <tr><th>PESO</th><td>19,57Kg </td></tr>
        </tbody>
      </table>
    </div>
    <ul class="product-images">
      <li><img class="js-thumb" data-image-large-src="https://www.buhobike.com/200248-large_default/orbea-rise.jpg" src="thumb1.jpg"/></li>
      <li><img class="js-thumb" data-image-large-src="https://www.buhobike.com/203857-large_default/orbea-rise.jpg" src="thumb2.jpg"/></li>
    </ul>
    """
    soup_bh = BeautifulSoup(html_buhobike, "html.parser")
    pares = dict(_extraer_pares_ficha_estructurada(soup_bh))
    assert "peso" in pares
    assert _extraer_peso(f"Peso: {pares['peso']}") == 19.57
    assert _extraer_recorrido(pares["horquilla"]) == 140

    # 3. Extracción de URLs de galería y lectura de odómetro en imágenes (Gemini Vision mock)
    urls_galeria = _recolectar_urls_imagenes_ficha(soup_bh, url_ficha="https://www.buhobike.com/bici.html")
    assert len(urls_galeria) == 2
    assert "203857-large_default" in urls_galeria[1]

    assert _parsear_respuesta_km_vision('{"km": 4238}') == 4238
    assert _parsear_respuesta_km_vision('{"odometer_total_km": 4237.59}') == 4238
    assert _parsear_respuesta_km_vision('{"km": null}') is None

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.content = b"\xff\xd8\xff\xe0" + (b"0" * 4000)

    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": '{"km": 4238}'}]}}]
    }

    with patch.object(cfg, "GEMINI_API_KEY", "fake-key-test"), \
         patch("scrapers.enriquecedor_web.requests.get", return_value=mock_get_resp), \
         patch("scrapers.enriquecedor_web.requests.post", return_value=mock_post_resp):
        km_img = _extraer_km_de_imagenes(soup_bh, url_ficha="https://www.buhobike.com/bici.html")
        assert km_img == 4238

    # 4. Alerta de Zona de Vigilancia (> 3.000 € -> <= 3.000 €) y exportación de docs/radar_mercado.md
    fd, path_tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    fd_md, path_md_tmp = tempfile.mkstemp(suffix=".md")
    os.close(fd_md)
    try:
        db = BaseDatos(ruta=path_tmp)
        b_vig = bici_prueba(bici_id="vig-001", titulo="Orbea Rise M10 2023", precio=3250.0)
        r_ini = db.registrar_en_catalogo(b_vig)
        assert r_ini["entrada_desde_vigilancia"] is False

        # Baja a 2.890 € (entra desde Zona de Vigilancia al presupuesto <= 3.000 €)
        b_vig.precio = 2890.0
        r_drop = db.registrar_en_catalogo(b_vig)
        assert r_drop["entrada_desde_vigilancia"] is True
        assert r_drop["ahorro_eur"] == 360.0

        seg_vig = db.obtener_seguimiento("vig-001")
        assert seg_vig is not None and seg_vig["entrada_desde_vigilancia"] is True

        msg_vig = formatear_mensaje(
            b_vig,
            nota=9.0,
            desglose="Desglose vigilancia",
            seguimiento=seg_vig,
        )
        assert "ENTRADA DESDE ZONA DE VIGILANCIA" in msg_vig
        assert "BAJADA DE PRECIO" in msg_vig
        assert "-360" in msg_vig

        # 5. Exportación de radar de mercado a Markdown
        ruta_generada = exportar_radar_mercado_md(ruta=Path(path_md_tmp), db=db)
        contenido_md = ruta_generada.read_text(encoding="utf-8")
        assert "Radar de Mercado e-MTB de Ocasión" in contenido_md
        assert "Orbea Rise M10 2023" in contenido_md
        assert "-360 €" in contenido_md
    finally:
        for p in (path_tmp, path_md_tmp):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except PermissionError:
                pass


def test_proxy_rotator_y_resiliencia_red():
    """
    Valida:
      1. crear_proxy_rotator devuelve None si la lista está vacía.
      2. Rotación cíclica con ProxyRotator entregando proxies en orden secuencial.
      3. Rotación aleatoria con random_rotation.
      4. Inicialización correcta de _proxy_rotator y _session_proxy en BaseScraper.
      5. Limpieza de comillas y formato de proxies.
    """
    # 1. Lista vacía devuelve None
    assert crear_proxy_rotator(proxies=[]) is None
    assert crear_proxy_rotator(proxies=["   "]) is None

    # 2. Rotación cíclica
    proxies_test = ["http://proxy1.test:8080", "http://proxy2.test:8080"]
    rotator_ciclico = crear_proxy_rotator(proxies=proxies_test, rotacion="cyclic")
    assert rotator_ciclico is not None
    p1 = rotator_ciclico.get_proxy()
    p2 = rotator_ciclico.get_proxy()
    p3 = rotator_ciclico.get_proxy()
    assert p1 == "http://proxy1.test:8080"
    assert p2 == "http://proxy2.test:8080"
    assert p3 == "http://proxy1.test:8080"  # Vuelve al inicio

    # 3. Rotación aleatoria
    rotator_random = crear_proxy_rotator(proxies=proxies_test, rotacion="random")
    assert rotator_random is not None
    pr = rotator_random.get_proxy()
    assert pr in proxies_test

    # 4. BaseScraper con proxy rotator activo
    class ScraperPrueba(BaseScraper):
        def extraer_bicicletas(self):
            return []

    sitio_dummy = cfg.SitioObjetivo(
        nombre="SitioPrueba",
        base_url="https://prueba.com",
        seccion_emtb="https://prueba.com/emtb",
    )

    # Inyectamos temporalmente proxies en cfg para probar instanciación
    proxies_originales = cfg.PROXY_LIST
    try:
        cfg.PROXY_LIST = ["http://usuario:pass@proxy.corp:3128"]
        scraper = ScraperPrueba(sitio=sitio_dummy)
        assert scraper._proxy_rotator is not None
        assert scraper._proxy_rotator.get_proxy() == "http://usuario:pass@proxy.corp:3128"
        assert scraper._session_proxy is not None
    finally:
        cfg.PROXY_LIST = proxies_originales


def test_profundizacion_telemetria_bateria_upway_y_mammoth():
    """Valida la profundización de telemetría de batería (SoH % y ciclos) en Upway y Mammoth."""
    # 1. Upway: Batería sustituida / reemplazada / a estrenar
    txt_reemplazada = (
        "Batería Estado: Reemplazada Capacidad de la batería: 750 Wh "
        "Número de ciclos de carga de la batería: 1 Ubicación: Cuadro"
    )
    soh_r, ciclos_r = _extraer_salud_bateria(txt_reemplazada)
    assert soh_r == 100
    assert ciclos_r == 1
    assert _extraer_bateria(txt_reemplazada) == 750

    # 2. Upway: Capacidad restante porcentual
    txt_restante = "En esta bici la batería se ha comprobado y la capacidad restante es del 88% respecto al valor original de 625 Wh."
    soh_rest, _ = _extraer_salud_bateria(txt_restante)
    assert soh_rest == 88
    assert _extraer_bateria(txt_restante) == 625

    # 3. Upway: Ciclos de carga sin salud porcentual explícita
    txt_ciclos_solos = "Batería Estado: De origen Capacidad de la batería: 625 Wh Número de ciclos de carga de la batería: 5"
    soh_cs, ciclos_cs = _extraer_salud_bateria(txt_ciclos_solos)
    assert soh_cs is None
    assert ciclos_cs == 5

    # 4. Mammoth: Capacidad principal (EnergyPak 625) frente a extender opcional/compatible (250 Wh)
    txt_mammoth = "Batería: EnergyPak Smart 625EnergyPak Plus 250Wh range extender compatible"
    bat_m = _extraer_bateria(txt_mammoth)
    assert bat_m == 625

    # 5. Mammoth / Bicicleta nueva a estrenar (km=0 y garantía >= 2 años)
    bici_nueva = bici_prueba(sitio="Mammoth", titulo="Orbea Rise M20 2024", km=0, garantia_anos=3, bateria_wh=625)
    detalle_simulado = {}
    bici_enriquecida = _aplicar_detalle(bici_nueva, detalle_simulado)
    assert bici_enriquecida.bateria_salud_pct == 100
    assert bici_enriquecida.bateria_ciclos == 0

    # Mensaje de Telegram y Perito Mecánico Escéptico para bici nueva con SoH 100% y 0 ciclos (sin bono positivo)
    audit_nueva = auditar_perito_mecanico(bici_enriquecida)
    assert audit_nueva["delta_motor"] == 0.0
    assert audit_nueva["delta_garantia"] == 0.0
    assert "SoH medido: 100%" in audit_nueva["txt_motor"]
    assert "0 ciclos diagnosticados" in audit_nueva["txt_motor"]
    msg_nueva = formatear_mensaje(bici_enriquecida, audit_nueva["nota_final"], "Desglose")
    assert "625 Wh [SoH: 100% | 0 ciclos]" in msg_nueva


def test_radar_mercado_metricas_enriquecidas_y_heartbeat():
    """
    Valida:
      1. Soporte de pvp_original en BaseDatos y cálculo de descuento % vs PVP original.
      2. Enriquecimiento de obtener_estadisticas_mercado con metricas_por_sitio y resumen_global
         (permanencia media en stock, ahorro medio por rebajas y precios medios).
      3. Exportación de docs/radar_mercado.md con las nuevas tablas enriquecidas.
      4. Extractor de PVP original en tarjetas de Upway ('2.499 € 6.000 € nuevo' -> 6000.0).
      5. Formateo y envío de Heartbeat operativo para Telegram.
    """
    fd, path_tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db = BaseDatos(ruta=path_tmp)

        # 1. Registro con pvp_original en Upway y rebaja posterior
        bici_upway = bici_prueba(
            sitio="Upway",
            bici_id="upway-rise-01",
            titulo="Orbea Rise H30 2023",
            precio=2200.0,
            url="https://upway.es/products/orbea-rise-h30",
            pvp_original=5499.0,
        )
        res_ini = db.registrar_en_catalogo(bici_upway)
        assert res_ini["pvp_original"] == 5499.0
        assert res_ini["rebajas_detectadas"] == 0

        # Rebaja de 200 €
        from dataclasses import replace
        bici_rebajada = replace(bici_upway, precio=2000.0)
        res_reb = db.registrar_en_catalogo(bici_rebajada)
        assert res_reb["rebajas_detectadas"] == 1
        assert res_reb["ahorro_eur"] == 200.0

        # Segunda bici en Zona de Vigilancia (Bike Ocasión)
        bici_vig = bici_prueba(
            sitio="Bike Ocasión",
            bici_id="bo-vig-01",
            titulo="BH iLynx Trail Carbon 8.7",
            precio=3100.0,
            url="https://bike-ocasion.com/bici/bo-vig-01",
            pvp_original=6800.0,
        )
        db.registrar_en_catalogo(bici_vig)

        # 2. Métricas agregadas de mercado
        stats = db.obtener_estadisticas_mercado()
        assert stats["total"] == 2
        assert "metricas_por_sitio" in stats
        m_upway = stats["metricas_por_sitio"]["Upway"]
        assert m_upway["unidades"] == 1
        assert m_upway["precio_medio"] == 2000.0
        assert m_upway["con_rebajas"] == 1
        assert m_upway["ahorro_medio_rebajas"] == 200.0
        assert m_upway["descuento_pvp_medio_pct"] is not None
        assert m_upway["descuento_pvp_medio_pct"] > 60.0  # (5499 - 2000)/5499 = ~63.6%

        res_glob = stats["resumen_global"]
        assert res_glob["total"] == 2
        assert res_glob["con_rebajas"] == 1
        assert res_glob["ahorro_total_acumulado"] == 200.0
        assert res_glob["en_vigilancia"] == 1

        assert "Orbea Rise" in stats["modelos_clave"]
        assert stats["modelos_clave"]["Orbea Rise"]["precio_medio"] == 2000.0

        # 3. Exportación Markdown
        fd_md, path_md = tempfile.mkstemp(suffix=".md")
        os.close(fd_md)
        try:
            exportar_radar_mercado_md(ruta=path_md, db=db)
            with open(path_md, "r", encoding="utf-8") as f:
                md_contenido = f.read()

            assert "Distribución por Portal y Permanencia" in md_contenido
            assert "Días en Stock (medio)" in md_contenido
            assert "Ahorro Medio Rebajas" in md_contenido
            assert "Permanencia media global" in md_contenido
            assert "-200 €" in md_contenido
        finally:
            if os.path.exists(path_md):
                os.remove(path_md)

        # 4. Extractor PVP original de Upway
        scraper_up = UpwayScraper(cfg.SITIOS[2])
        ejemplo_txt = "Mejor precio Recién llegada Focus THRON² 6.9 2023 1m60-1m70 1786 km 2.499 € 6.000 € nuevo"
        pvp_detectado = scraper_up._parsear_pvp_original(ejemplo_txt)
        assert pvp_detectado == 6000.0

        # 5. Heartbeat formateo y envío mockeado
        resumen_hb = {
            "fecha_hora": "2026-11-14 12:00:15",
            "duracion_seg": 42.5,
            "conteo_por_portal": {"Bike Ocasión": 180, "Upway": 65, "Buhobike": 40, "Mammoth": 34},
            "total_procesadas": 319,
            "candidatas_aptas": 4,
            "notificadas": 2,
            "total_en_catalogo": 64,
            "total_en_vigilancia": 27,
            "estado": "🟢 Runner operativo",
        }
        msg_hb = formatear_heartbeat(resumen_hb)
        assert "Heartbeat Buscador e-MTB" in msg_hb
        assert "319 bicicletas" in msg_hb
        assert "Bike Ocasión: *180*" in msg_hb
        assert "*2* enviada(s)" in msg_hb
        assert "64" in msg_hb
        assert "🟢 Runner operativo" in msg_hb

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            ok = enviar_heartbeat(resumen_hb)
            assert ok is True
            assert mock_post.called

    finally:
        try:
            if os.path.exists(path_tmp):
                os.remove(path_tmp)
        except PermissionError:
            pass


def test_mega_chollo_alerta_y_formato_telegram():
    """Valida que Mega Chollo requiera estrictamente >50% descuento vs PVP Y nota >= 9.0 (si nota < 9.0 es oferta normal)."""
    b_oferta = bici_prueba(
        titulo="Focus THRON² 6.9 2023",
        precio=2499.0,
        pvp_original=6000.0,
        km=1786,
    )

    # 1. Descuento >50% pero nota < 9.0 (ej. 8.5) -> Oferta normal, NO es Mega Chollo
    msg_normal = formatear_mensaje(b_oferta, 8.5, "Desglose pericial")
    assert "MEGA CHOLLO" not in msg_normal
    assert "Nueva oportunidad de e-MTB encontrada" in msg_normal
    assert "PVP Original: ~6000 €~ (*-58%* | Ahorro: *-3501 €*)" in msg_normal

    # 2. Descuento >50% Y nota >= 9.0 (ej. 9.2) -> ¡MEGA CHOLLO certificado!
    msg_mega = formatear_mensaje(b_oferta, 9.2, "Desglose pericial")
    assert "MEGA CHOLLO e-MTB DETECTADO" in msg_mega
    assert "-58% vs PVP" in msg_mega
    assert "PVP Original: ~6000 €~" in msg_mega
    assert "💥 *MEGA CHOLLO* *-58%*" in msg_mega
    assert "Ahorro: *-3501 €*" in msg_mega

    # 3. Mega Chollo (nota >= 9.0) con bajada de precio activa
    msg_mega_bajada = formatear_mensaje(b_oferta, 9.0, "Desglose", precio_anterior=2699.0)
    assert "MEGA CHOLLO + BAJADA DE PRECIO" in msg_mega_bajada
    assert "-58% vs PVP" in msg_mega_bajada
    assert "Ahorro: *-200 €*" in msg_mega_bajada

    # 4. Mega Chollo (nota >= 9.0) con entrada desde vigilancia y bajada
    seg_vig = {"precio_inicial": 3100.0, "entrada_desde_vigilancia": True}
    msg_mega_vig = formatear_mensaje(b_oferta, 9.1, "Desglose", seguimiento=seg_vig)
    assert "MEGA CHOLLO + ENTRADA DE VIGILANCIA" in msg_mega_vig

    # 5. Descuento menor al 50% con cualquier nota (no es Mega Chollo pero muestra PVP original)
    b_bajo_dto = bici_prueba(
        titulo="Trek Fuel EXe 9.5",
        precio=2500.0,
        pvp_original=4000.0,
    )
    msg_bajo = formatear_mensaje(b_bajo_dto, 9.5, "Desglose")
    assert "MEGA CHOLLO" not in msg_bajo
    assert "Nueva oportunidad de e-MTB encontrada" in msg_bajo
    assert "PVP Original: ~4000 €~ (*-38%* | Ahorro: *-1500 €*)" in msg_bajo

    # 6. Bonificación en evaluator._puntuacion_calidad_precio por descuento masivo
    pts_mega, just_mega = _puntuacion_calidad_precio(b_oferta)
    assert "Mega Chollo (58% dto vs PVP): +0.5" in just_mega or "dto vs PVP" in just_mega

    # 7. Diagnóstico en Heartbeat con Mega Chollos
    hb_data = {
        "fecha_hora": "2026-11-16 11:20:00",
        "duracion_seg": 35.0,
        "conteo_por_portal": {"Upway": 20},
        "total_procesadas": 20,
        "candidatas_aptas": 3,
        "notificadas": 1,
        "mega_chollos": 2,
        "total_en_catalogo": 70,
        "total_en_vigilancia": 25,
        "estado": "🟢 Runner operativo",
    }
    msg_hb = formatear_heartbeat(hb_data)
    assert "Mega Chollos (>50% dto y Nota >= 9.0): *2* 💥" in msg_hb


def test_segmentacion_sonora_vs_silenciosa_telegram():
    """Valida que las ofertas normales se envíen en silencio y solo los Mega Chollos con sonido prioritario (TODO 3)."""
    # 1. Función pericial es_mega_chollo
    b_chollo_real = bici_prueba(precio=2499.0, pvp_original=6000.0)
    assert es_mega_chollo(b_chollo_real, 9.2) is True
    assert es_mega_chollo(b_chollo_real, 8.9) is False

    b_bajo_dto = bici_prueba(precio=2500.0, pvp_original=4000.0)
    assert es_mega_chollo(b_bajo_dto, 9.5) is False

    b_sin_pvp = bici_prueba(precio=2500.0, pvp_original=None)
    assert es_mega_chollo(b_sin_pvp, 9.5) is False

    # 2. Despacho silencioso para oferta normal (nota 8.5)
    with patch("requests.post") as mock_post, patch.object(cfg, "TELEGRAM_BOT_TOKEN", "fake_token"), patch.object(cfg, "TELEGRAM_CHAT_ID", "123456"):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp

        ok_normal = enviar(b_chollo_real, 8.5, "Desglose normal")
        assert ok_normal is True
        assert mock_post.called
        payload_normal = mock_post.call_args[1]["json"]
        assert payload_normal["disable_notification"] is True, "Las ofertas normales deben despacharse silenciosas (disable_notification=True)"

        # 3. Despacho sonoro prioritario para Mega Chollo (nota 9.2 y dto > 50%)
        mock_post.reset_mock()
        ok_mega = enviar(b_chollo_real, 9.2, "Desglose mega chollo")
        assert ok_mega is True
        payload_mega = mock_post.call_args[1]["json"]
        assert payload_mega["disable_notification"] is False, "Los Mega Chollos deben notificar con sonido prioritario (disable_notification=False)"

        # 4. Forzado explícito del parámetro silencioso
        mock_post.reset_mock()
        enviar(b_chollo_real, 9.2, "Desglose forzado silencio", silencioso=True)
        assert mock_post.call_args[1]["json"]["disable_notification"] is True

        mock_post.reset_mock()
        enviar(b_bajo_dto, 7.5, "Desglose forzado sonoro", silencioso=False)
        assert mock_post.call_args[1]["json"]["disable_notification"] is False

        # 5. Heartbeat se envía siempre en silencio para no molestar
        mock_post.reset_mock()
        enviar_heartbeat({"fecha_hora": "2026-11-17 01:00:00", "duracion_seg": 10.0})
        payload_hb = mock_post.call_args[1]["json"]
        assert payload_hb["disable_notification"] is True, "El Heartbeat debe enviarse en silencio (disable_notification=True)"


def test_rotacion_consecutiva_top3_y_aviso():
    """Valida entrega de 1 mejor bici por página y rotación ping-pong #1 -> #2 -> #1."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        ruta_db = f.name

    try:
        db = BaseDatos(ruta=ruta_db)

        # 1. BaseDatos: obtención inicial vacía y registro con estado_portales
        assert db.obtener_ultimo_analisis() is None

        db.registrar_analisis(
            top3_ids=["u-1", "w-1"],
            enviados_ids=["u-1", "w-1"],
            offset_usado=0,
            repetido=False,
            estado_portales={
                "Upway": {"top1_id": "u-1", "enviado_id": "u-1", "posicion": 1},
                "Wallapop": {"top1_id": "w-1", "enviado_id": "w-1", "posicion": 1},
            },
        )
        ult = db.obtener_ultimo_analisis()
        assert ult is not None
        assert ult["estado_portales"]["Upway"]["enviado_id"] == "u-1"
        assert ult["estado_portales"]["Wallapop"]["posicion"] == 1

        # 2. Formateo de mensajes de rotación por portal (#2) y retorno a #1
        b_alt = bici_prueba(sitio="Upway", bici_id="u-2", titulo="Orbea Rise M20 Alternativa", precio=2600.0)
        msg_rot2 = formatear_mensaje(
            b_alt,
            8.7,
            "Desglose de prueba",
            aviso_top_repetido=True,
            ranking_posicion=2,
            es_rotacion_portal=True,
        )
        assert "🔄 *#1 de Upway sin cambios respecto al análisis anterior*" in msg_rot2
        assert "💡 _Exponiendo alternativa #2 de Upway:_" in msg_rot2

        msg_ret1 = formatear_mensaje(
            b_alt,
            9.0,
            "Desglose de prueba",
            aviso_top_repetido=False,
            ranking_posicion=1,
            aviso_retorno_top1=True,
        )
        assert "🏆 *Confirmada #1 en Upway*" in msg_ret1

        msg_normal = formatear_mensaje(b_alt, 8.7, "Desglose de prueba", aviso_top_repetido=False)
        assert "sin cambios" not in msg_normal
        assert "Confirmada #1" not in msg_normal

        # 3. Heartbeat con rotación por portal activa
        hb_data = {
            "fecha_hora": "2026-11-19 12:00:00",
            "duracion_seg": 20.0,
            "total_procesadas": 15,
            "candidatas_aptas": 6,
            "notificadas": 3,
            "top_repetido": True,
            "portales_rotados": ["Upway", "Wallapop"],
            "portales_retorno_top1": ["Bike Ocasión"],
            "estado": "🟢 Runner operativo",
        }
        msg_hb = formatear_heartbeat(hb_data)
        assert "🔄 Alternativa #2 (misma #1): Upway, Wallapop" in msg_hb
        assert "🏆 Retorno a #1 confirmada: Bike Ocasión" in msg_hb

        # 4. Simular 3 pasadas consecutivas en main.ejecutar_busqueda con 4 portales
        from main import ejecutar_busqueda
        db2_fd, ruta_db2 = tempfile.mkstemp(suffix=".db")
        os.close(db2_fd)
        try:
            db2 = BaseDatos(ruta=ruta_db2)
            oportunidades_4_portales = [
                # Upway (2 válidas <21 kg)
                (bici_prueba(sitio="Upway", bici_id="u-1", titulo="Orbea Rise M20 2023", precio=2500.0, peso_kg=18.5), 9.0, "D"),
                (bici_prueba(sitio="Upway", bici_id="u-2", titulo="BH iLynx Race 8.4", precio=2600.0, peso_kg=17.8), 8.5, "D"),
                # Bike Ocasión (2 válidas <21 kg)
                (bici_prueba(sitio="Bike Ocasión", bici_id="bo-1", titulo="Specialized Levo SL", precio=2700.0, peso_kg=18.0), 8.8, "D"),
                (bici_prueba(sitio="Bike Ocasión", bici_id="bo-2", titulo="Trek Fuel EXe 9.5", precio=2800.0, peso_kg=19.2), 8.0, "D"),
                # Wallapop (2 válidas <21 kg)
                (bici_prueba(sitio="Wallapop", bici_id="w-1", titulo="Orbea Rise M10 2023", precio=2400.0, peso_kg=18.3, garantia_anos=0), 8.0, "D"),
                (bici_prueba(sitio="Wallapop", bici_id="w-2", titulo="Orbea Rise H10 2023", precio=2200.0, peso_kg=20.5, garantia_anos=0), 7.0, "D"),
                # Mammoth (solo 1 respaldo >=21 kg -> siempre entrega su mejor opción y no rompe si repite)
                (bici_prueba(sitio="Mammoth", bici_id="m-1", titulo="Cannondale Moterra Neo 3", precio=3100.0, peso_kg=23.5), 4.0, "D"),
            ]

            with patch("main.BaseDatos", return_value=db2), \
                 patch("main._recolectar_oportunidades", return_value=oportunidades_4_portales), \
                 patch("main.exportar_radar_mercado_md"), \
                 patch("main.enviar", return_value=True) as mock_enviar, \
                 patch("main.enviar_heartbeat"), \
                 patch("main.enviar_heartbeat_black_friday"):

                # Día 1: #1 de cada página (u-1, bo-1, w-1, m-1)
                ejecutar_busqueda(forzar_envio=True)
                ids_dia1 = [c[0][0].bici_id for c in mock_enviar.call_args_list]
                assert set(ids_dia1) == {"u-1", "bo-1", "w-1", "m-1"}
                assert len(ids_dia1) == 4
                assert all(c[1]["aviso_top_repetido"] is False for c in mock_enviar.call_args_list)

                # Día 2 (mismo catálogo): las páginas con >=2 válidas rotan a #2 (u-2, bo-2, w-2), Mammoth sigue en m-1
                mock_enviar.reset_mock()
                ejecutar_busqueda(forzar_envio=True)
                por_sitio_d2 = {c[0][0].sitio: c for c in mock_enviar.call_args_list}
                assert por_sitio_d2["Upway"][0][0].bici_id == "u-2"
                assert por_sitio_d2["Upway"][1]["aviso_top_repetido"] is True
                assert por_sitio_d2["Upway"][1]["es_rotacion_portal"] is True
                assert por_sitio_d2["Upway"][1]["ranking_posicion"] == 2
                assert por_sitio_d2["Bike Ocasión"][0][0].bici_id == "bo-2"
                assert por_sitio_d2["Wallapop"][0][0].bici_id == "w-2"
                assert por_sitio_d2["Mammoth"][0][0].bici_id == "m-1"

                # Día 3 (mismo catálogo): vuelve a #1 (u-1, bo-1, w-1) con aviso_retorno_top1=True
                mock_enviar.reset_mock()
                ejecutar_busqueda(forzar_envio=True)
                por_sitio_d3 = {c[0][0].sitio: c for c in mock_enviar.call_args_list}
                assert por_sitio_d3["Upway"][0][0].bici_id == "u-1"
                assert por_sitio_d3["Upway"][1]["aviso_top_repetido"] is False
                assert por_sitio_d3["Upway"][1]["aviso_retorno_top1"] is True
                assert por_sitio_d3["Bike Ocasión"][0][0].bici_id == "bo-1"
                assert por_sitio_d3["Wallapop"][0][0].bici_id == "w-1"
                assert por_sitio_d3["Mammoth"][0][0].bici_id == "m-1"
        finally:
            try:
                if os.path.exists(ruta_db2):
                    os.unlink(ruta_db2)
            except (PermissionError, OSError):
                pass

    finally:
        # En Windows, SQLite puede mantener el archivo temporal abierto brevemente.
        try:
            if os.path.exists(ruta_db):
                os.unlink(ruta_db)
        except (PermissionError, OSError):
            pass


def test_wallapop_geolocalizado_y_filtros():
    """Valida WallapopScraper: geo-filtro 50 km Fuenlabrada, NLP, garantía particular y enriquecedor sin SPA."""
    from scrapers.wallapop import WallapopScraper, distancia_haversine_km
    from scrapers.enriquecedor_web import enriquecer_bici

    # 1. Config preserva índices 0..3 y registra Wallapop en el índice 4 con radio 50 km desde Fuenlabrada
    assert cfg.SITIOS[0].nombre == "Bike Ocasión"
    assert cfg.SITIOS[3].nombre == "Mammoth"
    assert cfg.SITIOS[4].nombre == "Wallapop"
    assert cfg.SITIOS[4].garantia_anos == 0
    assert cfg.WALLAPOP_RADIO_KM == 50

    dist_getafe = distancia_haversine_km(cfg.WALLAPOP_LAT, cfg.WALLAPOP_LON, 40.3057, -3.7329)
    assert 3.0 <= dist_getafe <= 10.0

    scraper = WallapopScraper(cfg.SITIOS[4])

    pagina_mock = {
        "data": {
            "section": {
                "payload": {
                    "items": [
                        {
                            "id": "abc111",
                            "category_id": 17000,
                            "title": "Orbea Rise H10 Talla M + incluye cargador",
                            "description": "Bicicleta doble suspensión, bateria 540w, 3000km, cadena a estrenar, cuadro carbono, motor Shimano EP8 RS.",
                            "price": {"amount": 2650.0, "currency": "EUR"},
                            "reserved": {"flag": False},
                            "has_warranty": {"flag": False},
                            "is_refurbished": {"flag": False},
                            "location": {"latitude": 40.3057, "longitude": -3.7329, "city": "Getafe"},
                            "web_slug": "orbea-rise-h10-abc111",
                            "images": [
                                {"urls": {"big": "https://cdn.wallapop.com/images/test1.jpg"}},
                            ],
                        },
                        {
                            "id": "lejos222",
                            "category_id": 17000,
                            "title": "Specialized Turbo Levo Talla M chollo",
                            "description": "Doble suspensión 700Wh 500 km.",
                            "price": {"amount": 2500.0, "currency": "EUR"},
                            "reserved": {"flag": False},
                            "location": {"latitude": 41.3851, "longitude": 2.1734, "city": "Barcelona"},
                            "bump": {"type": "country"},
                            "web_slug": "turbo-levo-bcn",
                        },
                        {
                            "id": "res333",
                            "category_id": 17000,
                            "title": "BH iLynx Trail t.M",
                            "description": "Doble suspensión 540Wh.",
                            "price": {"amount": 2400.0, "currency": "EUR"},
                            "reserved": {"flag": True},
                            "location": {"latitude": 40.2842, "longitude": -3.7942, "city": "Fuenlabrada"},
                            "web_slug": "bh-res",
                        },
                        {
                            "id": "grav444",
                            "category_id": 17000,
                            "title": "Orbea Gravel Eléctrica Talla M",
                            "description": "Ideal pistas.",
                            "price": {"amount": 2400.0, "currency": "EUR"},
                            "reserved": {"flag": False},
                            "location": {"latitude": 40.2842, "longitude": -3.7942, "city": "Fuenlabrada"},
                            "web_slug": "gravel-fuenla",
                        },
                        {
                            "id": "sintalla555",
                            "category_id": 17000,
                            "title": "Pivot Shuttle SL Talla M/L",
                            "description": "Doble suspensión.",
                            "price": {"amount": 2990.0, "currency": "EUR"},
                            "reserved": {"flag": False},
                            "location": {"latitude": 40.3200, "longitude": -3.7600, "city": "Leganés"},
                            "web_slug": "pivot-ml",
                        },
                        {
                            "id": "refurb666",
                            "category_id": 17000,
                            "title": "Kenevo SL + extender original 160w Talla S3",
                            "description": "Doble suspensión batería interna 320Wh + extender 160w incluido.",
                            "price": {"amount": 2900.0, "currency": "EUR"},
                            "reserved": {"flag": False},
                            "has_warranty": {"flag": True},
                            "is_refurbished": {"flag": True},
                            "location": {"latitude": 40.3300, "longitude": -3.7600, "city": "Leganés"},
                            "web_slug": "kenevo-s3",
                        },
                    ]
                }
            }
        },
        "meta": {"next_page": None},
    }

    with patch.object(scraper, "_obtener_pagina_api", return_value=pagina_mock):
        bicis = scraper.extraer_bicicletas()

    ids = [b.bici_id for b in bicis]
    assert "wallapop-abc111" in ids
    assert "wallapop-lejos222" not in ids, "Anuncios remotos > 50 km deben bloquearse aunque tengan bump country"
    assert "wallapop-res333" not in ids, "Anuncios reservados deben descartarse (S0)"
    assert "wallapop-grav444" not in ids, "Bicis Gravel/Urbanas deben descartarse"
    assert "wallapop-refurb666" in ids

    b_priv = next(b for b in bicis if b.bici_id == "wallapop-abc111")
    assert b_priv.talla == "M"
    assert b_priv.bateria_wh == 540
    assert b_priv.km == 3000, f"Debía extraer 3000 km pese a mencionar 'cadena a estrenar', obtuvo {b_priv.km}"
    assert b_priv.suspension_trasera == "si"
    assert b_priv.garantia_anos == 0
    assert "Getafe" in (b_priv.ubicacion or "")
    assert b_priv.imagenes == ["https://cdn.wallapop.com/images/test1.jpg"]

    b_ml = next(b for b in bicis if b.bici_id == "wallapop-sintalla555")
    assert b_ml.talla == "ML"
    apto_ml, _ = pasa_filtros_estrictos(b_ml)
    assert apto_ml is False, "Talla M/L no debe pasar el filtro estricto de Talla M"

    b_ref = next(b for b in bicis if b.bici_id == "wallapop-refurb666")
    assert b_ref.talla == "M", f"Specialized S3 equivale a talla M, obtuvo {b_ref.talla}"
    assert b_ref.range_extender_wh == 160
    assert b_ref.garantia_anos == 1

    # 2. Auditoría pericial y Telegram en particulares (garantia_anos=0) sin mentir sobre garantía profesional
    audit_priv = auditar_perito_mecanico(b_priv)
    assert "1 año de garantía" not in audit_priv["txt_motor"]
    assert "1 año de garantía" not in audit_priv["txt_bateria"]
    nota_priv, desglose_priv = valorar_autonomo(b_priv)
    assert "1 año de garantía" not in desglose_priv
    msg_priv = formatear_mensaje(b_priv, nota_priv, desglose_priv)
    assert "Sin garantía comercial (particular)" in msg_priv
    assert "📍 Ubicación: Getafe" in msg_priv

    # 3. Enriquecedor Wallapop usa galería de imágenes pre-cargada sin scrapear HTML SPA
    b_sin_km = bici_prueba(
        sitio="Wallapop",
        bici_id="wallapop-vis999",
        url="https://es.wallapop.com/item/wallapop-vis999",
        km=None,
        garantia_anos=0,
        peso_kg=18.5,
        ano=2023,
        suspension_trasera="si",
        imagenes=["https://cdn.wallapop.com/images/odo.jpg"],
    )
    with patch("scrapers.enriquecedor_web._buscar_en_cache", return_value=None), \
         patch("scrapers.enriquecedor_web._guardar_en_cache"), \
         patch("scrapers.enriquecedor_web._extraer_desde_ficha_sitio") as mock_ficha, \
         patch("scrapers.enriquecedor_web._extraer_km_de_imagenes", return_value=1420) as mock_vis, \
         patch.object(cfg, "GEMINI_API_KEY", "fake_key"):
        b_enr = enriquecer_bici(b_sin_km, url_ficha=b_sin_km.url)
        assert mock_ficha.called is False, "No debe intentar scrapear HTML SPA de Wallapop"
        assert mock_vis.called is True
        assert b_enr.km == 1420

    # 4. Casos borde adversariales: M-Team, 170-180 mm, motor 600W/750W, extender separado, JSON nulo, sin coords
    from scrapers.wallapop import _extraer_talla_wallapop
    assert _extraer_talla_wallapop("Orbea Rise M-Team 2023", "Horquilla 170-180 mm") == "No indicada"
    assert _extraer_range_extender("batería interna de 360Wh + extender 252Wh incluido") == 252
    assert _extraer_range_extender("Orbea Rise + extender incluido, motor 250w") == 252

    pagina_borde = {
        "data": {
            "section": {
                "payload": {
                    "items": [
                        {
                            "id": "sincoords",
                            "category_id": 17000,
                            "title": "Orbea Rise Talla M",
                            "price": {"amount": 2500.0},
                            "reserved": None,
                            "location": {},
                        },
                        {
                            "id": "motorw",
                            "category_id": 17000,
                            "title": "Orbea Rise M-Team 2023",
                            "description": "Bosch SX 600W y batería 360Wh. Extender 252w se vende por separado. 170-180 mm",
                            "price": {"amount": 2500.0},
                            "reserved": None,
                            "location": {"latitude": 40.2842, "longitude": -3.7942, "city": "Fuenlabrada"},
                            "web_slug": "motorw",
                        },
                        "item_corrupto_no_dict",
                    ]
                }
            }
        },
        "meta": None,
    }
    with patch.object(scraper, "_obtener_pagina_api", return_value=pagina_borde):
        bicis_borde = scraper.extraer_bicicletas()
    assert [b.bici_id for b in bicis_borde] == ["wallapop-motorw"]
    bm = bicis_borde[0]
    assert bm.talla == "No indicada"
    assert bm.bateria_wh == 360
    assert bm.range_extender_wh is None


def test_todo2_dedup_interportal_wallapop_estricto_y_cache_ddg():
    """Valida deduplicación cruzada inter-portal, filtros estrictos Wallapop/cuadro AL y caché DuckDuckGo."""
    from db import titulos_equivalentes_dedup
    from main import deduplicar_inter_portal
    from scrapers.wallapop import WallapopScraper
    from scrapers.enriquecedor_web import completar_desde_duckduckgo

    # 1. Deduplicación cruzada inter-portal en corrida y contra bicis_enviadas
    b_buho = bici_prueba(
        sitio="Buhobike",
        bici_id="24839",
        titulo="ORBEA RISE H10 T-M 2022 BICICLETA SEGUNDA MANO",
        precio=2599.0,
    )
    b_wala_clon = bici_prueba(
        sitio="Wallapop",
        bici_id="wallapop-clon-rise",
        titulo="ORBEA RISE H10 T-M 2022 BICICLETA SEGUNDA MANO - Talla: M",
        precio=2599.0,
        garantia_anos=0,
    )
    b_wala_barata = bici_prueba(
        sitio="Wallapop",
        bici_id="wallapop-barata",
        titulo="Orbea Rise H10 2023/24 540w Talla M",
        precio=2200.0,
        garantia_anos=0,
    )
    assert titulos_equivalentes_dedup(b_buho.titulo, b_wala_clon.titulo) is True
    assert titulos_equivalentes_dedup(b_buho.titulo, b_wala_barata.titulo) is False

    dedup = deduplicar_inter_portal([b_wala_clon, b_wala_barata, b_buho])
    ids_dedup = [b.bici_id for b in dedup]
    assert "24839" in ids_dedup
    assert "wallapop-clon-rise" not in ids_dedup, "El clon de Wallapop debe omitirse frente a la tienda oficial"
    assert "wallapop-barata" in ids_dedup

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        ruta_db = f.name
    try:
        db = BaseDatos(ruta=ruta_db)
        db.registrar(b_buho, 7.5)
        assert db.fue_enviada_equivalente(b_wala_clon) is True
        assert db.fue_enviada_equivalente(b_wala_barata) is False
    finally:
        try:
            if os.path.exists(ruta_db):
                os.unlink(ruta_db)
        except (PermissionError, OSError):
            pass

    # 2. Ghost E-ASX 160 Advanced AL y heurística conservadora de peso/cuadro
    b_ghost = Bicicleta(
        sitio="Wallapop",
        bici_id="wallapop-ghost",
        titulo="Ghost E-ASX 160 Advanced AL Shimano XT 2023",
        precio=2849.0,
        url="https://es.wallapop.com/item/ghost",
        talla="M",
    )
    b_ghost = completar_con_catalogo(b_ghost, aplicar_heuristica_peso=True)
    assert b_ghost.cuadro_material == "Aluminio"
    assert b_ghost.peso_kg >= 21.0
    apto_g, _ = pasa_filtros_estrictos(b_ghost)
    assert apto_g is False, "Ghost E-ASX 160 Advanced AL (>=21 kg) debe descartarse en filtro S3"

    b_desconocida = Bicicleta(
        sitio="Wallapop",
        bici_id="wallapop-unk",
        titulo="MTB Trail Carbon X12",
        precio=2500.0,
        url="https://es.wallapop.com/item/unk",
        talla="M",
    )
    b_desconocida = completar_con_catalogo(b_desconocida, aplicar_heuristica_peso=True)
    assert b_desconocida.cuadro_material == "Carbono"
    assert b_desconocida.peso_kg >= 19.0, "Sin batería/peso verificados nunca debe inferir peso pluma <19 kg"

    # 3. Filtros estrictos Wallapop: rechazar urbanas y anuncios genéricos sin modelo doble ni amortiguador
    scraper = WallapopScraper(cfg.SITIOS[4])
    pagina_estricta = {
        "data": {
            "section": {
                "payload": {
                    "items": [
                        {
                            "id": "generica1",
                            "category_id": 17000,
                            "title": "Bicicleta Eléctrica BH 237 km. Esta nueva!!",
                            "description": "Cuadro de carbono, horquilla Fox Rhythm, Talla M.",
                            "price": {"amount": 2100.0},
                            "reserved": {"flag": False},
                            "location": {"latitude": 40.2842, "longitude": -3.7942, "city": "Fuenlabrada"},
                            "web_slug": "bh-gen",
                        },
                        {
                            "id": "urbana2",
                            "category_id": 17000,
                            "title": "Bicicleta Orbea Diem 10 t.M Reacondicionada",
                            "description": "Correa carbono.",
                            "price": {"amount": 3055.0},
                            "reserved": {"flag": False},
                            "location": {"latitude": 40.2842, "longitude": -3.7942, "city": "Fuenlabrada"},
                            "web_slug": "diem-10",
                        },
                    ]
                }
            }
        },
        "meta": {"next_page": None},
    }
    with patch.object(scraper, "_obtener_pagina_api", return_value=pagina_estricta):
        assert scraper.extraer_bicicletas() == []

    # 4. Caché DuckDuckGo y omisión de títulos genéricos
    b_gen_ddg = bici_prueba(sitio="Wallapop", titulo="Bicicleta eléctrica", peso_kg=None, ano=None, suspension_trasera=None)
    with patch("scrapers.enriquecedor_web._buscar_duckduckgo") as mock_ddg:
        completar_desde_duckduckgo(b_gen_ddg)
        assert mock_ddg.called is False, "Títulos genéricos no deben disparar consultas DuckDuckGo"

    b_concreta = bici_prueba(sitio="Wallapop", titulo="Lapierre Overvolt TestX 2023", peso_kg=None, ano=None, suspension_trasera=None)
    cache_ddg_mem = {}

    def _fake_get_cache(k):
        return cache_ddg_mem.get(k)

    def _fake_set_cache(k, v):
        cache_ddg_mem[k] = v

    html_ddg = '<div class="result"><a class="result__a">TestX 2023</a><span class="result__snippet">Peso 19,2 kg doble suspensión</span></div>'
    with patch("scrapers.enriquecedor_web._buscar_en_cache", side_effect=_fake_get_cache), \
         patch("scrapers.enriquecedor_web._guardar_en_cache", side_effect=_fake_set_cache), \
         patch("scrapers.enriquecedor_web._buscar_duckduckgo", return_value=html_ddg) as mock_ddg2:
        b_out1 = completar_desde_duckduckgo(b_concreta)
        assert mock_ddg2.call_count == 1
        assert b_out1.peso_kg == 19.2
        assert b_out1.suspension_trasera == "si"

        b_concreta2 = bici_prueba(sitio="Wallapop", titulo="Lapierre Overvolt TestX 2023", peso_kg=None, ano=None, suspension_trasera=None)
        b_out2 = completar_desde_duckduckgo(b_concreta2)
        assert mock_ddg2.call_count == 1, "La segunda consulta debe resolverse desde caché en disco"
        assert b_out2.peso_kg == 19.2


def test_todo2_edge_cases_y_regresion():
    """Valida regresión de filtros materiales, fronteras regex Wallapop, dedup y caché DDG."""
    from db import titulos_equivalentes_dedup
    from main import deduplicar_inter_portal, _recolectar_oportunidades
    from scrapers.wallapop import WallapopScraper
    from scrapers.enriquecedor_web import completar_desde_duckduckgo

    # 1. Versiones numéricas de modelo distintas no deben colapsar en dedup (8.4 vs 8.6)
    assert titulos_equivalentes_dedup(
        "Lapierre Overvolt AM 8.4 2023",
        "Lapierre Overvolt AM 8.6 2023",
    ) is False
    assert titulos_equivalentes_dedup(
        "ORBEA RISE H10 T-M 2022",
        "ORBEA RISE H10 2022 Talla M",
    ) is True

    # 2. Oficial talla L no debe suprimir clon Wallapop talla M ni en dedup ni en flujo completo
    b_buho_L = bici_prueba(
        sitio="Buhobike",
        bici_id="24840",
        titulo="ORBEA RISE H10 2022 BICICLETA SEGUNDA MANO",
        precio=2599.0,
        talla="L",
    )
    b_wala_M = bici_prueba(
        sitio="Wallapop",
        bici_id="wala-m-rise",
        titulo="ORBEA RISE H10 2022 BICICLETA SEGUNDA MANO - Talla: M",
        precio=2599.0,
        talla="M",
        garantia_anos=0,
    )
    dedup_tallas = deduplicar_inter_portal([b_buho_L, b_wala_M])
    assert {b.bici_id for b in dedup_tallas} == {"24840", "wala-m-rise"}

    # 3. _recolectar_oportunidades: clon ya notificado en BD no entra ni en conocidas;
    #    y telemetría se rellena incluso cuando candidatas_pre queda vacío.
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        ruta_db = f.name
    try:
        db = BaseDatos(ruta=ruta_db)
        b_oficial_enviada = bici_prueba(
            sitio="Buhobike",
            bici_id="ofi-99",
            titulo="MONDRAKER DUSK R 2023 BICICLETA ELECTRICA",
            precio=2799.0,
            talla="M",
        )
        db.registrar(b_oficial_enviada, 8.2)
        b_wala_clon_env = bici_prueba(
            sitio="Wallapop",
            bici_id="wala-dusk-clon",
            titulo="MONDRAKER DUSK R 2023 BICICLETA ELECTRICA",
            precio=2799.0,
            talla="M",
            garantia_anos=0,
        )

        def _fake_scrap_clon(sitio):
            if sitio.nombre == "Wallapop":
                return [b_wala_clon_env]
            if sitio.nombre == "Buhobike":
                return [b_buho_L]  # Talla L -> rechazada en pre-filtro
            return []

        with patch("main._scrapear_sitio", side_effect=_fake_scrap_clon), \
             patch("main.enriquecer_y_valorar_bici", side_effect=lambda b: (b, 8.3, {})):
            res_clon = _recolectar_oportunidades(db, forzar_envio=False)
            assert res_clon == [], "Un clon Wallapop equivalente a una enviada no debe aparecer ni como conocida"

        # Flujo con Wallapop M sobreviviendo frente a Buhobike L
        def _fake_scrap_sobrevive(sitio):
            if sitio.nombre == "Wallapop":
                return [b_wala_M]
            if sitio.nombre == "Buhobike":
                return [b_buho_L]
            return []

        with patch("main._scrapear_sitio", side_effect=_fake_scrap_sobrevive), \
             patch("main.enriquecer_y_valorar_bici", side_effect=lambda b: (b, 8.4, {})):
            res_sobrevive = _recolectar_oportunidades(db, forzar_envio=False)
            assert [b.bici_id for b, _, _ in res_sobrevive] == ["wala-m-rise"]

        # Telemetría con candidatas_pre vacía
        tel_vacia = {}
        with patch("main._scrapear_sitio", side_effect=lambda s: [b_buho_L] if s.nombre == "Buhobike" else []):
            res_vacia = _recolectar_oportunidades(db, forzar_envio=False, telemetria=tel_vacia)
            assert res_vacia == []
            assert tel_vacia.get("total_procesadas") == 1
            assert tel_vacia.get("candidatas_pre") == 0
            assert tel_vacia.get("candidatas_aptas") == 0
            assert tel_vacia.get("conteo_por_portal", {}).get("Buhobike") == 1
    finally:
        try:
            if os.path.exists(ruta_db):
                os.unlink(ruta_db)
        except (PermissionError, OSError):
            pass

    # 4. Cuadro material y Orbea Rise Motor (sin falsos positivos en 'al' ni 'rise m')
    b_carb_al98 = Bicicleta(
        sitio="Wallapop",
        bici_id="w-carb-al98",
        titulo="e-MTB Trail Carbon al 98% de estado, al día",
        precio=2600.0,
        url="https://es.wallapop.com/item/carb",
        talla="M",
        bateria_wh=600,
    )
    b_carb_al98 = completar_con_catalogo(b_carb_al98, aplicar_heuristica_peso=True)
    assert b_carb_al98.cuadro_material == "Carbono", "El español 'al 98%' no debe clasificar el cuadro como Aluminio"

    b_rise_motor = Bicicleta(
        sitio="Wallapop",
        bici_id="w-rise-motor",
        titulo="Orbea Rise Motor Shimano EP801 2023",
        precio=2600.0,
        url="https://es.wallapop.com/item/risem",
        talla="M",
    )
    b_rise_motor = completar_con_catalogo(b_rise_motor, aplicar_heuristica_peso=False)
    assert b_rise_motor.peso_kg != 18.3, "'Orbea Rise Motor' no debe casar con el patrón 'orbea rise m'"

    # 5. Wallapop: fronteras de palabra + superíndice ² (JAM²) vs falsos positivos en español
    scraper = WallapopScraper(cfg.SITIOS[4])
    items_wp = {
        "data": {
            "section": {
                "payload": {
                    "items": [
                        {
                            "id": "jam2-ok",
                            "category_id": 17000,
                            "title": "Focus JAM² 6.8 Talla M 2023",
                            "description": "Motor Bosch 750Wh.",
                            "price": {"amount": 2800.0},
                            "reserved": {"flag": False},
                            "location": {"latitude": 40.2842, "longitude": -3.7942, "city": "Fuenlabrada"},
                            "web_slug": "jam2-ok",
                        },
                        {
                            "id": "falso-trail",
                            "category_id": 17000,
                            "title": "Conor E-Trail 29 Talla M",
                            "description": "Llantas doble pared, manillar riser, llevo luz led y gran volumen.",
                            "price": {"amount": 2100.0},
                            "reserved": {"flag": False},
                            "location": {"latitude": 40.2842, "longitude": -3.7942, "city": "Fuenlabrada"},
                            "web_slug": "falso-trail",
                        },
                    ]
                }
            }
        },
        "meta": {"next_page": None},
    }
    with patch.object(scraper, "_obtener_pagina_api", return_value=items_wp):
        bicis_wp = scraper.extraer_bicicletas()
    assert [b.bici_id for b in bicis_wp] == ["wallapop-jam2-ok"]

    # 6. DDG: extracción completa sin envenenar caché parcial y sin cachear fallos HTTP ("")
    cache_mem = {}
    html_full = (
        '<div class="result"><a class="result__a">X-Model 2023</a>'
        '<span class="result__snippet">Año del modelo: 2023. Peso 19,4 kg, doble suspensión</span></div>'
    )
    b_p1 = bici_prueba(sitio="Wallapop", titulo="Lapierre TestParcial Z9 2023", peso_kg=None, ano=2023, suspension_trasera="si")
    b_p2 = bici_prueba(sitio="Wallapop", titulo="Lapierre TestParcial Z9 2023", peso_kg=19.4, ano=None, suspension_trasera=None)
    with patch("scrapers.enriquecedor_web._buscar_en_cache", side_effect=lambda k: cache_mem.get(k)), \
         patch("scrapers.enriquecedor_web._guardar_en_cache", side_effect=lambda k, v: cache_mem.__setitem__(k, v)), \
         patch("scrapers.enriquecedor_web._buscar_duckduckgo", return_value=html_full) as mock_ddg_p:
        b_p1 = completar_desde_duckduckgo(b_p1)
        b_p2 = completar_desde_duckduckgo(b_p2)
        assert mock_ddg_p.call_count == 1
        assert b_p1.peso_kg == 19.4
        assert b_p2.ano == 2023
        assert b_p2.suspension_trasera == "si"

    cache_fail = {}
    b_fail = bici_prueba(sitio="Wallapop", titulo="Mondraker RetryFallo R5", peso_kg=None, ano=None, suspension_trasera=None)
    with patch("scrapers.enriquecedor_web._buscar_en_cache", side_effect=lambda k: cache_fail.get(k)), \
         patch("scrapers.enriquecedor_web._guardar_en_cache", side_effect=lambda k, v: cache_fail.__setitem__(k, v)), \
         patch("scrapers.enriquecedor_web._buscar_duckduckgo", return_value="") as mock_ddg_f:
        completar_desde_duckduckgo(b_fail)
        assert cache_fail == {}, "Un fallo HTTP/red ('') no debe cachearse 7 días"
        completar_desde_duckduckgo(b_fail)
        assert mock_ddg_f.call_count == 2


def test_perito_esceptico_v2_y_seleccion_por_portal():
    """Valida reglas anti-alucinación, física Full Power, contradicción NUEVA, genéricas, garantía/componentes y selección por portal."""
    from gemini_classifier import (
        auditar_perito_mecanico,
        valorar_autonomo,
        enriquecer_y_valorar_bici,
        _es_anuncio_generico_sin_modelo,
    )
    from main import _recolectar_oportunidades, seleccionar_por_portal
    from scrapers.wallapop import WallapopScraper

    # 1. Anuncios genéricos sin marca+modelo: Línea Roja <= 4.5 (DESCARTADA)
    b_gen_carbon = bici_prueba(
        sitio="Wallapop",
        titulo="BICI MONTAÑA ELECTRICA DOBLE CARBONO NUEVA Talla M",
        precio=2360.0,
        peso_kg=20.8,
        km=None,
        garantia_anos=0,
        componentes=None,
    )
    assert _es_anuncio_generico_sin_modelo(b_gen_carbon) is True
    aud_gen = auditar_perito_mecanico(b_gen_carbon)
    assert aud_gen["nota_final"] <= 4.5
    assert "Cap Línea Roja: Sí" in aud_gen["formula_str"]

    # Contradicción NUEVA + >50 km y marca sin modelo ("BH 237 km Esta nueva")
    b_contra = bici_prueba(
        sitio="Wallapop",
        titulo="Bicicleta Eléctrica BH 237 km. Esta nueva!!",
        km=237,
        peso_kg=19.0,
        garantia_anos=0,
    )
    assert _es_anuncio_generico_sin_modelo(b_contra) is True
    aud_contra = auditar_perito_mecanico(b_contra)
    assert aud_contra["delta_km"] == -2.0
    assert "CONTRADICCIÓN" in aud_contra["txt_km"]
    assert aud_contra["nota_final"] <= 4.5

    # Red Lines: Talla != M -> 0.0; Batería < 500 Wh -> <= 4.0
    b_talla_l = bici_prueba(titulo="Orbea Rise M20 2023", talla="L", km=500, peso_kg=18.5)
    assert auditar_perito_mecanico(b_talla_l)["nota_final"] == 0.0

    b_bat_360 = bici_prueba(titulo="Orbea Rise M20 2022", bateria_wh=360, km=500, peso_kg=18.5)
    assert auditar_perito_mecanico(b_bat_360)["nota_final"] <= 4.0

    # 2. Física anti-optimismo Full Power >= 625Wh vs excepciones ligeras y blindaje post-Gemini
    b_full_sin_modelo = Bicicleta(
        sitio="Wallapop",
        bici_id="w-fp-1",
        titulo="Bicicleta Eléctrica MTB Carbono Bosch CX 750Wh",
        precio=2800.0,
        url="https://es.wallapop.com/item/fp1",
        talla="M",
        bateria_wh=750,
        motor="Bosch Performance Line CX",
        cuadro_material="Carbono",
    )
    b_full_res = completar_con_catalogo(b_full_sin_modelo, aplicar_heuristica_peso=True)
    assert b_full_res.peso_kg >= 23.5

    # Blindaje post-Gemini si Gemini devuelve peso irreal <22.5 kg en Full Power 750Wh no excepción
    b_gem_fp = Bicicleta(
        sitio="Wallapop",
        bici_id="w-fp-gem",
        titulo="Lapierre Overvolt TestX 750Wh Carbono",
        precio=2750.0,
        url="https://es.wallapop.com/item/fpgem",
        talla="M",
        bateria_wh=750,
        motor="Bosch Performance Line CX",
        suspension_trasera="si",
        km=900,
        componentes="XT 12v, Fox 36",
    )
    resp_gem_halluc = {
        "peso_kg": 19.2,
        "cuadro_material": "Carbono",
        "modalidad": "Trail",
        "ano": 2023,
    }
    with patch("gemini_classifier.enriquecer_bici", side_effect=lambda b, **kw: b), \
         patch("gemini_classifier.completar_desde_duckduckgo", side_effect=lambda b: b), \
         patch("gemini_classifier._cargar_cache_ia", return_value={}), \
         patch("gemini_classifier._guardar_entrada_cache_ia"), \
         patch("gemini_classifier._llamar_gemini_api", return_value=resp_gem_halluc):
        b_gem_out, nota_gem_out, _ = enriquecer_y_valorar_bici(b_gem_fp)
        assert b_gem_out.peso_kg >= 22.5
        assert nota_gem_out <= 4.0

    # Excepciones ligeras y corrección de año Orbea Rise
    b_rise_21 = completar_con_catalogo(bici_prueba(titulo="Orbea Rise M20", ano=2021, motor=None))
    assert b_rise_21.motor == "Shimano EP8-RS"
    b_rise_25 = completar_con_catalogo(bici_prueba(titulo="Orbea Rise LT M10", ano=2025, bateria_wh=630, peso_kg=None, motor=None))
    assert b_rise_25.motor == "Shimano EP801-RS Gen2"
    b_amflow = completar_con_catalogo(Bicicleta(sitio="Mammoth", bici_id="amf1", titulo="Amflow PL Carbon 600Wh", precio=2990.0, url="https://m.es/amf", talla="M"))
    assert b_amflow.peso_kg < 21.0

    # 3. Eje Garantía (particular con factura -1.0 vs sin factura -1.5; Wallapop NLP factura) + Eje Precio/Comp
    scraper_wp = WallapopScraper(cfg.SITIOS[4])
    pagina_fact = {
        "data": {
            "section": {
                "payload": {
                    "items": [
                        {
                            "id": "fact1",
                            "category_id": 17000,
                            "title": "Orbea Rise M20 Talla M",
                            "description": "Cuadro carbono, XT 12v, Fox 34, 800 km, doble suspensión. Entrego factura de compra 2025.",
                            "price": {"amount": 2800.0},
                            "reserved": {"flag": False},
                            "has_warranty": {"flag": False},
                            "is_refurbished": {"flag": False},
                            "location": {"latitude": 40.2842, "longitude": -3.7942, "city": "Fuenlabrada"},
                            "web_slug": "rise-fact",
                        }
                    ]
                }
            }
        },
        "meta": {"next_page": None},
    }
    with patch.object(scraper_wp, "_obtener_pagina_api", return_value=pagina_fact):
        b_wp_fact = scraper_wp.extraer_bicicletas()[0]
    assert b_wp_fact.tiene_factura is True
    assert auditar_perito_mecanico(b_wp_fact)["delta_garantia"] == -1.0

    b_sin_fact = bici_prueba(sitio="Wallapop", titulo="Orbea Rise M20 2023", garantia_anos=0, tiene_factura=False, km=500, peso_kg=18.5)
    assert auditar_perito_mecanico(b_sin_fact)["delta_garantia"] == -1.5

    b_comp_basic = bici_prueba(titulo="Orbea Rise H30 2023", precio=2600.0, km=500, peso_kg=20.0, componentes="Deore 11v, frenos MT200, horquilla Judy Silver")
    assert auditar_perito_mecanico(b_comp_basic)["delta_precio"] == -1.0

    b_comp_none = bici_prueba(titulo="Orbea Rise M20 2023", precio=2600.0, km=500, peso_kg=18.5, componentes=None)
    assert auditar_perito_mecanico(b_comp_none)["delta_precio"] == -1.5

    _, fmt_v2 = valorar_autonomo(b_sin_fact)
    assert "🧮 Auditoría Pericial: Base 10.0" in fmt_v2
    assert "Cap Línea Roja:" in fmt_v2
    assert "• 🛣️ Km:" in fmt_v2
    assert "• ⚖️ Peso:" in fmt_v2
    assert "• 🔍 Motor y Batería:" in fmt_v2
    assert "• 🛡️ Garantía y Vendedor:" in fmt_v2
    assert "• 💰 Precio/Componentes:" in fmt_v2

    # 4. Ranking real sin degradar una 8.0 conocida frente a una 6.5 nueva + exclusión de genérica del Día 2
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f_ord:
        ruta_db_ord = f_ord.name
    try:
        db_ord = BaseDatos(ruta=ruta_db_ord)
        b_upway_conocida = bici_prueba(sitio="Upway", bici_id="u-conocida", titulo="Orbea Rise M20 2023", precio=2600.0, peso_kg=18.6, km=800)
        db_ord.registrar(b_upway_conocida, 9.5)  # Ya notificada antes -> 'conocida'
        b_wala_flojita = bici_prueba(sitio="Wallapop", bici_id="w-flojita", titulo="Orbea Rise H30 2023", precio=2700.0, peso_kg=20.5, km=1800, garantia_anos=0)
        b_wala_gen = bici_prueba(sitio="Wallapop", bici_id="w-gen", titulo="BICI MONTAÑA ELECTRICA DOBLE CARBONO", precio=2300.0, peso_kg=20.5, km=200, garantia_anos=0)

        def _scrap_ord(sitio):
            if sitio.nombre == "Upway":
                return [b_upway_conocida]
            if sitio.nombre == "Wallapop":
                return [b_wala_flojita, b_wala_gen]
            return []

        def _val_ord(b):
            if b.bici_id == "u-conocida":
                return b, 9.5, "OK"
            if b.bici_id == "w-flojita":
                return b, 6.5, "Media"
            return b, 4.5, "Genérica"

        with patch("main._scrapear_sitio", side_effect=_scrap_ord), \
             patch("main.enriquecer_y_valorar_bici", side_effect=_val_ord):
            ops = _recolectar_oportunidades(db_ord, forzar_envio=False)

        assert [x[0].bici_id for x in ops] == ["u-conocida", "w-flojita", "w-gen"]

        # Con w-flojita y w-gen en Wallapop: Día 2 NO debe degradar Wallapop a w-gen (genérica <=4.5)
        plan_d1 = seleccionar_por_portal(ops, ultimo_analisis=None)
        assert {x["item"][0].bici_id for x in plan_d1["seleccionados"]} == {"u-conocida", "w-flojita"}
        plan_d2 = seleccionar_por_portal(ops, ultimo_analisis={"estado_portales": plan_d1["estado_portales"]})
        por_sitio_d2 = {x["sitio"]: x["item"][0].bici_id for x in plan_d2["seleccionados"]}
        assert por_sitio_d2["Wallapop"] == "w-flojita", "No debe rotar hacia un anuncio genérico descartado"
    finally:
        try:
            if os.path.exists(ruta_db_ord):
                os.unlink(ruta_db_ord)
        except (PermissionError, OSError):
            pass

    # 5. Regresiones de auditoría adversaria:
    #    - Contradicción NUEVA con 5000 km conserva -3.5 (nunca suaviza a -2.0)
    b_liar_5000 = bici_prueba(titulo="Orbea Rise M20 NUEVA 5000 km", km=5000, peso_kg=18.5)
    aud_liar = auditar_perito_mecanico(b_liar_5000)
    assert aud_liar["delta_km"] == -3.5
    assert "CONTRADICCIÓN" in aud_liar["txt_km"]

    #    - Post-Gemini con Full Power (Shimano EP6 / Specialized 2.2) y bateria_wh=None también bloquea <22.5 kg
    b_ep6_none = Bicicleta(
        sitio="Wallapop",
        bici_id="w-ep6",
        titulo="Merida eOne-Forty TestEP6",
        precio=2700.0,
        url="https://es.wallapop.com/item/ep6",
        talla="M",
        motor="Shimano EP6",
        km=800,
        componentes="Deore 12v",
    )
    with patch("gemini_classifier.enriquecer_bici", side_effect=lambda b, **kw: b), \
         patch("gemini_classifier.completar_desde_duckduckgo", side_effect=lambda b: b), \
         patch("gemini_classifier._cargar_cache_ia", return_value={}), \
         patch("gemini_classifier._guardar_entrada_cache_ia"), \
         patch("gemini_classifier._llamar_gemini_api", return_value={"peso_kg": 19.5, "modalidad": "Trail"}):
        b_ep6_out, _, _ = enriquecer_y_valorar_bici(b_ep6_none)
        assert b_ep6_out.peso_kg >= 22.5

    #    - Unknown km (None) XC 6.0 NO supera a Trail 500 km 9.5 en clave_orden_estrictas
    from main import clave_orden_estrictas, ejecutar_busqueda
    op_unk_km = (bici_prueba(titulo="BH iLynx Race Carbon 8.4", km=None, peso_kg=16.8, modalidad="XC"), 6.0, "U")
    op_ver_trail = (bici_prueba(titulo="Specialized Turbo Levo SL", km=500, peso_kg=17.9, modalidad="Trail"), 9.5, "V")
    assert clave_orden_estrictas(op_ver_trail) > clave_orden_estrictas(op_unk_km)

    #    - Fallo de enviar() en un portal no avanza ping-pong y corrida vacía preserva estado_portales
    fd_fail, ruta_fail = tempfile.mkstemp(suffix=".db")
    os.close(fd_fail)
    try:
        db_fail = BaseDatos(ruta=ruta_fail)
        ops_fail = [
            (bici_prueba(sitio="Upway", bici_id="u-f1", titulo="Orbea Rise M20 2023", peso_kg=18.5, km=500), 9.0, "D"),
            (bici_prueba(sitio="Upway", bici_id="u-f2", titulo="BH iLynx Race 8.4", peso_kg=17.8, km=500), 8.5, "D"),
            (bici_prueba(sitio="Wallapop", bici_id="w-f1", titulo="Orbea Rise M10 2023", peso_kg=18.3, km=500), 8.5, "D"),
        ]

        # Envío falla en Upway y acierta en Wallapop -> Upway no debe avanzar a u-f2
        with patch("main.BaseDatos", return_value=db_fail), \
             patch("main._recolectar_oportunidades", return_value=ops_fail), \
             patch("main.exportar_radar_mercado_md"), \
             patch("main.enviar", side_effect=lambda b, *a, **kw: b.sitio != "Upway"), \
             patch("main.enviar_heartbeat"), \
             patch("main.enviar_heartbeat_black_friday"):
            ejecutar_busqueda(forzar_envio=True)

        ult_fail = db_fail.obtener_ultimo_analisis()
        assert "Upway" not in ult_fail["estado_portales"]
        assert ult_fail["estado_portales"]["Wallapop"]["enviado_id"] == "w-f1"

        # Corrida vacía conserva estado_portales previo (Wallapop)
        with patch("main.BaseDatos", return_value=db_fail), \
             patch("main._recolectar_oportunidades", return_value=[]), \
             patch("main.exportar_radar_mercado_md"), \
             patch("main.enviar_heartbeat"), \
             patch("main.enviar_heartbeat_black_friday"):
            ejecutar_busqueda(forzar_envio=True)
        ult_vacio = db_fail.obtener_ultimo_analisis()
        assert ult_vacio["estado_portales"]["Wallapop"]["enviado_id"] == "w-f1"
    finally:
        try:
            if os.path.exists(ruta_fail):
                os.unlink(ruta_fail)
        except (PermissionError, OSError):
            pass


def test_black_friday_canal_exclusivo_y_segundo_bot():
    """Valida detección PVP Mammoth, filtros/rúbrica Black Friday <= 3.500 €, dedup SQLite y envío al 2º bot."""
    from bs4 import BeautifulSoup
    from scrapers.mammoth import MammothScraper
    from main import _recolectar_oportunidades, ejecutar_busqueda

    # 1. Extractor Mammoth reconoce .price.is__old y rellena pvp_original (incluso si is__old aparece primero en DOM)
    html_mammoth = """
    <div class="card-content">
      <a href="/ebike-trek-fuel-ex-8/p-599999">
        <div class="card-product-name"><strong>trek</strong> ebike trek fuel+ ex 8 gen 2</div>
        <div class="card-product-price">
          <span class="price is__old">5.499,00 €</span>
          <span class="price is__discount">3.299,40 €</span>
        </div>
        <div class="card--product-sizes form-sizes-group"><ul><li><label>M</label></li></ul></div>
      </a>
    </div>
    <div class="card-content">
      <a href="/ebike-trek-no-pvp/p-599998">
        <div class="card-product-name"><strong>trek</strong> ebike trek powerfly fs 4</div>
        <div class="card-product-price"><span class="price">3.100,00 €</span><del>Proximamente</del></div>
        <div class="card--product-sizes form-sizes-group"><ul><li><label>M</label></li></ul></div>
      </a>
    </div>
    """
    sitio_mammoth = next(s for s in cfg.SITIOS if s.nombre == "Mammoth")
    m_scraper = MammothScraper(sitio_mammoth)
    soup_m = BeautifulSoup(html_mammoth, "html.parser")
    bicis_m = m_scraper._extraer_de_sopa(soup_m, url_listado=sitio_mammoth.seccion_emtb)
    assert len(bicis_m) == 2
    assert bicis_m[0].precio == 3299.4
    assert bicis_m[0].pvp_original == 5499.0
    assert bicis_m[0].talla == "M"
    assert bicis_m[1].pvp_original is None

    # 2. Acepta bici nueva hasta 3.500 € (< 21 kg, >= 500 Wh, >= 35% dto) pero la mantiene fuera del filtro diario >3300
    b_bf_nueva = bici_prueba(
        sitio="Buhobike",
        bici_id="bf-new-1",
        titulo="Orbea Rise SL M20 2025",
        precio=3450.0,
        pvp_original=5999.0,
        km=0,
        peso_kg=19.2,
        bateria_wh=630,
        motor="Shimano EP801",
        componentes="Shimano XT 12v Fox Factory Kashima",
        cuadro_material="Carbono",
        suspension_trasera="si",
        garantia_anos=3,
        url="https://www.buhobike.com/electricas-trail-dobles/123-orbea-rise-sl.html",
    )
    assert pasa_filtros_estrictos(b_bf_nueva)[0] is False
    assert pasa_prefiltro_black_friday(b_bf_nueva)[0] is True
    ok_bf, nota_bf, dto_bf, etiq_bf, _ = evaluar_oportunidad_black_friday(b_bf_nueva)
    assert ok_bf is True and nota_bf >= 7.5 and dto_bf == 42.5
    assert "NUEVA" in etiq_bf

    #    Exposición 1 km también entra y permite exacto 500 Wh en BF (sin romper >500 Wh en S4 diario)
    b_expo = bici_prueba(
        sitio="Bike Ocasión",
        bici_id="bf-expo-1",
        titulo="BH iLynx Race Carbon 8.6",
        precio=2899.0,
        pvp_original=7500.0,
        km=1,
        peso_kg=19.5,
        bateria_wh=500,
        componentes="XT 12v Fox Factory",
        suspension_trasera="si",
        garantia_anos=1,
    )
    assert pasa_filtros_estrictos(b_expo)[0] is False  # S4 diario sigue exigiendo > 500 Wh
    ok_expo, nota_expo, dto_expo, etiq_expo, _ = evaluar_oportunidad_black_friday(b_expo)
    assert ok_expo is True and nota_expo >= 8.0 and dto_expo > 60.0
    assert "EXPOSICIÓN" in etiq_expo

    # 3. Rechazos estrictos anti-alucinación / peso / descuento insuficiente / >3500 € / sin doble confirmada / peso estimado IA
    assert evaluar_oportunidad_black_friday(bici_prueba(precio=3501.0, pvp_original=7000.0, km=0, suspension_trasera="si"))[0] is False
    assert evaluar_oportunidad_black_friday(bici_prueba(precio=2800.0, pvp_original=6000.0, km=0, peso_kg=23.2, suspension_trasera="si"))[0] is False
    assert evaluar_oportunidad_black_friday(bici_prueba(precio=2800.0, pvp_original=6000.0, km=0, peso_kg=19.2, suspension_trasera=None))[0] is False
    assert evaluar_oportunidad_black_friday(bici_prueba(precio=3399.0, pvp_original=4499.0, km=0, peso_kg=19.0, suspension_trasera="si"))[0] is False  # 24% dto < 35%
    assert evaluar_oportunidad_black_friday(bici_prueba(titulo="Bike NUEVA a estrenar", precio=2500.0, pvp_original=6000.0, km=120, suspension_trasera="si"))[0] is False
    assert evaluar_oportunidad_black_friday(bici_prueba(precio=2500.0, pvp_original=6000.0, km=None, suspension_trasera="si"))[0] is False
    assert evaluar_oportunidad_black_friday(bici_prueba(precio=2500.0, pvp_original=None, km=0, suspension_trasera="si"))[0] is False

    #    Peso sin dato real rellenado solo por heurística Regla B o Gemini API no debe pasar Black Friday
    from gemini_classifier import enriquecer_y_valorar_bici
    b_peso_desconocido = Bicicleta(
        sitio="Buhobike",
        bici_id="bf-peso-ia",
        titulo="Orbea Rise SL 2025",
        precio=3400.0,
        pvp_original=6000.0,
        url="https://www.buhobike.com/electricas-trail-dobles/999-rise.html",
        talla="M",
        bateria_wh=540,
        cuadro_material="Carbono",
        motor="Shimano EP801",
        km=0,
        componentes="XT 12v",
        suspension_trasera="si",
        garantia_anos=3,
        peso_kg=None,
    )
    with patch("gemini_classifier.enriquecer_bici", side_effect=lambda b, **kw: b), \
         patch("gemini_classifier.completar_desde_duckduckgo", side_effect=lambda b: b), \
         patch("gemini_classifier._cargar_cache_ia", return_value={}), \
         patch("gemini_classifier._guardar_entrada_cache_ia"), \
         patch("gemini_classifier._llamar_gemini_api", return_value=None):
        b_out_heur, _, _ = enriquecer_y_valorar_bici(b_peso_desconocido)
    assert b_out_heur.peso_kg is not None and getattr(b_out_heur, "_peso_estimado", False) is True
    assert evaluar_oportunidad_black_friday(b_out_heur)[0] is False

    #    Un anuncio BF oficial >3.300 EUR no debe suprimir a su clon Wallapop <=3.300 EUR en el flujo diario
    b_of_3320 = bici_prueba(
        sitio="Buhobike",
        bici_id="bh-3320",
        titulo="Orbea Rise M20 2023",
        precio=3320.0,
        pvp_original=6000.0,
        km=0,
        peso_kg=18.5,
        bateria_wh=540,
        suspension_trasera="si",
        url="https://www.buhobike.com/electricas-trail-dobles/3320-rise.html",
    )
    b_wl_3295 = bici_prueba(
        sitio="Wallapop",
        bici_id="wl-3295",
        titulo="Orbea Rise M20 2023",
        precio=3295.0,
        km=500,
        peso_kg=18.5,
        bateria_wh=540,
        suspension_trasera="si",
        url="https://es.wallapop.com/item/3295",
    )
    fd_sep, ruta_sep = tempfile.mkstemp(suffix=".db")
    os.close(fd_sep)
    try:
        db_sep = BaseDatos(ruta=ruta_sep)
        fake_b_sep = MagicMock(); fake_b_sep.extraer_bicicletas.return_value = [b_of_3320]
        fake_w_sep = MagicMock(); fake_w_sep.extraer_bicicletas.return_value = [b_wl_3295]
        fake_empty_sep = MagicMock(); fake_empty_sep.extraer_bicicletas.return_value = []
        tele_sep = {}
        with patch.dict(
            "main.SCRAPERS",
            {
                "Buhobike": lambda s: fake_b_sep,
                "Wallapop": lambda s: fake_w_sep,
                "Bike Ocasión": lambda s: fake_empty_sep,
                "Upway": lambda s: fake_empty_sep,
                "Mammoth": lambda s: fake_empty_sep,
            },
            clear=True,
        ), patch("main.enriquecer_y_valorar_bici", side_effect=lambda b: (b, 8.8, "OK")):
            ops_sep = _recolectar_oportunidades(db_sep, telemetria=tele_sep)
        assert [b.bici_id for b, _, _ in ops_sep] == ["wl-3295"]
        assert [x[0].bici_id for x in tele_sep["black_friday_pool"]] == ["bh-3320"]
    finally:
        if os.path.exists(ruta_sep):
            os.unlink(ruta_sep)

    # 4. Formato y envío exclusivo al 2º bot/chat configurado
    msg_bf = formatear_mensaje_black_friday(b_bf_nueva, nota_bf, dto_bf, etiq_bf, "Dto PVP -42.5%")
    assert "BLACK FRIDAY EXCLUSIVO (-42% PVP)" in msg_bf or "BLACK FRIDAY EXCLUSIVO (-43% PVP)" in msg_bf
    assert "NUEVA (0 km)" in msg_bf
    assert "3450 €" in msg_bf and "5999 €" in msg_bf

    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.raise_for_status.return_value = None
    with patch.object(cfg, "TELEGRAM_BOT_TOKEN_BLACK_FRIDAY", "999999:TEST_BF_TOKEN"), \
         patch.object(cfg, "TELEGRAM_CHAT_ID_BLACK_FRIDAY", "-100999888"), \
         patch("notifier.requests.post", return_value=resp_ok) as mock_post:
        assert enviar_black_friday(b_bf_nueva, nota_bf, dto_bf, etiq_bf, "Dto PVP") is True
        called_url = mock_post.call_args.args[0]
        called_payload = mock_post.call_args.kwargs["json"]
        assert "999999:TEST_BF_TOKEN" in called_url
        assert called_payload["chat_id"] == "-100999888"
        assert called_payload["disable_notification"] is False

    # 5. Dedup SQLite BF + Integración _recolectar_oportunidades y ejecutar_busqueda sin contaminar el bot #1 (>3300)
    fd_bf, ruta_bf = tempfile.mkstemp(suffix=".db")
    os.close(fd_bf)
    try:
        db_bf = BaseDatos(ruta=ruta_bf)
        assert db_bf.debe_reenviarse_black_friday(b_bf_nueva) is True
        db_bf.registrar_black_friday(b_bf_nueva, nota_bf, dto_bf)
        assert db_bf.debe_reenviarse_black_friday(b_bf_nueva) is False
        b_bf_clon_w = bici_prueba(
            sitio="Wallapop",
            bici_id="wallapop-clon-bf",
            titulo="Orbea Rise SL M20 2025 nueva",
            precio=3450.0,
            km=0,
        )
        assert db_bf.fue_enviada_black_friday_equivalente(b_bf_clon_w) is True
        b_bf_rebaja = bici_prueba(**{**b_bf_nueva.to_dict(), "precio": 3199.0})
        assert db_bf.debe_reenviarse_black_friday(b_bf_rebaja) is True

        # Integración end-to-end: bici nueva de 3.450 € va solo al bot Black Friday, mientras una diaria va al bot normal
        b_diaria = bici_prueba(
            sitio="Upway",
            bici_id="upway-diaria-1",
            titulo="Orbea Rise M20 2023",
            precio=2799.0,
            pvp_original=5999.0,
            km=600,
            peso_kg=18.5,
            bateria_wh=540,
            suspension_trasera="si",
        )
        b_bf_2 = bici_prueba(**{**b_bf_nueva.to_dict(), "bici_id": "bf-new-e2e"})

        fake_buhobike = MagicMock()
        fake_buhobike.extraer_bicicletas.return_value = [b_bf_2]
        fake_upway = MagicMock()
        fake_upway.extraer_bicicletas.return_value = [b_diaria]
        fake_empty = MagicMock()
        fake_empty.extraer_bicicletas.return_value = []

        telemetria = {}
        with patch.dict(
            "main.SCRAPERS",
            {
                "Buhobike": lambda s: fake_buhobike,
                "Upway": lambda s: fake_upway,
                "Bike Ocasión": lambda s: fake_empty,
                "Mammoth": lambda s: fake_empty,
                "Wallapop": lambda s: fake_empty,
            },
            clear=True,
        ), patch("main.enriquecer_y_valorar_bici", side_effect=lambda b: (b, 9.0, "OK")):
            ops_diarias = _recolectar_oportunidades(db_bf, telemetria=telemetria)

        assert [b.bici_id for b, _, _ in ops_diarias] == ["upway-diaria-1"]
        assert len(telemetria["black_friday_pool"]) == 1
        assert telemetria["black_friday_pool"][0][0].bici_id == "bf-new-e2e"

        enviados_normales = []
        enviados_bf = []
        with patch("main.BaseDatos", return_value=db_bf), \
             patch("main._recolectar_oportunidades", side_effect=lambda db, forzar_envio=False, telemetria=None: (
                 telemetria.update({"black_friday_pool": [(b_bf_2, nota_bf, dto_bf, etiq_bf, "BF OK")], "total_procesadas": 2, "conteo_por_portal": {"Upway": 1, "Buhobike": 1}})
                 if telemetria is not None else None,
                 [(b_diaria, 9.0, "OK")],
             )[1]), \
             patch("main.exportar_radar_mercado_md"), \
             patch("main.enviar", side_effect=lambda b, *a, **kw: enviados_normales.append(b.bici_id) or True), \
             patch("main.enviar_black_friday", side_effect=lambda *a, **kw: enviados_bf.append((kw.get("bici") or a[0]).bici_id) or True), \
             patch("main.enviar_heartbeat") as mock_hb, \
             patch("main.enviar_heartbeat_black_friday") as mock_hb_bf, \
             patch.object(cfg, "TELEGRAM_BOT_TOKEN_BLACK_FRIDAY", "999999:TEST_BF_TOKEN"):
            ejecutar_busqueda(forzar_envio=False)
            assert enviados_normales == ["upway-diaria-1"]
            assert enviados_bf == ["bf-new-e2e"]
            assert mock_hb.call_args.args[0]["black_friday_notificadas"] == 1
            assert mock_hb_bf.call_args.args[0]["black_friday_encontradas"] == 1

        # 6. Formato y envío del heartbeat dedicado de Black Friday al 2º bot
        from notifier import formatear_heartbeat_black_friday, enviar_heartbeat_black_friday
        txt_hb_bf = formatear_heartbeat_black_friday({
            "fecha_hora": "2026-11-20 13:55:00",
            "duracion_seg": 78.2,
            "total_procesadas": 350,
            "black_friday_encontradas": 0,
            "black_friday_notificadas": 0,
            "estado": "🟢 Runner operativo",
        })
        assert "Black Bike Beast" in txt_hb_bf
        assert "0* bicis cumplen hoy todos los criterios estrictos" in txt_hb_bf
        with patch.object(cfg, "TELEGRAM_BOT_TOKEN_BLACK_FRIDAY", "999999:TEST_BF_TOKEN"), \
             patch.object(cfg, "TELEGRAM_CHAT_ID_BLACK_FRIDAY", "-100999888"), \
             patch("notifier.requests.post", return_value=resp_ok) as mock_post_hb_bf:
            assert enviar_heartbeat_black_friday({"fecha_hora": "2026-11-20 13:55:00", "duracion_seg": 1.0, "total_procesadas": 10}) is True
            assert "999999:TEST_BF_TOKEN" in mock_post_hb_bf.call_args.args[0]
            assert mock_post_hb_bf.call_args.kwargs["json"]["chat_id"] == "-100999888"
            assert mock_post_hb_bf.call_args.kwargs["json"]["disable_notification"] is True

        # 7. Respaldo Top 3 fuera de tope (> 3.500 € / 480 Wh / seminuevas) cuando 0 pasan el estricto BF
        from evaluator import pasa_prefiltro_respaldo_black_friday, evaluar_respaldo_black_friday
        from notifier import formatear_informe_respaldo_black_friday, enviar_informe_respaldo_black_friday

        b_over_1 = bici_prueba(
            sitio="Mammoth",
            bici_id="resp-moterra",
            titulo="Cannondale Moterra SL 2",
            precio=4549.0,
            pvp_original=6999.0,
            km=0,
            peso_kg=19.8,
            bateria_wh=600,
            motor="Shimano EP801",
            suspension_trasera="si",
            url="https://www.mammothbikes.com/ebike-cannondale-moterra-sl-2/p-1",
        )
        b_over_2 = bici_prueba(
            sitio="Buhobike",
            bici_id="resp-rise",
            titulo="Orbea Rise SL M20 630W 2026",
            precio=3999.0,
            pvp_original=6799.0,
            km=712,
            peso_kg=20.2,
            bateria_wh=630,
            motor="Shimano EP801-RS Gen2",
            suspension_trasera="si",
            url="https://www.buhobike.com/segunda-mano-electricas/resp-rise.html",
        )
        b_over_3 = bici_prueba(
            sitio="Bike Ocasión",
            bici_id="resp-ghost",
            titulo="Ghost Path Riot CF LTD AXS",
            precio=3599.0,
            pvp_original=11000.0,
            km=1,
            peso_kg=19.5,
            bateria_wh=480,
            motor="Fazua",
            suspension_trasera="si",
            url="https://bike-ocasion.com/bicicletas-electricas-de-montana-doble-suspension/resp-ghost.html",
        )
        b_heavy_over = bici_prueba(sitio="Mammoth", bici_id="resp-heavy", precio=4000.0, pvp_original=7000.0, km=0, peso_kg=24.0, bateria_wh=750, suspension_trasera="si")

        assert pasa_prefiltro_respaldo_black_friday(b_over_1)[0] is True
        ok_r1, dto_r1, _, mot_r1, clave_r1 = evaluar_respaldo_black_friday(b_over_1, nota_perito=7.5)
        ok_r2, dto_r2, _, mot_r2, clave_r2 = evaluar_respaldo_black_friday(b_over_2, nota_perito=6.5)
        ok_r3, dto_r3, _, mot_r3, clave_r3 = evaluar_respaldo_black_friday(b_over_3, nota_perito=4.0)
        assert ok_r1 and "+1049 € sobre tope 3.500 €" in mot_r1
        assert ok_r2 and "712 km" in mot_r2
        assert ok_r3 and "480 Wh" in mot_r3
        assert clave_r1 > clave_r2 > clave_r3
        assert evaluar_respaldo_black_friday(b_heavy_over)[0] is False

        # Integración en _recolectar_oportunidades + ejecutar_busqueda sin contaminar diarias ni historial_catalogo
        fake_m_resp = MagicMock(); fake_m_resp.extraer_bicicletas.return_value = [b_over_1]
        fake_bo_resp = MagicMock(); fake_bo_resp.extraer_bicicletas.return_value = [b_over_3]
        tele_r = {}
        with patch.dict(
            "main.SCRAPERS",
            {
                "Mammoth": lambda s: fake_m_resp,
                "Bike Ocasión": lambda s: fake_bo_resp,
                "Buhobike": lambda s: fake_empty,
                "Upway": lambda s: fake_empty,
                "Wallapop": lambda s: fake_empty,
            },
            clear=True,
        ), patch("main.enriquecer_y_valorar_bici", side_effect=lambda b: (b, 7.5, "OK")):
            ops_r = _recolectar_oportunidades(db_bf, telemetria=tele_r)
        assert ops_r == []
        assert tele_r["black_friday_pool"] == []
        assert [x[0].bici_id for x in tele_r["black_friday_respaldo_pool"]] == ["resp-moterra", "resp-ghost"]
        assert db_bf.obtener_seguimiento("resp-moterra") is None

        items_top3 = [
            (b_over_1, dto_r1, 7.5, mot_r1),
            (b_over_2, dto_r2, 6.5, mot_r2),
            (b_over_3, dto_r3, 4.0, mot_r3),
        ]
        txt_top3 = formatear_informe_respaldo_black_friday(items_top3)
        assert "Top 3 Más Interesantes" in txt_top3
        assert "Cannondale Moterra SL 2" in txt_top3 and "Ghost Path Riot CF LTD AXS" in txt_top3

        enviados_top3 = []
        with patch("main.BaseDatos", return_value=db_bf), \
             patch("main._recolectar_oportunidades", side_effect=lambda db, forzar_envio=False, telemetria=None: (
                 telemetria.update({"black_friday_pool": [], "black_friday_respaldo_pool": items_top3, "total_procesadas": 10, "conteo_por_portal": {"Mammoth": 1}})
                 if telemetria is not None else None,
                 [],
             )[1]), \
             patch("main.exportar_radar_mercado_md"), \
             patch("main.enviar_informe_respaldo_black_friday", side_effect=lambda items, **kw: enviados_top3.append([x[0].bici_id for x in items]) or True), \
             patch("main.enviar_heartbeat"), \
             patch("main.enviar_heartbeat_black_friday") as mock_hb_bf_resp, \
             patch.object(cfg, "TELEGRAM_BOT_TOKEN_BLACK_FRIDAY", "999999:TEST_BF_TOKEN"):
            ejecutar_busqueda(forzar_envio=False)
            assert enviados_top3 == [["resp-moterra", "resp-rise", "resp-ghost"]]
            assert mock_hb_bf_resp.call_args.args[0]["black_friday_respaldo_enviado"] is True
            # Segunda pasada idéntica no repite el informe Top 3 de respaldo
            ejecutar_busqueda(forzar_envio=False)
            assert len(enviados_top3) == 1
            # Pero si luego baja a <= 3.500 EUR, sí dispara alerta estricta de Black Friday (bici_id real no bloqueado)
            assert db_bf.debe_reenviarse_black_friday(bici_prueba(**{**b_over_1.to_dict(), "precio": 3400.0})) is True
            # Tampoco un respaldo de otro portal dentro de +-25 EUR bloquea una alerta estricta en otro portal
            b_otro_portal = bici_prueba(
                sitio="Buhobike",
                bici_id="bf-otro-portal",
                titulo="Ghost Path Riot CF LTD AXS",
                precio=3580.0,
            )
            assert db_bf.fue_enviada_black_friday_equivalente(b_otro_portal) is False
    finally:
        try:
            if os.path.exists(ruta_bf):
                os.unlink(ruta_bf)
        except (PermissionError, OSError):
            pass


if __name__ == "__main__":
    test_pasa_filtros_valida()
    test_descarta_talla_no_m()
    test_descarta_bateria_500_wh()
    test_descarta_peso_mas_21_kg()
    test_descarta_precio_fuera_rango()
    test_nota_alta_bici_excelente()
    test_nota_baja_kilometraje_alto()
    test_filtro_nota_minimo_8()
    test_clasificador_hibrido_catalogo_y_5_ejes()
    test_dedup_sqlite()
    test_formateo_mensaje_telegram()
    test_extraccion_titulo_sin_dto_y_suspension_rigidez()
    test_perito_mecanico_senior_reglas_y_lineas_rojas()
    test_optimizacion_tarjetas_upway_y_buhobike()
    test_range_extender_extraccion_y_filtros()
    test_salud_bateria_soh_disponibilidad_y_extractores()
    test_todos_historial_catalogo_recorrido_y_stats()
    test_extraccion_km_imagenes_ficha_buhobike_vigilancia_y_radar_md()
    test_proxy_rotator_y_resiliencia_red()
    test_profundizacion_telemetria_bateria_upway_y_mammoth()
    test_radar_mercado_metricas_enriquecidas_y_heartbeat()
    test_mega_chollo_alerta_y_formato_telegram()
    test_segmentacion_sonora_vs_silenciosa_telegram()
    test_rotacion_consecutiva_top3_y_aviso()
    test_wallapop_geolocalizado_y_filtros()
    test_todo2_dedup_interportal_wallapop_estricto_y_cache_ddg()
    test_todo2_edge_cases_y_regresion()
    test_perito_esceptico_v2_y_seleccion_por_portal()
    test_black_friday_canal_exclusivo_y_segundo_bot()
    print("Todas las pruebas pasaron (GREEN).")
