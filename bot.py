import discord
from discord.ext import commands, tasks
import subprocess
import os
import re
import psutil
import time
import requests
import asyncio
from datetime import datetime

try:
    from mcstatus import JavaServer
    MCSTATUS_AVAILABLE = True
except ImportError:
    MCSTATUS_AVAILABLE = False

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ================= CONFIGURACIÓN =================
OWNER_NAME = "dyronis_71572"
PLAYIT_FILE = "playit.tunnels"
JAVA_PORT = 25565
BEDROCK_PORT = 19132
AUTO_SHUTDOWN_MINUTES = 15
TMUX_SESSION = "mc-server"
LOG_FILE = "bot_debug.log"

server_start_time = None
minutes_empty = 0

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def hay_tmux():
    try:
        subprocess.run(['tmux', '-V'], capture_output=True, check=True)
        return True
    except:
        return False

def servidor_java_activo():
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            name = proc.info['name'] or ''
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'java' in name.lower():
                if any(x in cmdline.lower() for x in ['minecraft', 'paper', 'bukkit', 'spigot', 'minified_py']):
                    return True
        except:
            continue
    return False

def leer_ips_playit():
    if not os.path.exists(PLAYIT_FILE):
        return None, None
    try:
        with open(PLAYIT_FILE, 'r', encoding='utf-8') as f:
            contenido = f.read()
        java_ip, bedrock_ip = None, None
        for linea in contenido.split('\n'):
            if '=>' not in linea or '127.0.0.1' not in linea: continue
            partes = linea.split('=>')
            if len(partes) != 2: continue
            tunnel = partes[0].strip()
            destino = partes[1].strip()
            match = re.search(r':(\d+)$', destino)
            if not match: continue
            puerto = int(match.group(1))
            tunnel = re.sub(r'^[│●\s]+', '', tunnel).strip()
            if '.' not in tunnel or 'playit' not in tunnel.lower(): continue
            if puerto == JAVA_PORT:
                java_ip = tunnel.rsplit(':', 1)[0] if ':' in tunnel and tunnel.split(':')[-1] == str(JAVA_PORT) else tunnel
            elif puerto == BEDROCK_PORT:
                bedrock_ip = f"{tunnel}:{BEDROCK_PORT}" if ':' not in tunnel else tunnel
        return java_ip, bedrock_ip
    except Exception as e:
        log(f"❌ Error parseando túneles: {e}")
        return None, None

# ================= TAREAS AUTOMÁTICAS =================

@tasks.loop(minutes=1)
async def auto_manager():
    global minutes_empty
    activo = servidor_java_activo()
    
    if activo:
        players = 0
        if MCSTATUS_AVAILABLE:
            try:
                players = JavaServer.lookup(f"localhost:{JAVA_PORT}").status().players.online
            except: pass
        
        if players == 0:
            minutes_empty += 1
            if minutes_empty >= AUTO_SHUTDOWN_MINUTES:
                log(f"⏰ {minutes_empty} min sin jugadores. Apagando...")
                await ejecutar_stop("🤖 Auto-apagado (15 min vacío)")
                minutes_empty = 0
            elif minutes_empty % 5 == 0:
                log(f"⚠️ Vacío. Apagado en {AUTO_SHUTDOWN_MINUTES - minutes_empty} min.")
        else:
            if minutes_empty > 0:
                log(f"👥 Jugadores detectados. Contador reiniciado.")
                minutes_empty = 0
    else:
        if minutes_empty > 0:
            minutes_empty = 0
            log("🛑 Servidor apagado externamente. Contador reseteado.")

@tasks.loop(minutes=5)
async def keep_alive():
    try: requests.get("https://www.google.com", timeout=5)
    except: pass

@bot.event
async def on_ready():
    if not hay_tmux():
        log("⚠️ AVISO: tmux no detectado. Instala con: sudo apt update && sudo apt install tmux")
    log(f'✅ Bot listo: {bot.user}')
    keep_alive.start()
    auto_manager.start()

# ================= COMANDOS =================

@bot.command(name='start', aliases=['iniciar', 'encender'])
async def start(ctx):
    if servidor_java_activo():
        await ctx.send("⚠️ El servidor de Minecraft YA está corriendo (proceso Java detectado).")
        return

    # Limpiar sesión anterior si existe
    subprocess.run(['tmux', 'kill-session', '-t', TMUX_SESSION], capture_output=True)
    if os.path.exists(PLAYIT_FILE):
        os.remove(PLAYIT_FILE)
    
    await ctx.send("🚀 Iniciando MSX en terminal virtual... (espera ~40s)")
    log("📡 Iniciando sesión tmux...")
    
    try:
        # 1. Crear sesión tmux en segundo plano
        subprocess.Popen(['tmux', 'new-session', '-d', '-s', TMUX_SESSION, 'python3', 'msx.py'])
        await asyncio.sleep(6) # Esperar a que cargue el menú
        
        # 2. Enviar "1" + Enter a la sesión tmux
        subprocess.run(['tmux', 'send-keys', '-t', TMUX_SESSION, '1', 'Enter'])
        log("✅ Tecla '1' enviada a MSX.")
        
        # 3. Esperar a que Java levante y play.it genere túneles
        await ctx.send("⏳ Cargando servidor y túneles... (~30s)")
        await asyncio.sleep(30)
        
        # 4. Verificar túneles
        for _ in range(6):
            j_ip, b_ip = leer_ips_playit()
            if j_ip or b_ip:
                msg = "✅ **¡Servidor Listo!**\n"
                if j_ip: msg += f"🖥️ Java: `{j_ip}`\n"
                if b_ip: msg += f"📱 Bedrock: `{b_ip}`"
                await ctx.send(msg)
                log(f"🎉 Túneles OK: Java={j_ip}, Bedrock={b_ip}")
                return
            await asyncio.sleep(5)
            
        await ctx.send("⚠️ Servidor iniciado pero play.it tarda en generar túneles. Usa `!ips` en 1 min.")
        
    except Exception as e:
        log(f"❌ Error en !start: {e}")
        await ctx.send(f"❌ Error: `{e}`")

@bot.command(name='estado', aliases=['status', 'info'])
async def estado(ctx):
    activo = servidor_java_activo()
    j_ip, b_ip = leer_ips_playit()
    
    embed = discord.Embed(title="🎮 Estado MSX", color=0x00ff00 if activo else 0xff0000)
    embed.add_field(name="Servidor", value="✅ Online" if activo else "❌ Offline", inline=False)
    
    if activo:
        global server_start_time
        if server_start_time is None: server_start_time = datetime.now()
        embed.add_field(name="⏱️ Uptime", value=str(datetime.now() - server_start_time).split('.')[0], inline=True)
        
        players = 0
        if MCSTATUS_AVAILABLE:
            try: players = JavaServer.lookup(f"localhost:{JAVA_PORT}").status().players.online
            except: pass
        embed.add_field(name="👥 Jugadores", value=f"{players} conectados", inline=True)
        
        if players == 0 and minutes_empty > 0:
            embed.add_field(name="⏳ Auto-stop en", value=f"{max(0, AUTO_SHUTDOWN_MINUTES - minutes_empty)} min", inline=False)

    conex = ""
    if j_ip: conex += f"🖥️ Java: `{j_ip}`\n"
    elif activo: conex += f"🖥️ Java: `localhost:{JAVA_PORT}`\n"
    if b_ip: conex += f"📱 Bedrock: `{b_ip}`\n"
    elif activo: conex += f"📱 Bedrock: `localhost:{BEDROCK_PORT}`\n"
    
    embed.add_field(name="🌐 Conexión", value=conex if conex else "⏳ Esperando túneles...", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='ips')
async def ips(ctx):
    await ctx.send("🔄 Buscando túneles de play.it...")
    for _ in range(8):
        j, b = leer_ips_playit()
        if j or b:
            msg = "🌐 **IPs Encontradas:**\n"
            if j: msg += f"🖥️ `{j}`\n"
            if b: msg += f"📱 `{b}`"
            await ctx.send(msg)
            return
        await asyncio.sleep(5)
    await ctx.send("❌ No se encontraron túneles. El servidor puede estar cargando aún.")

@bot.command(name='stop', aliases=['apagar', 'cerrar', 'bajar'])
async def stop(ctx):
    if ctx.author.name != OWNER_NAME:
        await ctx.send("🔒 Solo `dyronis_71572` puede apagar el servidor.")
        return
    await ctx.send("🛑 Deteniendo servidor...")
    await ejecutar_stop(f"👤 Comando de {ctx.author.name}")

async def ejecutar_stop(reason):
    global server_start_time, minutes_empty
    log(f"🛑 Stop ejecutado: {reason}")
    
    # 1. Matar sesión tmux
    subprocess.run(['tmux', 'kill-session', '-t', TMUX_SESSION], capture_output=True)
    
    # 2. Matar procesos Java/Minecraft huérfanos
    for proc in psutil.process_iter(['name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'java' in (proc.info['name'] or '').lower() and any(x in cmdline.lower() for x in ['minecraft', 'paper', 'spigot']):
                proc.kill()
        except: pass
    
    server_start_time = None
    minutes_empty = 0
    log("✅ Servidor detenido limpiamente.")

# ================= INICIO =================
if __name__ == "__main__":
    bot.run('')
