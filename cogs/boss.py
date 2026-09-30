import asyncio
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands

# 📌 보스 타임 기록 및 알림 채널 ID
BOSS_LOG_CHANNEL_ID = 1528031320926584872

class BossKillView(discord.ui.View):
    def __init__(self, bot, channel_name, boss_name):
        super().__init__(timeout=None)  # 버튼 만료 시간 없음
        self.bot = bot
        self.channel_name = channel_name
        self.boss_name = boss_name
        self.killed = False  # 버튼 클릭 여부 플래그

    @discord.ui.button(label="마뇽다이", style=discord.ButtonStyle.danger, emoji="⚔️")
    async def kill_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.killed = True
        self.stop()  # View 대기 상태 종료

        # 기존 젠타임 메시지 삭제
        try:
            await interaction.message.delete()
        except:
            pass

        # 버튼을 누른 시각 (KST 기준)
        kst = timezone(timedelta(hours=9))
        kill_time = datetime.now(kst)

        await interaction.response.send_message(
            f"⚔️ **[{self.channel_name} 채널] {self.boss_name}** 잡힘 확인! ({kill_time.strftime('%H시 %M분')} 기준 재기록 시작)",
            ephemeral=True
        )

        # 같은 채널에 버튼 클릭 시각 기준으로 새 젠타임 타이머 작동
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


class BossTimer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start_boss_timer(self, channel, channel_name, boss_name, start_time):
        """보스 젠타임 카운트다운을 실행하는 공통 메소드"""
        # ⏱️ 시간 설정 (초 단위)
        min_delay = 7800      # 최소 젠타임: 2시간 10분 (7800초)
        avg_delay = 9000      # 평균 젠타임: 2시간 30분 (9000초)
        max_delay = 14400     # 최대 젠타임: 4시간 00분 (14400초)

        formatted_start = start_time.strftime("%H시 %M분")

        # 각 목표 시각 연산
        min_target = start_time + timedelta(seconds=min_delay)
        avg_target = start_time + timedelta(seconds=avg_delay)
        max_target = start_time + timedelta(seconds=max_delay)

        # 타임스탬프 태그 생성
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
        
        # 지정된 시간만큼 대기하되, 중간에 버튼이 눌리면 중단
        done, _ = await asyncio.wait(
            [asyncio.create_task(asyncio.sleep(max(0, time_to_min))),
             asyncio.create_task(view1.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )

        if view1.killed:
            return  # 버튼이 눌렸으므로 이전 타이머 흐름 종료

        try:
            await info_msg.delete()
        except:
            pass

        # ---------------------------------------------------------
        # 2단계: 최소 젠타임 시작 알림 + 평균 젠타임 카운트다운
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

        if view2.killed:
            return

        try:
            await avg_msg.delete()
        except:
            pass

        # ---------------------------------------------------------
        # 3단계: 평균 젠타임 경과 + 최대 젠타임 카운트다운
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

        if view3.killed:
            return

        try:
            await max_msg.delete()
        except:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        tokens = message.content.split()

        # 1. 숫자로 시작하는 제보 패턴 확인
        if tokens and tokens[0].isdigit():

            # 2. 지정된 보스 기록 채널이 아닐 경우 무시
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

            # 타이머 루프 실행
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
