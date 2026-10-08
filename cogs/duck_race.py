import asyncio
import logging
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
from .duck_race_engine import NAMES, simulate, render

DUCK_RACE_CHANNEL_ID = 1557805141795803256

ROOT = Path(__file__).resolve().parent
DB = Path(os.getenv('DUCK_RACE_DATA_DIR', str(ROOT.parent / 'data'))) / 'duck_race_results.sqlite3'
active = {}
render_gate = asyncio.Semaphore(1)

def save_results(guild, users, order):
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute('CREATE TABLE IF NOT EXISTS results (race_id TEXT, guild_id TEXT, user_id TEXT, duck INTEGER, rank INTEGER)')
        import uuid
        rid = str(uuid.uuid4())
        db.executemany('INSERT INTO results VALUES (?,?,?,?,?)', [(rid,str(guild),str(users[d]),d+1,i+1) for i,d in enumerate(order)])

async def announce_results(channel, users, labels, order, uploaded_at):
    # Use the successful upload time, rather than a viewer's playback time.
    await asyncio.sleep(max(0, uploaded_at + 35 - asyncio.get_running_loop().time()))
    ranking = '\n'.join(
        f'{i+1}위 · {discord.utils.escape_markdown(labels[d])} · <@{users[d]}>'
        for i,d in enumerate(order)
    )
    await channel.send(
        content='🏆 **오리 경주 결과**\n' + ranking,
        allowed_mentions=discord.AllowedMentions.none(),
    )

class RaceView(discord.ui.View):
    def __init__(self, owner, channel):
        super().__init__(timeout=300)
        self.owner, self.channel = owner, channel
        self.users = {}  # duck -> user ID
        self.labels = {}  # user ID -> server display name snapshot
        self.lock = asyncio.Lock()
        self.started = False
        self.message = None
        self.add_item(DuckSelect())

    def content(self):
        entries = '\n'.join(f'{d+1:02}. {NAMES[d]} — <@{u}>' for d,u in sorted(self.users.items()))
        return f'🦆 **꽥꽥 그랑프리** · {len(self.users)}/10명\n오리를 선택하세요. 선택을 바꾸거나 참가 취소할 수 있습니다.\n방장이 시작하며, 5분간 입력이 없으면 모집이 종료됩니다.\n{entries}'

    async def close(self, text):
        self.started = True
        self.stop()
        for item in self.children:
            item.disabled = True
        active.pop(self.channel, None)
        if self.message:
            await self.message.edit(content=text, view=self)

    async def on_timeout(self):
        async with self.lock:
            if not self.started:
                await self.close('모집 시간이 만료되었습니다. `/오리경주`로 다시 생성하세요.')

    @discord.ui.button(label='참가 취소', style=discord.ButtonStyle.secondary, row=1)
    async def leave(self, interaction, button):
        await interaction.response.defer()
        async with self.lock:
            if self.started:
                return
            self.users = {d:u for d,u in self.users.items() if u != interaction.user.id}
            await self.message.edit(content=self.content(), view=self)

    @discord.ui.button(label='경주 시작', style=discord.ButtonStyle.success, row=1)
    async def start(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            if self.started:
                await interaction.followup.send('이미 종료되거나 시작된 경주입니다.',ephemeral=True)
                return
            if interaction.user.id != self.owner:
                await interaction.followup.send('방장만 시작할 수 있습니다.',ephemeral=True)
                return
            if len(self.users)<2:
                await interaction.followup.send('2명 이상 참가해야 합니다.',ephemeral=True)
                return
            self.started = True
            self.stop()
            for item in self.children:
                item.disabled = True
            users = self.users.copy()
            labels = {d: self.labels.get(u, f"오리 {d+1:02}") for d,u in users.items()}
        try:
            await self.message.edit(content='🏁 자동 경주 영상 생성 중입니다. 잠시 기다려 주세요.',view=self)
            async with render_gate:
                with tempfile.TemporaryDirectory(prefix='duck-race-') as temp:
                    ducks = sorted(users)
                    frames, order = simulate(ducks)
                    path = await asyncio.to_thread(render,ducks,frames,order,Path(temp)/'race.gif',labels)
                    limit = interaction.guild.filesize_limit
                    if path.stat().st_size > limit:
                        raise RuntimeError('영상이 서버 업로드 한도를 초과했습니다.')
                    await interaction.channel.send(
                        content='🏁 오리 경주 GIF입니다! 업로드 후 35초 뒤에 결과를 발표합니다.',
                        file=discord.File(path,filename='duck-race.gif'),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    uploaded_at = asyncio.get_running_loop().time()
                    await asyncio.to_thread(save_results,interaction.guild_id,users,order)
            await announce_results(interaction.channel,users,labels,order,uploaded_at)
            await self.message.edit(content='✅ 경주가 완료되었습니다. 아래 영상을 확인하세요.',view=self)
        except Exception:
            logging.exception('Race failed')
            await self.message.edit(content='경주 처리에 실패했습니다. 봇 실행 창의 오류를 확인하고 다시 생성하세요.',view=self)
        finally:
            active.pop(self.channel,None)

    @discord.ui.button(label='모집 종료', style=discord.ButtonStyle.danger, row=1)
    async def cancel(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            if interaction.user.id != self.owner:
                await interaction.followup.send('방장만 종료할 수 있습니다.',ephemeral=True)
            elif not self.started:
                await self.close('방장이 모집을 종료했습니다.')

class DuckSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder='내 오리 선택 (01~10)',options=[discord.SelectOption(label=f'{i+1:02}. {n}',value=str(i)) for i,n in enumerate(NAMES)])

    async def callback(self, interaction):
        duck = int(self.values[0])
        await interaction.response.defer(ephemeral=True)
        view = self.view
        async with view.lock:
            if view.started:
                await interaction.followup.send('경주가 이미 시작되거나 종료되었습니다.',ephemeral=True)
                return
            if duck in view.users and view.users[duck] != interaction.user.id:
                await interaction.followup.send('이미 선택된 오리입니다. 다른 오리를 골라 주세요.',ephemeral=True)
                return
            view.users = {d:u for d,u in view.users.items() if u != interaction.user.id}
            view.users[duck] = interaction.user.id
            view.labels[interaction.user.id] = interaction.user.display_name
            await view.message.edit(content=view.content(),view=view,allowed_mentions=discord.AllowedMentions.none())
            await interaction.followup.send(f'{NAMES[duck]} 선택 완료!',ephemeral=True)

class DuckRace(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="오리경주", description="픽셀 오리 자동 경주 참가 모집 (2~10명)")
    @commands.guild_only()
    async def duck_race(self, ctx):
        if ctx.channel.id != DUCK_RACE_CHANNEL_ID:
            await ctx.send(
                f"오리 경주는 <#{DUCK_RACE_CHANNEL_ID}> 채널에서 이용해 주세요.",
                ephemeral=True,
            )
            return
        if ctx.channel.id in active:
            await ctx.send("이 채널에는 진행 중인 경주가 있습니다.")
            return
        view = RaceView(ctx.author.id, ctx.channel.id)
        active[ctx.channel.id] = view
        try:
            view.message = await ctx.send(view.content(), view=view, allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            active.pop(ctx.channel.id, None)
            view.stop()
            raise

    async def cog_unload(self):
        # Recruitment buttons from this instance must not remain active.
        for view in list(active.values()):
            if not view.started:
                try:
                    await view.close("오리 경주 기능이 재시작되었습니다. 새로 모집해 주세요.")
                except discord.HTTPException:
                    view.stop()
        active.clear()

async def setup(bot):
    await bot.add_cog(DuckRace(bot))
