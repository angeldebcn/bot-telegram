# -*- coding: utf-8 -*-
"""
keyboards.py
Todos los teclados de botones (inline) del bot.
Cada botón lleva un 'callback_data' tipo  "seccion:accion:dato".
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Listas fijas reutilizadas en varios sitios.
REGIONES = ["España", "Cono Sur", "Caribe", "Andina", "México"]
CATEGORIAS = ["ES", "Latam", "Trans", "Findom"]
DIAS = [("Lun", "mon"), ("Mar", "tue"), ("Mié", "wed"), ("Jue", "thu"),
        ("Vie", "fri"), ("Sáb", "sat"), ("Dom", "sun")]


def _b(builder: InlineKeyboardBuilder, ancho: int = 2) -> InlineKeyboardMarkup:
    builder.adjust(ancho)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# MENÚ PRINCIPAL
# ---------------------------------------------------------------------------
def menu_principal() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📡 Canales", callback_data="menu:channels")
    b.button(text="📢 Promos", callback_data="menu:promos")
    b.button(text="⚡ Enviar ahora", callback_data="menu:sendnow")
    b.button(text="⏰ Programar envío", callback_data="menu:schedule")
    b.button(text="🚀 Campañas auto", callback_data="menu:campaigns")
    b.button(text="🤝 Alianzas", callback_data="menu:alliances")
    b.button(text="🔁 Repost", callback_data="menu:repost")
    b.button(text="📅 Agenda", callback_data="menu:agenda")
    b.button(text="🧾 Historial", callback_data="menu:history")
    b.button(text="📊 Estadísticas", callback_data="menu:stats")
    b.button(text="⚙️ Ajustes", callback_data="menu:settings")
    b.button(text="❓ Ayuda y comandos", callback_data="menu:help")
    b.adjust(2, 2, 2, 2, 2, 2, 1)
    return b.as_markup()


def volver(destino: str = "menu:home") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Volver", callback_data=destino)
    return b.as_markup()


# ---------------------------------------------------------------------------
# CANALES
# ---------------------------------------------------------------------------
def menu_canales() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Añadir canal", callback_data="ch:add")
    b.button(text="📥 Importar lista", callback_data="ch:bulk")
    b.button(text="📋 Ver canales", callback_data="ch:list:0")
    b.button(text="🔍 Buscar canal", callback_data="ch:search")
    b.button(text="🏷️ Etiquetar", callback_data="ch:taglist:0")
    b.button(text="🗓️ Ver parrilla", callback_data="ch:grid")
    b.button(text="🛂 Verificar permisos", callback_data="ch:verify")
    b.button(text="🧹 Limpiar duplicados", callback_data="ch:dedup")
    b.button(text="🚷 Expulsados", callback_data="ch:removed")
    b.button(text="📶 Suscriptores", callback_data="ch:subs")
    b.button(text="⬅️ Volver", callback_data="menu:home")
    b.adjust(2, 2, 2, 2, 2, 1)
    return b.as_markup()


def expulsados_acciones(hay: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if hay:
        b.button(text="🧽 Limpiar lista de expulsados",
                 callback_data="ch:removed_clear")
    b.button(text="⬅️ Volver", callback_data="menu:channels")
    b.adjust(1)
    return b.as_markup()


def lista_canales(canales: list, pagina: int, accion: str,
                  por_pagina: int = 8) -> InlineKeyboardMarkup:
    """Lista paginada de canales. accion = 'del' o 'tag'."""
    b = InlineKeyboardBuilder()
    ini = pagina * por_pagina
    trozo = canales[ini:ini + por_pagina]
    for ch in trozo:
        marca = "✅" if ch["is_admin"] else "⚠️"
        nombre = ch["title"] or ch["username"] or str(ch["chat_id"])
        # Si tiene bloque asignado, lo mostramos: ayuda a distinguir
        # canales con el mismo nombre.
        sufijo = f" · B{ch['slot']}" if ch["slot"] else ""
        b.button(
            text=f"{marca} {nombre[:24]}{sufijo}",
            callback_data=f"ch:{accion}:{ch['chat_id']}",
        )
    b.adjust(1)
    nav = InlineKeyboardBuilder()
    if pagina > 0:
        nav.button(text="⬅️", callback_data=f"ch:{accion}list:{pagina-1}"
                   if accion == "tag" else f"ch:list:{pagina-1}")
    if ini + por_pagina < len(canales):
        nav.button(text="➡️", callback_data=f"ch:{accion}list:{pagina+1}"
                   if accion == "tag" else f"ch:list:{pagina+1}")
    nav.button(text="⬅️ Volver", callback_data="menu:channels")
    nav.adjust(3)
    return InlineKeyboardMarkup(
        inline_keyboard=b.as_markup().inline_keyboard
        + nav.as_markup().inline_keyboard
    )


def ficha_canal(chat_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🏷️ Región", callback_data=f"tag:region:{chat_id}")
    b.button(text="🏷️ Categoría", callback_data=f"tag:cat:{chat_id}")
    b.button(text="🔁 Modo repost", callback_data=f"rp:mode:{chat_id}")
    b.button(text="👤 Propietaria", callback_data=f"rp:owner:{chat_id}")
    b.button(text="🔀 Mover de bloque", callback_data=f"ch:move:{chat_id}")
    b.button(text="🧵 Hilos del foro", callback_data=f"ch:topics:{chat_id}")
    b.button(text="🗑️ Eliminar canal", callback_data=f"ch:del:{chat_id}")
    b.button(text="⬅️ Volver", callback_data="ch:taglist:0")
    b.adjust(2, 2, 2, 1, 1)
    return b.as_markup()


def gestion_topics(chat_id: int, tiene: bool, prefijo: str = "ch"
                   ) -> InlineKeyboardMarkup:
    """Menú para gestionar los hilos de un canal/grupo o alianza."""
    b = InlineKeyboardBuilder()
    b.button(text="➕ Añadir hilo(s)", callback_data=f"{prefijo}top:add:{chat_id}")
    if tiene:
        b.button(text="✏️ Reemplazar todos",
                 callback_data=f"{prefijo}top:set:{chat_id}")
        b.button(text="🗑️ Quitar todos",
                 callback_data=f"{prefijo}top:clear:{chat_id}")
    if prefijo == "ch":
        b.button(text="⬅️ Volver", callback_data=f"ch:open:{chat_id}")
    else:
        b.button(text="⬅️ Volver", callback_data=f"ally:view:{chat_id}")
    b.adjust(1)
    return b.as_markup()


def elegir_region(chat_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for r in REGIONES:
        b.button(text=r, callback_data=f"setregion:{chat_id}:{r}")
    b.button(text="⬅️ Volver", callback_data=f"ch:tag:{chat_id}")
    b.adjust(2)
    return b.as_markup()


def elegir_categoria(chat_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in CATEGORIAS:
        b.button(text=c, callback_data=f"setcat:{chat_id}:{c}")
    b.button(text="⬅️ Volver", callback_data=f"ch:tag:{chat_id}")
    b.adjust(2)
    return b.as_markup()


# ---------------------------------------------------------------------------
# PROMOS
# ---------------------------------------------------------------------------
def menu_promos(promos: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Nueva promo", callback_data="promo:new")
    for p in promos:
        b.button(text=f"#{p['id']} · {p['name']}",
                 callback_data=f"promo:view:{p['id']}")
    b.button(text="⬅️ Volver", callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()


def ficha_promo(promo_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="👁️ Previsualizar", callback_data=f"promo:prev:{promo_id}")
    b.button(text="✏️ Editar promo", callback_data=f"promo:edit:{promo_id}")
    b.button(text="🏷️ Cambiar nombre", callback_data=f"promo:rename:{promo_id}")
    b.button(text="🗑️ Eliminar", callback_data=f"promo:del:{promo_id}")
    b.button(text="⬅️ Volver", callback_data="menu:promos")
    b.adjust(1, 2, 1, 1)
    return b.as_markup()


# ---------------------------------------------------------------------------
# OBJETIVOS (a quién enviar)  -  reutilizable
# ---------------------------------------------------------------------------
def elegir_objetivo(prefijo: str) -> InlineKeyboardMarkup:
    """prefijo identifica el flujo, ej 'sendtarget' o 'camp'."""
    b = InlineKeyboardBuilder()
    b.button(text="🌍 TODOS los canales", callback_data=f"{prefijo}:all")
    for r in REGIONES:
        b.button(text=f"📍 {r}", callback_data=f"{prefijo}:region:{r}")
    for c in CATEGORIAS:
        b.button(text=f"🏷️ {c}", callback_data=f"{prefijo}:cat:{c}")
    b.button(text="⬅️ Volver", callback_data="menu:home")
    b.adjust(1, 2, 2, 2, 2, 1)
    return b.as_markup()


def elegir_promo(prefijo: str, promos: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in promos:
        b.button(text=f"#{p['id']} · {p['name']}",
                 callback_data=f"{prefijo}:{p['id']}")
    b.button(text="⬅️ Volver", callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()


def elegir_duracion(prefijo: str) -> InlineKeyboardMarkup:
    """Duración hasta el autoborrado. Valores predeterminados + personalizado."""
    b = InlineKeyboardBuilder()
    for horas, etq in [(6, "6 h"), (12, "12 h"), (24, "24 h"),
                       (48, "48 h"), (72, "72 h")]:
        b.button(text=etq, callback_data=f"{prefijo}:{horas}")
    b.button(text="♾️ No borrar", callback_data=f"{prefijo}:0")
    b.button(text="✏️ Personalizado", callback_data=f"{prefijo}:custom")
    b.adjust(3, 2, 2)
    return b.as_markup()


def modo_envio() -> InlineKeyboardMarkup:
    """Enviar de golpe o escalonado por lotes."""
    b = InlineKeyboardBuilder()
    b.button(text="💥 Todo de golpe", callback_data="sendmode:instant")
    b.button(text="🪜 Escalonado (lotes)", callback_data="sendmode:staggered")
    b.button(text="⬅️ Volver", callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()


def confirmar(prefijo: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Confirmar y enviar", callback_data=f"{prefijo}:yes")
    b.button(text="❌ Cancelar", callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()


def confirmar_borrado(prefijo: str, item_id, volver_a: str
                      ) -> InlineKeyboardMarkup:
    """Confirmación antes de eliminar algo. prefijo:yes:id o vuelve atrás."""
    b = InlineKeyboardBuilder()
    b.button(text="🗑️ Sí, eliminar", callback_data=f"{prefijo}:yes:{item_id}")
    b.button(text="↩️ No, cancelar", callback_data=volver_a)
    b.adjust(1)
    return b.as_markup()


# ---------------------------------------------------------------------------
# CAMPAÑAS
# ---------------------------------------------------------------------------
def menu_campanas(campanas: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Nueva campaña", callback_data="camp:new")
    for c in campanas:
        estado = "🟢" if c["active"] else "🔴"
        b.button(text=f"{estado} {c['name']}",
                 callback_data=f"camp:view:{c['id']}")
    b.button(text="⬅️ Volver", callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()


def ficha_campana(camp_id: int, activa: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if activa:
        b.button(text="⏸️ Pausar", callback_data=f"camp:off:{camp_id}")
    else:
        b.button(text="▶️ Activar", callback_data=f"camp:on:{camp_id}")
    b.button(text="✏️ Editar", callback_data=f"camp:edit:{camp_id}")
    b.button(text="🧪 Ejecutar ahora", callback_data=f"camp:run:{camp_id}")
    b.button(text="📑 Duplicar", callback_data=f"camp:dup:{camp_id}")
    b.button(text="🗑️ Eliminar", callback_data=f"camp:del:{camp_id}")
    b.button(text="⬅️ Volver", callback_data="menu:campaigns")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


def ejecutar_campana(camp_id: int) -> InlineKeyboardMarkup:
    """Opciones para lanzar una campaña manualmente."""
    b = InlineKeyboardBuilder()
    b.button(text="🚀 Desde el principio (bloque 1)",
             callback_data=f"crun:full:{camp_id}")
    b.button(text="🔢 Desde un bloque concreto",
             callback_data=f"crun:from:{camp_id}")
    b.button(text="🧹 Reempezar limpio (borra lo enviado)",
             callback_data=f"crun:clean:{camp_id}")
    b.button(text="⬅️ Volver", callback_data=f"camp:view:{camp_id}")
    b.adjust(1)
    return b.as_markup()


def editar_campana(camp_id: int) -> InlineKeyboardMarkup:
    """Menú para editar cada campo de una campaña."""
    b = InlineKeyboardBuilder()
    b.button(text="🏷️ Nombre", callback_data=f"cedit:name:{camp_id}")
    b.button(text="📍 Región", callback_data=f"cedit:region:{camp_id}")
    b.button(text="🗂️ Categoría", callback_data=f"cedit:cat:{camp_id}")
    b.button(text="📢 Promos", callback_data=f"cedit:promos:{camp_id}")
    b.button(text="🔄 Rotación", callback_data=f"cedit:rot:{camp_id}")
    b.button(text="📆 Días", callback_data=f"cedit:days:{camp_id}")
    b.button(text="⏰ Hora", callback_data=f"cedit:hour:{camp_id}")
    b.button(text="👥 Canales/bloque", callback_data=f"cedit:batch:{camp_id}")
    b.button(text="⏱️ Minutos/bloque", callback_data=f"cedit:interval:{camp_id}")
    b.button(text="🗑️ Autoborrado", callback_data=f"cedit:autodel:{camp_id}")
    b.button(text="⬅️ Volver a la campaña",
             callback_data=f"camp:view:{camp_id}")
    b.adjust(2, 2, 2, 2, 1, 1)
    return b.as_markup()


def editar_region_camp() -> InlineKeyboardMarkup:
    """Regiones para reasignar a una campaña (id va en el estado)."""
    b = InlineKeyboardBuilder()
    b.button(text="🌍 Todas", callback_data="csetreg:Todas")
    for r in REGIONES:
        b.button(text=r, callback_data=f"csetreg:{r}")
    b.adjust(1, 2)
    return b.as_markup()


def editar_categoria_camp() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🌍 Todas", callback_data="csetcat:Todas")
    for c in CATEGORIAS:
        b.button(text=c, callback_data=f"csetcat:{c}")
    b.adjust(1, 2)
    return b.as_markup()


def multi_promos(seleccion: list, promos: list,
                 prefijo: str = "campromo") -> InlineKeyboardMarkup:
    """Selección múltiple de promos (con rotación)."""
    b = InlineKeyboardBuilder()
    for p in promos:
        marca = "✅" if p["id"] in seleccion else "▫️"
        b.button(text=f"{marca} #{p['id']} {p['name']}",
                 callback_data=f"{prefijo}:toggle:{p['id']}")
    b.button(text="➡️ Continuar", callback_data=f"{prefijo}:done")
    b.button(text="❌ Cancelar", callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()


def multi_dias(seleccion: list, prefijo: str = "campday") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for etq, cod in DIAS:
        marca = "✅" if cod in seleccion else "▫️"
        b.button(text=f"{marca} {etq}",
                 callback_data=f"{prefijo}:toggle:{cod}")
    b.button(text="➡️ Continuar", callback_data=f"{prefijo}:done")
    b.adjust(4, 3, 1)
    return b.as_markup()


def opciones_numero(prefijo: str, valores: list) -> InlineKeyboardMarkup:
    """Botones con números predeterminados + personalizado."""
    b = InlineKeyboardBuilder()
    for v in valores:
        b.button(text=str(v), callback_data=f"{prefijo}:{v}")
    b.button(text="✏️ Personalizado", callback_data=f"{prefijo}:custom")
    b.adjust(3)
    return b.as_markup()


def region_camp() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🌍 Todas", callback_data="campreg:Todas")
    for r in REGIONES:
        b.button(text=r, callback_data=f"campreg:{r}")
    b.adjust(1, 2)
    return b.as_markup()


def categoria_camp() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🌍 Todas", callback_data="campcat:Todas")
    for c in CATEGORIAS:
        b.button(text=c, callback_data=f"campcat:{c}")
    b.adjust(1, 2)
    return b.as_markup()


# ---------------------------------------------------------------------------
# AJUSTES
# ---------------------------------------------------------------------------
def menu_ajustes() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📡 Modo de difusión", callback_data="set:mode")
    b.button(text="🕙 Zona horaria", callback_data="set:tz")
    b.button(text="💾 Backup ahora", callback_data="set:backup")
    b.button(text="♻️ Restaurar backup", callback_data="set:restore")
    b.button(text="🔕 Avisos de bloque", callback_data="set:quiet")
    b.button(text="⏸️ Pausar TODO", callback_data="set:pauseall")
    b.button(text="▶️ Reanudar TODO", callback_data="set:resumeall")
    b.button(text="🧹 Borrar TODO ahora", callback_data="set:delall")
    b.button(text="⬅️ Volver", callback_data="menu:home")
    b.adjust(1, 1, 2, 1, 2, 1, 1)
    return b.as_markup()


def modo_difusion(actual: str) -> InlineKeyboardMarkup:
    """Elegir entre copiar y reenviar."""
    b = InlineKeyboardBuilder()
    copia = "✅ " if actual == "copiar" else ""
    reenv = "✅ " if actual == "reenviar" else ""
    b.button(text=f"{copia}📋 Copiar (sin etiqueta)",
             callback_data="setmode:copiar")
    b.button(text=f"{reenv}↪️ Reenviar (emojis premium)",
             callback_data="setmode:reenviar")
    b.button(text="⬅️ Volver", callback_data="menu:settings")
    b.adjust(1)
    return b.as_markup()


# ---------------------------------------------------------------------------
# REGIÓN DIRECTA DESDE EL AVISO "canal añadido"
# ---------------------------------------------------------------------------
def elegir_region_aviso(chat_id: int) -> InlineKeyboardMarkup:
    """Botones de región que aparecen en el aviso de canal detectado."""
    b = InlineKeyboardBuilder()
    for r in REGIONES:
        b.button(text=r, callback_data=f"avregion:{chat_id}:{r}")
    b.button(text="🤝 Es una alianza (sin región)",
             callback_data=f"avregion:{chat_id}:Alianza")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


def recomprobar_canal(chat_id: int) -> InlineKeyboardMarkup:
    """Botón para volver a comprobar los permisos de un canal."""
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Ya le di permisos — recomprobar",
             callback_data=f"ch:recheck:{chat_id}")
    return b.as_markup()


# ---------------------------------------------------------------------------
# PARRILLA / MOVER CANAL
# ---------------------------------------------------------------------------
def ver_parrilla_region() -> InlineKeyboardMarkup:
    """Elegir de qué región ver la parrilla."""
    b = InlineKeyboardBuilder()
    for r in REGIONES:
        b.button(text=f"📋 {r}", callback_data=f"grid:{r}")
    b.button(text="⬅️ Volver", callback_data="menu:channels")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


# ---------------------------------------------------------------------------
# ALIANZAS
# ---------------------------------------------------------------------------
def menu_alianzas(alianzas: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="➕ Nueva alianza", callback_data="ally:new")
    for a in alianzas:
        estado = "🟢" if a["active"] else "🔴"
        b.button(text=f"{estado} {a['name']}",
                 callback_data=f"ally:view:{a['id']}")
    b.button(text="⬅️ Volver", callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()


def ficha_alianza(ally_id: int, activa: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if activa:
        b.button(text="⏸️ Pausar", callback_data=f"ally:off:{ally_id}")
    else:
        b.button(text="▶️ Activar", callback_data=f"ally:on:{ally_id}")
    b.button(text="✏️ Editar", callback_data=f"ally:edit:{ally_id}")
    b.button(text="🧵 Hilos del foro", callback_data=f"ally:topics:{ally_id}")
    b.button(text="🧪 Publicar ahora", callback_data=f"ally:run:{ally_id}")
    b.button(text="📑 Duplicar", callback_data=f"ally:dup:{ally_id}")
    b.button(text="🗑️ Eliminar", callback_data=f"ally:del:{ally_id}")
    b.button(text="⬅️ Volver", callback_data="menu:alliances")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def editar_alianza(ally_id: int) -> InlineKeyboardMarkup:
    """Menú para editar cada campo de una alianza."""
    b = InlineKeyboardBuilder()
    b.button(text="🏷️ Nombre", callback_data=f"aedit:name:{ally_id}")
    b.button(text="📢 Promo", callback_data=f"aedit:promo:{ally_id}")
    b.button(text="🕙 Zona horaria", callback_data=f"aedit:tz:{ally_id}")
    b.button(text="📆 Días", callback_data=f"aedit:days:{ally_id}")
    b.button(text="⏰ Horas", callback_data=f"aedit:times:{ally_id}")
    b.button(text="🗑️ Autoborrado", callback_data=f"aedit:autodel:{ally_id}")
    b.button(text="⬅️ Volver a la alianza",
             callback_data=f"ally:view:{ally_id}")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()


def elegir_grupo_alianza(canales: list) -> InlineKeyboardMarkup:
    """Lista de canales/grupos para escoger el de la alianza."""
    b = InlineKeyboardBuilder()
    for ch in canales:
        nombre = ch["title"] or ch["username"] or str(ch["chat_id"])
        b.button(text=nombre[:32], callback_data=f"allygrp:{ch['chat_id']}")
    b.button(text="❌ Cancelar", callback_data="menu:home")
    b.adjust(1)
    return b.as_markup()


def tz_alianza() -> InlineKeyboardMarkup:
    """Zona horaria de una alianza (en qué hora se interpretan sus horas)."""
    b = InlineKeyboardBuilder()
    b.button(text="🇪🇸 Hora de España", callback_data="allytz:España")
    b.button(text="Cono Sur", callback_data="allytz:Cono Sur")
    b.button(text="Caribe", callback_data="allytz:Caribe")
    b.button(text="Andina", callback_data="allytz:Andina")
    b.button(text="México", callback_data="allytz:México")
    b.adjust(1, 2, 2)
    return b.as_markup()
