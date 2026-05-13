"""Strings en español."""

# === Inicio en privado ===
START_PRIVATE = (
    "🤖 <b>Bot de moderación multimedia premium</b>\n\n"
    "Aplico hasta 3 reglas configurables sobre las publicaciones de fotos/vídeos "
    "más filtros granulares por tipo de contenido (estilo GroupHelp):\n\n"
    "🔄 <b>Cola rotatoria</b>\n"
    "⏱️ <b>Cooldown</b>\n"
    "🖼️ <b>Anti-duplicado</b>\n"
    "🎯 <b>17 tipos de contenido filtrables</b>\n\n"
    "<b>Cómo usarme:</b>\n"
    "1️⃣ Añádeme a tu grupo.\n"
    "2️⃣ Hazme administrador con permisos para "
    "<b>eliminar mensajes</b>, <b>silenciar</b> y <b>banear</b>.\n"
    "3️⃣ Activa tu suscripción contactando @{owner}.\n"
    "4️⃣ Pulsa /menu para configurarme.\n\n"
    "💎 <b>Suscripción</b>: 5 €/mes por grupo\n"
    "💳 Pago vía Revolut a @{owner}\n\n"
    "Escribe /help para ver todos los comandos."
)

# === Inicio en grupo ===
START_GROUP = (
    "🤖 <b>Bot activo en este grupo</b>\n\n"
    "Pulsa /menu para configurarme (solo admins).\n"
    "Pulsa /help para ver todos los comandos."
)

START_GROUP_NOT_LICENSED = (
    "🤖 <b>Bot añadido pero NO activado</b>\n\n"
    "Este grupo no tiene suscripción activa. Mientras tanto el bot está en pausa "
    "y no aplicará ninguna regla.\n\n"
    "💎 Para activarme: 5 €/mes\n"
    "📞 Contacta @{owner}"
)

# === Errores ===
ERR_NOT_ADMIN = "❌ Solo los administradores pueden usar este comando."
ERR_NO_GROUP = "❌ Este comando solo funciona en grupos."
ERR_NO_PRIVATE = "❌ Este comando solo funciona en privado."
ERR_REPLY_NEEDED = (
    "❌ Responde al mensaje de la usuaria, o usa el comando con @username o su ID."
)
ERR_USER_NOT_FOUND = (
    "❌ No encuentro a esa usuaria. Pídele que escriba algo primero, "
    "o responde a un mensaje suyo, o usa su ID numérico."
)
ERR_NOT_LICENSED = (
    "⚠️ <b>Suscripción no activa</b>\n\n"
    "Este grupo no tiene una licencia activa. El bot está en pausa."
)

# === Alianzas ===
OK_ALIANZA_ADDED = "✅ {mention} añadida a las alianzas. Exenta de las 3 reglas y filtros."
OK_ALIANZA_REMOVED = "✅ {mention} retirada de las alianzas."
OK_ALIANZA_ALREADY = "ℹ️ {mention} ya estaba en alianzas."
OK_ALIANZA_NOT_FOUND = "ℹ️ {mention} no estaba en alianzas."
NO_ALIANZAS = "📋 No hay alianzas en este grupo."

# === Selector grupo en privado ===
SELECT_GROUP = (
    "🤖 <b>Selecciona el grupo a configurar</b>\n\n"
    "Estos son los grupos donde estoy presente y tú eres administrador:"
)

NO_GROUPS_PRIVATE = (
    "❌ Aún no tengo ningún grupo registrado.\n\n"
    "Añádeme a un grupo y vuelve a intentarlo.\n"
    "Para activar la suscripción contacta @{owner}."
)

NOT_ADMIN_ANYWHERE = (
    "❌ No eres administrador en ninguno de mis grupos.\n\n"
    "Si crees que debería tener acceso, contacta @{owner}."
)

# Mantener compatibilidad con código antiguo
MENU_NO_GROUPS = NO_GROUPS_PRIVATE
MENU_SELECT_GROUP = SELECT_GROUP
