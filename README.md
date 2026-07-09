# 🐷 Bot de difusión · MALA STUDIOS

Bot propio de Telegram para subir tu promo a los canales de las creadoras
de forma automática, con autoborrado y **emojis premium intactos**.
Sustituye al bot de Nashra (@LeoparditaSpamBot) y lo mejora.

Se despliega en **GitHub + Railway**, igual que el bot de moderación.

---

## ✅ Qué resuelve este bot

| Problema del bot viejo | Solución de este bot |
|---|---|
| Solo aceptaba enlaces privados; fallaba con canales públicos | Acepta `@usuario`, enlaces `t.me/...`, IDs `-100...` **y canales públicos**. Además, si añades el bot como admin, el canal **se guarda solo**. |
| Los emojis premium se perdían al crear el mensaje | Tú envías la promo **una vez** y el bot la guarda como «mensaje maestro». Siempre la difunde con `copyMessage`, que **conserva los emojis premium**. |
| Programar era lentísimo y manual | **Campañas automáticas**: lo defines una vez y el bot lo hace solo cada semana, en bloques. |

---

## 📁 Archivos del proyecto

Todos los archivos van en la **raíz** del repositorio (sin carpetas).
Así la subida a GitHub es **una sola tanda**.

```
bot.py            broadcaster.py   h_broadcast.py   requirements.txt
config.py         guard.py         h_campaigns.py   Procfile
database.py       h_menu.py        h_misc.py        runtime.txt
states.py         h_channels.py    .gitignore       .env.example
keyboards.py      h_promos.py      README.md
```

---

## 1️⃣ Crear el bot en Telegram (@BotFather)

1. Abre Telegram y busca **@BotFather**.
2. Escribe `/newbot`.
3. Pon un **nombre** (ej: `MALA Difusión`).
4. Pon un **username** que termine en `bot` (ej: `mala_difusion_bot`).
5. BotFather te dará un **token** tipo `123456789:AAE...`. **Cópialo y guárdalo.**
6. (Opcional) `/setuserpic` para ponerle foto, `/setdescription` para la descripción.

> A diferencia del bot de moderación, **aquí NO hace falta tocar la privacidad**.
> Este bot solo trabaja contigo en privado y publica en canales donde sea admin.

### Comandos visibles (opcional pero recomendado)
Escribe `/setcommands` a BotFather, elige tu bot y pega esto:
```
menu - Abrir el menú principal
enviar - Enviar una promo ahora
promos - Gestionar promos
canales - Gestionar canales
campanas - Campañas automáticas
stats - Estadísticas
verify - Verificar permisos de los canales
delall - Borrar todas las publicaciones
id - Ver mi user_id
help - Ayuda
```

---

## 2️⃣ Saber tu OWNER_ID

El bot solo te obedecerá a ti. Necesitas tu **user_id** numérico.

- Opción rápida: abre **@userinfobot** en Telegram, te dice tu ID.
- O arranca el bot (pasos siguientes) y escríbele `/id` en privado.

Apunta ese número, lo usarás en el paso 5.

---

## 3️⃣ Subir el código a GitHub

1. Entra en **github.com** desde el navegador del móvil e inicia sesión
   (la misma cuenta del otro bot).
2. Arriba a la derecha: **+** → **New repository**.
3. **Repository name**: `bot-difusion-mala`.
4. Marca **Private**. **No** marques "Add a README".
5. Pulsa **Create repository**.
6. En la página del repo, pulsa el enlace **uploading an existing file**.
7. Pulsa **choose your files** y selecciona **TODOS** los archivos del bot
   (los 19 archivos de la lista de arriba) **de una sola vez**.
   - 💡 Como están todos en la raíz, no hay que hacer el truco de carpetas
     del otro bot. Una sola tanda y listo.
   - 🚨 **No subas** ningún archivo `.env` (el `.gitignore` ya lo evita).
8. Abajo, en "Commit changes", escribe `primera version` y pulsa el botón
   verde **Commit changes**.

---

## 4️⃣ Desplegar en Railway

> Usas la **misma cuenta de Railway** que ya pagas para el otro bot.
> Este será un **proyecto nuevo** dentro de la misma cuenta.

1. Entra en **railway.app** e inicia sesión.
2. Pulsa **+ New Project** → **Deploy from GitHub repo**.
3. Si hace falta, autoriza el acceso al repo `bot-difusion-mala`.
4. Selecciona ese repositorio. Railway empezará a construir.
   - ⚠️ Es normal que el primer intento falle: aún no le diste el token.

### 4.1 · Añadir el Volume (para no perder los datos)

El bot guarda canales, promos y campañas en una base de datos.
Para que **no se borre** cada vez que Railway reinicia, hay que montar
un **Volume**, igual que en el otro bot.

5. Dentro del proyecto, pulsa la tarjeta del servicio.
6. Pulsa **Settings** (o el icono de los tres puntos) → busca **Volumes**
   → **+ New Volume** (o **Add Volume**).
7. **Mount path**: escribe exactamente `/data`
8. Confirma.

### 4.2 · Añadir las variables

9. En el servicio, pulsa la pestaña **Variables**.
10. Pulsa **+ New Variable** y añade estas (una por una):

| Variable | Valor |
|---|---|
| `BOT_TOKEN` | el token que te dio BotFather |
| `OWNER_ID` | tu user_id numérico (paso 2) |
| `TZ` | `Europe/Madrid` |
| `DB_PATH` | `/data/bot.db` |

11. Railway redesplegará solo. Si no, pestaña **Deployments** → tres puntos
    → **Redeploy**.

### 4.3 · Comprobar que arranca

12. Pestaña **Deployments** → último deploy → **View Logs**.
13. Deberías ver algo así:
```
Base de datos lista en /data/bot.db
🤖 Bot @mala_difusion_bot arrancado correctamente
```
14. El bot te enviará un mensaje en privado: «🟢 Bot de difusión en marcha».
    Escríbele **/menu** y empieza.

---

## 5️⃣ Cómo usar el bot — paso a paso

Todo se maneja con **botones**. Escribe `/menu` para abrir el menú principal:

### 📢 Promos — crea tu publicación una vez
1. Menú → **📢 Promos** → **➕ Nueva promo**.
2. Escribe un nombre (ej: «España 1-6»).
3. **Envía la publicación tal cual** al bot: foto + texto + emojis premium.
4. Queda guardada. ⚠️ **No borres ese mensaje** del chat con el bot.
5. Puedes tener varias promos (una por categoría, por bloque, etc.).

### 📡 Canales — añade los canales de las creadoras
- **➕ Añadir canal**: pega `@usuario`, un enlace o un ID.
- **📥 Importar lista**: pega muchos canales de golpe.
- **Automático**: si una creadora añade el bot como admin a su canal,
  ese canal **aparece solo** en tu lista.
- **🏷️ Etiquetar**: toca un canal y ponle Región y Categoría.
- **🛂 Verificar permisos**: comprueba en cuáles el bot es admin de verdad.
- **📶 Suscriptores**: cuenta los miembros de cada canal.

### ⚡ Enviar ahora — difundir al instante
1. Menú → **⚡ Enviar ahora**.
2. Elige la promo.
3. Elige el destino: todos, una región o una categoría.
4. Elige el modo: **💥 todo de golpe** o **🪜 escalonado** (en bloques).
5. Elige cuándo se autoborra: 6/12/24/48/72 h, nunca, o **personalizado**.
6. Confirma. El bot envía y te da un informe (enviados / fallidos).
   Si hay fallos, aparece el botón **🔁 Reenviar fallidos**.

### ⏰ Programar envío — para una fecha y hora concreta
Igual que «Enviar ahora», pero al final escribes la fecha con el formato
`DD/MM HH:MM` (ej: `25/12 21:30`). El bot lo guarda y lo lanza solo.

### 🚀 Campañas automáticas — la función estrella
Defines una campaña **una sola vez** y el bot la repite cada semana solo.
Menú → **🚀 Campañas auto** → **➕ Nueva campaña**. Te pregunta:
1. Nombre.
2. Región y categoría de los canales.
3. Promo(s) — si marcas varias, se rotan entre bloques.
4. Cada cuántos bloques rotar de promo.
5. Días de la semana.
6. Hora de inicio (hora de España).
7. Canales por bloque (ej: 5).
8. Minutos entre bloques (ej: 5).
9. Cuándo se autoborra cada publicación.

A partir de ahí, **no tienes que hacer nada más**. Puedes pausarla,
reactivarla, ejecutarla a mano («🧪 Ejecutar ahora») o eliminarla.

### 📅 Agenda · 📊 Estadísticas · ⚙️ Ajustes
- **Agenda**: muestra las próximas tareas programadas (campañas, envíos,
  autoborrados).
- **Estadísticas**: canales, promos, campañas, envíos correctos y fallidos.
- **Ajustes**: zona horaria, y «🧹 Borrar TODO» para limpiar de los canales
  todas las publicaciones pendientes.

---

## 6️⃣ Comandos disponibles

| Comando | Qué hace |
|---|---|
| `/start` `/menu` | Abre el menú principal |
| `/enviar` | Inicia un envío |
| `/promos` | Gestiona las promos |
| `/canales` `/list` | Gestiona y ve los canales |
| `/campanas` | Campañas automáticas |
| `/alianzas` | Gestiona las alianzas |
| `/stats` | Estadísticas |
| `/historial` | Últimos envíos y su resultado |
| `/backup` | El bot te envía una copia de la base de datos |
| `/restore` | Restaura la base de datos desde un backup |
| `/verify` | Verifica los permisos de todos los canales |
| `/delall` | Borra TODAS las publicaciones enviadas |
| `/cancel` | Cancela lo que estés haciendo |
| `/id` | Te dice tu user_id |
| `/help` | Ayuda |

---

## 7️⃣ Mensaje para las creadoras

Pásales esto para que el bot pueda publicar en su canal:

> Añade este bot a tu canal y hazlo **administrador**.
> Activa estos permisos: **Publicar mensajes** y **Eliminar mensajes**.
> En cuanto lo hagas, tu canal queda enlazado automáticamente.

Para que un canal **público** funcione basta con eso. Para canales
**privados** es obligatorio añadir el bot como admin (con un enlace de
invitación privado el bot no puede entrar solo).

---

## 8️⃣ Errores frecuentes

| Problema | Solución |
|---|---|
| El build de Railway tarda mucho | Normal la primera vez. El `runtime.txt` ya usa Python 3.11 para acelerarlo. |
| El bot no responde a `/menu` | Revisa que `BOT_TOKEN` esté bien copiado en Variables. Mira los logs. |
| «el bot NO es administrador» al verificar | La creadora debe ascender el bot a admin con permiso de publicar y borrar. |
| «Es un enlace de invitación privado» | Pídele a la creadora que añada el bot como admin; el canal se guardará solo. |
| Una promo no se previsualiza / no se envía | No borres el mensaje maestro del chat con el bot. Si lo borraste, crea la promo otra vez. |
| Se perdieron los canales tras un reinicio | Falta el **Volume** montado en `/data`. Revisa el paso 4.1. |
| Los emojis premium no salen | Asegúrate de mandar la promo desde tu cuenta **Premium** y de no recrearla; el bot la copia tal cual. |
| Una campaña no se ejecuta | Revisa que esté en 🟢 activa y que el día/hora sean correctos. Usa «🧪 Ejecutar ahora» para probarla. |

---

## 🌎 Zonas horarias (importante)

Cuando creas una campaña y eliges la **región**, el bot le asigna sola la
zona horaria de esa región. A partir de ahí, la hora que escribes es la
**hora local de allí**:

- Campaña **España** → escribes `21:30` → sale a las 21:30 en España.
- Campaña **Cono Sur** → escribes `21:30` → sale a las 21:30 en Argentina.
- Campaña **Caribe** → escribes `21:30` → sale a las 21:30 en Venezuela.
- Campaña **Andina** → escribes `21:30` → sale a las 21:30 en Colombia.
- Campaña **México** → escribes `21:30` → sale a las 21:30 en México.

**No tienes que hacer ninguna conversión mental.** Antes, con el otro bot,
tú calculabas "21:30 Argentina = 01:30 España" y lo programabas a mano. Eso
además fallaba en verano, porque España y Argentina cambian la hora en
fechas distintas. Aquí el bot lo calcula solo y siempre acierta.

Si quieres que algo salga a las 21:30 hora local de cada sitio los
miércoles y domingos, en **todas** las campañas pones `21:30` y los días
`Mié` y `Dom`. El bot se encarga del resto.

---

---

## 🔒 Copias de seguridad

Tus canales, bloques, campañas y alianzas viven en la base de datos
(`bot.db`), que está **solo** en el Volume de Railway. El código está en
GitHub, pero **los datos no**. Por eso el bot tiene backup:

- **`/backup`** (o Ajustes → 💾 Backup ahora): el bot te envía el archivo
  `bot.db` a tu chat. Guárdalo.
- **`/restore`** (o Ajustes → ♻️ Restaurar backup): le reenvías un
  `bot.db` y el bot reemplaza la base de datos con esa copia. Útil si el
  Volume se corrompe o lo borras.
- **Backup automático:** cada lunes a las 09:00 el bot te manda una copia
  solo, sin que hagas nada.

El backup se restaura **desde el propio chat de Telegram**, NO desde
GitHub. Es una foto del momento en que lo hiciste: si restauras una copia
de hace una semana, recuperas el estado de hace una semana.

---

## 9️⃣ Notas técnicas

- **Python 3.11** · **aiogram 3.13.1** · **APScheduler** · **SQLite**.
- Modo *polling* (no necesita dominio ni webhook).
- La base de datos vive en `/data/bot.db` (Volume de Railway).
- Cada campaña y cada alianza guardan su propia zona horaria.
- Cada canal tiene un **bloque fijo**; si una creadora se va, su hueco
  queda libre y lo ocupa la siguiente que añadas.
- Si Telegram pide esperar (flood), el bot **espera y reintenta solo**.
- Las campañas **reintentan automáticamente** los canales que fallen.
- Antes de cada campaña, el bot revisa qué canales perdieron permisos.
- El bot guarda el **perfil del propietario** de cada canal y lo refresca
  cada vez que mira el canal (al verificar, al abrir la parrilla...).
- Backup automático semanal de la base de datos.
- Tras cada reinicio, el bot **recupera solo** los autoborrados pendientes
  y vuelve a programar las campañas y alianzas activas.
- El bot te avisa si una creadora quita el bot de su canal o le retira
  los permisos de administrador.
- Solo el `OWNER_ID` puede manejar el bot.
