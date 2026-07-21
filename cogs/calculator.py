import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Modal, TextInput
import math
import re

# 경험치 테이블
EXP_TABLE = [
    0, 15, 34, 57, 92, 135, 372, 560, 840, 1242, 1716,
    2360, 3216, 4200, 5460, 7050, 8840, 11040, 13716, 16680, 20216,
    24402, 28980, 34320, 40512, 47216, 54900, 63666, 73080, 83720, 95700,
    108480, 122760, 138666, 155540, 174216, 194832, 216600, 240500, 266682, 294216,
    324240, 356916, 391160, 428280, 468450, 510420, 555680, 604416, 655200, 709716,
    748608, 789631, 832902, 878545, 926689, 977471, 1031036, 1087536, 1147132, 1209994,
    1276301, 1346242, 1420016, 1497832, 1579913, 1666492, 1757815, 1854143, 1955750, 2062925,
    2175973, 2295216, 2420993, 2553663, 2693603, 2841212, 2996910, 3161140, 3334370, 3517993,
    3709829, 3913127, 4127566, 4353756, 4592341, 4844001, 5109452, 5389449, 5684790, 5996316,
    6324914, 6671519, 7037118, 7422752, 7829518, 8258575, 8711144, 9188514, 9692044, 10223168,
    10783397, 11374327, 11997640, 12655110, 13348610, 14080113, 14851703, 15665576, 16524049, 17429566,
    18384706, 19392187, 20454878, 21575805, 22758159, 24005306, 25320796, 26708375, 28171993, 29715818,
    31344244, 33061908, 34873700, 36784778, 38800583, 40926854, 43169645, 45535341, 48030677, 50662758,
    53439077, 56367538, 59456479, 62714694, 66151459, 69776558, 73600313, 77633610, 81887931, 86375389,
    91108760, 96101520, 101367883, 106922842, 112782213, 118922678, 125481832, 132358236, 139611467, 147262175,
    155332142, 163844343, 172823012, 182293713, 192283408, 202820538, 213935103, 225658746, 238024845, 251068606,
    264827165, 279339693, 294647508, 310794191, 327825712, 345790561, 364739883, 384727628, 405810702, 428049128,
    451506220, 476248760, 502347192, 529875818, 558913012, 589541445, 621848316, 655925603, 691870326, 729784819,
    769777027, 811960808, 856456260, 903390063, 952895838, 1005114529, 1060194805, 1118293480, 1179575962, 1244216724,
    1312399800, 1384319309, 1460180007, 1540197871, 1624600714, 1713628833, 1807535693, 1906588648, 2011069705, 2121276324
]

def parse_numeric_input(text: str, ref_exp: int = 0):
    if not text or not text.strip():
        return 0
    text_clean = text.replace(" ", "").replace(",", "")
    if '%' in text_clean:
        pct_match = re.search(r'([\d.]+)', text_clean)
        if pct_match and ref_exp > 0:
            percentage = float(pct_match.group(1))
            return math.floor(ref_exp * (percentage / 100.0))
        return 0
    if text_clean.isdigit():
        return int(text_clean)
    total = 0
    if '억' in text_clean:
        billion_match = re.search(r'(\d+)억', text_clean)
        if billion_match:
            total += int(billion_match.group(1)) * 100000000
        parts = text_clean.split('억')
        if len(parts) > 1 and parts[1]:
            after_billion = parts[1]
            million_match = re.search(r'(\d+)', after_billion)
            if million_match:
                val = million_match.group(1)
                if '만' in after_billion or int(val) < 10000:
                    total += int(val) * 10000
                else:
                    total += int(val)
    else:
        million_match = re.search(r'(\d+)만', text_clean)
        if million_match:
            total += int(million_match.group(1)) * 10000
        else:
            pure_num = re.search(r'(\d+)', text_clean)
            if pure_num:
                total = int(pure_num.group(1))
    return total

def parse_item_input(text: str):
    if not text or not text.strip():
        return "미입력", 0
    text_strip = text.strip()
    text_no_space = text_strip.replace(" ", "").replace(",", "")
    price_match = re.search(r'(\d+억\d+만|\d+억\d+|\d+억|\d+만|\d+)$', text_no_space)
    if not price_match:
        return text_strip, 0
    origin_price_match = re.search(r'(\d+[\s,]*억?[\s,]*\d*[\s,]*만?)$', text_strip)
    if origin_price_match:
        price_string = origin_price_match.group(1)
        item_name = text_strip[:origin_price_match.start()].strip()
    else:
        price_string = text_strip
        item_name = "아이템"
    item_name = re.sub(r'[\s/]+$', '', item_name).strip()
    if not item_name:
        item_name = "아이템"
    total_price = parse_numeric_input(price_string)
    return item_name, total_price


# --- 모달 클래스 정의 ---
class ExpModal(Modal, title="📊 레벨업 시뮬레이터"):
    현재레벨 = TextInput(label="현재 레벨 (1~199)", placeholder="예: 195", required=True)
    현재경험치 = TextInput(label="현재 경험치 (만 단위 또는 %)", placeholder="예: 5500만 또는 33.33%", required=True)
    목표레벨 = TextInput(label="목표 레벨 (2~200)", placeholder="예: 200", required=True)
    시간당경험치 = TextInput(label="시간당 사냥 경험치 (선택)", placeholder="예: 8000만", required=False)
    보스경험치요약 = TextInput(label="보스경험치/처치횟수 (선택)", placeholder="예: 500만/12", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cur_lvl = int(self.현재레벨.value)
            tar_lvl = int(self.목표레벨.value)
        except ValueError:
            await interaction.response.send_message("레벨은 숫자만 입력해주세요.", ephemeral=True)
            return
        if cur_lvl >= tar_lvl or cur_lvl < 1 or tar_lvl > 200:
            await interaction.response.send_message("레벨 범위가 올바르지 않습니다. (1~200)", ephemeral=True)
            return

        level_max_exp = EXP_TABLE[cur_lvl]
        current_exp = parse_numeric_input(self.현재경험치.value, ref_exp=level_max_exp)
        hourly_exp = parse_numeric_input(self.시간당경험치.value)
        
        boss_single_exp = 0
        boss_count = 1
        if self.보스경험치요약.value:
            boss_raw = self.보스경험치요약.value.replace(" ", "")
            if "/" in boss_raw:
                parts = boss_raw.split("/")
                boss_single_exp = parse_numeric_input(parts[0], ref_exp=level_max_exp)
                if parts[1].isdigit():
                    boss_count = int(parts[1])
            else:
                boss_single_exp = parse_numeric_input(boss_raw, ref_exp=level_max_exp)

        if current_exp > level_max_exp:
            current_exp = level_max_exp

        total_required_exp = level_max_exp - current_exp
        for lvl in range(cur_lvl + 1, tar_lvl): 
            total_required_exp += EXP_TABLE[lvl]
        total_boss_exp = boss_single_exp * boss_count
        hunting_required_exp = max(0, total_required_exp - total_boss_exp)

        calc_percent = (current_exp / level_max_exp) * 100 if level_max_exp > 0 else 0.0
        boss_percent = (boss_single_exp / level_max_exp) * 100 if level_max_exp > 0 else 0.0

        embed = discord.Embed(title="📊 레벨업 시뮬레이터 결과", color=discord.Color.green())
        embed.add_field(name="📈 현재 상태", value=f"Lv.{cur_lvl} ({calc_percent:.2f}%)\n({current_exp:,} / {level_max_exp:,} EXP)", inline=True)
        embed.add_field(name="🏁 목표 상태", value=f"Lv.{tar_lvl}\n(필요 레벨업: {tar_lvl - cur_lvl}업)", inline=True)
        embed.add_field(name="🎯 총 필요 경험치", value=f"**{total_required_exp:,}** EXP", inline=False)
        
        if total_boss_exp > 0:
            embed.add_field(name="───────────────────", value="**👾 보스 경험치 정산 내역**", inline=False)
            embed.add_field(name="보스 정산 경험치", value=f"{boss_single_exp:,} EXP ({boss_percent:.2f}%) × {boss_count}회\n= **-{total_boss_exp:,}** EXP", inline=True)
            embed.add_field(name="⚔️ 사냥 필요 잔여 경험치", value=f"**{hunting_required_exp:,}** EXP", inline=True)
        
        if hourly_exp > 0:
            if hunting_required_exp == 0:
                time_text = "**사냥 불필요**\n(보스로 렙업 가능)"
            else:
                needed_hours = hunting_required_exp / hourly_exp
                hours = int(needed_hours)
                minutes = math.ceil((needed_hours - hours) * 60)
                if minutes == 60: hours += 1; minutes = 0
                time_text = f"**{hours}시간 {minutes}분**" if minutes > 0 else f"**{hours}시간**"
            embed.add_field(name="───────────────────", value="**⏱️ 사냥 소요 시간 분석**", inline=False)
            embed.add_field(name="🔥 시간당 사냥 경험치", value=f"{hourly_exp:,} EXP", inline=True)
            embed.add_field(name="⏳ 예상 남은 사냥 시간", value=time_text, inline=True)
            
        await interaction.response.send_message(embed=embed)


class CashModal(Modal, title="⚖️ 캐시템 메포 효율 계산"):
    캐시템이름 = TextInput(label="캐시템 이름 (⚠️숫자 제외!)", placeholder="예: '혈반 한달' 또는 '혈반'", required=True)
    캐시템가격_메포 = TextInput(label="캐시 가격 (소모 메포)", placeholder="예: 1000", required=True)
    경매장판매가격 = TextInput(label="경매장 등록 단가 (메소)", placeholder="예: 5억 또는 1억 1000", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            mp_price = int(self.캐시템가격_메포.value.replace(",", "").replace(" ", ""))
        except ValueError:
            await interaction.response.send_message("메포 가격은 숫자만 정확히 입력해주세요.", ephemeral=True)
            return
        if mp_price <= 0:
            await interaction.response.send_message("캐시템 가격은 0보다 커야 합니다.", ephemeral=True)
            return

        _, price = parse_item_input(self.경매장판매가격.value)
        if price == 0:
            await interaction.response.send_message("경매장 판매 금액을 인식하지 못했습니다. (예: 5억 또는 1억 1000)", ephemeral=True)
            return

        net_meso = math.floor(price * 0.9)
        if net_meso == 0:
            await interaction.response.send_message("수수료 차감 후 금액이 너무 적어 계산할 수 없습니다.", ephemeral=True)
            return

        efficiency = math.floor((mp_price * 1000000) / net_meso)

        embed = discord.Embed(title="📊 캐시템 메포 효율 분석 결과", color=discord.Color.blue())
        embed.add_field(name="📦 분석 대상 아이템", value=f"**{self.캐시템이름.value}**", inline=False)
        embed.add_field(name="💳 캐시 가격 (소모 메포)", value=f"{mp_price:,} 메포", inline=True)
        embed.add_field(name="⚖️ 경매장 등록 단가", value=f"{price:,} 메소", inline=True)
        embed.add_field(name="🏢 수수료 10% 공제 후 수령액", value=f"{net_meso:,} 메소", inline=False)
        embed.add_field(name="🔥 실질 가치 (100만 메소당 효율)", value=f"➡️ **{efficiency:,} 메포**", inline=False)
        
        await interaction.response.send_message(embed=embed)


class DistributeModal(Modal, title="💰 보스 분배금 계산기"):
    정산인원 = TextInput(label="총 정산 인원수", placeholder="예: 6", required=True)
    아이템입력_a = TextInput(label="아이템 A (⚠️이름엔 숫자 금지)", placeholder="예: 메용 1억 2000", required=True)
    차감금액 = TextInput(label="정산 전 총액에서 차감할 금액 (선택)", placeholder="예: 2000만", required=False)
    아이템입력_b = TextInput(label="아이템 B (선택)", placeholder="예: 고확 5000만", required=False)
    아이템입력_c = TextInput(label="아이템 C (선택)", placeholder="예: 일비 800만", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.정산인원.value.replace(" ", ""))
        except ValueError:
            await interaction.response.send_message("인원수는 숫자만 적어주세요.", ephemeral=True)
            return
        if count <= 0:
            await interaction.response.send_message("인원수는 1명 이상이어야 합니다.", ephemeral=True)
            return

        name_a, price_a = parse_item_input(self.아이템입력_a.value)
        name_b, price_b = parse_item_input(self.아이템입력_b.value)
        name_c, price_c = parse_item_input(self.아이템입력_c.value)
        deduct_value = parse_numeric_input(self.차감금액.value)

        if price_a == 0:
            await interaction.response.send_message("첫 번째 아이템의 금액을 인식하지 못했습니다.", ephemeral=True)
            return

        profit_a = math.floor(price_a * 0.9)
        profit_b = math.floor(price_b * 0.9) if price_b > 0 else 0
        profit_c = math.floor(price_c * 0.9) if price_c > 0 else 0

        total_sales = price_a + price_b + price_c
        pure_profit_before_deduct = profit_a + profit_b + profit_c
        final_pure_profit = max(0, pure_profit_before_deduct - deduct_value)
        base_share = math.floor(final_pure_profit / count)
        
        taxi_fee_pct = math.floor(base_share * 0.08)
        total_taxi_deduct = taxi_fee_pct + 10000
        after_taxi_share = max(0, base_share - total_taxi_deduct)

        embed = discord.Embed(title="💰 보스 레이드 분배금 정산 결과", color=discord.Color.gold())
        items_text = f"• {name_a}: {price_a:,} 메소 (경매장 10%)\n"
        if price_b > 0:
            items_text += f"• {name_b}: {price_b:,} 메소 (경매장 10%)\n"
        if price_c > 0:
            items_text += f"• {name_c}: {price_c:,} 메소 (경매장 10%)\n"

        embed.add_field(name="🛒 총 등록 금액", value=f"{total_sales:,} 메소\n({items_text.strip()})", inline=False)
        embed.add_field(name="📉 수수료 제외 금액", value=f"{pure_profit_before_deduct:,} 메소", inline=True)
        embed.add_field(name="💸 공용 차감 금액", value=f"- {deduct_value:,} 메소", inline=True)
        embed.add_field(name="✨ 최종 순수익 합계", value=f"**{final_pure_profit:,}** 메소", inline=False)
        embed.add_field(name="👥 정산 인원수", value=f"{count} 명", inline=True)
        embed.add_field(name="💵 1인당 기본 분배금 (교환)", value=f"**{base_share:,}** 메소", inline=True)
        
        taxi_desc = f"• 택배 수수료 (8%): {taxi_fee_pct:,} 메소\n• 택배 발송비: 10,000 메소\n➡️ **최종 수령액 (택배): {after_taxi_share:,} 메소**"
        embed.add_field(name="📦 택배 수령 시 금액", value=taxi_desc, inline=False)
        
        await interaction.response.send_message(embed=embed)


# --- Cog 클래스 구현 ---
class Calculator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.channel_id = 1524082505903378495  # 채널 이름을 실시간 인원수로 변경할 채널 ID

    def cog_load(self):
        # Cog가 로드되면 유저/봇 수 업데이트 루프 실행
        if not self.update_stats.is_running():
            self.update_stats.start()

    def cog_unload(self):
        # Cog가 언로드되면 루프 중단
        self.update_stats.cancel()

    @tasks.loop(minutes=5)
    async def update_stats(self):
        if not self.bot.guilds:
            return
            
        guild = self.bot.guilds[0]
        channel = guild.get_channel(self.channel_id)
        
        if channel:
            total_members = guild.member_count
            bot_count = sum(1 for member in guild.members if member.bot)
            human_count = total_members - bot_count
            
            try:
                await channel.edit(name=f"👥 유저: {human_count}명 | 🤖 봇: {bot_count}개")
            except Exception as e:
                print(f"채널 이름 업데이트 실패: {e}")

    @update_stats.before_loop
    async def before_update_stats(self):
        await self.bot.wait_until_ready()

    # --- 슬래시 명령어 ---
    @app_commands.command(name="경험치", description="레벨업 경험치 및 사냥 예상 시간을 시뮬레이션합니다.")
    async def exp_slash(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ExpModal())

    @app_commands.command(name="메포", description="캐시 아이템의 메이플포인트 효율을 계산합니다.")
    async def cash_slash(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CashModal())

    @app_commands.command(name="분배금", description="보스 레이드 전리품 판매 수익을 인원별로 분배 정산합니다.")
    async def distribute_slash(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DistributeModal())


async def setup(bot):
    await bot.add_cog(Calculator(bot))
