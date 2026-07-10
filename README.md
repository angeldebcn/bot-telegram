# 🤖 Bot de Moderación Multimedia para Telegram · Edición SaaS

Bot **multifunción** para grupos de Telegram con:

- 🔄 **Cola rotatoria** (cuántas chicas deben publicar antes de tu turno)
- ⏱️ **Cooldown** (tiempo mínimo entre tus propias publicaciones)
- 🖼️ **Anti-duplicado** con perceptual hashing (fotos y vídeos)
- 🎯 **17 filtros de tipos de contenido** estilo GroupHelp (foto/vídeo/sticker/gif/audio/voice/...)
- ⚖️ **6 castigos por regla**: solo borrar / aviso autodestructivo / warn acumulativo / mute / kick / ban
- ✅ **Toggles independientes**: cada regla se puede activar/desactivar sin perder configuración
- 🔕 **/lock /unlock**: pausa temporal del bot sin tocar nada
- ⚡ **/forcepost**: pase libre para la próxima publicación de una usuaria
- 🧹 **Auto-borrado de mensajes de servicio** ("X se unió", "foto del grupo cambiada", etc.)
- 👥 **Alianzas**: lista de exentas (admins lo son siempre)
- ⚠️ **Sistema de warns** acumulativos con expiración configurable
- 💎 **Sistema de licencias SaaS**: monetiza el bot cobrando 5€/mes por grupo

---

## 📦 Estructura

```
bot_telegram/   (TODOS los archivos en la misma carpeta, sin subcarpetas)
├── bot.py                 # Punto de entrada
├── config.py              # Constantes, defaults, opciones de menú
├── es.py                  # Todos los strings en español
├── db.py                  # Esquema SQLite + migración automática
├── config_db.py           # CRUD de la config por grupo
├── posts.py               # Posts publicados (para reglas)
├── alianzas.py            # Lista de exentas
├── warns.py               # Advertencias acumulativas
├── licenses.py            # Sistema de suscripciones
├── stats.py               # Logs y estadísticas
├── admin.py               # /admin (panel del owner)
├── commands.py            # /start /menu /help /freespam /warn /delete ...
├── menu.py                # /menu con selector de grupo
├── callbacks.py           # Todos los botones inline
├── media.py               # Lógica de moderación + my_chat_member
├── builders.py            # Teclados del menú normal
├── admin_builders.py      # Teclados del panel owner
├── album_collector.py     # Buffer 2s para álbumes
├── filters.py             # Detección de tipo de contenido
├── license_helpers.py     # Comprobación de suscripción
├── media_hash.py          # pHash de fotos/vídeos
├── middleware.py          # Cacheo + auto-registro de licencias
├── permissions.py         # Verificación de admins
├── punishment.py          # 6 castigos por regla
├── helpers.py             # Utilidades genéricas
├── scheduler.py           # Tareas programadas
├── requirements.txt       # Dependencias
├── runtime.txt            # Versión de Python
└── Procfile               # Comando de arranque
```

> 📌 **Estructura plana**: todos los archivos van en la misma carpeta, sin
> subcarpetas. Así puedes seleccionarlos todos de golpe y subirlos a GitHub
> en una sola tanda.

---

## 🚀 Despliegue en Railway

### 1. Subir a GitHub

Sube TODO el contenido de la carpeta `bot_telegram/` a tu repositorio.

### 2. Crear servicio en Railway

- Pulsa **New Project → Deploy from GitHub repo**.
- Selecciona tu repositorio.
- Railway detectará Python automáticamente (gracias a `runtime.txt` y `requirements.txt`).

### 3. Variables de entorno

En **Variables**, añade:

| Variable | Valor | Obligatoria |
|---|---|---|
| `BOT_TOKEN` | Token del bot (de @BotFather) | ✅ Sí |
| `OWNER_USER_ID` | Tu user_id de Telegram (entero) | ✅ Sí, para licencias |
| `OWNER_USERNAME` | Tu @ sin la @ (`lapanteraoficial`) | Recomendado |
| `SUBSCRIPTION_PRICE_EUR` | Precio que mostrará el bot (default: `5`) | Opcional |
| `LICENSING_ENABLED` | `true` (default) o `false` para modo libre | Opcional |
| `DB_PATH` | Ruta del archivo SQLite | Recomendado: `/data/bot.db` |
| `LOG_LEVEL` | `INFO` (default) o `DEBUG` | Opcional |

### 4. Volumen persistente

⚠️ **CRÍTICO**: sin esto, perderás la BD en cada deploy.

- En Railway, en tu servicio → **Volumes → New Volume**.
- Mount path: `/data`.
- Size: 5 GB (basta).
- Asegúrate de tener `DB_PATH=/data/bot.db` en Variables.

### 5. Arranque

El bot arranca automáticamente. Verifica en logs:

```
👑 Owner configurado: user_id=7860549875 @lapanteraoficial
🤖 Bot arrancando en modo polling...
✅ Base de datos inicializada en /data/bot.db
```

---

## 💎 Sistema de licencias

### Cómo funciona

Cuando alguien añade el bot a un grupo:

- **Si lo añades TÚ** (owner): se activa automáticamente como `owner` (gratis y permanente).
- **Si lo añade otro**: estado `pending`. El bot NO aplica reglas. Manda mensaje al grupo pidiendo contactar a `@lapanteraoficial`. Y te avisa a TI por privado con botones de activación rápida.

### Estados

| Estado | Bot funciona? |
|---|---|
| 👑 `owner` | ✅ Sí, gratis para siempre |
| ✅ `active` | ✅ Sí, hasta la fecha de expiración |
| ⏳ `pending` | ❌ No |
| ❌ `expired` | ❌ No |
| 🚫 `banned` | ❌ No |

### Comandos del owner

Solo funcionan si `from_user.id == OWNER_USER_ID`:

```
/admin                              → panel con botones
/admin help                         → lista de subcomandos
/admin list                         → todas las licencias
/admin list pending                 → solo pendientes
/admin list active                  → solo activas
/admin activate <chat_id> <días>    → extender X días
/admin lifetime <chat_id>           → activación permanente
/admin deactivate <chat_id>         → volver a pendiente
/admin ban <chat_id>                → vetar (no podrá usar el bot)
/admin info <chat_id>               → detalles
/admin leave <chat_id>              → sacar el bot del grupo
```

El panel `/admin` (con botones) es lo más cómodo: dashboard con totales, listas filtradas, y para cada grupo botones "+30d / +90d / lifetime / vetar / sacar el bot".

### Avisos automáticos

- **3 días antes de caducar**: aviso al grupo + DM al owner con botones de renovación rápida.
- **Al caducar**: el estado pasa a `expired` automáticamente y el bot deja de funcionar en ese grupo.

---

## 🎯 Funcionalidades clave

### Toggles por regla

Cada regla (cola/cooldown/antidup) tiene un botón "Activada/Desactivada" en su submenú. Si está desactivada, no se evalúa, pero la configuración se mantiene para cuando la actives de nuevo.

### Filtros de tipos de contenido

17 tipos: foto, vídeo, gif, sticker, sticker animado, archivo, voz, audio, video redondo, encuesta, contacto, ubicación, sorteo, vía bot, reenviado, mayúsculas, enlaces.

Cada uno tiene 6 acciones: Off / Borrar / Warn / Mute / Kick / Ban.

### /forcepost

`/forcepost @user` o `/forcepost ID` o responde con `/forcepost` al mensaje de una chica → su próxima publicación ignora las 3 reglas. Útil cuando una chica especial necesita publicar ya mismo.

### /lock y /unlock

`/lock` pausa el bot completamente. `/unlock` lo reanuda. La configuración no se toca.

### /freespam mejorado

Acepta:
- Reply al mensaje de la usuaria.
- `/freespam @username`.
- `/freespam 123456789` (ID numérico, lo da @userinfobot).

Si no encuentra a la usuaria por @username (porque nunca habló en el grupo), te dice exactamente qué hacer para arreglarlo.

### Auto-borrado de mensajes de servicio

En *Opciones avanzadas* del menú. Si activado, borra automáticamente:
- "X se unió al grupo"
- "X salió del grupo"
- "Foto del grupo cambiada"
- "Título del grupo cambiado"
- "Mensaje fijado"
- Notificaciones de chats de voz

---

## 📚 Lista completa de comandos

### En el grupo (admins)

```
/menu          Configuración completa (botones)
/status        Estado del grupo (últimas 24h)
/help          Lista de comandos
/lock          Pausar el bot
/unlock        Reanudar
/freespam @u   Añadir a alianzas
/unfreespam @u Quitar de alianzas
/alianzas      Listar exentas
/forcepost @u  Pase libre próxima publicación
/warn @u       Advertir
/unwarn @u     Quitar último warn
/warns @u      Ver warns activos
/logs          Últimas 20 acciones
/reload        Recargar lista de admins
/export        Exportar config a JSON
/import        Importar config (reply a JSON)
```

### En el grupo (cualquier usuaria)

```
/myturn        Cuándo me toca a mí publicar
/whocanpost    Quién puede publicar ahora
```

### En privado contigo

```
/start         Información del bot
/menu          Listar y configurar tus grupos
/help          Ayuda
```

### Solo para ti (owner)

```
/admin         Panel completo de licencias
```

---

## 🔧 Troubleshooting

**El bot no responde en mi grupo**
- ¿Está activada la licencia? Mira `/admin info <chat_id>`.
- ¿Tiene permisos de admin con "borrar mensajes" y "silenciar"?
- ¿Está en `/lock`? Usa `/unlock`.

**No detecta admins / dice que no soy admin**
- Tras hacerte admin, escribe `/reload` en el grupo (invalida cache de 5 min).

**/freespam @user no funciona**
- La usuaria debe haber escrito algo en el grupo primero (para que la cachee).
- Si no, usa su ID numérico: pídele que abra @userinfobot.

**El bot no me avisa cuando alguien lo añade a un grupo nuevo**
- Verifica que `OWNER_USER_ID` esté bien configurado.
- Tienes que haberle escrito al bot al menos una vez en privado (Telegram bloquea bots que envían DM "fríos").

**Filtros: las fotos siguen pasando aunque las puse en Borrar**
- En filtros, las fotos y vídeos se procesan por álbum (espera 2s). Funciona.

**Una chica vacía la cola constantemente**
- Marca filtro de "Reenviado" como Borrar o Warn.
- Considera bajar el cooldown o subir la cola.

**No quiero el sistema de licencias, quiero gratis para todos**
- Pon `LICENSING_ENABLED=false` en Railway. El bot funcionará en cualquier grupo sin restricciones.

---

## 💰 Estrategia comercial sugerida

**Precio base: 5 €/mes por grupo, pago por Revolut a @lapanteraoficial**

Ideas para vender mejor:

1. **Prueba 7 días gratis** al primer contacto. Tras 7 días, si paga, sigue; si no, lo desactivas.
2. **Pack 3 grupos**: 12 €/mes (en vez de 15 €).
3. **Pack ilimitado**: 49 €/mes para clientes con muchos grupos.
4. **Plan vitalicio**: 99 € pago único = activación permanente.

Cuando contactes con clientes:
- Captura del menú del bot (las 3 reglas + filtros).
- Frase clave: "Es como GroupHelp Premium pero con cola rotatoria configurable. 5 €/mes."

⚠️ **Recuerda**: las comunicaciones comerciales y el cobro se hacen FUERA del bot, por DM directo. El bot solo gestiona el estado de las licencias.
