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

import shutil
# En Railway usa el ffmpeg del sistema (Linux), en Mac usa el binario local
_local_ffmpeg = os.path.join(os.path.dirname(__file__), "ffmpeg")
FFMPEG_PATH = _local_ffmpeg if os.path.exists(_local_ffmpeg) and os.access(_local_ffmpeg, os.X_OK) else (shutil.which("ffmpeg") or "ffmpeg")

RADIO_STATIONS = [
    "https://ice1.somafm.com/jazzgroove-128-mp3",
    "https://ice1.somafm.com/groovesalad-128-mp3",
    "https://ice1.somafm.com/lush-128-mp3",
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
    radio_watchdog.start()
    print("✅ Tareas programadas iniciadas")
    print(f"🔧 ffmpeg path: {FFMPEG_PATH}")
    await asyncio.sleep(3)
    await start_radio()


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

async def start_radio(station_index: int = 0):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    vc_channel = guild.get_channel(VC_FOCUS)
    if not vc_channel:
        return

    voice = guild.voice_client
    if not voice or not voice.is_connected():
        try:
            voice = await vc_channel.connect()
        except Exception as e:
            print(f"❌ Error conectando a voz: {e}")
            return

    if voice.is_playing():
        return

    url = RADIO_STATIONS[station_index % len(RADIO_STATIONS)]

    def after_play(error):
        asyncio.run_coroutine_threadsafe(
            start_radio((station_index + 1) % len(RADIO_STATIONS)),
            bot.loop
        )

    ffmpeg_opts = {
        "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
        "options": "-vn -af loudnorm"
    }
    try:
        source = discord.FFmpegPCMAudio(url, executable=FFMPEG_PATH, **ffmpeg_opts)
        source = discord.PCMVolumeTransformer(source, volume=0.4)
        voice.play(source, after=after_play)
        print(f"🎵 Reproduciendo: {url}")
    except Exception as e:
        print(f"❌ Error iniciando radio: {e}")


@tasks.loop(minutes=5)
async def radio_watchdog():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    voice = guild.voice_client
    if voice and voice.is_connected() and not voice.is_playing():
        await start_radio()
    elif not voice or not voice.is_connected():
        await start_radio()


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


@bot.tree.command(name="radio", description="Cambiar la estación de radio del Focus Room", guild=discord.Object(id=GUILD_ID))
@app_commands.choices(estacion=[
    app_commands.Choice(name="🎷 Jazz Groove", value="0"),
    app_commands.Choice(name="🌿 Groove Salad (ambient/chill)", value="1"),
    app_commands.Choice(name="🌸 Lush (chillout)", value="2"),
])
async def radio(interaction: discord.Interaction, estacion: app_commands.Choice[str]):
    guild = bot.get_guild(GUILD_ID)
    voice = guild.voice_client if guild else None
    if voice and voice.is_playing():
        voice.stop()
    await start_radio(int(estacion.value))
    await interaction.response.send_message(
        f"🎵 Cambiando a **{estacion.name}** en 🎧 Focus...", ephemeral=True
    )


@bot.tree.command(name="volumen", description="Cambiar el volumen de la radio (0-100)", guild=discord.Object(id=GUILD_ID))
async def volumen(interaction: discord.Interaction, nivel: int):
    guild = bot.get_guild(GUILD_ID)
    voice = guild.voice_client if guild else None
    if voice and voice.source:
        voice.source.volume = max(0, min(nivel, 100)) / 100
        await interaction.response.send_message(f"🔊 Volumen: {nivel}%", ephemeral=True)
    else:
        await interaction.response.send_message("No hay radio reproduciéndose.", ephemeral=True)


bot.run(TOKEN)
