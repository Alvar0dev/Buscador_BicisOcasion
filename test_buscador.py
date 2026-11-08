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
from evaluator import evaluar, calcular_nota_oportunidad, pasa_filtros_estrictos, _puntuacion_calidad_precio
from gemini_classifier import (
    completar_con_catalogo,
    evaluar_documentacion_motor,
    valorar_autonomo,
    auditar_perito_mecanico,
)
from scrapers.enriquecedor_web import _extraer_range_extender
from db import BaseDatos
from notifier import formatear_mensaje


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
    assert "Diagnóstico motor" in desglose
    assert "Estado batería" in desglose

    pts_bosch, txt_bosch = evaluar_documentacion_motor("Bosch Performance Line SX")
    assert pts_bosch >= 1.9
    assert "Bosch DiagnosticTool" in txt_bosch


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
    """Verifica el cálculo paso a paso del Perito Mecánico Senior y sus Líneas Rojas."""
    from gemini_classifier import auditar_perito_mecanico

    # Caso 1: Línea Roja > 6.000 km + BH (-1.0 base centralita -1.5 >3000km = -2.5)
    b_roja_km = bici_prueba(km=8407, peso_kg=16.8, motor="BH 2EXMAG", precio=2768.0)
    res_km = auditar_perito_mecanico(b_roja_km)
    assert res_km["nota_final"] <= 4.5, f"Línea roja >6000 km violada: {res_km}"
    assert res_km["delta_motor"] == -2.5

    # Caso 2: Línea Roja > 21.0 kg (nota máxima 4.0)
    b_roja_peso = bici_prueba(km=500, peso_kg=22.4, motor="Bosch CX", precio=2500.0)
    res_peso = auditar_perito_mecanico(b_roja_peso)
    assert res_peso["nota_final"] <= 4.0, f"Línea roja >21 kg violada: {res_peso}"

    # Caso 3: BH con 1.193 km (-1.0 km) + 18.2 kg (+0.5 peso) - 1.0 (centralita BH) => 8.5/10
    b_bh_bajos_km = bici_prueba(km=1193, peso_kg=18.2, motor="BH 2EXMAG", precio=2981.0)
    res_bh = auditar_perito_mecanico(b_bh_bajos_km)
    assert res_bh["delta_motor"] == -1.0
    assert res_bh["nota_final"] == 8.5, f"Esperado 8.5, obtenido: {res_bh}"

    # Caso 4: Precio > 3.000 € y > 2.000 km (-1.5 precio, -2.5 km) con Shimano (-0.0)
    b_cara_rodada = bici_prueba(km=2500, peso_kg=19.5, motor="Shimano EP8", precio=3150.0)
    res_cara = auditar_perito_mecanico(b_cara_rodada)
    assert res_cara["delta_km"] == -2.5
    assert res_cara["delta_precio"] == -1.5
    assert res_cara["nota_final"] == 6.0


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
    assert "Shimano EP801" in b_plus.motor and "BH" in b_plus.motor

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
    print("Todas las pruebas pasaron (GREEN).")
