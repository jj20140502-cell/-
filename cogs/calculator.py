import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import Modal, TextInput, View, Button
import math
import re

# 경험치 테이블 (1레벨 ~ 220레벨)
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
    1312399800, 1384319309, 1460180007, 1540197871, 1624600714, 1713628833, 1807535693, 1906588648, 2011069705, 2121276324,
    5027674262, 5681271916, 6419837265, 7254416109, 8197490203, 9263163929, 10467375239, 11828134020, 13365791442, 15103344329,
    22503983050, 24529341524, 26736982261, 29143310664, 31766208623, 34625167399, 37741432464, 41138161385, 44840595909, 48876249540
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


def parse_meso_input(text: str):
    """분배금 전용 메소 파서. 단위 없는 소수는 억 단위로 처리합니다."""
    if not text or not text.strip():
        return 0

    raw = text.strip().replace(",", "").replace(" ", "")

    # 1.5 -> 150,000,000 / 1.69 -> 169,000,000
    if re.fullmatch(r"\d+(?:\.\d+)", raw):
        return math.floor(float(raw) * 100_000_000)

    # 1억5천만 -> 1억5000만
    raw = re.sub(
        r"(\d+)천만",
        lambda m: str(int(m.group(1)) * 1000) + "만",
        raw
    )

    return parse_numeric_input(raw)


def format_meso(value: int):
    return f"{value:,} 메소"

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
    현재레벨 = TextInput(label="현재 레벨 (1~219)", placeholder="예: 195", required=True)
    현재경험치 = TextInput(label="현재 경험치 (만 단위 또는 %)", placeholder="예: 5500만 또는 33.33%", required=True)
    목표레벨 = TextInput(label="목표 레벨 (2~220)", placeholder="예: 220", required=True)
    시간당경험치 = TextInput(label="시간당 사냥 경험치 (선택)", placeholder="예: 1억 8000만", required=False)
    보스경험치요약 = TextInput(label="보스경험치/처치횟수 (선택)", placeholder="예: 3억/12", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cur_lvl = int(self.현재레벨.value)
            tar_lvl = int(self.목표레벨.value)
        except ValueError:
            await interaction.response.send_message("레벨은 숫자만 입력해주세요.", ephemeral=True)
            return
        if cur_lvl >= tar_lvl or cur_lvl < 1 or tar_lvl > 220:
            await interaction.response.send_message("레벨 범위가 올바르지 않습니다. (1~220)", ephemeral=True)
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
    캐시템이름 = TextInput(label="캐시템 이름", placeholder="예: '큐브' 또는 '코반'", required=True)
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


class DistributeModal(Modal):
    def __init__(self, price_mode: str):
        self.price_mode = price_mode
        title = "💰 분배금 계산기 · 판매금 기준" if price_mode == "sale" else "💰 분배금 계산기 · 수령금액 기준"
        super().__init__(title=title)

        self.item_name = TextInput(label="아이템명", placeholder="예: 카혼목", required=True, max_length=100)
        self.member_count = TextInput(label="정산인원", placeholder="예: 6", required=True, max_length=3)
        self.amount = TextInput(label="정산금액", placeholder="예: 1.5 / 1억 5천만 / 1억 5000 / 150,000,000", required=True)
        self.deduct = TextInput(label="차감금액 (가위)", placeholder="예: 330만 / 3,300,000", required=False)

        self.add_item(self.item_name)
        self.add_item(self.member_count)
        self.add_item(self.amount)
        self.add_item(self.deduct)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            count = int(self.member_count.value.replace(",", "").replace(" ", ""))
        except ValueError:
            await interaction.response.send_message("정산 인원은 숫자로 입력해주세요.", ephemeral=True)
            return

        if count <= 0:
            await interaction.response.send_message("정산 인원은 1명 이상이어야 합니다.", ephemeral=True)
            return

        amount = parse_meso_input(self.amount.value)
        deduct_value = parse_meso_input(self.deduct.value)

        if amount <= 0:
            await interaction.response.send_message(
                "정산금액을 인식하지 못했습니다.\n예: `1.5`, `1억 5천만`, `1억 5000`, `150,000,000`",
                ephemeral=True
            )
            return

        if self.price_mode == "sale":
            received_amount = math.floor(amount * 0.9)
            fee_amount = amount - received_amount
            mode_text = "판매금 기준"
        else:
            received_amount = amount
            fee_amount = 0
            mode_text = "수령금액 기준"

        final_profit = max(0, received_amount - deduct_value)
        base_share = math.floor(final_profit / count)

        # 택배: 1인당 교환 분배금에서 8% + 10,000 메소 차감
        taxi_fee_pct = math.floor(base_share * 0.08)
        taxi_send_fee = 10_000
        after_taxi_share = max(0, base_share - taxi_fee_pct - taxi_send_fee)

        embed = discord.Embed(title="💰 보스 레이드 분배금 정산 결과", color=discord.Color.gold())
        embed.add_field(name="📦 아이템", value=f"**{self.item_name.value}**", inline=False)
        embed.add_field(name="⚙️ 정산 기준", value=f"**{mode_text}**", inline=True)
        embed.add_field(name="👥 정산 인원", value=f"**{count}명**", inline=True)
        embed.add_field(name="💰 입력 정산금액", value=format_meso(amount), inline=False)

        if self.price_mode == "sale":
            embed.add_field(
                name="🏢 경매장 수수료 10%",
                value=f"- {format_meso(fee_amount)}\n➡️ 수수료 제외: **{format_meso(received_amount)}**",
                inline=False
            )

        embed.add_field(name="✂️ 차감금액 (가위)", value=f"- {format_meso(deduct_value)}", inline=False)
        embed.add_field(name="✨ 최종 정산금액", value=f"**{format_meso(final_profit)}**", inline=False)
        embed.add_field(name="💵 1인당 기본 분배금 (교환)", value=f"**{format_meso(base_share)}**", inline=False)
        embed.add_field(
            name="📦 택배 수령 시 금액",
            value=(
                f"• 택배 수수료 (8%): {format_meso(taxi_fee_pct)}\n"
                f"• 택배 발송비: {format_meso(taxi_send_fee)}\n"
                f"➡️ **최종 수령액 (택배): {format_meso(after_taxi_share)}**"
            ),
            inline=False
        )
        await interaction.response.send_message(embed=embed)


class DistributePanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="판매금 기준 계산", emoji="💰", style=discord.ButtonStyle.primary, custom_id="calculator:distribute:sale")
    async def sale_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DistributeModal("sale"))

    @discord.ui.button(label="수령금액 기준 계산", emoji="💵", style=discord.ButtonStyle.secondary, custom_id="calculator:distribute:received")
    async def received_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DistributeModal("received"))


class ExpPanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="상세 입력", emoji="📊", style=discord.ButtonStyle.primary, custom_id="calculator:exp:detail")
    async def detail_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(ExpModal())


class CashPanel(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="메포 효율 계산", emoji="⚖️", style=discord.ButtonStyle.primary, custom_id="calculator:cash:open")
    async def cash_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(CashModal())


# --- Cog 클래스 구현 ---
class Calculator(commands.Cog):
    DISTRIBUTE_CHANNEL_ID = 1555270492179537991
    EXP_CHANNEL_ID = 1555270546747297843
    CASH_CHANNEL_ID = 1555270628129636422

    def __init__(self, bot):
        self.bot = bot
        self.channel_id = 1524082505903378495
        self.panels_initialized = False

    async def cog_load(self):
        if not self.update_stats.is_running():
            self.update_stats.start()

        self.bot.add_view(DistributePanel())
        self.bot.add_view(ExpPanel())
        self.bot.add_view(CashPanel())

    def cog_unload(self):
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

    @commands.Cog.listener()
    async def on_ready(self):
        if self.panels_initialized:
            return
        self.panels_initialized = True
        await self.ensure_calculator_panels()

    async def ensure_panel_message(self, channel, embed, view, title_keyword):
        try:
            async for message in channel.history(limit=50):
                if message.author.id != self.bot.user.id or not message.embeds:
                    continue
                if title_keyword in (message.embeds[0].title or ""):
                    await message.edit(embed=embed, view=view)
                    if not message.pinned:
                        try:
                            await message.pin()
                        except discord.HTTPException:
                            pass
                    return

            message = await channel.send(embed=embed, view=view)
            try:
                await message.pin()
            except discord.HTTPException:
                pass
        except discord.Forbidden:
            print(f"[계산기] 채널 권한 부족: {channel.id}")
        except discord.HTTPException as e:
            print(f"[계산기] 패널 생성/갱신 실패 {channel.id}: {e}")

    async def ensure_calculator_panels(self):
        channel = self.bot.get_channel(self.DISTRIBUTE_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="💰 보스 분배금 계산기",
                description=(
                    "아래에서 정산 기준을 선택해주세요.\n\n"
                    "**💰 판매금 기준**\n판매금에서 경매장 수수료 **10%**를 제외하고 가위값을 차감한 뒤 인원수로 분배합니다.\n\n"
                    "**💵 수령금액 기준**\n이미 수수료가 제외된 수령금액에서 가위값만 차감한 뒤 인원수로 분배합니다.\n\n"
                    "**금액 입력 예시**\n`1.5` / `1억 5천만` / `1억 5000` / `150,000,000`\n\n"
                    "결과에는 **교환 분배금**과 **택배 최종 수령액**이 함께 표시됩니다."
                ),
                color=discord.Color.gold()
            )
            await self.ensure_panel_message(channel, embed, DistributePanel(), "보스 분배금 계산기")

        channel = self.bot.get_channel(self.EXP_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="📊 레벨업 경험치 계산기",
                description=(
                    "이 채널에 아래 형식으로 바로 입력할 수 있습니다.\n\n"
                    "`현재레벨 현재경험치% 목표레벨`\n예: `195 53.2% 220`\n\n"
                    "`%`를 생략한 `195 53.2 220` 형식도 사용할 수 있습니다.\n\n"
                    "시간당 사냥 경험치나 보스 경험치까지 계산하려면 아래 **상세 입력** 버튼을 이용해주세요."
                ),
                color=discord.Color.green()
            )
            await self.ensure_panel_message(channel, embed, ExpPanel(), "레벨업 경험치 계산기")

        channel = self.bot.get_channel(self.CASH_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="⚖️ 캐시템 메포 효율 계산기",
                description="아래 버튼을 눌러 캐시 아이템의 메포 효율을 계산할 수 있습니다.",
                color=discord.Color.blue()
            )
            await self.ensure_panel_message(channel, embed, CashPanel(), "캐시템 메포 효율 계산기")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id != self.EXP_CHANNEL_ID:
            return

        match = re.fullmatch(r"(\d+)\s+([\d.]+)%?\s+(\d+)", message.content.strip())
        if not match:
            return

        try:
            cur_lvl = int(match.group(1))
            current_pct = float(match.group(2))
            tar_lvl = int(match.group(3))
        except ValueError:
            return

        if cur_lvl < 1 or cur_lvl > 219 or tar_lvl <= cur_lvl or tar_lvl > 220:
            await message.reply(
                "❌ 레벨 범위가 올바르지 않습니다. (현재 레벨 1~219 / 목표 레벨 최대 220)",
                mention_author=False
            )
            return

        if not 0 <= current_pct <= 100:
            await message.reply("❌ 현재 경험치는 0~100% 사이로 입력해주세요.", mention_author=False)
            return

        level_max_exp = EXP_TABLE[cur_lvl]
        current_exp = math.floor(level_max_exp * (current_pct / 100.0))
        total_required_exp = level_max_exp - current_exp
        for lvl in range(cur_lvl + 1, tar_lvl):
            total_required_exp += EXP_TABLE[lvl]

        embed = discord.Embed(title="📊 레벨업 경험치 계산 결과", color=discord.Color.green())
        embed.add_field(
            name="📈 현재 상태",
            value=f"Lv.{cur_lvl} ({current_pct:.2f}%)\n({current_exp:,} / {level_max_exp:,} EXP)",
            inline=True
        )
        embed.add_field(
            name="🏁 목표 상태",
            value=f"Lv.{tar_lvl}\n(필요 레벨업: {tar_lvl - cur_lvl}업)",
            inline=True
        )
        embed.add_field(name="🎯 총 필요 경험치", value=f"**{total_required_exp:,}** EXP", inline=False)
        await message.reply(embed=embed, mention_author=False)



    @app_commands.command(
        name="계산기패널",
        description="계산기 전용 채널의 패널을 생성하거나 갱신합니다."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def calculator_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            await self.ensure_calculator_panels()
            await interaction.followup.send(
                "✅ 계산기 패널을 확인했습니다.\n"
                "분배금 / 경험치 / 메포 채널에 기존 패널이 있으면 갱신하고, "
                "없으면 새로 생성했습니다.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"❌ 계산기 패널 처리 중 오류가 발생했습니다: `{e}`",
                ephemeral=True
            )

    @calculator_panel.error
    async def calculator_panel_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            message = "❌ 이 명령어는 서버 관리자만 사용할 수 있습니다."
        else:
            message = f"❌ 명령어 실행 중 오류가 발생했습니다: `{error}`"

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Calculator(bot))
