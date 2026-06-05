import discord
from discord.ext import commands
import yt_dlp
import asyncio
import random
import os

# Opcje dla yt-dlp
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
}

# Opcje dla yt-dlp – playlista
YDL_OPTIONS_PLAYLIST = {
    'format': 'bestaudio/best',
    'noplaylist': False,
    'quiet': True,
    'extract_flat': True,
}

# Opcje dla FFmpeg
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn',
}

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents)

queues = {}
last_played = {}
played_history = {}
autoplay_enabled = {}

SEARCH_SUFFIXES = [
    "official video",
    "music video",
    "live",
    "lyrics",
    "acoustic",
    "remix",
    "cover",
]


def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = []
    return queues[guild_id]


def get_history(guild_id):
    if guild_id not in played_history:
        played_history[guild_id] = []
    return played_history[guild_id]


async def get_related(url: str, guild_id: int):
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
    }
    history = get_history(guild_id)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', '')
            artist = info.get('uploader', '')
            clean_title = title.split('(')[0].split('[')[0].strip()

            search_queries = [
                f"ytsearch5:{clean_title} similar",
                f"ytsearch5:{artist} inne utwory",
                f"ytsearch5:{clean_title} {random.choice(SEARCH_SUFFIXES)}",
            ]

            for query in search_queries:
                result = ydl.extract_info(query, download=False)
                if not result or 'entries' not in result:
                    continue

                for entry in result['entries']:
                    if not entry:
                        continue
                    found_url = entry.get('webpage_url') or entry.get('url', '')
                    found_title = entry.get('title', '')

                    if found_url == url:
                        continue
                    if any(found_title == h for h in history):
                        continue

                    print(f"Autoplay znalazł: {found_title}")
                    return found_url

    except Exception as e:
        print(f"Błąd autoplay: {e}")

    return None


async def play_next(ctx):
    queue = get_queue(ctx.guild.id)

    if not queue:
        if not autoplay_enabled.get(ctx.guild.id, True):
            await ctx.send("⏹️ Kolejka jest pusta.")
            return

        last_url = last_played.get(ctx.guild.id)
        if last_url:
            await ctx.send("🔀 Kolejka pusta – szukam następnego utworu...")
            next_url = await get_related(last_url, ctx.guild.id)
            if next_url:
                queue.append(next_url)
            else:
                await ctx.send("⏹️ Nie znalazłem nic nowego, kończę.")
                return
        else:
            await ctx.send("⏹️ Kolejka jest pusta.")
            return

    url = queue.pop(0)
    last_played[ctx.guild.id] = url

    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        stream_url = info['url']
        title = info.get('title', 'Nieznany tytuł')

    history = get_history(ctx.guild.id)
    history.append(title)
    if len(history) > 20:
        history.pop(0)

    source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)

    def after_playing(error):
        if error:
            print(f"Błąd odtwarzania: {error}")
        fut = asyncio.run_coroutine_threadsafe(play_next(ctx), bot.loop)
        try:
            fut.result()
        except Exception as e:
            print(f"Błąd po zakończeniu: {e}")

    ctx.voice_client.play(source, after=after_playing)
    await ctx.send(f"▶️ Teraz gram: **{title}**")


@bot.event
async def on_ready():
    print(f"Bot uruchomiony jako {bot.user}")


@bot.command(name='play', aliases=['p'])
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        return await ctx.send("❌ Musisz być na kanale głosowym!")

    channel = ctx.author.voice.channel

    if ctx.voice_client is None:
        await channel.connect()
    elif ctx.voice_client.channel != channel:
        await ctx.voice_client.move_to(channel)

    if not query.startswith('http'):
        query = f"ytsearch:{query}"

    queue = get_queue(ctx.guild.id)
    queue.append(query)
    await ctx.send(f"✅ Dodano do kolejki: `{query}`")

    if not ctx.voice_client.is_playing():
        await play_next(ctx)


@bot.command(name='playlist', aliases=['pl'])
async def playlist(ctx, *, url: str):
    if not ctx.author.voice:
        return await ctx.send("❌ Musisz być na kanale głosowym!")

    if not url.startswith('http'):
        return await ctx.send("❌ Podaj pełny link do playlisty YouTube.")

    channel = ctx.author.voice.channel

    if ctx.voice_client is None:
        await channel.connect()
    elif ctx.voice_client.channel != channel:
        await ctx.voice_client.move_to(channel)

    await ctx.send("⏳ Wczytuję playlistę, chwilka...")

    try:
        with yt_dlp.YoutubeDL(YDL_OPTIONS_PLAYLIST) as ydl:
            info = ydl.extract_info(url, download=False)

            if 'entries' not in info:
                return await ctx.send("❌ Nie znalazłem żadnych utworów w tej playliście.")

            entries = [e for e in info['entries'] if e]
            queue = get_queue(ctx.guild.id)

            for entry in entries:
                video_url = entry.get('url') or entry.get('webpage_url')
                if video_url:
                    if not video_url.startswith('http'):
                        video_url = f"https://www.youtube.com/watch?v={video_url}"
                    queue.append(video_url)

            playlist_title = info.get('title', 'Nieznana playlista')
            await ctx.send(f"✅ Dodano **{len(entries)}** utworów z playlisty **{playlist_title}** do kolejki!")

    except Exception as e:
        print(f"Błąd playlisty: {e}")
        return await ctx.send("❌ Nie udało się wczytać playlisty.")

    if not ctx.voice_client.is_playing():
        await play_next(ctx)


@bot.command(name='skip', aliases=['s'])
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭️ Pominięto.")
    else:
        await ctx.send("❌ Nic nie gra.")


@bot.command(name='stop')
async def stop(ctx):
    if ctx.voice_client:
        queues[ctx.guild.id] = []
        played_history[ctx.guild.id] = []
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        await ctx.send("⏹️ Zatrzymano i rozłączono.")


@bot.command(name='queue', aliases=['q'])
async def show_queue(ctx):
    queue = get_queue(ctx.guild.id)
    if not queue:
        return await ctx.send("📋 Kolejka jest pusta.")
    visible = queue[:10]
    msg = "\n".join(f"{i+1}. {url}" for i, url in enumerate(visible))
    extra = f"\n...i {len(queue) - 10} więcej" if len(queue) > 10 else ""
    await ctx.send(f"📋 Kolejka ({len(queue)} utworów):\n{msg}{extra}")


@bot.command(name='pause')
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Wstrzymano.")
    else:
        await ctx.send("❌ Nic nie gra.")


@bot.command(name='resume')
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Wznowiono.")
    else:
        await ctx.send("❌ Nic nie jest wstrzymane.")


@bot.command(name='autoplay')
async def toggle_autoplay(ctx):
    guild_id = ctx.guild.id
    autoplay_enabled[guild_id] = not autoplay_enabled.get(guild_id, True)
    status = "włączony" if autoplay_enabled[guild_id] else "wyłączony"
    await ctx.send(f"🔀 Autoplay {status}.")


@bot.command(name='clear')
async def clear(ctx):
    queues[ctx.guild.id] = []
    await ctx.send("🗑️ Kolejka wyczyszczona.")


# Token pobierany ze zmiennej środowiskowej (bezpieczne na Railway)
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise ValueError("Brak tokenu! Ustaw zmienną środowiskową DISCORD_TOKEN na Railway.")

bot.run(TOKEN)
