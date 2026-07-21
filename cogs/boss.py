import asyncio
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands

# 📌 보스 타임 기록 및 알림 채널 ID
BOSS_LOG_CHANNEL_ID = 1528031320926584872

class BossTimer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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
            
            # ⏱️ 시간 설정 (초 단위)
            min_delay = 9000      # 최소 젠타임: 2시간 30분 (9000초)
            avg_delay = 10020     # 평균 젠타임: 2시간 47분 (10020초)
            max_delay = 14400     # 최대 젠타임: 4시간 00분 (14400초)
            
            log_channel = message.guild.get_channel(BOSS_LOG_CHANNEL_ID)
            if not log_channel:
                return
            
            kst = timezone(timedelta(hours=9))
            now = datetime.now(kst)
            
            if len(tokens) >= 2:
                time_str = tokens[1]
                try:
                    parsed_time = datetime.strptime(time_str, "%H:%M")
                    base_time = now.replace(hour=parsed_time.hour, minute=parsed_time.minute, second=0, microsecond=0)
                    start_time = base_time
                except ValueError:
                    await message.channel.send("⚠️ 시간 형식이 올바르지 않습니다. (예: `1000 22:34`)")
                    return
            else:
                start_time = now

            formatted_start = start_time.strftime("%H시 %M분")

            # 각 목표 시각 연산
            min_target = start_time + timedelta(seconds=min_delay)
            avg_target = start_time + timedelta(seconds=avg_delay)
            max_target = start_time + timedelta(seconds=max_delay)

            # 타임스탬프 태그 생성
            min_unix = int(min_target.timestamp())
            avg_unix = int(avg_target.timestamp())
            max_unix = int(max_target.timestamp())

            # ---------------------------------------------------------
            # 1단계: 최초 제보 ~ 최소 젠타임(2시간 30분) 대기
            # ---------------------------------------------------------
            info_msg = await log_channel.send(
                f"📢 **[{channel_name} 채널] {boss_name}** 컷 확인 ({formatted_start} 기준) | ⏱️ **<t:{min_unix}:t>** 최소 젠타임 시작 예정 (<t:{min_unix}:R>)"
            )

            time_to_min = (min_target - datetime.now(kst)).total_seconds()
            await asyncio.sleep(max(0, time_to_min))

            try:
                await info_msg.delete()
            except:
                pass

            # ---------------------------------------------------------
            # 2단계: 최소 젠타임 시작 알림 + 평균 젠타임(2시간 47분) 카운트다운
            # ---------------------------------------------------------
            avg_msg = await log_channel.send(
                f"⚠️ @everyone **[{channel_name} 채널] {boss_name}** ({formatted_start} 컷)\n"
                f"최소 젠타임이 시작되었습니다! 채널을 확인해 주세요.\n"
                f"📊 **<t:{avg_unix}:t>** 평균 젠타임까지 (<t:{avg_unix}:R>)"
            )

            time_to_avg = (avg_target - datetime.now(kst)).total_seconds()
            await asyncio.sleep(max(0, time_to_avg))

            try:
                await avg_msg.delete()
            except:
                pass

            # ---------------------------------------------------------
            # 3단계: 평균 젠타임 경과 + 최대 젠타임(4시간 00분) 카운트다운
            # ---------------------------------------------------------
            max_msg = await log_channel.send(
                f" **[{channel_name} 채널] {boss_name}** ({formatted_start} 컷) 평균 젠타임 경과 | **<t:{max_unix}:t>** 최대 젠타임(젠 확정)까지 (<t:{max_unix}:R>)"
            )

            time_to_max = (max_target - datetime.now(kst)).total_seconds()
            await asyncio.sleep(max(0, time_to_max))

            try:
                await max_msg.delete()
            except:
                pass

async def setup(bot):
    await bot.add_cog(BossTimer(bot))
