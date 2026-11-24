"""
evaluator.py
Filtros estrictos (S1-S6, S8) y algoritmo de "Nota de Oportunidad" 0-10 (S7).

Cada bicicleta que pase los filtros estrictos recibe una nota del 0 al 10.
Solo las que obtengan >= 8.0 se guardan y notifican (S8).
"""

import re
from typing import Tuple, List, Optional
from models import Bicicleta
import config as cfg

TECHO_NOTA_BH: float = 8.5


def es_bici_bh(bici: Bicicleta) -> bool:
    """Detecta si la bicicleta pertenece a la marca BH (centralita cerrada sin informe pericial PDF)."""
    texto = f"{bici.titulo or ''} {bici.motor or ''}".lower()
    if any(k in texto for k in ("ilynx", "atomx", "xtep", "2exmag", "2esmag")):
        return True
    return bool(re.search(r"\bbh\b", texto))


_RE_MODALIDAD_NO_XC = re.compile(
    r"\b(?:trail|enduro|all[- ]?mountain|freeride|dh)\b",
    re.IGNORECASE,
)

_RE_MODALIDAD_NO_MTB = re.compile(
    r"\b(?:gravel|carretera|road|urbana|urban|paseo|trekking|ciudad|plegable)\b",
    re.IGNORECASE,
)


_RE_MOTOR_FULL_POWER_ESTRICTA = re.compile(
    r"\b(?:polini|bafang|bosch(?:\s+performance(?:\s+line)?)?\s*cx|brose(?:\s+s\s*mag)?|"
    r"yamaha|pw-?x\d*|syncdrive|specialized\s*(?:2\.[12]|full\s*power)|full\s*power|oli|ananda|panasonic)\b",
    re.IGNORECASE,
)

_PATRONES_MODELO_FULL_POWER_PESADA = (
    "berria mako",
    "mako hybrid",
    "berria stratos",
    "berria nexxen",
    "orbea rise lt h",
    "bh ilynx 9.",
    "bh ilynx+ 9.",
    "bh ilynx+ dl",
    "ilynx+ dl",
    "bh ilynx+ nx",
    "ilynx+ nx",
    "olympia hekton",
    "megamo reason al",
    "bh atomx",
    "atomx",
    "bh xtep",
    "xtep",
    "orbea wild",
    "trek rail",
    "trek powerfly",
    "cube stereo",
    "mondraker crafty",
    "mondraker dusk",
    "focus thron",
    "giant reign",
    "giant stance",
    "scott strike",
    "scott patron",
    "bianchi t-tronik",
    "bianchi e-vertic",
    "bulls sonic",
    "bulls e-stream",
    "conway xyron",
    "conway cairon",
    "megamo crave",
    "ghost e-asx",
    "ghost e-axs",
    "ghost e-riot",
    "husqvarna",
    "gasgas",
    "gas gas",
    "commencal meta",
    "niner rip",
    "rocky mountain",
    "merida eone",
    "haibike allmtn",
    "haibike alltrail",
    "ktm macina kapoho",
    "ktm macina chacana",
    "lapierre overvolt",
    "liv embolden",
    "liv intrigue",
    "ecobike",
    "fantic",
    "centurion no pogo",
    "carver suv",
)


def es_full_power_o_pesada(bici: Bicicleta) -> Tuple[bool, str]:
    """
    Detecta bicicletas e-MTB Full Power o chasis pesados (>= 21 kg reales, p. ej. Berria Mako Hybrid
    Polini/Bafang 720 Wh, Orbea Rise LT Aluminio 630 Wh, motores Bosch CX/Brose/Yamaha/Polini/Bafang),
    evitando que entren en las búsquedas de e-MTB ligeras (< 21 kg).
    """
    titulo = (bici.titulo or "").lower().replace("²", "2")
    motor = (bici.motor or "").lower()

    # Excepciones ligeras verificadas (< 21 kg reales)
    es_excepcion_ultra_ligera = (
        any(
            k in titulo
            for k in (
                "trance x advanced e+ elite",
                "moterra sl",
                "moterra neo sl",
                "levo sl",
                "kenevo sl",
                "jam2 sl",
                "jam 2 sl",
                "amflow pl",
                "am flow pl",
            )
        )
        and "amflow tl" not in titulo
        and "am flow tl" not in titulo
    )
    if not es_excepcion_ultra_ligera:
        if any(p in titulo for p in _PATRONES_MODELO_FULL_POWER_PESADA) or "amflow tl" in titulo or "am flow tl" in titulo:
            return True, f"Modelo Full Power / pesado (>= 21 kg reales) descartado: {bici.titulo}"
        if (
            ("turbo levo" in titulo and "levo sl" not in titulo)
            or ("moterra" in titulo and "moterra sl" not in titulo and "moterra neo sl" not in titulo)
            or (("focus jam2" in titulo or "focus jam 2" in titulo) and "sl" not in titulo)
            or ("giant trance" in titulo and "elite" not in titulo)
        ):
            return True, f"Modelo Full Power (>= 21 kg reales) descartado: {bici.titulo}"
        if motor and _RE_MOTOR_FULL_POWER_ESTRICTA.search(motor):
            return True, f"Motor Full Power descartado ({bici.motor})"
        if _RE_MOTOR_FULL_POWER_ESTRICTA.search(titulo):
            return True, f"Motor Full Power declarado en título ({bici.titulo})"
    return False, "OK"


def es_modalidad_mtb_doble_valida(bici: Bicicleta) -> bool:
    """
    True si la bicicleta pertenece a una modalidad e-MTB válida (XC/Downcountry,
    Trail ligera o MTB doble suspensión), rechazando carretera, gravel, urbana o trekking.
    """
    mod = (bici.modalidad or "").strip().lower()
    if mod and _RE_MODALIDAD_NO_MTB.search(mod):
        return False
    return True

_PATRONES_MODELO_TRAIL_ENDURO = (
    "orbea rise",
    "ilynx trail",
    "i-lynx trail",
    "ilynx+",
    "ilynx plus",
    "i-lynx+",
    "moterra",
    "path riot",
    "e-riot",
    "e-asx",
    "easx",
    "mondraker neat",
    "mondraker dune",
    "fuel+",
    "fuel exe",
    "trek rail",
    "turbo levo",
    "levo sl",
    "kenevo",
    "orbea wild",
    "crafty",
    "chaser",
    "mondraker dusk",
    "reign",
    "trance x",
    "stance e+",
    "stereo hybrid",
    "ams hybrid one44",
    "one44",
    "habit neo",
    "allmtn",
    "alltrail",
    "jam2",
    "jam 2",
    "thron2",
    "thron 2",
    "sam2",
    "sam 2",
    "macina scarp",
    "scarp sx",
    "spectral",
    "neuron:on",
    "patron eride",
    "strike eride",
    "atomx",
    "xtep",
    "kapoho",
    "amflow",
    "am flow",
    "e-zesty",
    "ezesty",
    "haibike lyke",
    "heckler",
    "shuttle sl",
    "eone-forty",
    "eone-sixty",
    "samedi",
    "xyron",
    "no pogo",
    "no-pogo",
    "overvolt",
    "aminga",
    "embolden",
    "intrigue",
    "tero x",
)


def es_modalidad_xc(modalidad: Optional[str]) -> bool:
    """Devuelve True si modalidad es vacía o estrictamente XC / Downcountry (sin Trail/Enduro)."""
    if not modalidad:
        return True
    m_low = modalidad.strip().lower()
    if _RE_MODALIDAD_NO_XC.search(m_low):
        return False
    return any(m.lower() in m_low for m in cfg.MODALIDADES_VALIDAS)


def es_modelo_trail_o_enduro(bici: Bicicleta) -> bool:
    """Detecta familias conocidas Trail / All-Mountain / Enduro (>= 140 mm) por título."""
    titulo = (bici.titulo or "").lower().replace("²", "2")
    return any(p in titulo for p in _PATRONES_MODELO_TRAIL_ENDURO)


def es_xc_ampliable_en_presupuesto(bici: Bicicleta, precio_tope: int) -> bool:
    """
    True para XC puras ligeras Fazua Ride 60 (420-430 Wh, <=130 mm, <19 kg)
    cuyo precio deja >= 450 € de margen para añadir el extender oficial +210 Wh
    (total 630-640 Wh >= 500 Wh) dentro del presupuesto tope.
    """
    if es_modelo_trail_o_enduro(bici) or not es_modalidad_xc(bici.modalidad):
        return False
    if bici.recorrido_mm is not None and bici.recorrido_mm > cfg.RECORRIDO_MAX_XC_MM:
        return False
    if bici.peso_kg is None or bici.peso_kg >= 19.0:
        return False
    if bici.bateria_wh is None or not (420 <= bici.bateria_wh < cfg.BATERIA_MIN_WH):
        return False
    txt_m = f"{bici.motor or ''} {bici.titulo or ''}".lower().replace("²", "2")
    es_modelo_xc_fazua = any(k in txt_m for k in ("urta hybrid", "wilier urta", "vam2", "vam 2", "vam 8.", "vam 9."))
    tiene_xc_verificado = bool(
        (bici.modalidad and any(m.lower() in bici.modalidad.lower() for m in cfg.MODALIDADES_VALIDAS))
        or (bici.recorrido_mm is not None and bici.recorrido_mm <= cfg.RECORRIDO_MAX_XC_MM)
    )
    if not ("fazua" in txt_m and (es_modelo_xc_fazua or tiene_xc_verificado)) and not es_modelo_xc_fazua:
        return False
    return bici.precio <= (precio_tope - 450)


def es_unicornio_xc(bici: Bicicleta) -> bool:
    """
    True para unicornios XC puros (<=130 mm, <19 kg, >=600 Wh reales y km <=500)
    autorizados hasta 3.500 € también en el canal diario.
    """
    if es_modelo_trail_o_enduro(bici) or not es_modalidad_xc(bici.modalidad):
        return False
    if bici.recorrido_mm is not None and bici.recorrido_mm > cfg.RECORRIDO_MAX_XC_MM:
        return False
    if bici.peso_kg is None or bici.peso_kg >= 19.0:
        return False
    if bici.bateria_wh is None or bici.bateria_wh < 600:
        return False
    if bici.km is None or bici.km > 500:
        return False
    return bici.precio <= getattr(cfg, "PRECIO_MAX_UNICORNIO_XC_EUR", 3500)


# ---------------------------------------------------------------------------
# FILTROS ESTRICTOS
# ---------------------------------------------------------------------------

def _pasa_requisitos_base_mecanicos(
    bici: Bicicleta,
    precio_max: int,
    bateria_estricta_gt: bool = True,
    permitir_fazua_extender: bool = False,
    permitir_trail_respaldo: bool = False,
) -> Tuple[bool, str]:
    """
    Valida compatibilidad física y de presupuesto base compartida entre el flujo
    diario (S0-S6) y el canal exclusivo Black Friday.
    """
    # S0: Disponibilidad real (no reservada ni agotada)
    if getattr(bici, "disponible", True) is False:
        return False, "Bicicleta reservada o agotada"

    # S1: Talla exclusivamente M
    if bici.talla and bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
        return False, f"Talla no es M: {bici.talla}"

    # S2: Modalidad estrictamente XC en diario; en Black Friday permite Trail ligera / MTB como respaldo
    if permitir_trail_respaldo:
        if not es_modalidad_mtb_doble_valida(bici):
            return False, f"Modalidad no válida para MTB: {bici.modalidad}"
    else:
        if bici.modalidad and not es_modalidad_xc(bici.modalidad):
            return False, f"Modalidad no válida para XC: {bici.modalidad}"

        if es_modelo_trail_o_enduro(bici):
            return False, f"Modelo Trail/Enduro descartado (objetivo XC <= {cfg.RECORRIDO_MAX_XC_MM} mm): {bici.titulo}"

    # S4: Batería > 500 Wh estricta
    if bici.bateria_wh is not None:
        if permitir_fazua_extender and es_xc_ampliable_en_presupuesto(bici, precio_max):
            pass
        elif bateria_estricta_gt and bici.bateria_wh <= cfg.BATERIA_MIN_WH:
            return False, f"Batería <= 500 Wh: {bici.bateria_wh} Wh"
        elif not bateria_estricta_gt and bici.bateria_wh < cfg.BATERIA_MIN_WH:
            return False, f"Batería < 500 Wh: {bici.bateria_wh} Wh"

    # S3: Peso >= 21 kg se descarta explícitamente (objetivo: estrictamente < 21 kg)
    if bici.peso_kg is not None and bici.peso_kg >= cfg.PESO_DESCARTE_KG:
        return False, f"Peso >= 21 kg: {bici.peso_kg} kg"

    # S3ter: Bloqueo explícito de e-MTB Full Power / pesadas (ej. Berria Mako Hybrid Polini/Bafang, Rise LT Alu)
    es_fp, motivo_fp = es_full_power_o_pesada(bici)
    if es_fp:
        return False, motivo_fp

    # S3bis: Doble suspensión obligatoria.
    if bici.suspension_trasera is not None and str(bici.suspension_trasera).lower() in ("false", "no", "0"):
        return False, "No tiene suspensión trasera (no es doble suspensión)"

    # S2bis: En modo estricto XC, si el recorrido supera 130 mm se descarta
    if not permitir_trail_respaldo and bici.recorrido_mm is not None and bici.recorrido_mm > cfg.RECORRIDO_MAX_XC_MM:
        return False, f"Recorrido de suspensión excesivo para XC (>{cfg.RECORRIDO_MAX_XC_MM} mm): {bici.recorrido_mm} mm"
    if permitir_trail_respaldo and bici.recorrido_mm is not None and bici.recorrido_mm > 170:
        return False, f"Recorrido de suspensión excesivo (>170 mm): {bici.recorrido_mm} mm"

    # S5/S6: Rango de presupuesto según canal (hasta 3.500 € para Unicornios XC >=600 Wh, <=500 km)
    techo_precio = (
        getattr(cfg, "PRECIO_MAX_UNICORNIO_XC_EUR", precio_max)
        if (precio_max == cfg.PRECIO_MAX_EXCEPCIONAL_EUR and es_unicornio_xc(bici))
        else precio_max
    )
    if bici.precio < cfg.PRECIO_MIN_EUR:
        return False, f"Precio < {cfg.PRECIO_MIN_EUR} €: {bici.precio} €"
    if bici.precio > techo_precio:
        return False, f"Precio > {techo_precio} €: {bici.precio} €"

    return True, "OK"


def pasa_filtros_estrictos(bici: Bicicleta, permitir_trail_respaldo: bool = False) -> Tuple[bool, str]:
    """
    Devuelve (apto, motivo) aplicando todos los filtros estrictos.
    Si permitir_trail_respaldo=True (flujo de ocasión/segunda mano con prioridad XC > Trail ligera > MTB),
    admite también modelos Trail ligera / MTB doble suspensión (< 21 kg, > 500 Wh, Talla M).
    """
    return _pasa_requisitos_base_mecanicos(
        bici,
        precio_max=cfg.PRECIO_MAX_EXCEPCIONAL_EUR,
        bateria_estricta_gt=True,
        permitir_trail_respaldo=permitir_trail_respaldo,
    )


def prioridad_modalidad(bici: Bicicleta) -> int:
    """
    Devuelve el nivel de prioridad de la modalidad para priorizar siempre XC frente a Trail:
      3 -> XC / Cross Country / Downcountry (<= 130 mm, ej. BH iLynx Race, Scott Lumen, KTM Scarp)
      2 -> Light e-MTB / Trail ligero (131-145 mm o familias Light e-MTB <= 150 mm: Orbea Rise, Trek Fuel EXe, BH iLynx Trail sin '+', Berria Mako Hybrid, Moterra SL)
      1 -> Trail / All Mountain general (146-165 mm, ej. BH iLynx+ Trail)
      0 -> Otras / sin clasificar (> 165 mm / Enduro)
    """
    titulo = (bici.titulo or "").lower().replace("²", "2")
    modalidad = (bici.modalidad or "").lower()
    texto = f"{titulo} {modalidad}"

    es_familia_light_trail = (
        "ilynx+" not in titulo
        and "ilynx plus" not in titulo
        and any(
            k in texto
            for k in (
                "orbea rise",
                "ams hybrid one44",
                "macina scarp",
                "fuel exe",
                "levo sl",
                "ilynx trail",
                "e-zesty",
                "ezesty",
                "jam2 sl",
                "jam 2 sl",
                "mondraker neat",
                "moterra sl",
                "moterra neo sl",
                "mmr kaizen",
                "amflow pl",
                "light e-mtb",
                "light emtb",
            )
        )
    )

    # 1. Prioridad objetiva por recorrido físico de suspensión si se conoce (TODO 2)
    if bici.recorrido_mm is not None:
        rec = bici.recorrido_mm
        if rec <= 130:
            return 3
        elif rec <= 145 or (rec <= 150 and es_familia_light_trail):
            return 2
        elif rec <= 165:
            return 1
        else:
            return 0

    # Nivel 3: XC / Cross Country / Downcountry puro
    if not es_modelo_trail_o_enduro(bici):
        if any(
            k in texto
            for k in (
                "ilynx race",
                "scott lumen",
                "fourstroke",
                "wilier urta",
                "urta hybrid",
                "vam2",
                "vam 2",
                "vam 8.",
                "e-caliber",
                "downcountry",
                "cross country",
            )
        ) or "xc" in modalidad.split():
            return 3
        if "xc" in modalidad:
            return 3

    # Nivel 2: Light e-MTB / Trail ligero (excluyendo iLynx+ de 160 mm)
    if es_familia_light_trail:
        return 2

    # Nivel 1: Trail / All Mountain
    if any(k in texto for k in ("trail", "all mountain")) or es_modelo_trail_o_enduro(bici):
        return 1

    return 0


# ---------------------------------------------------------------------------
# ALGORITMO DE NOTA DE OPORTUNIDAD (0-10) (S7)
# ---------------------------------------------------------------------------

def _puntuacion_km(km) -> Tuple[float, str]:
    """
    Kilometraje: penaliza fuertemente > 4.000 km, premia < 2.000 km.
    Devuelve (puntos 0-2.5, justificación).
    """
    if km is None:
        return 1.0, "Kilometraje desconocido (neutro)"
    if km < 2000:
        return 2.5, f"Km bajos ({km} km): +2.5"
    if km <= 4000:
        return 1.5, f"Km moderados ({km} km): +1.5"
    return 0.5, f"Km altos ({km} km): +0.5"


def _puntuacion_calidad_precio(bici: Bicicleta) -> Tuple[float, str]:
    """
    Relación calidad-precio: compara precio frente a componentes (XT/AXS,
    suspensiones Kashima/Ultimate, cuadro de carbono).
    Devuelve (puntos 0-3.0, justificación).
    """
    texto = f"{bici.titulo} {bici.componentes or ''}".lower()
    puntos = 0.0
    partes: List[str] = []

    if any(m in texto for m in cfg.MATERIALES_CUADRO_LIGERO):
        puntos += 1.0
        partes.append("cuadro carbono: +1.0")
    if any(m in texto for m in ["xt", "axs", "x0", "xtr"]):
        puntos += 1.0
        partes.append("transmisión tope (XT/AXS): +1.0")
    if any(m in texto for m in ["kashima", "ultimate", "factory"]):
        puntos += 1.0
        partes.append("suspensión premium (Kashima/Ultimate): +1.0")
    if getattr(bici, "range_extender_wh", None):
        puntos += 0.5
        partes.append(f"Range Extender {bici.range_extender_wh}Wh incluido: +0.5")
    pvp_orig = getattr(bici, "pvp_original", None)
    if pvp_orig and pvp_orig > bici.precio > 0:
        pct_dto = (pvp_orig - bici.precio) / pvp_orig
        if pct_dto >= 0.50:
            puntos += 0.5
            partes.append(f"Mega Chollo ({pct_dto*100:.0f}% dto vs PVP): +0.5")

    if bici.precio <= cfg.PRECIO_MAX_EUR:
        puntos += 0.5
        partes.append("precio en rango principal: +0.5")

    return min(puntos, 3.0), "; ".join(partes) if partes else "Componentes estándar"


def _puntuacion_motor(bici: Bicicleta) -> Tuple[float, str]:
    """
    Desgaste de motor: mayor puntuación si marca con diagnóstico claro
    (Shimano EP8/EP801, Bosch) o muy pocos kilómetros.
    Las bicicletas BH pierden la bonificación de diagnóstico transparente por usar
    centralita propietaria sin informe PDF oficial verificable.
    Devuelve (puntos 0-2.5, justificación).
    """
    texto = f"{bici.motor or ''} {bici.titulo or ''}".lower()
    es_bh = es_bici_bh(bici)
    puntos = 0.0
    partes: List[str] = []

    if es_bh:
        if any(m.lower() in texto for m in cfg.MOTORES_LIGEROS):
            puntos += 0.5
            partes.append("motor ligero BH sin informe PDF oficial: +0.5")
        else:
            partes.append("centralita BH sin informe pericial oficial: +0.0")
    elif any(m.lower() in texto for m in cfg.MOTORES_LIGEROS):
        puntos += 1.5
        partes.append("motor ligero/diagnóstico claro: +1.5")

    if bici.km is not None and bici.km < 1000:
        puntos += 1.0
        partes.append("pocos km en motor: +1.0")
    salud_bat = getattr(bici, "bateria_salud_pct", None)
    if salud_bat is not None:
        if salud_bat >= 92:
            puntos += 0.5
            partes.append(f"salud batería certificada ({salud_bat}%): +0.5")
        elif salud_bat < 85:
            puntos = max(0.0, puntos - 1.0)
            partes.append(f"salud batería degradada ({salud_bat}%): -1.0")

    return min(puntos, 2.5), "; ".join(partes) if partes else "Motor estándar o desconocido"


def _puntuacion_precio_excepcional(bici: Bicicleta) -> Tuple[float, str]:
    """
    Oportunidad excepcional: precio muy competitivo para los componentes.
    Devuelve (puntos 0-2.0, justificación).
    """
    if bici.precio <= cfg.PRECIO_MAX_EUR:
        return 2.0, "Precio en rango principal 2.000-3.000 €: +2.0"
    if bici.precio <= cfg.PRECIO_MAX_EXCEPCIONAL_EUR:
        return 1.0, "Precio en rango excepcional hasta 3.300 €: +1.0"
    if bici.precio <= getattr(cfg, "PRECIO_MAX_UNICORNIO_XC_EUR", cfg.PRECIO_MAX_EXCEPCIONAL_EUR) and es_unicornio_xc(bici):
        return 1.5, f"Unicornio XC <= {getattr(cfg, 'PRECIO_MAX_UNICORNIO_XC_EUR', 3500)} € (>=600 Wh, <=500 km): +1.5"
    return 0.0, "Fuera de rango de precio"


def calcular_nota_oportunidad(bici: Bicicleta) -> Tuple[float, str]:
    """
    Calcula la nota de oportunidad (0-10) y devuelve (nota, desglose).
    Pesos:
      - Kilometraje:           2.5
      - Calidad-precio:        3.0
      - Motor / diagnóstico:   2.5
      - Precio excepcional:    2.0
    Aplica deducción preventiva (-1.0 pt) y techo (máx 8.5) a bicis BH
    por carecer de informe pericial verificable de desgaste y batería.
    Total máximo: 10.0
    """
    p_km, j_km = _puntuacion_km(bici.km)
    p_cp, j_cp = _puntuacion_calidad_precio(bici)
    p_motor, j_motor = _puntuacion_motor(bici)
    p_precio, j_precio = _puntuacion_precio_excepcional(bici)

    nota = p_km + p_cp + p_motor + p_precio
    sufijo_bh = ""
    if es_bici_bh(bici):
        nota = min(nota - 1.0, TECHO_NOTA_BH)
        sufijo_bh = f" | Ajuste BH (sin informe pericial PDF): -1.0 (máx {TECHO_NOTA_BH})"

    nota = round(max(0.0, min(10.0, nota)), 2)

    desglose = (
        f"Kilometraje: {j_km} | "
        f"Calidad-precio: {j_cp} | "
        f"Motor: {j_motor} | "
        f"Precio: {j_precio}{sufijo_bh}"
    )
    return nota, desglose


def evaluar(bici: Bicicleta) -> Tuple[bool, float, str]:
    """
    Aplica filtros estrictos y, si pasa, calcula la nota.
    Devuelve (apto, nota, desglose).
    """
    apto, motivo = pasa_filtros_estrictos(bici)
    if not apto:
        return False, 0.0, motivo
    nota, desglose = calcular_nota_oportunidad(bici)
    if nota < cfg.NOTA_MIN_AGUARDAR:
        return False, nota, f"Nota {nota} < {cfg.NOTA_MIN_AGUARDAR}: {desglose}"
    return True, nota, desglose


# ---------------------------------------------------------------------------
# CANAL EXCLUSIVO BLACK FRIDAY (NUEVAS / EXPOSICIÓN <= 3.500 €)
# ---------------------------------------------------------------------------

_RE_RECLAMO_NUEVA = re.compile(
    r"\b(?:nueva|a\s+estrenar|sin\s+usar|precintad[oa]|km\.?\s*0|exposici[oó]n)\b",
    re.IGNORECASE,
)


def calcular_descuento_pvp_pct(bici: Bicicleta) -> Optional[float]:
    """Calcula el % de descuento real frente a pvp_original, o None si no hay PVP válido."""
    pvp_orig = getattr(bici, "pvp_original", None)
    precio = getattr(bici, "precio", None)
    if not pvp_orig or pvp_orig <= 0 or not precio or precio <= 0 or pvp_orig <= precio:
        return None
    return round(((pvp_orig - precio) / pvp_orig) * 100.0, 1)


def clasificar_estado_nueva_exposicion(bici: Bicicleta) -> Tuple[bool, str, str]:
    """
    Verifica con escepticismo si la bicicleta es realmente nueva o de exposición (km <= 50)
    sin contradicciones de anuncio ni kilometrajes desconocidos.
    """
    texto = f"{bici.titulo or ''} {bici.componentes or ''}"
    km = bici.km

    if km is not None and km > cfg.KM_MAX_BLACK_FRIDAY:
        if _RE_RECLAMO_NUEVA.search(texto):
            return False, "CONTRADICCIÓN", f"Reclamo de nueva/exposición contradictorio con {km} km"
        return False, "USADA", f"Kilometraje > {cfg.KM_MAX_BLACK_FRIDAY} km ({km} km)"

    if km is None:
        return False, "KM_NO_CONFIRMADO", "Kilometraje no especificado para garantizar estado nuevo/exposición"

    es_tienda_nueva = cfg.es_sitio_tienda_nueva(bici.sitio, bici.url, texto)
    if km == 0 and es_tienda_nueva:
        return True, "NUEVA (0 km)", "Tienda oficial con 0 km confirmados"
    if km == 0:
        return True, "A ESTRENAR / KM 0 (0 km)", "0 km confirmados"
    return True, f"EXPOSICIÓN / KM 0 ({km} km)", f"Unidad de exposición/test con {km} km"


_RE_OCASION_TEXTO = re.compile(
    r"\b(?:reacondicionad[oa]s?|refurbished|segunda\s+mano|valor\s+de\s+recompra|medio\s+uso|de\s+ocasi[oó]n)\b",
    re.IGNORECASE,
)

_SITIOS_OCASION = ("bike ocasión", "bike ocasion", "upway")


def es_bici_de_ocasion(bici: Bicicleta) -> bool:
    """
    True si la bicicleta proviene de un portal de segunda mano / ocasión
    (Bike Ocasión, Upway, sección segunda mano de Buhobike) o si el anuncio
    indica explícitamente reacondicionada / segunda mano / medio uso.
    """
    if getattr(bici, "es_ocasion", False):
        return True
    sitio_low = (bici.sitio or "").strip().lower()
    if sitio_low in _SITIOS_OCASION:
        return True
    url_low = (bici.url or "").lower()
    if any(tok in url_low for tok in ("segunda-mano", "segundamano", "reacondicionad", "/ocasion")):
        return True
    texto = f"{bici.titulo or ''} {bici.componentes or ''}"
    return bool(_RE_OCASION_TEXTO.search(texto))


def pasa_prefiltro_black_friday(bici: Bicicleta) -> Tuple[bool, str]:
    """
    Pre-filtro previo al enriquecimiento para rescatar bicis nuevas/exposición
    de 2.000-3.500 € (doble suspensión, > 500 Wh, < 21 kg, XC preferente o Trail ligera/MTB).
    """
    if es_bici_de_ocasion(bici):
        return False, "Anuncio/portal de ocasión o reacondicionada (solo nuevas/seminuevas)"

    apto_base, motivo_base = _pasa_requisitos_base_mecanicos(
        bici,
        precio_max=cfg.PRECIO_MAX_BLACK_FRIDAY_EUR,
        bateria_estricta_gt=True,
        permitir_fazua_extender=False,
        permitir_trail_respaldo=True,
    )
    if not apto_base:
        return False, motivo_base

    es_nueva, _, motivo_estado = clasificar_estado_nueva_exposicion(bici)
    if not es_nueva:
        return False, motivo_estado
    return True, "OK"


def _puntuacion_black_friday(
    bici: Bicicleta,
    descuento_pct: float,
    etiqueta_estado: str,
) -> Tuple[float, str]:
    """
    Rúbrica específica de oportunidad Black Friday (0.0 a 10.0) sobre unidades
    nuevas o de exposición (< 21 kg, Talla M, >= 500 Wh, <= 3.500 €).
    """
    # 1. Descuento real frente a PVP (hasta 4.0 pts)
    if descuento_pct >= 55.0:
        p_dto = 4.0
    elif descuento_pct >= 45.0:
        p_dto = 3.5
    elif descuento_pct >= 40.0:
        p_dto = 3.0
    else:
        p_dto = 2.5

    # 2. Peso real verificado < 21.0 kg (hasta 2.5 pts)
    peso = float(bici.peso_kg)
    if peso <= 19.0:
        p_peso = 2.5
    elif peso <= 19.8:
        p_peso = 2.0
    elif peso <= 20.5:
        p_peso = 1.5
    else:
        p_peso = 1.0

    # 3. Estado nuevo / exposición (hasta 1.5 pts)
    km = int(bici.km or 0)
    if km == 0:
        p_estado = 1.5
    elif km <= 15:
        p_estado = 1.3
    else:
        p_estado = 1.0

    # 4. Garantía y canal (hasta 1.0 pt)
    sitio_lower = (bici.sitio or "").lower()
    garantia = bici.garantia_anos if bici.garantia_anos is not None else 0
    if sitio_lower == "wallapop":
        p_gar = 0.4 if getattr(bici, "tiene_factura", False) else 0.1
    elif garantia >= 2:
        p_gar = 1.0
    elif garantia >= 1:
        p_gar = 0.8
    else:
        p_gar = 0.4

    # 5. Montaje, auditoría de motor y banda de presupuesto (hasta 1.0 pt)
    comp = (bici.componentes or "").lower()
    cuadro = (bici.cuadro_material or "").lower()
    motor_str = (bici.motor or "").lower()
    es_gama_alta = any(k in comp for k in ("xtr", "xx1", "x01", "axs", "xt", "gx", "kashima", "factory", "ultimate"))
    es_carbono = any(k in f"{cuadro} {bici.titulo or ''}".lower() for k in ("carbon", "carbono"))
    p_comp = 1.0 if (es_gama_alta or es_carbono) else 0.6

    notas_extra: List[str] = []
    if "2exmag" in motor_str or (es_bici_bh(bici) and "ilynx+" not in (bici.titulo or "").lower()):
        p_comp -= 0.5
        notas_extra.append("motor cerrado BH 2EXMAG (-0.5)")
    elif "bosch" in motor_str and "sx" not in motor_str and "pdf" not in comp:
        p_comp -= 0.3
        notas_extra.append("Bosch sin informe PDF (-0.3)")

    if bici.precio > cfg.PRECIO_MAX_EXCEPCIONAL_EUR:
        p_comp -= 0.3
        notas_extra.append("tramo tope 3.301-3.500 € (-0.3)")
    if bici.bateria_wh is not None and bici.bateria_wh < cfg.BATERIA_MIN_WH:
        notas_extra.append(f"ext. +210 Wh opc. (~{bici.precio + 450:.0f} € total)")

    nota_bf = round(max(0.0, min(10.0, p_dto + p_peso + p_estado + p_gar + p_comp)), 2)
    extra_txt = f" | Matices: {', '.join(notas_extra)}" if notas_extra else ""
    desglose = (
        f"Dto PVP -{descuento_pct:.1f}% (+{p_dto:.1f}) | "
        f"Peso {peso:.1f} kg (+{p_peso:.1f}) | "
        f"{etiqueta_estado} (+{p_estado:.1f}) | "
        f"Garantía (+{p_gar:.1f}) | "
        f"Montaje (+{p_comp:.1f}){extra_txt}"
    )
    return nota_bf, desglose


def evaluar_oportunidad_black_friday(
    bici: Bicicleta,
    nota_perito: Optional[float] = None,
) -> Tuple[bool, float, Optional[float], str, str]:
    """
    Evalúa post-enriquecimiento si una bicicleta califica como oportunidad super
    exclusiva de Black Friday para el segundo chat de Telegram:
    doble suspensión, batería > 500 Wh, peso < 21 kg, Talla M, <= 3.500 €, nueva/exposición.
    Devuelve (califica, nota_bf, descuento_pct, etiqueta_estado, desglose).
    """
    if es_bici_de_ocasion(bici):
        return False, 0.0, None, "OCASIÓN", "Portal o anuncio de ocasión/reacondicionada (solo nuevas/seminuevas)"

    apto_base, motivo_base = _pasa_requisitos_base_mecanicos(
        bici,
        precio_max=cfg.PRECIO_MAX_BLACK_FRIDAY_EUR,
        bateria_estricta_gt=True,
        permitir_fazua_extender=False,
        permitir_trail_respaldo=True,
    )
    if not apto_base:
        return False, 0.0, None, "DESCARTADA", motivo_base

    # Guardas estrictas de completitud para evitar falsos positivos con datos ausentes
    if not bici.talla or bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
        return False, 0.0, None, "DESCARTADA", f"Talla no confirmada como M ({bici.talla})"
    if str(bici.suspension_trasera or "").strip().lower() not in ("si", "sí", "true", "1"):
        return False, 0.0, None, "DESCARTADA", f"Doble suspensión no confirmada ({bici.suspension_trasera})"
    if getattr(bici, "_peso_estimado", False):
        return False, 0.0, None, "DESCARTADA", f"Peso estimado por heurística/IA sin verificación real ({bici.peso_kg} kg)"
    if bici.peso_kg is None or bici.peso_kg >= cfg.PESO_DESCARTE_KG:
        return False, 0.0, None, "DESCARTADA", f"Peso real no confirmado < 21.0 kg ({bici.peso_kg})"
    if bici.bateria_wh is None or bici.bateria_wh <= cfg.BATERIA_MIN_WH:
        return False, 0.0, None, "DESCARTADA", f"Batería no confirmada > 500 Wh ({bici.bateria_wh})"

    es_nueva, etiqueta_estado, motivo_estado = clasificar_estado_nueva_exposicion(bici)
    if not es_nueva:
        return False, 0.0, None, etiqueta_estado, motivo_estado

    descuento_pct = calcular_descuento_pvp_pct(bici)
    if descuento_pct is None:
        return False, 0.0, None, "SIN_PVP", "Sin PVP original verificable para acreditar chollo exclusivo"
    if descuento_pct < cfg.DESCUENTO_MIN_BLACK_FRIDAY_PCT:
        return (
            False,
            0.0,
            descuento_pct,
            "DTO_INSUFICIENTE",
            f"Descuento -{descuento_pct:.1f}% < mínimo exclusivo -{cfg.DESCUENTO_MIN_BLACK_FRIDAY_PCT:.0f}%",
        )

    nota_bf, desglose_bf = _puntuacion_black_friday(bici, descuento_pct, etiqueta_estado)
    if nota_bf < cfg.NOTA_MIN_BLACK_FRIDAY:
        return (
            False,
            nota_bf,
            descuento_pct,
            "NOTA_INSUFICIENTE",
            f"Nota BF {nota_bf}/10 < {cfg.NOTA_MIN_BLACK_FRIDAY}: {desglose_bf}",
        )

    return True, nota_bf, descuento_pct, etiqueta_estado, desglose_bf


def pasa_prefiltro_respaldo_black_friday(bici: Bicicleta) -> Tuple[bool, str]:
    """
    Pre-filtro previo al enriquecimiento para localizar el Top 3 de nuevas y seminuevas
    más interesantes: doble suspensión, Talla M, batería > 500 Wh, peso < 21 kg,
    precio <= 3.500 € (respaldo hasta 4.000 €), priorizando XC y luego Trail ligera / MTB.
    """
    if es_bici_de_ocasion(bici):
        return False, "Anuncio/portal de ocasión o reacondicionada (solo nuevas/seminuevas)"
    if getattr(bici, "disponible", True) is False:
        return False, "Bicicleta reservada o agotada"
    if bici.talla and bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
        return False, f"Talla no es M: {bici.talla}"
    if not es_modalidad_mtb_doble_valida(bici):
        return False, f"Modalidad no válida para MTB: {bici.modalidad}"
    if bici.suspension_trasera is not None and str(bici.suspension_trasera).lower() in ("false", "no", "0"):
        return False, "No tiene suspensión trasera"
    if bici.bateria_wh is not None and bici.bateria_wh <= cfg.BATERIA_MIN_WH:
        return False, f"Batería <= {cfg.BATERIA_MIN_WH} Wh: {bici.bateria_wh} Wh"
    if bici.peso_kg is not None and bici.peso_kg >= cfg.PESO_DESCARTE_KG:
        return False, f"Peso >= 21 kg: {bici.peso_kg} kg"
    es_fp, motivo_fp = es_full_power_o_pesada(bici)
    if es_fp:
        return False, motivo_fp
    if bici.precio < cfg.PRECIO_MIN_EUR:
        return False, f"Precio < {cfg.PRECIO_MIN_EUR} €"
    precio_tope_resp = getattr(cfg, "PRECIO_RESPALDO_BLACK_FRIDAY_EUR", 4000)
    if bici.precio > precio_tope_resp:
        return False, f"Precio > {precio_tope_resp} €: {bici.precio} €"
    km_max_semi = getattr(cfg, "KM_MAX_SEMINUEVA_BLACK_FRIDAY", 1000)
    if bici.km is not None and bici.km > km_max_semi:
        return False, f"Kilometraje > {km_max_semi} km (ocasión/usada)"
    return True, "OK"


def evaluar_respaldo_black_friday(
    bici: Bicicleta,
    nota_perito: Optional[float] = None,
    requerir_descuento_pvp: bool = True,
) -> Tuple[bool, Optional[float], float, str, tuple]:
    """
    Evalúa candidatas para el canal de nuevas/seminuevas (Black Bike Beast):
    - Requisitos innegociables: doble suspensión confirmada, batería > 500 Wh,
      peso < 21.0 kg, Talla M, sin ocasión/reacondicionadas, km <= KM_MAX_SEMINUEVA_BLACK_FRIDAY.
    - Presupuesto: tramo principal <= 3.500 €; respaldo 3.501 - 4.000 € si no hay suficientes
      <= 3.500 € (rechazo estricto > 4.000 €).
    - Modalidad: prioriza siempre XC / Downcountry (<= 130 mm, nivel 3) y, si no hay XC,
      admite Trail ligera (nivel 2) o MTB doble suspensión (nivel 1).
    Devuelve (califica, dto_pct, nota_ref, motivo_fuera, clave_orden).
    """
    if es_bici_de_ocasion(bici):
        return False, None, 0.0, "Ocasión o reacondicionada (solo nuevas/seminuevas)", ()
    if getattr(bici, "disponible", True) is False:
        return False, None, 0.0, "No disponible", ()
    if not bici.talla or bici.talla.strip().upper() != cfg.TALLA_OBJETIVO.upper():
        return False, None, 0.0, "Talla no M", ()
    if not es_modalidad_mtb_doble_valida(bici):
        return False, None, 0.0, f"Modalidad no MTB: {bici.modalidad}", ()
    if str(bici.suspension_trasera or "").strip().lower() not in ("si", "sí", "true", "1"):
        return False, None, 0.0, "Doble suspensión no confirmada", ()
    if bici.peso_kg is None or bici.peso_kg >= cfg.PESO_DESCARTE_KG:
        return False, None, 0.0, "Peso >= 21 kg o desconocido", ()
    es_fp, motivo_fp = es_full_power_o_pesada(bici)
    if es_fp:
        return False, None, 0.0, motivo_fp, ()
    if bici.bateria_wh is None or bici.bateria_wh <= cfg.BATERIA_MIN_WH:
        return False, None, 0.0, f"Batería <= {cfg.BATERIA_MIN_WH} Wh", ()
    km_max_semi = getattr(cfg, "KM_MAX_SEMINUEVA_BLACK_FRIDAY", 1000)
    if bici.km is None or bici.km > km_max_semi:
        return False, None, 0.0, f"Kilometraje > {km_max_semi} km o no confirmado", ()
    if bici.precio < cfg.PRECIO_MIN_EUR:
        return False, None, 0.0, "Precio < mínimo", ()
    precio_tope_resp = getattr(cfg, "PRECIO_RESPALDO_BLACK_FRIDAY_EUR", 4000)
    if bici.precio > precio_tope_resp:
        return False, None, 0.0, f"Precio > {precio_tope_resp} €", ()

    dto_pct = calcular_descuento_pvp_pct(bici)
    min_dto_resp = 20.0 if bici.km <= cfg.KM_MAX_BLACK_FRIDAY else 25.0
    tiene_dto_verificado = dto_pct is not None and dto_pct >= min_dto_resp
    if requerir_descuento_pvp and not tiene_dto_verificado:
        return False, dto_pct, 0.0, f"Descuento < {min_dto_resp:.0f}% o sin PVP", ()

    prio_mod = prioridad_modalidad(bici)
    razones: List[str] = []
    if bici.precio > cfg.PRECIO_MAX_BLACK_FRIDAY_EUR:
        razones.append(f"+{bici.precio - cfg.PRECIO_MAX_BLACK_FRIDAY_EUR:.0f} € sobre tope 3.500 € (<= 4.000 €)")
    if prio_mod == 2:
        razones.append("Trail ligera (< 21 kg, respaldo XC)")
    elif prio_mod < 2:
        razones.append("e-MTB doble (< 21 kg, respaldo XC)")
    if bici.km > cfg.KM_MAX_BLACK_FRIDAY:
        razones.append(f"{bici.km} km (seminueva)")
    if dto_pct is None:
        razones.append("sin PVP original verificado")
    elif dto_pct < cfg.DESCUENTO_MIN_BLACK_FRIDAY_PCT:
        razones.append(f"dto -{dto_pct:.0f}% (< 35%)")
    if getattr(bici, "_peso_estimado", False):
        razones.append("peso est. sin báscula")

    motivo_fuera = " | ".join(razones) if razones else "Cumple requisitos (< 21 kg, > 500 Wh, <= 3.500 €)"
    en_tramo_3500 = 1 if bici.precio <= cfg.PRECIO_MAX_BLACK_FRIDAY_EUR else 0
    tramo_km = 2 if bici.km <= cfg.KM_MAX_BLACK_FRIDAY else (1 if bici.km <= 500 else 0)
    nota_ref = round(nota_perito if nota_perito is not None else 0.0, 2)
    clave_orden = (
        en_tramo_3500,
        prio_mod,
        tramo_km,
        1 if tiene_dto_verificado else 0,
        round(dto_pct, 1) if tiene_dto_verificado else nota_ref,
        nota_ref,
        -(bici.peso_kg or 21.0),
        -float(bici.precio),
    )
    return True, dto_pct, nota_ref, motivo_fuera, clave_orden
