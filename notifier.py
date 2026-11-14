"""
notifier.py
Notificador de Telegram vía requests (S9).
Envía mensaje formateado en Markdown con la ficha de la bicicleta.
"""

from typing import Optional
import requests
import config as cfg


def formatear_mensaje(
    bici,
    nota: float,
    desglose: str,
    precio_anterior: Optional[float] = None,
    seguimiento: Optional[dict] = None,
) -> str:
    """
    Construye el mensaje Markdown para Telegram (S9).
    Incluye: título, precio (con alerta de bajada si aplica), nota destacada 🔥,
    kilómetros, batería, cuadro, recorrido de suspensión, seguimiento en stock,
    desglose de la nota y enlace directo.
    """
    km = bici.km if bici.km is not None else "no indicado"
    if getattr(bici, "range_extender_wh", None):
        extender_val = bici.range_extender_wh
        bat_interna = (bici.bateria_wh - extender_val) if bici.bateria_wh else None
        if bat_interna and bat_interna > 0:
            bateria = f"{bici.bateria_wh} Wh ({bat_interna} Wh + 🔋 {extender_val} Wh Range Extender)"
        else:
            bateria = f"{bici.bateria_wh} Wh (+ 🔋 {extender_val} Wh Range Extender)"
    elif bici.bateria_wh:
        bateria = f"{bici.bateria_wh} Wh"
    else:
        bateria = "no indicado"

    salud_pct = getattr(bici, "bateria_salud_pct", None)
    ciclos_bat = getattr(bici, "bateria_ciclos", None)
    if salud_pct is not None or ciclos_bat is not None:
        partes_soh = []
        if salud_pct is not None:
            partes_soh.append(f"SoH: {salud_pct}%")
        if ciclos_bat is not None:
            partes_soh.append(f"{ciclos_bat} ciclos")
        bateria = f"{bateria} [{' | '.join(partes_soh)}]"
    cuadro = bici.cuadro_material or "no indicado"
    motor = bici.motor or "no indicado"
    ano = bici.ano or "no indicado"
    talla = bici.talla or "no indicada"
    modalidad = bici.modalidad or "no indicada"
    if getattr(bici, "recorrido_mm", None):
        modalidad = f"{modalidad} ({bici.recorrido_mm} mm)"
    garantia = (
        bici.garantia_anos
        if bici.garantia_anos is not None
        else cfg.SITIOS[0].garantia_anos
    )

    desglose_seguro = (
        str(desglose)
        .replace("_", "-")
        .replace("*", "")
        .replace("`", "'")
    )

    precio_ref = precio_anterior
    if precio_ref is None and seguimiento and seguimiento.get("precio_inicial"):
        p_ini = float(seguimiento["precio_inicial"])
        if p_ini > bici.precio:
            precio_ref = p_ini

    es_bajada = precio_ref is not None and bici.precio < precio_ref
    es_vigilancia = bool(seguimiento and seguimiento.get("entrada_desde_vigilancia"))

    if es_vigilancia and es_bajada:
        ahorro = precio_ref - bici.precio
        linea_precio = f"💰 Precio: *{bici.precio:.0f} €* (Antes: ~{precio_ref:.0f} €~ | 🚨 Ahorro: *-{ahorro:.0f} €*)"
        cabecera = "🚨 *¡ENTRADA DESDE ZONA DE VIGILANCIA! BAJADA DE PRECIO DETECTADA*"
    elif es_bajada:
        ahorro = precio_ref - bici.precio
        linea_precio = f"💰 Precio: *{bici.precio:.0f} €* (Antes: ~{precio_ref:.0f} €~ | 📉 Ahorro: *-{ahorro:.0f} €*)"
        cabecera = "📉 *¡BAJADA DE PRECIO DETECTADA! Oportunidad e-MTB*"
    else:
        linea_precio = f"💰 Precio: *{bici.precio} €*"
        cabecera = "🚵‍♂️ *Nueva oportunidad de e-MTB encontrada*"

    linea_seguimiento = ""
    if seguimiento:
        dias = seguimiento.get("dias_en_stock", 0)
        rebajas = seguimiento.get("rebajas_detectadas", 0)
        partes_seg = []
        if dias > 0:
            partes_seg.append(f"⏳ {dias} días en catálogo")
        if rebajas > 0:
            partes_seg.append(f"🏷️ {rebajas} rebaja(s)")
        if partes_seg:
            linea_seguimiento = f"📊 Seguimiento: {' | '.join(partes_seg)}\n"

    mensaje = (
        f"{cabecera}\n\n"
        f"*{bici.titulo}*\n"
        f"🏪 Tienda: {bici.sitio}\n"
        f"{linea_precio}\n"
        f"🔥 Nota de Oportunidad: *{nota}/10*\n\n"
        f"📏 Talla: {talla}\n"
        f"⚙️ Modalidad: {modalidad}\n"
        f"⚖️ Peso: {bici.peso_kg if bici.peso_kg else 'no indicado'} kg\n"
        f"🔋 Batería: {bateria}\n"
        f"🛞 Cuadro: {cuadro}\n"
        f"⚡ Motor: {motor}\n"
        f"📅 Año: {ano}\n"
        f"🛣️ Kilómetros: {km}\n"
        f"🛡️ Garantía: {garantia} año(s)\n"
        f"{linea_seguimiento}\n"
        f"_Valoración técnica (IA / 5 ejes):_\n{desglose_seguro}\n\n"
        f"🔗 [Enlace directo de compra]({bici.url})"
    )
    return mensaje


def enviar(
    bici,
    nota: float,
    desglose: str,
    precio_anterior: Optional[float] = None,
    seguimiento: Optional[dict] = None,
) -> bool:
    """
    Envía el mensaje a Telegram. Devuelve True si tuvo éxito.
    Maneja excepciones de red para no caer la ejecución diaria (S13).
    """
    if not cfg.TELEGRAM_BOT_TOKEN or not cfg.TELEGRAM_CHAT_ID:
        print("[Telegram] Credenciales no configuradas. Se omite el envío.")
        return False

    url = cfg.TELEGRAM_API_URL.format(token=cfg.TELEGRAM_BOT_TOKEN)
    texto = formatear_mensaje(
        bici,
        nota,
        desglose,
        precio_anterior=precio_anterior,
        seguimiento=seguimiento,
    )
    payload = {
        "chat_id": cfg.TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 400:
            # Fallback sin parse_mode por si algún carácter especial rompe Markdown v1
            payload.pop("parse_mode", None)
            resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        print(f"[Telegram] Enviado: {bici.resumen_corto()}")
        return True
    except requests.RequestException as e:
        print(f"[Telegram] Error enviando mensaje: {e}")
        return False


def formatear_heartbeat(resumen: dict) -> str:
    """
    Construye el mensaje Markdown del Heartbeat para Telegram (TODO 2).
    Informa del pulso diario de salud del scraper, portales procesados,
    candidatas analizadas y estado del radar de mercado.
    """
    fecha_hora = resumen.get("fecha_hora", "")
    duracion = resumen.get("duracion_seg", 0.0)
    total_proc = resumen.get("total_procesadas", 0)
    conteo_sitios = resumen.get("conteo_por_portal", {})
    aptas = resumen.get("candidatas_aptas", 0)
    notificadas = resumen.get("notificadas", 0)
    en_catalogo = resumen.get("total_en_catalogo", 0)
    en_vigilancia = resumen.get("total_en_vigilancia", 0)
    estado = resumen.get("estado", "🟢 Runner operativo")

    lineas_portales = []
    for sitio, cant in sorted(conteo_sitios.items(), key=lambda x: x[1], reverse=True):
        lineas_portales.append(f"  • {sitio}: *{cant}* bicis")
    bloque_portales = "\n".join(lineas_portales) if lineas_portales else "  • _Sin desglose disponible_"

    if notificadas > 0:
        texto_notif = f"*{notificadas}* enviada(s) 🔥"
    else:
        texto_notif = "0 (sin nuevas oportunidades ni rebajas en el Top)"

    mensaje = (
        f"💓 *Heartbeat Buscador e-MTB* — Pulso Operativo\n"
        f"📅 `{fecha_hora}` | ⏱️ `{duracion}s`\n\n"
        f"🏪 *Portales rastreados ({total_proc} bicicletas)*:\n"
        f"{bloque_portales}\n\n"
        f"📊 *Diagnóstico del runner*:\n"
        f"  • Candidatas aptas analizadas: *{aptas}*\n"
        f"  • Alertas prioritarias: {texto_notif}\n"
        f"  • Radar activo en seguimiento: *{en_catalogo}* unidades\n"
        f"  • Zona de vigilancia (2.900-3.500 €): *{en_vigilancia}* unidades\n\n"
        f"{estado}"
    )
    return mensaje


def enviar_heartbeat(resumen: dict) -> bool:
    """
    Envía el mensaje de heartbeat a Telegram. Devuelve True si tuvo éxito.
    """
    if not cfg.TELEGRAM_BOT_TOKEN or not cfg.TELEGRAM_CHAT_ID:
        print("[Telegram/Heartbeat] Credenciales no configuradas. Se omite el envío.")
        return False

    url = cfg.TELEGRAM_API_URL.format(token=cfg.TELEGRAM_BOT_TOKEN)
    texto = formatear_heartbeat(resumen)
    payload = {
        "chat_id": cfg.TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 400:
            payload.pop("parse_mode", None)
            resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        print(f"[Telegram/Heartbeat] Heartbeat enviado exitosamente.")
        return True
    except requests.RequestException as e:
        print(f"[Telegram/Heartbeat] Error enviando heartbeat: {e}")
        return False
