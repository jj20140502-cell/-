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
        
        # 1. 숫자로 시작하는 제보 패턴인지 확인
        if tokens and tokens[0].isdigit():
            
            # 2. 지정된 보스 기록 채널이 아닐 경우(인증 채널 등) 보스 타임 로직 무시
            if message.channel.id != BOSS_LOG_CHANNEL_ID:
                return

            channel_name = tokens[0]
            boss_name = "마뇽"
            spawn_delay = 9600  # 2시간 40분 = 9600초
            
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

            # 1. 2시간 40분 뒤의 정확한 목표 시각 계산
            target_time = start_time + timedelta(seconds=spawn_delay)
            unix_timestamp = int(target_time.timestamp())
            
            exact_time_tag = f"<t:{unix_timestamp}:t>"
            countdown_tag = f"<t:{unix_timestamp}:R>"

            formatted_start = start_time.strftime("%H시 %M분")
            
            # 2. 📢 컷 확인 안내 메시지 전송
            info_msg = await log_channel.send(
                f"📢 **[{channel_name} 채널] {boss_name}** 컷 확인되었습니다. ({formatted_start} 기준)\n"
                f"⏱️ **{exact_time_tag}** 최소 젠타임 시작 예정 ({countdown_tag})"
            )

            # 3. 실제 최소 젠타임까지 대기
            time_to_wait = (target_time - datetime.now(kst)).total_seconds()
            await asyncio.sleep(max(0, time_to_wait))

            # 4. 시간이 되면 기존 안내 메시지 삭제
            try:
                await info_msg.delete()
            except:
                pass

            # 5. 최소 젠타임 시작 알림 전송 (컷 시간 포함)
            await log_channel.send(
                f"⚠️ @everyone **[{channel_name} 채널] {boss_name}** ({formatted_start} 컷) "
                f"최소 젠타임이 시작되었습니다! 채널을 확인해 주세요."
            )

async def setup(bot):
    await bot.add_cog(BossTimer(bot))
