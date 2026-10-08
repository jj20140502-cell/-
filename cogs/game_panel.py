"""Persistent game menu for discord.py 2.x. No additional dependencies."""
import asyncio
import random
import logging
import discord
from discord.ext import commands

CHANNEL_ID = 1557805141795803256
log = logging.getLogger(__name__)


def safe(name):
    return discord.utils.escape_markdown(' '.join(name.split()))[:80]


class Lobby(discord.ui.View):
    def __init__(self, cog, owner, kind, reward=''):
        super().__init__(timeout=180)
        self.cog, self.owner, self.kind, self.reward = cog, owner, kind, reward
        self.players = {}
        self.message = None
        self.lock = asyncio.Lock()
        self.closed = False

    def text(self):
        names = ', '.join(safe(n) for n in self.players.values()) or '아직 없음'
        title = '💣 폭탄 돌리기' if self.kind == 'bomb' else '⚔️ 레이드'
        extra = f'\n보상 안내: {self.reward}' if self.reward else ''
        return f'**{title} 참가 모집**{extra}\n참가자 {len(self.players)}/10명: {names}\n참가 신청 후 방장이 시작하세요. 3분간 입력이 없으면 종료됩니다.'

    @discord.ui.button(label='참가 신청', style=discord.ButtonStyle.success)
    async def join(self, interaction, button):
        await interaction.response.defer()
        async with self.lock:
            if self.closed:
                return
            if interaction.user.id not in self.players and len(self.players) >= 10:
                await interaction.followup.send('최대 10명입니다.', ephemeral=True)
                return
            self.players[interaction.user.id] = interaction.user.display_name
            await self.message.edit(content=self.text(), view=self)

    @discord.ui.button(label='참가 취소')
    async def leave(self, interaction, button):
        await interaction.response.defer()
        async with self.lock:
            if not self.closed:
                self.players.pop(interaction.user.id, None)
                await self.message.edit(content=self.text(), view=self)

    @discord.ui.button(label='게임 시작', style=discord.ButtonStyle.primary)
    async def start(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            if self.closed:
                return
            if interaction.user.id != self.owner:
                await interaction.followup.send('방장만 시작할 수 있습니다.', ephemeral=True)
                return
            if len(self.players) < 2:
                await interaction.followup.send('2명 이상 참가해야 합니다.', ephemeral=True)
                return
            self.closed = True
            self.stop()
            if self.kind == 'bomb':
                game = Bomb(self.cog, self.players.copy())
            else:
                game = Raid(self.cog, self.players.copy(), self.reward)
            game.message = self.message
            self.cog.games[self.kind] = game
            await self.message.edit(content=game.text(), view=game)
            self.cog.launch(game)

    @discord.ui.button(label='모집 종료', style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            if interaction.user.id != self.owner:
                await interaction.followup.send('방장만 종료할 수 있습니다.', ephemeral=True)
            elif not self.closed:
                await self.finish('모집을 종료했습니다.')

    async def finish(self, text):
        self.closed = True
        self.stop()
        self.cog.release(self.kind, self)
        if self.message:
            await self.message.edit(content=text, view=None)

    async def on_timeout(self):
        async with self.lock:
            if not self.closed:
                await self.finish('참가 모집 시간이 만료되었습니다.')


class PassSelect(discord.ui.Select):
    def __init__(self, game):
        super().__init__(placeholder='폭탄을 넘길 참가자 선택', options=[
            discord.SelectOption(label=n[:90], value=str(uid))
            for uid,n in game.players.items() if uid != game.holder
        ])

    async def callback(self, interaction):
        target = int(self.values[0])
        game = self.view
        await interaction.response.defer(ephemeral=True)
        async with game.lock:
            if game.ended:
                return
            if asyncio.get_running_loop().time() >= game.deadline:
                await game.explode()
                return
            if interaction.user.id != game.holder:
                await interaction.followup.send('현재 폭탄 보유자만 전달할 수 있습니다.', ephemeral=True)
                return
            if target == game.holder or target not in game.players:
                await interaction.followup.send('다른 참가자를 선택하세요.', ephemeral=True)
                return
            now = asyncio.get_running_loop().time()
            if now < game.next_pass:
                await interaction.followup.send('전달 후 1초 동안 기다려 주세요.', ephemeral=True)
                return
            game.holder = target
            game.next_pass = now + 1
            game.refresh()
            await game.message.edit(content=game.text(), view=game)


class Bomb(discord.ui.View):
    def __init__(self, cog, players):
        super().__init__(timeout=None)
        self.cog, self.players = cog, players
        self.holder = random.choice(list(players))
        self.deadline = asyncio.get_running_loop().time() + random.uniform(20,40)
        self.next_pass = 0
        self.ended = False
        self.lock = asyncio.Lock()
        self.message = None
        self.refresh()

    def refresh(self):
        self.clear_items()
        self.add_item(PassSelect(self))

    def text(self):
        return f'💣 **폭탄 돌리기 진행 중!**\n현재 보유자: **{safe(self.players[self.holder])}**\n보유자가 아래 메뉴에서 다른 참가자를 선택해 넘기세요.\n20~40초 사이에 폭발합니다! 보유자에게 💥 꽝!'

    async def explode(self):
        if self.ended:
            return
        self.ended = True
        self.stop()
        self.cog.release('bomb', self)
        await self.message.edit(content=f'💥 **폭탄 폭발!**\n**{safe(self.players[self.holder])}** 님이 마지막 보유자입니다.\n🎉 **꽝!**', view=None)

    async def timer(self):
        await asyncio.sleep(max(0,self.deadline-asyncio.get_running_loop().time()))
        async with self.lock:
            await self.explode()


class Raid(discord.ui.View):
    def __init__(self, cog, players, reward):
        super().__init__(timeout=None)
        self.cog, self.players, self.reward = cog, players, reward
        self.order = list(players)
        random.shuffle(self.order)
        self.index = 0
        self.max_hp = 65 * len(players)
        self.hp = self.max_hp
        self.damage = {uid:0 for uid in players}
        self.turns = 0
        self.ended = False
        self.lock = asyncio.Lock()
        self.message = None
        self.last = '보스가 등장했습니다!'
        self.curse = False
        self.deadline = asyncio.get_running_loop().time()+30

    @property
    def current(self):
        return self.order[self.index]

    def text(self):
        warning = '\n⚠️ 보스의 저주! 이번 공격은 실패합니다.' if self.curse else ''
        return (f'⚔️ **꽥괴물 레이드** · HP **{self.hp}/{self.max_hp}**\n'
                f'현재 차례: **{safe(self.players[self.current])}** (30초 제한){warning}\n'
                f'{self.last}\n보상 안내: {self.reward}\n참가 신청한 사람만 자신의 차례에 공격할 수 있습니다.')

    @discord.ui.button(label='공격', emoji='⚔️', style=discord.ButtonStyle.danger)
    async def attack(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        async with self.lock:
            if self.ended:
                return
            if interaction.user.id != self.current:
                await interaction.followup.send('참가자의 자기 차례에만 공격할 수 있습니다.', ephemeral=True)
                return
            if asyncio.get_running_loop().time() >= self.deadline:
                await self.advance(skipped=True)
                return
            uid = self.current
            hit = 0 if self.curse else min(self.hp,random.randint(20,40))
            self.hp -= hit
            self.damage[uid] += hit
            self.last = (f'{safe(self.players[uid])} · {hit} 피해!' if hit else
                         f'공격 실패! 보스: {random.choice(["간지럽지도 않다 꽥!", "허공에 뭐가 있니?", "그건 공격이 아니라 인사잖아!"])}')
            if self.hp <= 0:
                await self.finish(True)
            else:
                await self.advance()

    async def advance(self, skipped=False):
        if skipped:
            self.last = f'{safe(self.players[self.current])} · 시간 초과로 차례를 건너뜁니다.'
        heal = min(self.max_hp-self.hp,random.randint(0,8))
        self.hp += heal
        self.last += f' 보스가 {heal} HP 회복!'
        self.index = (self.index+1)%len(self.order)
        self.turns += 1
        self.curse = random.random()<0.04
        self.deadline = asyncio.get_running_loop().time()+30
        if self.turns >= len(self.players)*12:
            await self.finish(False)
        else:
            await self.message.edit(content=self.text(),view=self)

    async def finish(self, victory):
        self.ended = True
        self.stop()
        self.cog.release('raid', self)
        ranked = sorted(self.damage.items(),key=lambda pair:-pair[1])
        lines=[]
        previous=None
        rank=0
        for i,(uid,damage) in enumerate(ranked,1):
            if damage != previous:
                rank=i
            previous=damage
            lines.append(f'{rank}위 · {safe(self.players[uid])} · {damage} 피해')
        result='🏆 **레이드 성공!**' if victory else '⌛ **레이드 종료: 턴 제한 초과**'
        await self.message.edit(content=result+'\n'+'\n'.join(lines)+'\n**사전 입력 보상 안내**\n'+self.reward+'\n※ 실제 아이템·코인 지급은 운영자가 처리합니다.',view=None)

    async def timer(self):
        while not self.ended:
            await asyncio.sleep(max(0,self.deadline-asyncio.get_running_loop().time()))
            async with self.lock:
                if not self.ended and asyncio.get_running_loop().time() >= self.deadline:
                    await self.advance(skipped=True)


class RewardModal(discord.ui.Modal,title='레이드 보상 사전 입력'):
    reward = discord.ui.TextInput(label='보상과 배분 기준',placeholder='예: 1위 1000코인 / 2위 500코인 / 나머지 100코인',style=discord.TextStyle.paragraph,max_length=500)
    def __init__(self,cog):
        super().__init__()
        self.cog=cog
    async def on_submit(self,interaction):
        await self.cog.open_lobby(interaction,'raid',discord.utils.escape_mentions(discord.utils.escape_markdown(self.reward.value)))


class GamePanel(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=None)
        self.cog=cog

    async def interaction_check(self,interaction):
        if interaction.channel_id != CHANNEL_ID:
            await interaction.response.send_message(f'<#{CHANNEL_ID}> 채널에서 이용해 주세요.',ephemeral=True)
            return False
        return True

    @discord.ui.button(label='폭탄 돌리기',emoji='💣',custom_id='games:bomb:v1',style=discord.ButtonStyle.danger)
    async def bomb(self,interaction,button):
        await self.cog.open_lobby(interaction,'bomb')

    @discord.ui.button(label='오리 경주',emoji='🦆',custom_id='games:duck:v1',style=discord.ButtonStyle.primary)
    async def duck(self,interaction,button):
        if not self.cog.bot.get_cog('DuckRace'):
            await interaction.response.send_message('오리 경주 Cog가 로드되지 않았습니다.',ephemeral=True)
            return
        from .duck_race import RaceView, active
        if interaction.channel_id in active:
            await interaction.response.send_message('진행 중인 오리 경주가 있습니다.',ephemeral=True)
            return
        view=RaceView(interaction.user.id,interaction.channel_id)
        active[interaction.channel_id]=view
        try:
            await interaction.response.send_message(view.content(),view=view,allowed_mentions=discord.AllowedMentions.none())
            view.message=await interaction.original_response()
        except Exception:
            active.pop(interaction.channel_id,None)
            view.stop()
            raise

    @discord.ui.button(label='레이드',emoji='⚔️',custom_id='games:raid:v1',style=discord.ButtonStyle.success)
    async def raid(self,interaction,button):
        await interaction.response.send_modal(RewardModal(self.cog))


class GameHub(commands.Cog):
    def __init__(self,bot):
        self.bot=bot
        self.games={}
        self.tasks=set()
        self.panel=GamePanel(self)

    async def cog_load(self):
        self.bot.add_view(self.panel)

    def release(self,kind,game):
        if self.games.get(kind) is game:
            self.games.pop(kind,None)

    def launch(self,game):
        async def guarded():
            try:
                await game.timer()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Game timer failed')
                game.stop()
                kind = 'bomb' if isinstance(game, Bomb) else 'raid'
                self.release(kind,game)
                if game.message:
                    try:
                        await game.message.edit(content='게임 처리에 실패했습니다. 새로 모집해 주세요.',view=None)
                    except discord.HTTPException:
                        pass
        task=asyncio.create_task(guarded())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def open_lobby(self,interaction,kind,reward=''):
        if interaction.channel_id != CHANNEL_ID:
            await interaction.response.send_message(f'<#{CHANNEL_ID}> 채널에서 이용해 주세요.',ephemeral=True)
            return
        if kind in self.games:
            await interaction.response.send_message('같은 게임이 모집 또는 진행 중입니다.',ephemeral=True)
            return
        view=Lobby(self,interaction.user.id,kind,reward)
        self.games[kind]=view
        try:
            await interaction.response.send_message(view.text(),view=view,allowed_mentions=discord.AllowedMentions.none())
            view.message=await interaction.original_response()
        except Exception:
            self.release(kind,view)
            view.stop()
            raise

    @commands.command(name='게임패널')
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def game_panel(self,ctx):
        if ctx.channel.id != CHANNEL_ID:
            await ctx.send(f'<#{CHANNEL_ID}> 채널에서 실행해 주세요.')
            return
        message = await ctx.send('🎮 **게임 선택**\n아래에서 게임을 선택하세요. 참가 모집 후 방장이 시작합니다.',view=self.panel)
        try:
            await message.pin(reason='상시 게임 선택 패널')
        except discord.HTTPException:
            await ctx.send('게임 패널을 만들었습니다. 고정 권한이 없어 운영자가 직접 메시지를 고정해 주세요.')

    @commands.hybrid_command(name='폭탄시작',description='폭탄 돌리기 참가 모집')
    @commands.guild_only()
    async def bomb_start(self,ctx):
        if ctx.channel.id != CHANNEL_ID:
            await ctx.send(f'<#{CHANNEL_ID}> 채널에서 이용해 주세요.',ephemeral=True)
            return
        if 'bomb' in self.games:
            await ctx.send('폭탄 게임이 이미 진행 중입니다.',ephemeral=True)
            return
        view=Lobby(self,ctx.author.id,'bomb')
        self.games['bomb']=view
        try:
            view.message=await ctx.send(view.text(),view=view,allowed_mentions=discord.AllowedMentions.none())
        except Exception:
            self.release('bomb',view)
            view.stop()
            raise

    async def cog_unload(self):
        self.panel.stop()
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks,return_exceptions=True)
        for game in list(self.games.values()):
            game.stop()
            if game.message:
                try:
                    await game.message.edit(content='봇 기능이 재시작되어 게임이 종료되었습니다. 새로 모집해 주세요.',view=None)
                except discord.HTTPException:
                    pass
        self.games.clear()

async def setup(bot):
    await bot.add_cog(GameHub(bot))
