"""
gemini_classifier.py
Clasificador y enriquecedor híbrido (Gemini Flash + Motor Autónomo Local sin API).

Responsabilidades:
  1. Completar campos técnicos faltantes de cada bicicleta (peso_kg, bateria_wh,
     motor, cuadro_material, suspension_trasera, modalidad, componentes, ano, km, talla)
     combinando:
       a) Ficha técnica de la tienda (Scrapling via enriquecedor_web)
       b) Catálogo técnico local de modelos e-MTB de referencia
       c) Gemini Flash (gemini-3.5-flash / gemini-3.5-flash-lite con Google Search)
  2. Evaluar la oportunidad de compra (nota 0.0 a 10.0 y análisis técnico)
     ponderando los 5 ejes clave:
       - Kilómetros y desgaste mecánico
       - Peso (< 21 kg excluyente, premiando <= 19 kg y cuadro de carbono)
       - Posibilidad de obtener documentación/diagnóstico fiable del motor
       - Estado y capacidad de la batería (> 500 Wh, degradación por km/año y garantía)
       - Componentes y relación calidad-precio dentro del rango 2.000-3.300 €
  3. Funcionar 100% autónomo sin API de Google si no hay GEMINI_API_KEY o si la cuota
     gratuita devuelve error/rate-limit.
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

import config as cfg
from models import Bicicleta
from scrapers.enriquecedor_web import enriquecer_bici, _buscar_en_cache

log = logging.getLogger("buscador.ia")

CACHE_DIR = Path("cache")
CACHE_IA_FILE = CACHE_DIR / "valoraciones_ia.json"


# ---------------------------------------------------------------------------
# Catálogo técnico de referencia e-MTB (para inferencia sin API y validación)
# ---------------------------------------------------------------------------
# Cada entrada define patrones de modelo y sus especificaciones reales de catálogo.
CATALOGO_EMTB = [
    {
        "patrones": ["bh ilynx race carbon", "ilynx race carbon"],
        "peso_kg": 16.8,
        "bateria_wh_default": 540,
        "motor": "BH 2EXMAG",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
    },
    {
        "patrones": ["bh ilynx trail carbon", "ilynx trail carbon"],
        "peso_kg": 18.2,
        "bateria_wh_default": 540,
        "motor": "BH 2EXMAG",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Trail",
    },
    {
        "patrones": ["bh ilynx trail", "bh ilynx race"],
        "peso_kg": 19.6,
        "bateria_wh_default": 540,
        "motor": "BH 2EXMAG",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["orbea rise m", "orbea rise m10", "orbea rise m20", "orbea rise m-team", "orbea rise m-ltd"],
        "peso_kg": 18.3,
        "bateria_wh_default": 540,
        "motor": "Shimano EP801 RS",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Trail",
    },
    {
        "patrones": ["orbea rise h", "orbea rise h10", "orbea rise h15", "orbea rise h20", "orbea rise h30"],
        "peso_kg": 20.3,
        "bateria_wh_default": 540,
        "motor": "Shimano EP8 / EP6 RS",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Trail",
    },
    {
        "patrones": ["cannondale moterra sl"],
        "peso_kg": 19.5,
        "bateria_wh_default": 601,
        "motor": "Shimano EP801",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Trail",
    },
    {
        "patrones": ["specialized turbo levo sl", "levo sl"],
        "peso_kg": 17.9,
        "bateria_wh_default": 480,
        "motor": "Specialized SL 1.1 / 1.2",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["trek fuel exe", "fuel exe"],
        "peso_kg": 18.4,
        "bateria_wh_default": 360,
        "motor": "TQ HPR50",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["scott lumen"],
        "peso_kg": 16.5,
        "bateria_wh_default": 520,
        "motor": "TQ HPR50",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
    },
    {
        "patrones": ["mondraker neat"],
        "peso_kg": 18.5,
        "bateria_wh_default": 360,
        "motor": "TQ HPR50",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["giant trance x advanced e+ elite"],
        "peso_kg": 19.1,
        "bateria_wh_default": 400,
        "motor": "Giant SyncDrive Pro",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["ktm macina scarp"],
        "peso_kg": 17.8,
        "bateria_wh_default": 500,
        "motor": "Bosch Performance Line SX / CX",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "XC / Downcountry",
    },
    {
        "patrones": ["cube ams hybrid one44"],
        "peso_kg": 17.4,
        "bateria_wh_default": 400,
        "motor": "Bosch Performance Line SX",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB / Downcountry",
    },
    {
        "patrones": ["lapierre e-zesty", "ezesty"],
        "peso_kg": 18.4,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["focus vam2 sl", "focus jam2 sl"],
        "peso_kg": 17.9,
        "bateria_wh_default": 430,
        "motor": "Fazua Ride 60",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Light e-MTB",
    },
    {
        "patrones": ["merida eone-forty", "eone-forty"],
        "peso_kg": 20.6,
        "bateria_wh_default": 630,
        "motor": "Shimano EP8",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail / All Mountain",
    },
    {
        "patrones": ["moustache samedi 29 trail", "samedi 29 trail"],
        "peso_kg": 23.3,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["giant reign e+"],
        "peso_kg": 24.2,
        "bateria_wh_default": 625,
        "motor": "Giant SyncDrive Pro (Yamaha)",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Enduro / Trail",
    },
    {
        "patrones": ["giant stance e+"],
        "peso_kg": 23.8,
        "bateria_wh_default": 625,
        "motor": "Giant SyncDrive Sport (Yamaha)",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["specialized turbo levo", "turbo levo"],
        "peso_kg": 22.1,
        "bateria_wh_default": 700,
        "motor": "Specialized 2.2 (Brose)",
        "cuadro_material": "Carbono",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["orbea wild"],
        "peso_kg": 22.8,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Enduro / Trail",
    },
    {
        "patrones": ["scott strike eride", "scott patron eride"],
        "peso_kg": 23.5,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail",
    },
    {
        "patrones": ["trek rail"],
        "peso_kg": 22.9,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
    },
    {
        "patrones": ["mondraker crafty"],
        "peso_kg": 23.4,
        "bateria_wh_default": 625,
        "motor": "Bosch Performance Line CX",
        "cuadro_material": "Aluminio",
        "suspension_trasera": "si",
        "modalidad": "Trail / Enduro",
    },
]


# ---------------------------------------------------------------------------
# Base de conocimiento sobre documentación/diagnóstico fiable por motor
# ---------------------------------------------------------------------------
def evaluar_documentacion_motor(motor_str: Optional[str], titulo: str = "") -> Tuple[float, str]:
    """
    Evalúa la viabilidad de extraer un informe oficial de diagnóstico del motor y batería.
    Devuelve (puntos sobre 2.0, explicación técnica).
    """
    texto = f"{motor_str or ''} {titulo}".lower()

    if "bosch" in texto:
        return (
            2.0,
            "Alta (Bosch DiagnosticTool 3 genera informe PDF oficial con km reales, "
            "ciclos de carga completos, tiempo por modo de asistencia y registro de errores)",
        )
    if "shimano" in texto or "ep8" in texto or "ep6" in texto or "orbea rise" in texto:
        return (
            1.9,
            "Alta (Shimano E-Tube Project Professional con interfaz PCE02 permite auditar "
            "salud de batería SoH %, ciclos de carga, odómetro interno y fallos registrados)",
        )
    if "specialized" in texto or "brose" in texto or "levo" in texto:
        return (
            1.8,
            "Alta (Specialized Turbo Studio y app Mission Control muestran salud de batería "
            "en %, ciclos exactos, odómetro de motor y números de serie)",
        )
    if any(m in texto for m in ["tq", "fazua", "mahle"]):
        return (
            1.7,
            "Media-Alta (Fazua Toolbox / TQ Service Tool permite verificar ciclos de batería, "
            "estado de celdas y horas de uso del sistema ligero)",
        )
    if "giant" in texto or "syncdrive" in texto or "yamaha" in texto:
        return (
            1.5,
            "Media-Alta (Giant RideControl / diagnóstico Yamaha en taller oficial verifica "
            "salud de EnergyPak, ciclos de carga y odómetro)",
        )
    if "bh" in texto or "2exmag" in texto or "2esmag" in texto or "ilynx" in texto:
        return (
            1.5,
            "Media (diagnóstico en servicio oficial BH Core/2EXMAG verifica estado de celdas "
            "y odómetro; respaldado por 1 año de garantía mecánica de tienda)",
        )
    return (
        1.2,
        "Media (requiere lectura de taller multimarca; cubierta por 1 año de garantía "
        "mecánica de la tienda profesional)",
    )


# ---------------------------------------------------------------------------
# Caché de valoraciones IA
# ---------------------------------------------------------------------------
def _cargar_cache_ia() -> Dict[str, dict]:
    if not CACHE_IA_FILE.exists():
        return {}
    try:
        with open(CACHE_IA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _guardar_cache_ia(cache: Dict[str, dict]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    try:
        with open(CACHE_IA_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"[IA Caché] No se pudo guardar {CACHE_IA_FILE}: {e}")


# ---------------------------------------------------------------------------
# Paso 1: Enriquecimiento con catálogo técnico local + ficha de tienda
# ---------------------------------------------------------------------------
def completar_con_catalogo(bici: Bicicleta) -> Bicicleta:
    """
    Completa campos faltantes de la bicicleta cruzando su título y datos actuales
    con el catálogo técnico de referencia de modelos e-MTB.
    """
    texto = f"{bici.titulo} {bici.motor or ''} {bici.componentes or ''}".lower()

    for entrada in CATALOGO_EMTB:
        if any(p in texto for p in entrada["patrones"]):
            if bici.peso_kg is None:
                bici.peso_kg = entrada["peso_kg"]
            if bici.bateria_wh is None:
                bici.bateria_wh = entrada["bateria_wh_default"]
            if not bici.motor:
                bici.motor = entrada["motor"]
            if not bici.cuadro_material:
                bici.cuadro_material = entrada["cuadro_material"]
            if bici.suspension_trasera is None:
                bici.suspension_trasera = entrada["suspension_trasera"]
            if not bici.modalidad:
                bici.modalidad = entrada["modalidad"]
            break

    # Inferencia adicional por heurística técnica si el modelo no está en la tabla exacta
    if not bici.cuadro_material:
        if any(k in texto for k in ["carbon", "carbono", " m10", " m20", " m-team", "advanced", "cf "]):
            bici.cuadro_material = "Carbono"
        elif any(k in texto for k in ["aluminio", "alloy", "alu", " h10", " h20", " h30"]):
            bici.cuadro_material = "Aluminio"

    if bici.peso_kg is None:
        # Estimación conservadora basada en material de cuadro y capacidad de batería
        es_carbono = (bici.cuadro_material or "").lower() == "carbono"
        bat = bici.bateria_wh or 540
        if es_carbono and bat <= 560:
            bici.peso_kg = 18.6
        elif not es_carbono and bat <= 540:
            bici.peso_kg = 20.4
        elif es_carbono and bat <= 630:
            bici.peso_kg = 20.8
        else:
            bici.peso_kg = 22.8

    if not bici.modalidad:
        if bici.peso_kg is not None and bici.peso_kg < 21.0:
            bici.modalidad = "Light e-MTB / Trail"
        else:
            bici.modalidad = "Trail"

    return bici


# ---------------------------------------------------------------------------
# Paso 2: Valoración técnica autónoma (5 ejes) — funciona sin API
# ---------------------------------------------------------------------------
def valorar_autonomo(bici: Bicicleta) -> Tuple[float, str]:
    """
    Calcula la nota de oportunidad (0.0 a 10.0) y genera la valoración técnica
    estructurada en los 5 ejes solicitados (km, peso, documentación motor,
    estado de batería y componentes/precio).
    """
    # 1. Kilómetros (0 - 2.0 pts)
    if bici.km is None:
        p_km = 1.2
        txt_km = "No especificado en ficha (se recomienda pedir lectura en tienda)"
    elif bici.km < 500:
        p_km = 2.0
        txt_km = f"Excelente ({bici.km} km, prácticamente reestreno)"
    elif bici.km < 1500:
        p_km = 1.8
        txt_km = f"Muy bajo ({bici.km} km, desgaste mínimo de transmisión)"
    elif bici.km <= 3000:
        p_km = 1.4
        txt_km = f"Moderado ({bici.km} km, uso normal)"
    elif bici.km <= 4500:
        p_km = 0.9
        txt_km = f"Medio-alto ({bici.km} km, revisar casete y cadena)"
    else:
        p_km = 0.4
        txt_km = f"Alto ({bici.km} km, penaliza por desgaste acumulado)"

    # 2. Peso y chasis (< 21 kg objetivo) (0 - 2.0 pts)
    es_carbono = "carbon" in (bici.cuadro_material or "").lower()
    if bici.peso_kg is not None:
        if bici.peso_kg <= 18.5:
            p_peso = 2.0
            txt_peso = f"{bici.peso_kg} kg (ultraligera, cuadro {bici.cuadro_material or 'Carbono'})"
        elif bici.peso_kg < 20.0:
            p_peso = 1.8 if es_carbono else 1.6
            txt_peso = f"{bici.peso_kg} kg (muy ágil, cumple < 21 kg holgadamente)"
        elif bici.peso_kg < 21.0:
            p_peso = 1.5 if es_carbono else 1.3
            txt_peso = f"{bici.peso_kg} kg (dentro del límite < 21 kg)"
        else:
            p_peso = 0.5
            txt_peso = f"{bici.peso_kg} kg (supera el objetivo de 21 kg)"
    else:
        p_peso = 1.2
        txt_peso = f"Estimado según cuadro ({bici.cuadro_material or 'estándar'})"

    # 3. Documentación fiable del motor (0 - 2.0 pts)
    p_motor, txt_motor = evaluar_documentacion_motor(bici.motor, bici.titulo)

    # 4. Estado y capacidad de la batería (0 - 2.0 pts)
    bat = bici.bateria_wh
    if bat is not None and bat >= 600:
        p_bat = 1.9
        salud_est = "92-98% SoH estimado" if (bici.km or 0) < 2500 else "85-90% SoH estimado"
        txt_bat = f"{bat} Wh (gran autonomía, {salud_est}, con 1 año de garantía)"
    elif bat is not None and bat > 500:
        p_bat = 1.8 if (bici.km or 0) < 2000 else 1.5
        salud_est = "94-99% SoH estimado" if (bici.km or 0) < 1500 else "88-93% SoH estimado"
        txt_bat = f"{bat} Wh (óptimo equilibrio peso/autonomía, {salud_est})"
    elif bat is not None:
        p_bat = 0.8
        txt_bat = f"{bat} Wh (capacidad ajustada <= 500 Wh)"
    else:
        p_bat = 1.1
        txt_bat = "Capacidad pendiente de confirmar en ficha"

    # 5. Componentes y relación calidad-precio (0 - 2.0 pts)
    texto_comp = f"{bici.titulo} {bici.componentes or ''}".lower()
    p_comp = 1.0
    detalles_comp = []
    if es_carbono:
        p_comp += 0.3
        detalles_comp.append("cuadro carbono")
    if any(k in texto_comp for k in ["xt", "xtr", "axs", "x0", "gx"]):
        p_comp += 0.4
        detalles_comp.append("transmisión gama alta (XT/AXS)")
    elif "deore" in texto_comp or "slx" in texto_comp:
        p_comp += 0.2
        detalles_comp.append("transmisión fiable (SLX/Deore)")
    if any(k in texto_comp for k in ["kashima", "factory", "ultimate", "fox"]):
        p_comp += 0.3
        detalles_comp.append("suspensión Fox/ Factory")
    if bici.precio <= cfg.PRECIO_MAX_EUR:
        p_comp += 0.2
        detalles_comp.append(f"precio en rango ideal ({bici.precio:.0f} €)")
    else:
        detalles_comp.append(f"precio en rango excepcional ({bici.precio:.0f} €)")

    p_comp = min(2.0, p_comp)
    txt_comp = ", ".join(detalles_comp) if detalles_comp else "Montaje estándar de serie"

    nota = round(max(0.0, min(10.0, p_km + p_peso + p_motor + p_bat + p_comp)), 2)

    desglose = (
        f"• 🛣️ Km: {txt_km}\n"
        f"• ⚖️ Peso: {txt_peso}\n"
        f"• 🔍 Diagnóstico motor: {txt_motor}\n"
        f"• 🔋 Estado batería: {txt_bat}\n"
        f"• ⚙️ Componentes/Precio: {txt_comp}"
    )
    return nota, desglose


# ---------------------------------------------------------------------------
# Paso 3: Enriquecimiento y valoración con Gemini Flash (gemini-3.5-flash)
# ---------------------------------------------------------------------------
def _llamar_gemini_api(prompt: str, usar_busqueda: bool = False) -> Optional[dict]:
    """
    Invoca Gemini Flash (gemini-3.5-flash -> fallback gemini-3.5-flash-lite).
    Devuelve el dict JSON parseado o None si no hay clave o falla la cuota.
    """
    api_key = cfg.GEMINI_API_KEY
    if not api_key:
        return None

    for model in cfg.GEMINI_MODELS:
        url = f"{cfg.GEMINI_API_URL.format(model=model)}?key={api_key}"
        payload: dict = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        if usar_busqueda:
            payload["tools"] = [{"google_search": {}}]
            # Cuando se activa google_search en algunas versiones de API no se admite responseMimeType
            payload["generationConfig"].pop("responseMimeType", None)

        try:
            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code != 200:
                log.debug(f"[Gemini {model}] HTTP {resp.status_code}: {resp.text[:180]}")
                continue

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                continue

            parts = candidates[0].get("content", {}).get("parts", [])
            texto_respuesta = "".join(p.get("text", "") for p in parts if "text" in p).strip()
            if not texto_respuesta:
                continue

            # Extraer bloque JSON aunque venga envuelto en ```json ... ```
            match = re.search(r"\{.*\}", texto_respuesta, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            log.debug(f"[Gemini {model}] Excepción: {e}")
            continue

    return None


def enriquecer_y_valorar_bici(bici: Bicicleta) -> Tuple[Bicicleta, float, str]:
    """
    Flujo híbrido completo para una bicicleta candidata:
      1. Extrae ficha de producto del sitio con Scrapling (enriquecer_bici).
      2. Completa especificaciones de referencia con el catálogo técnico local.
      3. Si GEMINI_API_KEY está activa, consulta Gemini Flash (gemini-3.5-flash)
         para afinar cualquier dato faltante y obtener la valoración inteligente
         de los 5 ejes (km, peso < 21 kg, documentación fiable del motor,
         estado de batería y componentes).
      4. Si Gemini no está disponible o falla, usa el motor autónomo local.

    Devuelve (bici_enriquecida, nota, desglose_valoracion).
    """
    # 1. Enriquecimiento desde la ficha HTML del sitio (con caché local)
    try:
        bici = enriquecer_bici(bici, url_ficha=bici.url)
    except Exception as e:
        log.warning(f"[IA] Error en enriquecer_bici para {bici.titulo}: {e}")

    # 2. Enriquecimiento desde catálogo técnico de modelos e-MTB
    bici = completar_con_catalogo(bici)

    # Verificar caché de valoración IA para esta bici y precio
    cache_key = f"{bici.sitio}:{bici.bici_id}:{int(bici.precio)}"
    cache_ia = _cargar_cache_ia()
    if cache_key in cache_ia:
        entry = cache_ia[cache_key]
        for campo in ("talla", "modalidad", "peso_kg", "bateria_wh", "cuadro_material",
                      "motor", "km", "ano", "componentes", "suspension_trasera"):
            if entry.get(campo) is not None and getattr(bici, campo, None) is None:
                setattr(bici, campo, entry[campo])
        return bici, float(entry["nota"]), str(entry["desglose"])

    # 3. Intentar clasificación y valoración con Gemini Flash
    _, doc_motor_ref = evaluar_documentacion_motor(bici.motor, bici.titulo)
    prompt = f"""Eres un experto mecánico y tasador de bicicletas eléctricas de montaña (e-MTB) de ocasión en España.
Analiza esta bicicleta y completa los datos técnicos que falten según el catálogo oficial del fabricante:

Datos actuales extraídos de la tienda ({bici.sitio}):
- Título: {bici.titulo}
- Precio: {bici.precio} €
- Talla: {bici.talla or 'desconocida'}
- Peso (kg): {bici.peso_kg if bici.peso_kg is not None else 'desconocido'}
- Batería (Wh): {bici.bateria_wh if bici.bateria_wh is not None else 'desconocida'}
- Motor: {bici.motor or 'desconocido'}
- Cuadro: {bici.cuadro_material or 'desconocido'}
- Kilómetros: {bici.km if bici.km is not None else 'desconocido'}
- Año: {bici.ano if bici.ano is not None else 'desconocido'}
- Componentes: {bici.componentes or 'de serie'}
- Suspensión trasera (doble suspensión): {bici.suspension_trasera or 'si'}
- Referencia diagnóstico motor: {doc_motor_ref}

Parámetros objetivo del comprador:
- Buscamos e-MTB doble suspensión en Talla M, precio 2.000-3.300 €, batería > 500 Wh y peso estricto < 21 kg (priorizando <= 19 kg y carbono).
- Valora de 0.0 a 10.0 la oportunidad de compra evaluando obligatoriamente:
  1) Kilómetros y desgaste
  2) Peso real (penalizando si llega o supera 21 kg, premiando < 19.5 kg)
  3) Posibilidad de sacarle documentación/diagnóstico fiable al motor (informe Bosch, Shimano E-Tube, Specialized, etc.)
  4) Estado estimado y capacidad de la batería (Wh, ciclos esperados por km/año y garantía)
  5) Componentes (transmisión, suspensiones, cuadro) frente al precio.

Devuelve ÚNICAMENTE un objeto JSON válido con esta estructura exacta:
{{
  "peso_kg": numero_float_peso_estimado_real,
  "bateria_wh": numero_int_wh,
  "motor": "marca y modelo del motor",
  "cuadro_material": "Carbono o Aluminio",
  "suspension_trasera": "si o no",
  "modalidad": "Light e-MTB / XC / Downcountry / Trail",
  "ano": numero_int_ano,
  "componentes": "resumen breve de transmisión y suspensiones",
  "nota": numero_float_de_0_a_10,
  "km_analisis": "valoración breve de los km",
  "peso_analisis": "valoración breve del peso y chasis",
  "motor_doc_analisis": "explicación de qué informe/diagnóstico fiable se puede extraer del motor",
  "bateria_analisis": "valoración del estado y capacidad de la batería",
  "componentes_analisis": "valoración de componentes y relación calidad-precio"
}}"""

    res_gemini = _llamar_gemini_api(prompt, usar_busqueda=False)
    if res_gemini:
        try:
            if bici.peso_kg is None and res_gemini.get("peso_kg"):
                bici.peso_kg = float(res_gemini["peso_kg"])
            if bici.bateria_wh is None and res_gemini.get("bateria_wh"):
                bici.bateria_wh = int(res_gemini["bateria_wh"])
            if not bici.motor and res_gemini.get("motor"):
                bici.motor = str(res_gemini["motor"])
            if not bici.cuadro_material and res_gemini.get("cuadro_material"):
                bici.cuadro_material = str(res_gemini["cuadro_material"])
            if bici.suspension_trasera is None and res_gemini.get("suspension_trasera"):
                bici.suspension_trasera = str(res_gemini["suspension_trasera"]).lower()
            if not bici.modalidad and res_gemini.get("modalidad"):
                bici.modalidad = str(res_gemini["modalidad"])
            if bici.ano is None and res_gemini.get("ano"):
                bici.ano = int(res_gemini["ano"])
            if not bici.componentes and res_gemini.get("componentes"):
                bici.componentes = str(res_gemini["componentes"])

            nota_ia = round(max(0.0, min(10.0, float(res_gemini.get("nota", 8.0)))), 2)
            desglose_ia = (
                f"🤖 Valoración Gemini Flash:\n"
                f"• 🛣️ Km: {res_gemini.get('km_analisis', '')}\n"
                f"• ⚖️ Peso: {res_gemini.get('peso_analisis', '')}\n"
                f"• 🔍 Diagnóstico motor: {res_gemini.get('motor_doc_analisis', '')}\n"
                f"• 🔋 Estado batería: {res_gemini.get('bateria_analisis', '')}\n"
                f"• ⚙️ Componentes/Precio: {res_gemini.get('componentes_analisis', '')}"
            )

            cache_ia[cache_key] = {
                "talla": bici.talla,
                "modalidad": bici.modalidad,
                "peso_kg": bici.peso_kg,
                "bateria_wh": bici.bateria_wh,
                "cuadro_material": bici.cuadro_material,
                "motor": bici.motor,
                "km": bici.km,
                "ano": bici.ano,
                "componentes": bici.componentes,
                "suspension_trasera": bici.suspension_trasera,
                "nota": nota_ia,
                "desglose": desglose_ia,
            }
            _guardar_cache_ia(cache_ia)
            log.info(f"[Gemini Flash] Valorada: {bici.titulo} -> {nota_ia}/10 (peso={bici.peso_kg} kg)")
            return bici, nota_ia, desglose_ia
        except Exception as e:
            log.warning(f"[Gemini Flash] Error procesando respuesta JSON para {bici.titulo}: {e}")

    # 4. Fallback al motor autónomo local (100% sin API)
    nota_auto, desglose_auto = valorar_autonomo(bici)
    log.info(f"[Motor Autónomo] Valorada: {bici.titulo} -> {nota_auto}/10 (peso={bici.peso_kg} kg)")
    return bici, nota_auto, desglose_auto
