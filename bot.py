import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import os
import asyncio
from datetime import datetime, time
import pytz

TOKEN = os.environ["DISCORD_TOKEN"]
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
GUILD_ID = 1506296906509193256

FFMPEG_PATH = os.path.join(os.path.dirname(__file__), "ffmpeg")

# Radios chill/jazz — rota entre ellas si alguna falla
RADIO_STATIONS = [
    "https://ice1.somafm.com/jazzgroove-128-mp3",   # Jazz Groove
    "https://ice1.somafm.com/groovesalad-128-mp3",  # Groove Salad (ambient/chill)
    "https://ice1.somafm.com/lush-128-mp3",          # Lush (chillout)
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

TZ = pytz.timezone("America/Argentina/Buenos_Aires")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ─── EVENTOS ──────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user}")
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    daily_standup.start()
    foto_del_viernes.start()
    hilo_comida.start()
    notion_watcher.start()
    radio_watchdog.start()
    print("✅ Tareas programadas iniciadas")
    await asyncio.sleep(3)
    await start_radio()


async def start_radio(station_index: int = 0):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    vc_channel = guild.get_channel(VC_FOCUS)
    if not vc_channel:
        return

    # Conectar al canal de voz si no está ya
    voice = guild.voice_client
    if not voice or not voice.is_connected():
        try:
            voice = await vc_channel.connect()
            print(f"🎵 Conectado a {vc_channel.name}")
        except Exception as e:
            print(f"❌ Error conectando a voz: {e}")
            return

    if voice.is_playing():
        return

    url = RADIO_STATIONS[station_index % len(RADIO_STATIONS)]

    def after_play(error):
        if error:
            print(f"⚠️ Error en radio: {error}")
        # Reconectar automáticamente al terminar o fallar
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
    # Reiniciar si el bot está conectado pero no reproduciendo
    if voice and voice.is_connected() and not voice.is_playing():
        print("🔄 Radio detenida, reiniciando...")
        await start_radio()
    # Reconectar si se desconectó
    elif not voice or not voice.is_connected():
        print("🔄 Bot desconectado del canal de voz, reconectando...")
        await start_radio()


@bot.event
async def on_member_join(member: discord.Member):
    canal = bot.get_channel(CH_GENERAL)
    if canal:
        embed = discord.Embed(
            title=f"¡Bienvenido/a al equipo, {member.display_name}! 🎉",
            description=(
                f"Hola {member.mention}! Estamos contentos de que estés acá.\n\n"
                "**Canales para arrancar:**\n"
                "👋 `#general` — presentate\n"
                "📢 `#anuncios` — info importante\n"
                "☕ `#daily` — standup diario\n"
                "🎉 `#wins` — celebrá los logros\n\n"
                "Pedile a un Admin que te asigne tu rol de área."
            ),
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await canal.send(embed=embed)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Detectar "urgente" y responder dramáticamente
    if "urgente" in message.content.lower():
        await message.add_reaction("🚨")
        await message.reply(
            "🚨 **ALERTA URGENTE** 🚨\n"
            f"{message.author.mention} necesita atención inmediata. ¡Todos al canal!"
        )

    await bot.process_commands(message)


# ─── TAREAS PROGRAMADAS ───────────────────────────────────────────────────────

@tasks.loop(time=time(9, 0, tzinfo=TZ))  # 9:00 AM todos los días
async def daily_standup():
    if datetime.now(TZ).weekday() >= 5:  # saltar finde
        return
    canal = bot.get_channel(CH_DAILY)
    if canal:
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


@tasks.loop(time=time(10, 0, tzinfo=TZ))  # 10:00 AM los viernes
async def foto_del_viernes():
    if datetime.now(TZ).weekday() != 4:  # solo viernes
        return
    canal = bot.get_channel(CH_FOTO_VIERNES)
    if canal:
        await canal.send(
            "📸 **¡Es viernes!**\n"
            "Mandá una foto de donde estás trabajando hoy. "
            "Home office, café, playa... ¡lo que sea! 🌍"
        )


@tasks.loop(time=time(12, 0, tzinfo=TZ))  # 12:00 PM todos los días
async def hilo_comida():
    if datetime.now(TZ).weekday() >= 5:
        return
    canal = bot.get_channel(CH_COMIENDO)
    if canal:
        msg = await canal.send(
            f"🍽️ **¿Qué estás comiendo hoy?** — {datetime.now(TZ).strftime('%d/%m')}\n"
            "Mandá foto, describilo, o mandá lo que pediste. ¡El canal más importante del servidor!"
        )
        await msg.create_thread(name=f"Comida del {datetime.now(TZ).strftime('%d/%m/%Y')}")


@tasks.loop(minutes=10)  # revisa Notion cada 10 minutos
async def notion_watcher():
    await check_notion_updates()


async def check_notion_updates():
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    # Busca páginas modificadas en los últimos 10 minutos
    from datetime import timedelta
    since = (datetime.now(pytz.utc) - timedelta(minutes=11)).isoformat()

    payload = {
        "filter": {
            "timestamp": "last_edited_time",
            "last_edited_time": {"after": since}
        },
        "sort": {"direction": "descending", "timestamp": "last_edited_time"}
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.notion.com/v1/search",
            headers=headers,
            json=payload
        ) as resp:
            if resp.status != 200:
                return
            data = await resp.json()

    canal = bot.get_channel(CH_RECORDATORIOS)
    if not canal:
        return

    for page in data.get("results", []):
        page_id = page["id"]

        # Evitar notificar la misma página dos veces
        if not hasattr(bot, "_notified_pages"):
            bot._notified_pages = set()
        if page_id in bot._notified_pages:
            continue
        bot._notified_pages.add(page_id)

        # Obtener título
        props = page.get("properties", {})
        title_prop = props.get("title") or props.get("Name") or props.get("Page") or {}
        title_list = title_prop.get("title", []) if isinstance(title_prop, dict) else []
        title = title_list[0].get("plain_text", "Sin título") if title_list else "Sin título"

        url = page.get("url", "")
        editor = page.get("last_edited_by", {}).get("id", "alguien")

        embed = discord.Embed(
            title="📝 Página de Notion actualizada",
            description=f"**{title}**",
            color=discord.Color.blurple(),
            url=url
        )
        embed.set_footer(text="Notion")
        await canal.send(embed=embed)


# ─── COMANDOS SLASH ───────────────────────────────────────────────────────────

@bot.tree.command(name="anuncio", description="Publicar un anuncio en #anuncios", guild=discord.Object(id=GUILD_ID))
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


@bot.tree.command(name="recordatorio", description="Programar un recordatorio en #recordatorios", guild=discord.Object(id=GUILD_ID))
async def recordatorio(interaction: discord.Interaction, mensaje: str, minutos: int):
    await interaction.response.send_message(
        f"⏰ Recordatorio programado en {minutos} minutos.", ephemeral=True
    )
    await asyncio.sleep(minutos * 60)
    canal = bot.get_channel(CH_RECORDATORIOS)
    await canal.send(
        f"⏰ **Recordatorio** de {interaction.user.mention}:\n{mensaje}"
    )


@bot.tree.command(name="win", description="Compartir un logro del equipo", guild=discord.Object(id=GUILD_ID))
async def win(interaction: discord.Interaction, logro: str):
    canal = bot.get_channel(1506316418063401051)  # #wins
    embed = discord.Embed(
        title="🏆 Nuevo Win!",
        description=logro,
        color=discord.Color.yellow()
    )
    embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    await canal.send(embed=embed)
    await interaction.response.send_message("🎉 Win publicado!", ephemeral=True)


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
