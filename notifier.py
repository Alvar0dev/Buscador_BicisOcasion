"""
notifier.py
Notificador de Telegram vía requests (S9).
Envía mensaje formateado en Markdown con la ficha de la bicicleta.
"""

from typing import Optional
import requests
import config as cfg


def es_mega_chollo(bici, nota: float) -> bool:
    """
    Determina si una bicicleta califica como Mega Chollo:
    Requiere simultáneamente descuento >= 50% frente a PVP original nuevo Y nota pericial >= 9.0.
    """
    pvp_orig = getattr(bici, "pvp_original", None)
    precio = getattr(bici, "precio", None)
    if not pvp_orig or pvp_orig <= 0 or not precio or precio <= 0:
        return False
    if pvp_orig <= precio:
        return False
    pct_dto = ((pvp_orig - precio) / pvp_orig) * 100.0
    return pct_dto >= 50.0 and nota >= 9.0


def _campos_ficha_bici(bici, desglose: str) -> dict:
    """Normaliza los campos comunes de una bicicleta para mensajes Markdown de Telegram."""
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

    modalidad = bici.modalidad or "no indicada"
    if getattr(bici, "recorrido_mm", None):
        modalidad = f"{modalidad} ({bici.recorrido_mm} mm)"

    garantia = (
        bici.garantia_anos
        if bici.garantia_anos is not None
        else cfg.SITIOS[0].garantia_anos
    )
    garantia_txt = (
        "Sin garantía comercial (particular)"
        if garantia == 0
        else f"{garantia} año(s)"
    )

    desglose_seguro = (
        str(desglose)
        .replace("_", "-")
        .replace("*", "")
        .replace("`", "'")
    )

    linea_ubicacion = (
        f"📍 Ubicación: {bici.ubicacion}\n"
        if getattr(bici, "ubicacion", None)
        else ""
    )

    return {
        "km": km,
        "bateria": bateria,
        "cuadro": bici.cuadro_material or "no indicado",
        "motor": bici.motor or "no indicado",
        "ano": bici.ano or "no indicado",
        "talla": bici.talla or "no indicada",
        "modalidad": modalidad,
        "garantia_txt": garantia_txt,
        "desglose_seguro": desglose_seguro,
        "linea_ubicacion": linea_ubicacion,
    }


def _enviar_telegram(
    token: str,
    chat_id: str,
    texto: str,
    silencioso: bool,
    disable_web_page_preview: bool,
    log_tag: str,
    log_ok: str,
) -> bool:
    """Envía un mensaje a Telegram Bot API con reintento sin Markdown ante error 400."""
    if not token or not chat_id:
        print(f"[{log_tag}] Credenciales no configuradas. Se omite el envío.")
        return False

    url = cfg.TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "Markdown",
        "disable_web_page_preview": disable_web_page_preview,
        "disable_notification": bool(silencioso),
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 400:
            # Fallback sin parse_mode por si algún carácter especial rompe Markdown v1
            payload.pop("parse_mode", None)
            resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        print(f"[{log_tag}] {log_ok}")
        return True
    except requests.RequestException as e:
        print(f"[{log_tag}] Error enviando mensaje: {e}")
        return False


def formatear_mensaje(
    bici,
    nota: float,
    desglose: str,
    precio_anterior: Optional[float] = None,
    seguimiento: Optional[dict] = None,
    aviso_top_repetido: bool = False,
    ranking_posicion: Optional[int] = None,
    es_rotacion_portal: bool = False,
    aviso_retorno_top1: bool = False,
) -> str:
    """
    Construye el mensaje Markdown para Telegram (S9).
    Incluye: título, precio (con alerta de bajada si aplica), nota destacada 🔥,
    kilómetros, batería, cuadro, recorrido de suspensión, seguimiento en stock,
    desglose de la nota y enlace directo.
    Si aviso_top_repetido es True, antepone un aviso claro de que el Top 3 no varió
    y se expone la siguiente alternativa disponible.
    """
    c = _campos_ficha_bici(bici, desglose)
    km = c["km"]
    bateria = c["bateria"]
    cuadro = c["cuadro"]
    motor = c["motor"]
    ano = c["ano"]
    talla = c["talla"]
    modalidad = c["modalidad"]
    garantia_txt = c["garantia_txt"]
    desglose_seguro = c["desglose_seguro"]

    precio_ref = precio_anterior
    if precio_ref is None and seguimiento and seguimiento.get("precio_inicial"):
        p_ini = float(seguimiento["precio_inicial"])
        if p_ini > bici.precio:
            precio_ref = p_ini

    es_bajada = precio_ref is not None and bici.precio < precio_ref
    es_vigilancia = bool(seguimiento and seguimiento.get("entrada_desde_vigilancia"))

    # Detección de Mega Chollo: solo si tiene >= 50% de descuento vs PVP original Y nota pericial >= 9.0
    pvp_orig = getattr(bici, "pvp_original", None)
    es_mega = es_mega_chollo(bici, nota)
    pct_dto_pvp = 0.0
    ahorro_pvp = 0.0
    if pvp_orig and pvp_orig > bici.precio > 0:
        pct_dto_pvp = ((pvp_orig - bici.precio) / pvp_orig) * 100.0
        ahorro_pvp = pvp_orig - bici.precio

    if es_vigilancia and es_bajada:
        ahorro = precio_ref - bici.precio
        linea_precio = f"💰 Precio: *{bici.precio:.0f} €* (Antes: ~{precio_ref:.0f} €~ | 🚨 Ahorro: *-{ahorro:.0f} €*)"
        if es_mega:
            cabecera = f"🚨💥 *¡MEGA CHOLLO + ENTRADA DE VIGILANCIA! (-{pct_dto_pvp:.0f}% vs PVP)*"
        else:
            cabecera = "🚨 *¡ENTRADA DESDE ZONA DE VIGILANCIA! BAJADA DE PRECIO DETECTADA*"
    elif es_bajada:
        ahorro = precio_ref - bici.precio
        linea_precio = f"💰 Precio: *{bici.precio:.0f} €* (Antes: ~{precio_ref:.0f} €~ | 📉 Ahorro: *-{ahorro:.0f} €*)"
        if es_mega:
            cabecera = f"💥📉 *¡MEGA CHOLLO + BAJADA DE PRECIO! (-{pct_dto_pvp:.0f}% vs PVP)*"
        else:
            cabecera = "📉 *¡BAJADA DE PRECIO DETECTADA! Oportunidad e-MTB*"
    elif es_mega:
        linea_precio = f"💰 Precio: *{bici.precio:.0f} €*"
        cabecera = f"💥🏷️ *¡MEGA CHOLLO e-MTB DETECTADO! (-{pct_dto_pvp:.0f}% vs PVP)*"
    else:
        linea_precio = f"💰 Precio: *{bici.precio} €*"
        cabecera = "🚵‍♂️ *Nueva oportunidad de e-MTB encontrada*"

    linea_pvp = ""
    if pvp_orig and pvp_orig > bici.precio:
        badge_chollo = "💥 *MEGA CHOLLO* " if es_mega else ""
        linea_pvp = f"🏷️ PVP Original: ~{pvp_orig:.0f} €~ ({badge_chollo}*-{pct_dto_pvp:.0f}%* | Ahorro: *-{ahorro_pvp:.0f} €*)\n"

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

    banner_repetido = ""
    if aviso_top_repetido and es_rotacion_portal:
        banner_repetido = (
            f"🔄 *#1 de {bici.sitio} sin cambios respecto al análisis anterior*\n"
            f"💡 _Exponiendo alternativa #2 de {bici.sitio}:_\n\n"
        )
    elif aviso_top_repetido:
        pos_txt = f" #{ranking_posicion}" if ranking_posicion is not None else ""
        banner_repetido = (
            f"🔄 *Top 3 sin cambios respecto al análisis anterior*\n"
            f"💡 _Exponiendo siguiente mejor alternativa{pos_txt} del catálogo:_\n\n"
        )
    elif aviso_retorno_top1:
        banner_repetido = (
            f"🏆 *Confirmada #1 en {bici.sitio}*\n"
            f"💡 _Vuelve al primer puesto tras alternar al #2 (sigue siendo la mejor opción de {bici.sitio}):_\n\n"
        )

    mensaje = (
        f"{banner_repetido}"
        f"{cabecera}\n\n"
        f"*{bici.titulo}*\n"
        f"🏪 Tienda: {bici.sitio}\n"
        f"{c['linea_ubicacion']}"
        f"{linea_precio}\n"
        f"{linea_pvp}"
        f"🔥 Nota de Oportunidad: *{nota}/10*\n\n"
        f"📏 Talla: {talla}\n"
        f"⚙️ Modalidad: {modalidad}\n"
        f"⚖️ Peso: {bici.peso_kg if bici.peso_kg else 'no indicado'} kg\n"
        f"🔋 Batería: {bateria}\n"
        f"🛞 Cuadro: {cuadro}\n"
        f"⚡ Motor: {motor}\n"
        f"📅 Año: {ano}\n"
        f"🛣️ Kilómetros: {km}\n"
        f"🛡️ Garantía: {garantia_txt}\n"
        f"{linea_seguimiento}\n"
        f"_Valoración técnica (Perito Escéptico / 5 ejes):_\n{desglose_seguro}\n\n"
        f"🔗 [Enlace directo de compra]({bici.url})"
    )
    return mensaje


def enviar(
    bici,
    nota: float,
    desglose: str,
    precio_anterior: Optional[float] = None,
    seguimiento: Optional[dict] = None,
    silencioso: Optional[bool] = None,
    aviso_top_repetido: bool = False,
    ranking_posicion: Optional[int] = None,
    es_rotacion_portal: bool = False,
    aviso_retorno_top1: bool = False,
) -> bool:
    """
    Envía el mensaje a Telegram. Devuelve True si tuvo éxito.
    Maneja excepciones de red para no caer la ejecución diaria (S13).
    Si silencioso es None, silencia automáticamente las ofertas normales (disable_notification=True)
    y envía con sonido prioritario (disable_notification=False) únicamente los Mega Chollos (TODO 3).
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
        aviso_top_repetido=aviso_top_repetido,
        ranking_posicion=ranking_posicion,
        es_rotacion_portal=es_rotacion_portal,
        aviso_retorno_top1=aviso_retorno_top1,
    )

    es_mega = es_mega_chollo(bici, nota)
    if silencioso is None:
        if getattr(cfg, "TELEGRAM_SILENCIAR_OFERTAS_NORMALES", True):
            silencioso = not es_mega
        else:
            silencioso = False

    modo_txt = "silencioso" if silencioso else "prioritario/sonoro"
    return _enviar_telegram(
        token=cfg.TELEGRAM_BOT_TOKEN,
        chat_id=cfg.TELEGRAM_CHAT_ID,
        texto=texto,
        silencioso=bool(silencioso),
        disable_web_page_preview=False,
        log_tag="Telegram",
        log_ok=f"Enviado ({modo_txt}): {bici.resumen_corto()}",
    )


def formatear_mensaje_black_friday(
    bici,
    nota_bf: float,
    descuento_pct: Optional[float],
    etiqueta_estado: str,
    desglose: str,
    precio_anterior: Optional[float] = None,
) -> str:
    """Construye la alerta prioritaria de oportunidades exclusivas Black Friday (nuevas / exposición)."""
    c = _campos_ficha_bici(bici, desglose)
    pvp_orig = getattr(bici, "pvp_original", None)
    dto_real = descuento_pct
    if dto_real is None and pvp_orig and pvp_orig > bici.precio > 0:
        dto_real = ((pvp_orig - bici.precio) / pvp_orig) * 100.0

    es_bajada = precio_anterior is not None and bici.precio < precio_anterior
    if es_bajada:
        ahorro_bajada = precio_anterior - bici.precio
        linea_precio = f"💰 Precio Black Friday: *{bici.precio:.0f} €* (Antes: ~{precio_anterior:.0f} €~ | 📉 *-{ahorro_bajada:.0f} €*)"
    else:
        linea_precio = f"💰 Precio Black Friday: *{bici.precio:.0f} €*"

    linea_pvp = ""
    if pvp_orig and pvp_orig > bici.precio and dto_real is not None:
        ahorro_pvp = pvp_orig - bici.precio
        linea_pvp = f"🏷️ PVP Original: ~{pvp_orig:.0f} €~ (*-{dto_real:.0f}% DTO* | Ahorro: *-{ahorro_pvp:.0f} €*)\n"

    cabecera = "🔥⚡ *¡CHOLLO EXCLUSIVO BLACK FRIDAY!* ⚡🔥"
    if dto_real is not None:
        cabecera = f"🔥⚡ *¡BLACK FRIDAY EXCLUSIVO (-{dto_real:.0f}% PVP)!* ⚡🔥"

    nota_extender = ""
    if bici.bateria_wh is not None and bici.bateria_wh < cfg.BATERIA_MIN_WH:
        nota_extender = (
            f"💡 _Extender +210 Wh (~450 €):_ *~{bici.bateria_wh + 210} Wh* totales dentro de tope (~{bici.precio + 450:.0f} €)\n"
        )

    mensaje = (
        f"{cabecera}\n\n"
        f"🆕 Estado: *{etiqueta_estado}*\n"
        f"*{bici.titulo}*\n"
        f"🏪 Tienda: {bici.sitio}\n"
        f"{c['linea_ubicacion']}"
        f"{linea_precio}\n"
        f"{linea_pvp}"
        f"{nota_extender}"
        f"🏆 Índice Black Friday: *{nota_bf}/10*\n\n"
        f"📏 Talla: {c['talla']}\n"
        f"⚙️ Modalidad: {c['modalidad']}\n"
        f"⚖️ Peso real est.: {bici.peso_kg if bici.peso_kg else 'no indicado'} kg\n"
        f"🔋 Batería: {c['bateria']}\n"
        f"🛞 Cuadro: {c['cuadro']}\n"
        f"⚡ Motor: {c['motor']}\n"
        f"📅 Año: {c['ano']}\n"
        f"🛣️ Kilómetros: {c['km']}\n"
        f"🛡️ Garantía: {c['garantia_txt']}\n\n"
        f"_Auditoría Black Friday (Perito Escéptico):_\n{c['desglose_seguro']}\n\n"
        f"🔗 [Ver oferta exclusiva]({bici.url})"
    )
    return mensaje


def enviar_black_friday(
    bici,
    nota_bf: float,
    descuento_pct: Optional[float],
    etiqueta_estado: str,
    desglose: str,
    precio_anterior: Optional[float] = None,
    silencioso: bool = False,
) -> bool:
    """Envía una oferta exclusiva Black Friday al segundo bot/chat de Telegram configurado."""
    token_bf = getattr(cfg, "TELEGRAM_BOT_TOKEN_BLACK_FRIDAY", "")
    chat_bf = getattr(cfg, "TELEGRAM_CHAT_ID_BLACK_FRIDAY", "") or getattr(cfg, "TELEGRAM_CHAT_ID", "")
    texto = formatear_mensaje_black_friday(
        bici=bici,
        nota_bf=nota_bf,
        descuento_pct=descuento_pct,
        etiqueta_estado=etiqueta_estado,
        desglose=desglose,
        precio_anterior=precio_anterior,
    )
    return _enviar_telegram(
        token=token_bf,
        chat_id=chat_bf,
        texto=texto,
        silencioso=silencioso,
        disable_web_page_preview=False,
        log_tag="Telegram/BlackFriday",
        log_ok=f"Enviado exclusivo: {bici.resumen_corto()}",
    )


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
    mega_chollos = resumen.get("mega_chollos", 0)
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

    linea_mega = f"  • Mega Chollos (>50% dto y Nota >= 9.0): *{mega_chollos}* 💥\n" if mega_chollos > 0 else ""
    bf_notif = resumen.get("black_friday_notificadas", 0)
    linea_bf = f"  • ⚡ Black Friday (Black Bike Beast): *{bf_notif}* enviada(s)\n" if bf_notif > 0 else ""

    linea_rotacion = ""
    portales_rot = resumen.get("portales_rotados") or []
    portales_ret = resumen.get("portales_retorno_top1") or []
    if portales_rot:
        linea_rotacion += f"  • 🔄 Alternativa #2 (misma #1): {', '.join(portales_rot)}\n"
    if portales_ret:
        linea_rotacion += f"  • 🏆 Retorno a #1 confirmada: {', '.join(portales_ret)}\n"
    if not linea_rotacion and resumen.get("top_repetido"):
        off = resumen.get("offset_usado", 3)
        cant_rot = resumen.get("notificadas", 3)
        linea_rotacion = f"  • 🔄 Rotación activa: Top 3 idéntico (exponiendo #{off + 1} a #{off + cant_rot})\n"

    mensaje = (
        f"💓 *Heartbeat Buscador e-MTB* — Pulso Operativo\n"
        f"📅 `{fecha_hora}` | ⏱️ `{duracion}s`\n\n"
        f"🏪 *Portales rastreados ({total_proc} bicicletas)*:\n"
        f"{bloque_portales}\n\n"
        f"📊 *Diagnóstico del runner*:\n"
        f"  • Candidatas aptas analizadas: *{aptas}*\n"
        f"  • Alertas prioritarias: {texto_notif}\n"
        f"{linea_rotacion}"
        f"{linea_mega}"
        f"{linea_bf}"
        f"  • Radar activo en seguimiento: *{en_catalogo}* unidades\n"
        f"  • Zona de vigilancia (2.900-3.500 €): *{en_vigilancia}* unidades\n\n"
        f"{estado}"
    )
    return mensaje


def enviar_heartbeat(resumen: dict) -> bool:
    """
    Envía el mensaje de heartbeat a Telegram. Devuelve True si tuvo éxito.
    Se envía con disable_notification=True para diagnóstico silencioso que no molesta al usuario.
    """
    texto = formatear_heartbeat(resumen)
    return _enviar_telegram(
        token=cfg.TELEGRAM_BOT_TOKEN,
        chat_id=cfg.TELEGRAM_CHAT_ID,
        texto=texto,
        silencioso=True,
        disable_web_page_preview=True,
        log_tag="Telegram/Heartbeat",
        log_ok="Heartbeat enviado exitosamente.",
    )


def formatear_heartbeat_black_friday(resumen: dict) -> str:
    """Construye el pulso operativo Markdown para el segundo bot (Black Friday)."""
    fecha_hora = resumen.get("fecha_hora", "")
    duracion = resumen.get("duracion_seg", 0.0)
    total_proc = resumen.get("total_procesadas", 0)
    bf_encontradas = resumen.get("black_friday_encontradas", 0)
    bf_notificadas = resumen.get("black_friday_notificadas", 0)
    estado = resumen.get("estado", "🟢 Runner operativo")

    km_max = getattr(cfg, "KM_MAX_BLACK_FRIDAY", 50)
    peso_max = getattr(cfg, "PESO_DESCARTE_KG", 21.0)
    bat_min = getattr(cfg, "BATERIA_MIN_WH", 500)
    precio_max = getattr(cfg, "PRECIO_MAX_BLACK_FRIDAY_EUR", 3500)
    dto_min = getattr(cfg, "DESCUENTO_MIN_BLACK_FRIDAY_PCT", 35.0)

    if bf_notificadas > 0:
        res_linea = f"🔥 Chollos exclusivos enviados: *{bf_notificadas}* (elegibles: *{bf_encontradas}*)"
    elif resumen.get("black_friday_respaldo_enviado"):
        res_linea = "📊 *0* en presupuesto <= 3.500 € — enviado *Informe Top 3 más interesantes fuera de tope*"
    elif bf_encontradas > 0:
        res_linea = f"✅ *{bf_encontradas}* elegible(s) ya notificada(s) previamente (sin rebaja extra)"
    else:
        res_linea = "🔍 *0* bicis cumplen hoy todos los criterios estrictos (sin alertas nuevas)"

    return (
        f"⚡ *Black Bike Beast — Pulso Black Friday*\n"
        f"📅 `{fecha_hora}` | ⏱️ `{duracion}s`\n\n"
        f"🏪 Bicis analizadas en catálogo: *{total_proc}*\n"
        f"🎯 Filtros activos: *XC <= {getattr(cfg, 'RECORRIDO_MAX_XC_MM', 130)} mm*, "
        f"nuevas/expo (`<= {km_max} km`), Talla `{cfg.TALLA_OBJETIVO}`, "
        f"`< {peso_max:.1f} kg`, `>= {bat_min} Wh` (o Fazua 420+ Wh c/ margen ext.), `<= {precio_max} €`, `>= -{dto_min:.0f}% PVP`\n\n"
        f"{res_linea}\n\n"
        f"{estado}"
    )


def enviar_heartbeat_black_friday(resumen: dict) -> bool:
    """Envía el heartbeat silencioso de Black Friday al segundo bot si está configurado."""
    token_bf = getattr(cfg, "TELEGRAM_BOT_TOKEN_BLACK_FRIDAY", "")
    chat_bf = getattr(cfg, "TELEGRAM_CHAT_ID_BLACK_FRIDAY", "") or getattr(cfg, "TELEGRAM_CHAT_ID", "")
    if not token_bf or not chat_bf:
        return False
    texto = formatear_heartbeat_black_friday(resumen)
    return _enviar_telegram(
        token=token_bf,
        chat_id=chat_bf,
        texto=texto,
        silencioso=True,
        disable_web_page_preview=True,
        log_tag="Telegram/BlackFridayHeartbeat",
        log_ok="Heartbeat Black Friday enviado exitosamente.",
    )


def formatear_informe_respaldo_black_friday(items: list) -> str:
    """
    Formatea un informe consolidado con el Top N (hasta 3) de bicis ligeras más
    interesantes encontradas cuando 0 unidades cumplen el tope estricto <= 3.500 €.
    Cada elemento es (bici, dto_pct, nota_perito, motivo_fuera).
    """
    bloques = []
    for idx, (bici, dto_pct, nota_ref, motivo_fuera) in enumerate(items, 1):
        pvp_orig = getattr(bici, "pvp_original", None)
        dto_txt = f"*-{dto_pct:.1f}% PVP*" if dto_pct is not None else ""
        if pvp_orig and pvp_orig > bici.precio:
            ahorro = pvp_orig - bici.precio
            linea_pvp = f" (~{pvp_orig:.0f} €~ | {dto_txt} | Ahorro *-{ahorro:.0f} €*)"
        else:
            linea_pvp = ""

        peso_tag = "~" if getattr(bici, "_peso_estimado", False) else ""
        peso_txt = f"{peso_tag}{bici.peso_kg:.1f} kg" if bici.peso_kg is not None else "peso n/d"
        km_txt = "NUEVA 0 km" if bici.km == 0 else (f"EXPO {bici.km} km" if (bici.km or 0) <= 50 else f"{bici.km} km")
        motivo_seguro = str(motivo_fuera).replace("_", "-").replace("*", "").replace("`", "'")

        bloques.append(
            f"*{idx}. {bici.titulo}* ({bici.sitio})\n"
            f"💰 *{bici.precio:.0f} €*{linea_pvp}\n"
            f"⚙️ {km_txt} | ⚖️ {peso_txt} | 🔋 {bici.bateria_wh} Wh | ⚡ {bici.motor or 'n/d'} | 📏 {bici.talla}\n"
            f"⚠️ _Fuera de filtro:_ {motivo_seguro}\n"
            f"🔗 [Ver oferta en {bici.sitio}]({bici.url})"
        )

    cuerpo = "\n\n".join(bloques)
    return (
        f"📊⚡ *Black Bike Beast — Top {len(items)} XC Puro Más Interesantes (Fuera de Tope / Criterio)*\n"
        f"_Solo e-MTB XC/Downcountry (<= {getattr(cfg, 'RECORRIDO_MAX_XC_MM', 130)} mm), Talla {cfg.TALLA_OBJETIVO}, doble suspensión y < 21 kg. "
        f"Ninguna unidad cumplió hoy todos los límites estrictos (<= 3.500 €, km <= 50, >= 500 Wh, -35% PVP):_\n\n"
        f"{cuerpo}"
    )


def enviar_informe_respaldo_black_friday(items: list, silencioso: bool = False) -> bool:
    """Envía al segundo bot el Top 3 de bicicletas más interesantes fuera de presupuesto."""
    if not items:
        return False
    token_bf = getattr(cfg, "TELEGRAM_BOT_TOKEN_BLACK_FRIDAY", "")
    chat_bf = getattr(cfg, "TELEGRAM_CHAT_ID_BLACK_FRIDAY", "") or getattr(cfg, "TELEGRAM_CHAT_ID", "")
    if not token_bf or not chat_bf:
        return False
    texto = formatear_informe_respaldo_black_friday(items)
    return _enviar_telegram(
        token=token_bf,
        chat_id=chat_bf,
        texto=texto,
        silencioso=silencioso,
        disable_web_page_preview=True,
        log_tag="Telegram/BlackFridayTop3",
        log_ok=f"Informe Top {len(items)} de respaldo enviado exitosamente.",
    )
