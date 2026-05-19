import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import os
import asyncio
import json
import random
from datetime import datetime, time, timedelta
import pytz
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TOKEN = os.environ["DISCORD_TOKEN"]
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
GUILD_ID = 1506296906509193256

import glob
import ctypes.util

FFMPEG_PATH = "ffmpeg"  # instalado via apt en el Dockerfile


def _load_opus():
    if discord.opus.is_loaded():
        return
    import subprocess

    # apt instala libopus0 en /usr/lib/x86_64-linux-gnu — ctypes lo encuentra solo
    for name in ["opus", "libopus.so.0", "libopus.so"]:
        try:
            discord.opus.load_opus(name)
            print(f"✅ Opus cargado: {name}")
            return
        except Exception:
            pass

    # Fallback: buscar con find en todo el sistema
    try:
        result = subprocess.run(
            ["find", "/usr", "/lib", "-name", "libopus.so*", "-type", "f"],
            capture_output=True, text=True, timeout=10
        )
        for path in result.stdout.strip().splitlines():
            path = path.strip()
            if not path:
                continue
            try:
                discord.opus.load_opus(path)
                print(f"✅ Opus encontrado en: {path}")
                return
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️ find falló: {e}")

    print("❌ No se pudo cargar libopus — la música no funcionará")


_load_opus()

# Direct internet radio streams (no auth, datacenter-friendly)
RADIO_STATIONS = [
    ("🌿 Groove Salad",    "https://ice6.somafm.com/groovesalad-128-mp3"),
    ("🎷 Radio Swiss Jazz", "http://stream.srg-ssr.ch/m/rsj/mp3_128"),
    ("🎹 Lush",            "https://ice6.somafm.com/lush-128-mp3"),
]

# IDs de canales
CH_DAILY         = 1506312211163906139
CH_GENERAL       = 1506312207254683839
CH_ANUNCIOS      = 1506312197624565992
CH_FOTO_VIERNES  = 1506316429526307048
CH_COMIENDO      = 1506316433032872017
CH_RECORDATORIOS = 1506312233746170048
CH_WINS          = 1506316418063401051
VC_FOCUS         = 1506312245616054322

# IDs de roles de área
ROLES_AREA = {
    "design":    1506316499340497060,
    "dev":       1506316503363092581,
    "marketing": 1506316507263668264,
    "miembro":   1506316496165540033,
}

TZ = pytz.timezone("America/Argentina/Buenos_Aires")

PUNTOS_FILE = "puntos.json"

CHISTES = [
    "¿Por qué los programadores confunden Halloween con Navidad? Porque Oct 31 = Dec 25. 🎃",
    "Un QA entra a un bar y pide 0 cervezas, 1 cerveza, 99999 cervezas, -1 cervezas, una lagartija, y NULL cervezas. 🍺",
    "¿Cómo se llama el campeón de buceo japonés? Tokofondo. 🤿",
    "¿Por qué el café es el mejor programador? Porque trabaja con Java. ☕",
    "¿Qué hace una abeja en el gimnasio? ¡Zum-ba! 🐝",
    "¿Cómo se despide un químico? Ácido un placer. 🧪",
    "¿Cuál es el colmo de un electricista? Que su hijo sea una lámpara y no encienda. 💡",
]

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─── PUNTOS ───────────────────────────────────────────────────────────────────

def cargar_puntos():
    if os.path.exists(PUNTOS_FILE):
        with open(PUNTOS_FILE) as f:
            return json.load(f)
    return {}

def guardar_puntos(data):
    with open(PUNTOS_FILE, "w") as f:
        json.dump(data, f)

def sumar_punto(user_id: str):
    data = cargar_puntos()
    data[user_id] = data.get(user_id, 0) + 1
    guardar_puntos(data)
    return data[user_id]


# ─── EVENTOS ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    daily_standup.start()
    reunion_semanal.start()
    foto_del_viernes.start()
    hilo_comida.start()
    ranking_semanal.start()
    notion_watcher.start()
    print("✅ Tareas programadas iniciadas")
    print(f"🔧 ffmpeg: {FFMPEG_PATH} | opus loaded: {discord.opus.is_loaded()}")
    await asyncio.sleep(3)
    guild = bot.get_guild(GUILD_ID)
    if guild and focus_humans(guild):
        print(f"🎵 Hay gente en Focus al iniciar, arrancando radio...")
        await start_radio(guild)


@bot.event
async def on_member_join(member: discord.Member):
    canal = bot.get_channel(CH_GENERAL)
    if not canal:
        return
    embed = discord.Embed(
        title=f"¡Bienvenido/a al equipo, {member.display_name}! 🎉",
        description=(
            f"Hola {member.mention}! Estamos contentos de que estés acá.\n\n"
            "**Canales para arrancar:**\n"
            "💬 `#general` — presentate\n"
            "📣 `#anuncios` — info importante\n"
            "☕ `#daily` — standup diario\n"
            "🏆 `#wins` — celebrá los logros\n"
            "🍽️ `#que-estas-comiendo` — el más importante\n\n"
            "Usá `/mirol` para elegir tu área y `/chiste` para romper el hielo. 😄"
        ),
        color=discord.Color.green()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await canal.send(embed=embed)

    # Asignar rol Miembro automáticamente
    guild = member.guild
    rol_miembro = guild.get_role(ROLES_AREA["miembro"])
    if rol_miembro:
        await member.add_roles(rol_miembro)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.lower()

    # "urgente" → alerta
    if "urgente" in content:
        await message.add_reaction("🚨")
        await message.reply(
            "🚨 **ALERTA URGENTE** 🚨\n"
            f"{message.author.mention} necesita atención inmediata. ¡Todos al canal!"
        )

    # "lunes" → Garfield
    if "lunes" in content:
        await message.reply("https://media.giphy.com/media/lcmgMCGCIqkCk/giphy.gif")

    # Sumar punto por participar
    sumar_punto(str(message.author.id))

    await bot.process_commands(message)


# ─── RADIO ────────────────────────────────────────────────────────────────────

_current_station = 0
_radio_retries = 0
MAX_RADIO_RETRIES = len(RADIO_STATIONS)
_radio_lock: asyncio.Lock | None = None  # initialized after event loop starts
_stopping_manually = False  # True while we're manually stopping to change station


def _get_radio_lock() -> asyncio.Lock:
    global _radio_lock
    if _radio_lock is None:
        _radio_lock = asyncio.Lock()
    return _radio_lock


def focus_humans(guild: discord.Guild) -> list:
    vc = guild.get_channel(VC_FOCUS)
    return [m for m in vc.members if not m.bot] if vc else []


async def get_voice(guild: discord.Guild) -> discord.VoiceClient | None:
    vc_channel = guild.get_channel(VC_FOCUS)
    if not vc_channel:
        print("❌ Canal Focus no encontrado")
        return None

    voice = guild.voice_client
    if voice:
        if not voice.is_connected():
            await voice.disconnect(force=True)
            voice = None
        else:
            return voice

    for attempt in range(3):
        try:
            voice = await vc_channel.connect(timeout=20, reconnect=False)
            print(f"✅ Conectado a {vc_channel.name}")
            return voice
        except discord.errors.ConnectionClosed as e:
            # 4006 = sesión vieja todavía activa en Discord — esperar y reintentar
            print(f"⚠️ ConnectionClosed (intento {attempt+1}): {e} — esperando 3s")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"❌ Error conectando a voz: {type(e).__name__}: {e}")
            return None

    print("❌ No se pudo conectar a voz después de 3 intentos")
    return None


async def stop_radio(guild: discord.Guild):
    global _radio_retries
    _radio_retries = 0
    voice = guild.voice_client
    if not voice:
        return
    if voice.is_playing():
        voice.stop()
    await asyncio.sleep(0.3)
    try:
        await voice.disconnect(force=True)
    except Exception:
        pass
    print("🔇 Radio detenida")


async def start_radio(guild: discord.Guild, station: int = 0):
    global _current_station, _radio_retries, _stopping_manually

    lock = _get_radio_lock()
    if lock.locked():
        print("⚠️ start_radio ya en progreso, ignorando llamada duplicada")
        return

    async with lock:
        if _radio_retries >= MAX_RADIO_RETRIES:
            print("❌ Todas las estaciones fallaron — cancelando radio")
            _radio_retries = 0
            return

        _current_station = station % len(RADIO_STATIONS)
        name, stream_url = RADIO_STATIONS[_current_station]

        voice = await get_voice(guild)
        if not voice:
            return

        if voice.is_playing():
            _stopping_manually = True
            voice.stop()
            await asyncio.sleep(0.3)
            _stopping_manually = False

        print(f"🎵 Conectando a: {name} ({stream_url})")

        def after_play(error):
            global _radio_retries, _stopping_manually
            if _stopping_manually:
                return  # manual station change in progress — don't auto-restart
            if error:
                print(f"⚠️ Stream cortado: {type(error).__name__}: {error}")
                _radio_retries += 1
            else:
                _radio_retries = 0
            g = bot.get_guild(GUILD_ID)
            if g and focus_humans(g):
                next_s = (_current_station + 1) % len(RADIO_STATIONS)
                asyncio.run_coroutine_threadsafe(start_radio(g, next_s), bot.loop)

        try:
            source = discord.FFmpegPCMAudio(
                stream_url,
                executable=FFMPEG_PATH,
                before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 10 -nostdin",
                options="-vn -ar 48000 -ac 2 -b:a 128k"
            )
            voice.play(discord.PCMVolumeTransformer(source, volume=0.5), after=after_play)
            _radio_retries = 0
            print(f"✅ Reproduciendo: {name}")
        except Exception as e:
            import traceback
            print(f"❌ Error al reproducir {name}: {type(e).__name__}: {e}")
            traceback.print_exc()
            _radio_retries += 1
            await asyncio.sleep(2)
            next_s = (_current_station + 1) % len(RADIO_STATIONS)
        else:
            return

    # Retry outside the lock so the lock is released before recursing
    await start_radio(guild, next_s)


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return
    guild = member.guild

    if after.channel and after.channel.id == VC_FOCUS:
        print(f"👤 {member.display_name} entró a Focus")
        voice = guild.voice_client
        if not voice or not voice.is_playing():
            await start_radio(guild, _current_station)

    if before.channel and before.channel.id == VC_FOCUS:
        if not focus_humans(guild):
            print("👤 Focus vacío — deteniendo radio")
            await stop_radio(guild)


# ─── TAREAS PROGRAMADAS ───────────────────────────────────────────────────────

@tasks.loop(time=time(9, 0, tzinfo=TZ))
async def daily_standup():
    if datetime.now(TZ).weekday() >= 5:
        return
    canal = bot.get_channel(CH_DAILY)
    if not canal:
        return
    embed = discord.Embed(
        title="☕ Daily Standup",
        description=(
            "Buenos días equipo! Hora del standup diario.\n\n"
            "Respondé en un hilo con:\n"
            "1️⃣ **¿Qué hice ayer?**\n"
            "2️⃣ **¿Qué voy a hacer hoy?**\n"
            "3️⃣ **¿Tengo algún blocker?**"
        ),
        color=discord.Color.orange(),
        timestamp=datetime.now(TZ)
    )
    msg = await canal.send(embed=embed)
    await msg.create_thread(name=f"Standup {datetime.now(TZ).strftime('%d/%m/%Y')}")


@tasks.loop(time=[time(9, 0, tzinfo=TZ), time(9, 30, tzinfo=TZ)])
async def reunion_semanal():
    now = datetime.now(TZ)
    weekday = now.weekday()  # 0=lunes, 1=martes, 2=miércoles, 3=jueves, 4=viernes
    hora = now.hour
    minuto = now.minute

    # Lunes, Martes, Jueves, Viernes a las 9:00
    if weekday in [0, 1, 3, 4] and hora == 9 and minuto == 0:
        canal = bot.get_channel(CH_RECORDATORIOS)
        if canal:
            await canal.send(
                "📅 **Recordatorio — Reunión de equipo**\n"
                "Súmense a 🎤 **Reuniones** cuando estén listos! @here"
            )

    # Miércoles a las 9:30
    elif weekday == 2 and hora == 9 and minuto == 30:
        canal = bot.get_channel(CH_RECORDATORIOS)
        if canal:
            await canal.send(
                "📅 **Recordatorio — Reunión de equipo**\n"
                "Súmense a 🎤 **Reuniones** cuando estén listos! @here"
            )


@tasks.loop(time=time(10, 0, tzinfo=TZ))
async def foto_del_viernes():
    if datetime.now(TZ).weekday() != 4:
        return
    canal = bot.get_channel(CH_FOTO_VIERNES)
    if not canal:
        return
    await canal.send(
        "📸 **¡Es viernes!**\n"
        "Mandá una foto de donde estás trabajando hoy. "
        "Home office, café, playa... ¡lo que sea! 🌍"
    )


@tasks.loop(time=time(12, 0, tzinfo=TZ))
async def hilo_comida():
    if datetime.now(TZ).weekday() >= 5:
        return
    canal = bot.get_channel(CH_COMIENDO)
    if not canal:
        return
    msg = await canal.send(
        f"🍽️ **¿Qué estás comiendo hoy?** — {datetime.now(TZ).strftime('%d/%m')}\n"
        "Mandá foto, describilo, o mandá lo que pediste. ¡El canal más importante del servidor!"
    )
    await msg.create_thread(name=f"Comida del {datetime.now(TZ).strftime('%d/%m/%Y')}")


@tasks.loop(time=time(18, 0, tzinfo=TZ))
async def ranking_semanal():
    # Solo los viernes
    if datetime.now(TZ).weekday() != 4:
        return
    guild = bot.get_guild(GUILD_ID)
    canal = bot.get_channel(CH_GENERAL)
    if not canal or not guild:
        return

    data = cargar_puntos()
    if not data:
        return

    sorted_users = sorted(data.items(), key=lambda x: x[1], reverse=True)[:5]
    lines = []
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, (uid, pts) in enumerate(sorted_users):
        member = guild.get_member(int(uid))
        name = member.display_name if member else f"Usuario {uid}"
        lines.append(f"{medals[i]} **{name}** — {pts} pts")

    embed = discord.Embed(
        title="🏆 Ranking semanal de participación",
        description="\n".join(lines),
        color=discord.Color.gold(),
        timestamp=datetime.now(TZ)
    )
    embed.set_footer(text="Los puntos se reinician el lunes")
    await canal.send(embed=embed)

    # Reiniciar puntos
    guardar_puntos({})


@tasks.loop(minutes=10)
async def notion_watcher():
    if not NOTION_TOKEN:
        return
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    since = (datetime.now(pytz.utc) - timedelta(minutes=11)).isoformat()
    payload = {
        "filter": {"timestamp": "last_edited_time", "last_edited_time": {"after": since}},
        "sort": {"direction": "descending", "timestamp": "last_edited_time"}
    }
    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.notion.com/v1/search", headers=headers, json=payload) as resp:
            if resp.status != 200:
                return
            data = await resp.json()

    canal = bot.get_channel(CH_RECORDATORIOS)
    if not canal:
        return

    if not hasattr(bot, "_notified_pages"):
        bot._notified_pages = set()

    for page in data.get("results", []):
        page_id = page["id"]
        if page_id in bot._notified_pages:
            continue
        bot._notified_pages.add(page_id)

        props = page.get("properties", {})
        title_prop = props.get("title") or props.get("Name") or props.get("Page") or {}
        title_list = title_prop.get("title", []) if isinstance(title_prop, dict) else []
        title = title_list[0].get("plain_text", "Sin título") if title_list else "Sin título"

        embed = discord.Embed(
            title="📝 Página de Notion actualizada",
            description=f"**{title}**",
            color=discord.Color.blurple(),
            url=page.get("url", "")
        )
        embed.set_footer(text="Notion")
        await canal.send(embed=embed)


# ─── COMANDOS SLASH ───────────────────────────────────────────────────────────

@bot.tree.command(name="mirol", description="Elegí tu área de trabajo", guild=discord.Object(id=GUILD_ID))
@app_commands.choices(area=[
    app_commands.Choice(name="🎨 Design", value="design"),
    app_commands.Choice(name="💻 Dev", value="dev"),
    app_commands.Choice(name="📣 Marketing", value="marketing"),
])
async def mirol(interaction: discord.Interaction, area: app_commands.Choice[str]):
    guild = interaction.guild
    member = interaction.user

    # Quitar roles de área anteriores
    for key, rid in ROLES_AREA.items():
        if key == "miembro":
            continue
        rol = guild.get_role(rid)
        if rol and rol in member.roles:
            await member.remove_roles(rol)

    # Asignar nuevo rol
    nuevo_rol = guild.get_role(ROLES_AREA[area.value])
    if nuevo_rol:
        await member.add_roles(nuevo_rol)
        await interaction.response.send_message(
            f"✅ Rol **{area.name}** asignado!", ephemeral=True
        )


@bot.tree.command(name="anuncio", description="Publicar un anuncio en #anuncios (solo Admins)", guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_role("Admin")
async def anuncio(interaction: discord.Interaction, mensaje: str):
    canal = bot.get_channel(CH_ANUNCIOS)
    embed = discord.Embed(
        description=mensaje,
        color=discord.Color.gold(),
        timestamp=datetime.now(TZ)
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    await canal.send(embed=embed)
    await interaction.response.send_message("✅ Anuncio publicado.", ephemeral=True)


@bot.tree.command(name="recordatorio", description="Programar un recordatorio", guild=discord.Object(id=GUILD_ID))
async def recordatorio(interaction: discord.Interaction, mensaje: str, minutos: int):
    await interaction.response.send_message(
        f"⏰ Te recuerdo en {minutos} minutos.", ephemeral=True
    )
    await asyncio.sleep(minutos * 60)
    canal = bot.get_channel(CH_RECORDATORIOS)
    await canal.send(f"⏰ **Recordatorio** de {interaction.user.mention}:\n{mensaje}")


@bot.tree.command(name="win", description="Compartir un logro del equipo", guild=discord.Object(id=GUILD_ID))
async def win(interaction: discord.Interaction, logro: str):
    embed = discord.Embed(
        title="🏆 Nuevo Win!",
        description=logro,
        color=discord.Color.yellow()
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    canal = bot.get_channel(CH_WINS)
    await canal.send(embed=embed)
    await interaction.response.send_message("🎉 Win publicado!", ephemeral=True)


@bot.tree.command(name="ruleta", description="¿Quién paga el café hoy?", guild=discord.Object(id=GUILD_ID))
async def ruleta(interaction: discord.Interaction):
    guild = interaction.guild
    members = [m for m in guild.members if not m.bot]
    elegido = random.choice(members)
    await interaction.response.send_message(
        f"☕ La ruleta giró y el resultado es...\n\n"
        f"## {elegido.mention} paga el café hoy! 🎰\n"
        f"No hay excusas. ¡A prepararlo!"
    )


@bot.tree.command(name="dado", description="Tirar un dado para resolver debates internos", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(opciones="Opciones separadas por coma. Ej: pizza, sushi, hamburguesa")
async def dado(interaction: discord.Interaction, opciones: str):
    lista = [o.strip() for o in opciones.split(",") if o.strip()]
    if len(lista) < 2:
        await interaction.response.send_message("Necesitás al menos 2 opciones separadas por coma.", ephemeral=True)
        return
    resultado = random.choice(lista)
    await interaction.response.send_message(
        f"🎲 El dado tiró y la respuesta es...\n\n## **{resultado}**\n\nNo se discute más. ¡Caso cerrado!"
    )


@bot.tree.command(name="chiste", description="Un chiste malo garantizado", guild=discord.Object(id=GUILD_ID))
async def chiste(interaction: discord.Interaction):
    await interaction.response.send_message(random.choice(CHISTES))


@bot.tree.command(name="puntos", description="Ver tus puntos de participación", guild=discord.Object(id=GUILD_ID))
async def puntos(interaction: discord.Interaction):
    data = cargar_puntos()
    mis_puntos = data.get(str(interaction.user.id), 0)
    sorted_users = sorted(data.items(), key=lambda x: x[1], reverse=True)
    posicion = next((i + 1 for i, (uid, _) in enumerate(sorted_users) if uid == str(interaction.user.id)), "?")
    await interaction.response.send_message(
        f"⭐ Tenés **{mis_puntos} puntos** de participación esta semana.\n"
        f"Estás en el puesto **#{posicion}** del ranking.",
        ephemeral=True
    )


@bot.tree.command(name="musica", description="Arrancar la música en Focus manualmente", guild=discord.Object(id=GUILD_ID))
async def musica(interaction: discord.Interaction):
    await interaction.response.send_message("🎵 Arrancando radio en 🎧 Focus...", ephemeral=True)
    await start_radio(interaction.guild)


@bot.tree.command(name="radio", description="Cambiar la estación de radio del Focus Room", guild=discord.Object(id=GUILD_ID))
@app_commands.choices(estacion=[
    app_commands.Choice(name="🌿 Groove Salad", value="0"),
    app_commands.Choice(name="🎷 Radio Swiss Jazz", value="1"),
    app_commands.Choice(name="🎹 Lush", value="2"),
])
async def radio(interaction: discord.Interaction, estacion: app_commands.Choice[str]):
    await start_radio(interaction.guild, int(estacion.value))
    await interaction.response.send_message(
        f"🎵 Cambiando a **{estacion.name}** en 🎧 Focus...", ephemeral=True
    )


@bot.tree.command(name="volumen", description="Cambiar el volumen de la radio (0-100)", guild=discord.Object(id=GUILD_ID))
async def volumen(interaction: discord.Interaction, nivel: int):
    voice = interaction.guild.voice_client
    if voice and voice.source:
        voice.source.volume = max(0, min(nivel, 100)) / 100
        await interaction.response.send_message(f"🔊 Volumen: {nivel}%", ephemeral=True)
    else:
        await interaction.response.send_message("No hay radio reproduciéndose.", ephemeral=True)


bot.run(TOKEN)
