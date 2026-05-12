"""Strings en español."""

START_PRIVATE = (
    "🤖 <b>Bot de moderación multimedia</b>\n\n"
    "Soy un bot que aplica 3 reglas configurables en grupos:\n"
    "🔄 <b>Cola rotatoria</b> · ⏱️ <b>Cooldown</b> · 🖼️ <b>Anti-duplicado</b>\n\n"
    "<b>Cómo usarme:</b>\n"
    "1️⃣ Añádeme a tu grupo.\n"
    "2️⃣ Hazme administrador con permiso para <b>eliminar mensajes</b>.\n"
    "3️⃣ Pulsa /menu aquí o en el grupo para configurarme.\n\n"
    "Soy compatible con @GroupHelpBot — yo me ocupo de las 3 reglas, "
    "él del permiso individual con /free."
)

START_GROUP = (
    "🤖 Bot activado en este grupo.\n"
    "Pulsa /menu para configurarme (solo admins)."
)

ERR_NOT_ADMIN = "❌ Solo los administradores pueden usar este comando."
ERR_NO_GROUP = "❌ Este comando solo funciona en grupos."
ERR_NO_PRIVATE = "❌ Este comando solo funciona en privado."
ERR_REPLY_NEEDED = "❌ Responde al mensaje de la usuaria, o usa el comando con @username."
ERR_USER_NOT_FOUND = "❌ No encuentro a esa usuaria. Pídele que escriba algo primero, o responde a un mensaje suyo."

OK_ALIANZA_ADDED = "✅ {mention} añadida a las alianzas. Exenta de las 3 reglas."
OK_ALIANZA_REMOVED = "✅ {mention} retirada de las alianzas."
OK_ALIANZA_ALREADY = "ℹ️ {mention} ya estaba en alianzas."
OK_ALIANZA_NOT_FOUND = "ℹ️ {mention} no estaba en alianzas."

NO_ALIANZAS = "📋 No hay alianzas en este grupo."

MENU_NO_GROUPS = (
    "❌ No tengo ningún grupo en común contigo donde tú seas admin.\n\n"
    "Añádeme a tu grupo y hazme administrador primero."
)

MENU_SELECT_GROUP = (
    "🤖 <b>Selecciona el grupo a configurar</b>\n\n"
    "Estos son los grupos donde estoy presente y tú eres administrador:"
)
