import asyncio
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands

# 📌 보스 타임 기록 및 알림 채널 ID
BOSS_LOG_CHANNEL_ID = 1528031320926584872


# ---------------------------------------------------------
# 1. 제보 입력 모달 (팝업 창)
# ---------------------------------------------------------
class BossKillModal(discord.ui.Modal, title="⚔️ 마뇽다이 제보"):
    channel_input = discord.ui.TextInput(
        label="채널 번호",
        placeholder="예: 132",
        required=True,
        max_length=10
    )
    time_input = discord.ui.TextInput(
        label="잡은 시간 (미입력 시 현재 시각)",
        placeholder="예: 15:19 (비워두면 현재 시각 자동 입력)",
        required=False,
        max_length=5
    )

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        kst = timezone(timedelta(hours=9))
        now = datetime.now(kst)

        channel_name = self.channel_input.value.strip()
        time_str = self.time_input.value.strip()

        # 시간 파싱
        if time_str:
            try:
                parsed_time = datetime.strptime(time_str, "%H:%M")
                start_time = now.replace(hour=parsed_time.hour, minute=parsed_time.minute, second=0, microsecond=0)
            except ValueError:
                await interaction.response.send_message("⚠️ 시간 형식이 올바르지 않습니다. (예: `15:19`)", ephemeral=True)
                return
        else:
            start_time = now

        formatted_start = start_time.strftime("%H시 %M분")
        await interaction.response.send_message(
            f"✅ **[{channel_name} 채널]** {formatted_start} 컷 등록 완료!",
            ephemeral=True
        )

        # 타이머 시작
        cog = self.bot.get_cog("BossTimer")
        if cog:
            asyncio.create_task(
                cog.start_boss_timer(
                    channel=interaction.channel,
                    channel_name=channel_name,
                    boss_name="마뇽",
                    start_time=start_time
                )
            )


# ---------------------------------------------------------
# 2. 메시지 내 '마뇽다이' & '오제보' 버튼
# ---------------------------------------------------------
class BossKillView(discord.ui.View):
    def __init__(self, bot, channel_name, boss_name):
        super().__init__(timeout=None)
        self.bot = bot
        self.channel_name = channel_name
        self.boss_name = boss_name
        self.action = None  # "kill" 또는 "cancel"

    @discord.ui.button(label="마뇽다이", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def kill_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.action = "kill"
        self.stop()

        try:
            await interaction.message.delete()
        except:
            pass

        kst = timezone(timedelta(hours=9))
        kill_time = datetime.now(kst)

        await interaction.response.send_message(
            f"⚔️ **[{self.channel_name} 채널] {self.boss_name}** 잡힘 확인! ({kill_time.strftime('%H시 %M분')} 기준 재기록 시작)",
            ephemeral=True
        )

        cog = self.bot.get_cog("BossTimer")
        if cog:
            asyncio.create_task(
                cog.start_boss_timer(
                    channel=interaction.channel,
                    channel_name=self.channel_name,
                    boss_name=self.boss_name,
                    start_time=kill_time
                )
            )

    @discord.ui.button(label="오제보", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.action = "cancel"
        self.stop()

        try:
            await interaction.message.delete()
        except:
            pass

        await interaction.response.send_message(
            f"❌ **[{self.channel_name} 채널]** {self.boss_name} 제보가 오제보 처리되어 타이머가 취소되었습니다.",
            ephemeral=True
        )


# ---------------------------------------------------------
# 3. 상시 유지 패널용 버튼 View
# ---------------------------------------------------------
class BossPanelControlView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)  # 버튼 지속 유지
        self.bot = bot

    @discord.ui.button(label="⚔️ 마뇽다이 / 젠 등록", style=discord.ButtonStyle.primary, custom_id="boss_panel_kill_btn")
    async def open_modal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(BossKillModal(self.bot))


# ---------------------------------------------------------
# 4. BossTimer Cog 메인
# ---------------------------------------------------------
class BossTimer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # 봇 재시작 시 상시 패널 버튼 리스너 유지
        self.bot.add_view(BossPanelControlView(self.bot))

    @commands.command(name="마뇽패널")
    async def send_panel(self, ctx):
        """채널에 상시 제보 패널을 생성합니다."""
        if ctx.channel.id != BOSS_LOG_CHANNEL_ID:
            await ctx.send("⚠️ 보스 알림 지정 채널에서만 사용할 수 있습니다.")
            return

        embed = discord.Embed(
            title="🐲 마뇽 젠타임 제보 패널",
            description="아래 버튼을 눌러 **채널 번호**와 **시간**을 입력해주세요.\n(시간을 입력하지 않으면 **현재 시각**으로 자동 입력됩니다.)",
            color=0x00ff7f
        )
        await ctx.send(embed=embed, view=BossPanelControlView(self.bot))

    async def start_boss_timer(self, channel, channel_name, boss_name, start_time):
        """보스 젠타임 카운트다운을 실행하는 공통 메소드"""
        min_delay = 7800      # 최소 젠타임: 2시간 10분
        avg_delay = 9000      # 평균 젠타임: 2시간 30분
        max_delay = 14400     # 최대 젠타임: 4시간 00분

        formatted_start = start_time.strftime("%H시 %M분")

        min_target = start_time + timedelta(seconds=min_delay)
        avg_target = start_time + timedelta(seconds=avg_delay)
        max_target = start_time + timedelta(seconds=max_delay)

        min_unix = int(min_target.timestamp())
        avg_unix = int(avg_target.timestamp())
        max_unix = int(max_target.timestamp())

        kst = timezone(timedelta(hours=9))

        # ---------------------------------------------------------
        # 1단계: 최초 제보 ~ 최소 젠타임 대기
        # ---------------------------------------------------------
        view1 = BossKillView(self.bot, channel_name, boss_name)
        info_msg = await channel.send(
            f"📢 **[{channel_name} 채널] {boss_name}** 컷 확인 ({formatted_start} 기준) | ⏱️ **<t:{min_unix}:t>** 최소 젠타임 시작 예정 (<t:{min_unix}:R>)",
            view=view1
        )

        time_to_min = (min_target - datetime.now(kst)).total_seconds()
        done, _ = await asyncio.wait(
            [asyncio.create_task(asyncio.sleep(max(0, time_to_min))),
             asyncio.create_task(view1.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )

        # 마뇽다이(재기록) 또는 오제보(취소)가 선택된 경우 알림 취소 후 종료
        if view1.action in ["kill", "cancel"]:
            return

        try:
            await info_msg.delete()
        except:
            pass

        # ---------------------------------------------------------
        # 2단계: 최소 젠타임 시작 알림
        # ---------------------------------------------------------
        view2 = BossKillView(self.bot, channel_name, boss_name)
        avg_msg = await channel.send(
            f"⚠️ @everyone **[{channel_name} 채널] {boss_name}** ({formatted_start} 컷)\n"
            f"최소 젠타임이 시작되었습니다! 채널을 확인해 주세요.\n"
            f"📊 **<t:{avg_unix}:t>** 평균 젠타임까지 (<t:{avg_unix}:R>)",
            view=view2
        )

        time_to_avg = (avg_target - datetime.now(kst)).total_seconds()
        done, _ = await asyncio.wait(
            [asyncio.create_task(asyncio.sleep(max(0, time_to_avg))),
             asyncio.create_task(view2.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )

        if view2.action in ["kill", "cancel"]:
            return

        try:
            await avg_msg.delete()
        except:
            pass

        # ---------------------------------------------------------
        # 3단계: 평균 젠타임 경과
        # ---------------------------------------------------------
        view3 = BossKillView(self.bot, channel_name, boss_name)
        max_msg = await channel.send(
            f" **[{channel_name} 채널] {boss_name}** ({formatted_start} 컷) 평균 젠타임 경과 | **<t:{max_unix}:t>** 최대 젠타임(젠 확정)까지 (<t:{max_unix}:R>)",
            view=view3
        )

        time_to_max = (max_target - datetime.now(kst)).total_seconds()
        done, _ = await asyncio.wait(
            [asyncio.create_task(asyncio.sleep(max(0, time_to_max))),
             asyncio.create_task(view3.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )

        if view3.action in ["kill", "cancel"]:
            return

        try:
            await max_msg.delete()
        except:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        """기존 채팅 제보 방식(132 15:19) 하위 호환 유지"""
        if message.author == self.bot.user:
            return

        tokens = message.content.split()

        if tokens and tokens[0].isdigit():
            if message.channel.id != BOSS_LOG_CHANNEL_ID:
                return

            channel_name = tokens[0]
            boss_name = "마뇽"

            kst = timezone(timedelta(hours=9))
            now = datetime.now(kst)

            if len(tokens) >= 2:
                time_str = tokens[1]
                try:
                    parsed_time = datetime.strptime(time_str, "%H:%M")
                    start_time = now.replace(hour=parsed_time.hour, minute=parsed_time.minute, second=0, microsecond=0)
                except ValueError:
                    await message.channel.send("⚠️ 시간 형식이 올바르지 않습니다. (예: `1000 22:34`)")
                    return
            else:
                start_time = now

            asyncio.create_task(
                self.start_boss_timer(
                    channel=message.channel,
                    channel_name=channel_name,
                    boss_name=boss_name,
                    start_time=start_time
                )
            )

async def setup(bot):
    await bot.add_cog(BossTimer(bot))
