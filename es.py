"""Strings en español."""

# === Inicio en privado (SOLO owner) ===
START_PRIVATE_OWNER = (
    "👑 <b>Panel de control — MALA MODERADOR</b>\n\n"
    "Bienvenido de vuelta. Este bot gestiona la moderación y las sanciones "
    "de toda la comunidad.\n\n"
    "⚙️ <code>/config</code> — Configurar roles de grupos y staff\n"
    "📋 <code>/lista</code> — Ver personas sancionadas\n"
    "🔎 <code>/buscar</code> — Buscar a una persona\n"
    "⏳ <code>/pendientes</code> — Reportes sin resolver\n"
    "📚 <code>/help</code> — Todos los comandos\n\n"
    "🛡️ Sistema de sanciones activo en toda la comunidad."
)

# (compatibilidad: algunos módulos viejos importan START_PRIVATE)
START_PRIVATE = START_PRIVATE_OWNER

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
