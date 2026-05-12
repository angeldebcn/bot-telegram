# 🤖 Bot de Moderación Multimedia para Telegram

Bot completo en Python que aplica **3 reglas configurables** a las publicaciones de fotos/vídeos de tus grupos de Telegram:

- 🔄 **Cola rotatoria**: cada chica espera a que publiquen otras N antes de repetir
- ⏱️ **Cooldown**: tiempo mínimo entre publicaciones de la misma chica
- 🖼️ **Anti-duplicado**: detecta fotos/vídeos repetidos (con hash perceptual)

Todo se configura **desde el móvil con botones** dentro de Telegram. Sin tocar código.

---

## 📑 Índice

1. [Lo que vas a necesitar](#1-lo-que-vas-a-necesitar)
2. [Crear el bot en Telegram](#2-crear-el-bot-en-telegram-con-botfather)
3. [Subir el código a GitHub](#3-subir-el-código-a-github)
4. [Desplegar en Railway](#4-desplegar-en-railway)
5. [Configurar el BOT_TOKEN](#5-configurar-el-bot_token)
6. [Comprobar que arranca](#6-comprobar-que-arranca)
7. [Añadir el bot al grupo](#7-añadir-el-bot-al-grupo)
8. [Configurar el bot con /menu](#8-configurar-el-bot-con-menu)
9. [Comandos disponibles](#9-comandos-disponibles)
10. [Actualizar el bot en el futuro](#10-actualizar-el-bot-en-el-futuro)
11. [Problemas frecuentes](#11-problemas-frecuentes-troubleshooting)
12. [Ruta alternativa: Termux (solo si Railway no te funciona)](#12-ruta-alternativa-termux)

---

## 1. Lo que vas a necesitar

⚠️ **Importante**: TODO esto se puede hacer desde el móvil. No necesitas ordenador.

- 📱 Tu móvil con Telegram
- 🌐 Conexión a internet
- 📧 Una cuenta de email (la que ya uses)
- ⏱️ Unos 30-60 minutos la primera vez

**No necesitas saber programación. No necesitas instalar nada. Sigue los pasos uno a uno.**

---

## 2. Crear el bot en Telegram con @BotFather

> Aquí pides a Telegram que te dé un "token", que es como la contraseña con la que tu bot se identifica.

### Paso 2.1 · Abrir BotFather

1. Abre **Telegram** en tu móvil.
2. En la barra de búsqueda, escribe `@BotFather` y pulsa el primer resultado (el que tiene el tick azul ✅).
3. Pulsa **INICIAR** (o **/start** si ya hablaste con él antes).

### Paso 2.2 · Crear el bot

4. Escribe `/newbot` y envía.
5. BotFather te preguntará: *"Alright, a new bot. How are we going to call it?"*
   - Responde con el **nombre visible** del bot. Por ejemplo: `Moderador Marquesa`
6. BotFather te preguntará: *"Good. Now let's choose a username for your bot."*
   - Responde con un **username único** que termine en `bot`. Por ejemplo: `marquesa_moderacion_bot`
   - ⚠️ Si ya está cogido te pedirá otro. Prueba añadiendo números.

### Paso 2.3 · ⚠️ GUARDAR EL TOKEN (MUY IMPORTANTE)

Cuando lo crees, BotFather te enviará un mensaje como este:

```
Done! Congratulations on your new bot. You will find it at t.me/marquesa_moderacion_bot.
...
Use this token to access the HTTP API:
1234567890:ABCdefGHIjklMNOpqrsTUVwxyz0123456789

Keep your token secure...
```

🚨 **Esa línea larga con números y letras es tu TOKEN**. Cópialo y guárdalo en un sitio seguro (notas del móvil, por ejemplo). Lo vas a pegar en Railway en el paso 5.

> El token es como la contraseña del bot. **No se lo enseñes a nadie**. Si alguien lo consigue, puede controlar tu bot.

### Paso 2.4 · ⚠️ DESACTIVAR LA PRIVACIDAD DEL BOT (CRÍTICO)

Por defecto, los bots de Telegram solo ven mensajes que les mencionan directamente. Para que tu bot pueda ver todas las fotos/vídeos del grupo, hay que **desactivar** esto.

7. En el mismo chat con BotFather, escribe `/setprivacy`.
8. BotFather te listará tus bots. Pulsa el que acabas de crear.
9. BotFather mostrará 2 opciones: `Enable` y `Disable`. **Pulsa `Disable`**.
10. Verás el mensaje: *"Success! The new status is: DISABLED."* ✅

> ⚠️ **Si te saltas este paso, el bot no detectará nada en los grupos.**

### Paso 2.5 · (Opcional) Poner foto y descripción al bot

- `/setuserpic` → enviar foto
- `/setdescription` → enviar texto que aparece al iniciar
- `/setabouttext` → bio corta

Esto puedes hacerlo más adelante.

---

## 3. Subir el código a GitHub

> GitHub es una página web donde guardas el código gratis. Railway lo descargará de ahí automáticamente cuando quieras actualizarlo.

### Paso 3.1 · Crear cuenta de GitHub (si no tienes)

1. Abre el navegador del móvil (Chrome, etc.) y entra en **github.com**.
2. Pulsa **Sign up** (arriba a la derecha).
3. Pon tu email, contraseña y elige un username (lo que sea).
4. Verifica el email pulsando el enlace que te llegue.

### Paso 3.2 · Crear un repositorio nuevo

5. Una vez con sesión iniciada, pulsa el **+** arriba a la derecha → **New repository**.
6. **Repository name**: por ejemplo `bot-moderacion`.
7. Marca **Public** (gratis) o **Private** (también gratis pero menos visible).
8. Marca **Add a README file**. (Solo para que el repo no esté vacío al crearlo.)
9. Pulsa **Create repository**.

### Paso 3.3 · Subir los archivos del bot

10. Dentro del repositorio recién creado, pulsa **Add file** (botón gris arriba a la derecha) → **Upload files**.
11. Pulsa **choose your files** o arrastra todos los archivos de la carpeta del bot:
    - `bot.py`
    - `config.py`
    - `requirements.txt`
    - `Procfile`
    - `runtime.txt`
    - `.gitignore`
    - `.env.example`
    - Y las carpetas: `database/`, `handlers/`, `keyboards/`, `utils/`, `locales/`

    💡 **Truco para móvil**: GitHub web móvil te deja seleccionar archivos sueltos pero NO carpetas. La forma más fácil:
    - Descomprime el ZIP que te di en tu móvil.
    - Sube primero los archivos sueltos del raíz (`bot.py`, `config.py`, etc.).
    - Luego, para cada subcarpeta (`database`, `handlers`, etc.):
      - En GitHub, pulsa **Add file** → **Create new file**.
      - En el campo del nombre, escribe `database/__init__.py` y deja el contenido vacío. Pulsa **Commit**.
      - Ahora la carpeta existe. Entra en ella, pulsa **Add file** → **Upload files** y sube los demás archivos de esa carpeta.
      - Repite para `handlers/`, `keyboards/`, `utils/`, `locales/`.

    🚨 **NO subas el archivo `.env`** (si lo tienes). Contiene el token y debe quedarse fuera de GitHub. El `.gitignore` ya lo ignora.

12. Cuando termines, debes ver una estructura así en GitHub:
    ```
    bot.py
    config.py
    requirements.txt
    Procfile
    runtime.txt
    .gitignore
    .env.example
    database/
    handlers/
    keyboards/
    locales/
    utils/
    ```

---

## 4. Desplegar en Railway

> Railway es el servicio que mantiene tu bot encendido 24/7. Tienen plan gratuito limitado y un plan "Hobby" de unos 5 USD al mes que sobra para esto.

### Paso 4.1 · Crear cuenta en Railway

1. En el navegador, ve a **railway.app**.
2. Pulsa **Login** → **Login with GitHub**. Acepta los permisos.
3. Te llevará al panel principal.

### Paso 4.2 · Crear nuevo proyecto desde GitHub

4. Pulsa **+ New Project** (botón morado).
5. Selecciona **Deploy from GitHub repo**.
6. Si te pide autorizar acceso a tus repositorios, **Authorize** (puedes darle acceso solo al repo `bot-moderacion`).
7. Selecciona tu repositorio `bot-moderacion`.
8. Railway empezará a construir automáticamente. Verás logs en pantalla.

⚠️ **Es normal que la primera construcción falle** porque aún no le has dado el BOT_TOKEN. Pasa al siguiente paso.

---

## 5. Configurar el BOT_TOKEN

### Paso 5.1 · Añadir la variable de entorno

1. En tu proyecto de Railway, pulsa la tarjeta del servicio (debería decir `bot-moderacion`).
2. Pulsa la pestaña **Variables**.
3. Pulsa **+ New Variable**.
4. **Variable name**: `BOT_TOKEN`
5. **Value**: pega el token que te dio BotFather (paso 2.3).
6. Pulsa **Add**.

### Paso 5.2 · Redesplegar

7. Railway detectará el cambio y redesplegará solo. Si no, en la pestaña **Deployments** pulsa los tres puntitos del último deploy → **Redeploy**.

---

## 6. Comprobar que arranca

1. En Railway, dentro del servicio, pulsa la pestaña **Deployments**.
2. Pulsa el último despliegue (en verde si fue bien).
3. Pulsa **View Logs**.
4. Deberías ver líneas como:
   ```
   ✅ Base de datos inicializada en /app/bot.db
   🤖 Bot arrancando en modo polling...
   ```
5. Si lo ves: **¡tu bot está corriendo!** 🎉

### ¿Y si veo errores rojos?

Mira [la sección de problemas frecuentes](#11-problemas-frecuentes-troubleshooting).

---

## 7. Añadir el bot al grupo

### Paso 7.1 · Invitar al bot

1. Abre tu grupo de Telegram.
2. Pulsa el nombre del grupo arriba → **Añadir miembros**.
3. Busca el username de tu bot (ej: `@marquesa_moderacion_bot`) y añádelo.

### Paso 7.2 · ⚠️ HACERLO ADMINISTRADOR (OBLIGATORIO)

Para que el bot pueda borrar mensajes y aplicar castigos, **necesita ser admin con los permisos correctos**.

4. En la lista de miembros del grupo, mantén pulsado el bot.
5. Pulsa **Ascender a administrador** (o el icono de "promote").
6. Activa los siguientes permisos:
   - ✅ **Eliminar mensajes** (CRÍTICO)
   - ✅ **Banear usuarios** (para castigos de kick/ban/mute)
   - ✅ **Restringir miembros** (para mute)
   - ✅ **Invitar usuarios** (recomendado)
   - ⬜ Cambiar info del grupo (no necesario)
   - ⬜ Anclar mensajes (no necesario)
   - ⬜ Añadir admins (NO, peligroso)
7. Pulsa **Guardar** (✓).

### Paso 7.3 · Comprobar que el bot responde

8. En el grupo, escribe `/start`. El bot debería responder con un mensaje.

✅ **Si responde, todo va bien.** Si no, mira [problemas frecuentes](#11-problemas-frecuentes-troubleshooting).

---

## 8. Configurar el bot con /menu

### Paso 8.1 · Abrir el menú

En el grupo (o en chat privado con el bot), escribe `/menu`.

Aparecerá un mensaje con un teclado de botones:

```
🤖 Configuración de [tu grupo]

🔄 Cola rotatoria: 5 chicas
⏱️ Cooldown: 30 min
🖼️ Anti-duplicado: 12h (sensibilidad 5)

Castigos:
  • Cola: 🟢 Borrar + aviso
  • Cooldown: 🟢 Borrar + aviso
  • Duplicado: 🟢 Borrar + aviso

[ 🔄 Cola · 5 chicas ]
[ ⏱️ Cooldown · 30 min ]
[ 🖼️ Anti-duplicado · 12h ]
[ ⚖️ Castigos ]
[ ⚠️ Sistema de warns ]
[ 👥 Alianzas ]
[ 📊 Estadísticas ]
[ ⚙️ Opciones avanzadas ]
[ ❌ Cerrar ]
```

### Paso 8.2 · Configurar cada regla

Toca cualquier botón para entrar a su submenú. Verás opciones rápidas (3, 5, 10, etc.) y un "Valor personalizado" para escribir el número que quieras.

**Configuración recomendada para empezar** (puedes cambiarla cuando quieras):

| Regla | Valor recomendado |
|---|---|
| Cola rotatoria | 5 chicas |
| Cooldown | 30 min |
| Anti-duplicado | 12h, sensibilidad Normal |
| Castigo cola | Borrar + aviso 15s |
| Castigo cooldown | Borrar + aviso 15s |
| Castigo duplicado | Borrar + aviso 30s |
| Warns | 3 → Mute 1h, expiran 7 días |

### Paso 8.3 · Usar el menú desde chat privado

También puedes configurar tus grupos desde el chat privado con el bot:

1. Abre el chat con el bot (búscalo por username).
2. Escribe `/menu`.
3. El bot te listará los grupos donde estás presente y eres admin.
4. Toca el que quieras configurar.

---

## 9. Comandos disponibles

Comandos para admins (funcionan en el grupo):

| Comando | Qué hace |
|---|---|
| `/menu` | Abrir el menú de configuración |
| `/status` | Ver estado y estadísticas del grupo |
| `/freespam` | Añadir a alianzas (responde a la usuaria o usa @username) |
| `/unfreespam` | Quitar de alianzas |
| `/alianzas` | Listar todas las alianzas |
| `/warn @user motivo` | Advertir manualmente |
| `/unwarn @user` | Quitar la última advertencia |
| `/warns @user` | Ver advertencias de una usuaria |
| `/whocanpost` | Lista quién puede publicar AHORA |
| `/myturn` | Cuándo me toca a mí publicar (cualquier usuaria) |
| `/logs` | Últimas 20 acciones del bot |
| `/reload` | Refrescar quién es admin (úsalo si acabas de promover/quitar admins) |
| `/export` | Exportar config a JSON (para copiarla a otro grupo) |
| `/import` | Importar config desde JSON (responder al archivo) |

---

## 10. Actualizar el bot en el futuro

Si cambias el código (por ejemplo añades una función nueva):

1. Sube los archivos modificados a tu repo de GitHub.
2. Railway detectará el cambio y **redesplegará automáticamente** en 1-2 minutos.
3. Tu BD y configuración se conservan (están en disco persistente de Railway).

### Para añadir volumen persistente (recomendado)

Por defecto Railway puede reiniciar el sistema de archivos cada cierto tiempo. Para que tu `bot.db` no se pierda:

1. En Railway, en tu servicio, ve a **Settings** → **Volumes**.
2. Pulsa **+ New Volume**.
3. **Mount path**: `/data`
4. Guardar.
5. Ve a **Variables** y añade: `DB_PATH=/data/bot.db`
6. Redesplegar.

Ahora tu BD vive en un disco persistente que no se borra. ✅

---

## 11. Problemas frecuentes (troubleshooting)

### ❌ "BOT_TOKEN no está definido"

→ No has añadido la variable `BOT_TOKEN` en Railway. Repasa el [paso 5](#5-configurar-el-bot_token).

### ❌ El bot está online pero no responde a /start

- Verifica que el token sea correcto (sin espacios al copiar).
- Mira los logs en Railway: ¿hay errores de Telegram?
- ¿Has hablado tú primero con el bot en privado? Algunos bots requieren un /start inicial.

### ❌ El bot está en el grupo pero no ve los mensajes

→ Olvidaste hacer `/setprivacy` → `Disable` con BotFather. Repasa el [paso 2.4](#paso-24--desactivar-la-privacidad-del-bot-crítico). **Después de cambiar la privacidad, saca al bot del grupo y vuélvelo a meter** para que el cambio surta efecto.

### ❌ El bot ve los mensajes pero no borra nada

→ No es administrador o no tiene el permiso **Eliminar mensajes**. Repasa el [paso 7.2](#paso-72--hacerlo-administrador-obligatorio).

### ❌ El bot borra pero no aplica mute/kick/ban

→ Le faltan los permisos **Banear usuarios** y **Restringir miembros**. Edita sus permisos de admin.

### ❌ El despliegue falla en Railway: "Could not install opencv"

→ Es por dependencias del sistema. Soluciones:
- En Railway → Settings → asegúrate de que el builder es **Nixpacks** (por defecto).
- Si persiste, edita `requirements.txt` y cambia `opencv-python-headless==4.10.0.84` por `opencv-python-headless` (sin versión). Sube el cambio.

### ❌ El bot dice "TelegramConflictError"

→ Hay otra instancia del bot corriendo en algún sitio con el mismo token. Apaga la otra (puede ser otro Railway, Heroku, tu PC, etc.).

### ❌ /menu en privado no me muestra mis grupos

→ El bot solo lista grupos donde TÚ eres admin Y donde él ha visto al menos un mensaje. Habla en el grupo (escribe cualquier cosa) y vuelve a probar.

### ❌ Quiero que el bot ignore a las admins

→ Las admins están exentas automáticamente. Si una admin publica, ninguna regla se le aplica.

### ❌ Una chica de confianza no es admin pero quiero que pueda publicar sin reglas

→ Usa `/freespam` respondiendo a un mensaje suyo. Queda añadida a las alianzas.

### ❌ El bot detecta como duplicadas fotos que claramente son diferentes

→ La sensibilidad está demasiado alta. Ve a `/menu` → Anti-duplicado → Ajustar sensibilidad → **🔴 Estricta**.

### ❌ Una chica está reenviando vídeos repetidos y el bot no los detecta

→ Pasa lo contrario: la sensibilidad es demasiado baja. Ponla en **🟡 Tolerante** o **🔵 Agresiva**.

### ❌ He cambiado /privacy en BotFather y sigue sin ver mensajes

→ El cambio requiere **sacar al bot del grupo y volverlo a meter**.

### ❌ Quiero que las warns no caduquen nunca

→ Por diseño caducan para no dejar usuarias castigadas eternamente. Pon la expiración a 90 días (lo máximo del selector) si quieres "casi sin caducidad".

### ❌ El bot tarda en responder

→ Railway en plan gratuito puede "dormirse". Cambia al plan **Hobby** (~5 USD/mes) o usa keep-alive externo.

### ❌ Quiero exportar la config de un grupo a otro

→ En el grupo origen: `/export` te devuelve un archivo JSON.
→ En el grupo destino: reenvía ese archivo y responde a él con `/import`.

---

## 12. Ruta alternativa: Termux

Si por lo que sea Railway no te encaja, también puedes correr el bot **directamente en tu móvil Android** con la app gratuita **Termux**.

**Resumen rápido** (no incluyo paso a paso completo aquí):

1. Instala **Termux** desde F-Droid (NO desde Google Play, esa versión está obsoleta).
2. En Termux:
   ```bash
   pkg update && pkg upgrade -y
   pkg install python git ffmpeg libjpeg-turbo -y
   git clone https://github.com/TU_USER/bot-moderacion.git
   cd bot-moderacion
   pip install -r requirements.txt
   echo "BOT_TOKEN=tu_token_aqui" > .env
   python bot.py
   ```
3. Para que siga corriendo aunque cierres Termux:
   ```bash
   pkg install termux-services tmux -y
   tmux new -s bot
   python bot.py
   # Pulsa Ctrl+B y luego D para "desanclar". El bot seguirá corriendo.
   ```
4. Para reconectar: `tmux attach -t bot`

⚠️ Esta opción consume batería y datos. **Railway es mejor para uso 24/7**.

---

## 📜 Licencia y soporte

Este código es para tu uso personal. No tiene soporte oficial.

Si algo no te funciona:

1. Revisa los logs en Railway (pestaña Deployments → ver logs).
2. Repasa el paso correspondiente del README.
3. Si nada funciona, mira el último cambio que hiciste y revírtelo.

---

**¡Disfruta de tus grupos ordenados! 🎉**
