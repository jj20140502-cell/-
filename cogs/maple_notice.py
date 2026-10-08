import asyncio
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import aiohttp
import discord
from bs4 import BeautifulSoup
from discord.ext import commands


# =========================================================
# 메이플플래닛 공지 자동 알림 설정
# =========================================================

BASE_URL = "https://mapleplanet.co.kr"

# 📢 점검 공지 채널
MAINTENANCE_CHANNEL_ID = 1557841882095030302

# 📢 패치노트 채널
PATCHNOTE_CHANNEL_ID = 1557841935593513032

# 메이플플래닛 목록 페이지
MAINTENANCE_LIST_URL = (
    "https://mapleplanet.co.kr/news/notices?status=maintenance"
)

PATCHNOTE_LIST_URL = (
    "https://mapleplanet.co.kr/news/updates"
)

# 몇 초마다 확인할지
CHECK_INTERVAL = 60

# 상태 저장 파일
STATE_FILE = Path("maple_notice_state.json")


# =========================================================
# Cog
# =========================================================

class MapleNotice(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.notice_task = None

        print("🟣 maple_notice.py 파일이 불러와졌습니다!", flush=True)

    # =====================================================
    # Cog 로드
    # =====================================================

    async def cog_load(self):

        print("🔵 MapleNotice Cog 로딩 시작", flush=True)

        self.session = aiohttp.ClientSession(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                )
            },
            timeout=aiohttp.ClientTimeout(total=20)
        )

        self.notice_task = asyncio.create_task(
            self.notice_loop()
        )

        print("📢 메이플플래닛 공지 감시 시작", flush=True)

    # =====================================================
    # Cog 해제
    # =====================================================

    async def cog_unload(self):

        if self.notice_task:
            self.notice_task.cancel()

            try:
                await self.notice_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        if self.session:
            await self.session.close()

    # =====================================================
    # 상태 파일 불러오기
    # =====================================================

    def load_state(self):

        default_state = {
            "maintenance": {},
            "patchnote": {}
        }

        if not STATE_FILE.exists():
            return default_state

        try:
            with open(
                STATE_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            if "maintenance" not in data:
                data["maintenance"] = {}

            if "patchnote" not in data:
                data["patchnote"] = {}

            return data

        except Exception as e:

            print(
                f"⚠️ 상태 파일 읽기 실패: {e}",
                flush=True
            )

            return default_state

    # =====================================================
    # 상태 파일 저장
    # =====================================================

    def save_state(self, state):

        try:

            with open(
                STATE_FILE,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    state,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

        except Exception as e:

            print(
                f"⚠️ 상태 파일 저장 실패: {e}",
                flush=True
            )

    # =====================================================
    # 웹페이지 가져오기
    # =====================================================

    async def fetch_html(self, url):

        try:

            async with self.session.get(url) as response:

                if response.status != 200:

                    print(
                        f"⚠️ HTTP 오류 {response.status}: {url}",
                        flush=True
                    )

                    return None

                return await response.text()

        except asyncio.CancelledError:
            raise

        except Exception as e:

            print(
                f"⚠️ 웹페이지 요청 실패: {e}",
                flush=True
            )

            return None

    # =====================================================
    # 목록 페이지에서 가장 최신 게시글 찾기
    # =====================================================

    async def get_latest_post(self, list_url):

        html = await self.fetch_html(list_url)

        if not html:
            return None

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        posts = []

        # /news/notices/123
        # /news/updates/123
        links = soup.find_all(
            "a",
            href=True
        )

        for link in links:

            href = link.get("href", "").strip()

            absolute_url = urljoin(
                BASE_URL,
                href
            )

            match = re.search(
                r"/news/(?:notices|updates)/(\d+)",
                absolute_url
            )

            if not match:
                continue

            post_id = int(match.group(1))

            title = link.get_text(
                " ",
                strip=True
            )

            if not title:
                continue

            posts.append(
                (
                    post_id,
                    absolute_url,
                    title
                )
            )

        if not posts:
            print(
                f"⚠️ 게시글을 찾지 못했습니다: {list_url}",
                flush=True
            )

            return None

        # 게시글 번호가 가장 큰 것을 최신으로 사용
        posts.sort(
            key=lambda x: x[0],
            reverse=True
        )

        latest = posts[0]

        return latest[1], latest[2]

    # =====================================================
    # 게시글 본문 가져오기
    # =====================================================

    async def get_article(self, url):

        html = await self.fetch_html(url)

        if not html:
            return None

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        # 필요 없는 태그 제거
        for tag in soup.find_all(
            [
                "script",
                "style",
                "noscript",
                "header",
                "footer",
                "nav"
            ]
        ):

            tag.decompose()

        # 게시글 본문 후보
        article = soup.find("article")

        if article:
            container = article

        else:

            main = soup.find("main")

            if main:
                container = main

            else:
                container = soup.body or soup

        # 제목 영역은 본문에서 제외
        for tag in container.find_all(
            ["h1", "h2"]
        ):

            tag.decompose()

        # 줄 단위 텍스트 추출
        text = container.get_text(
            "\n",
            strip=True
        )

        # 공백 정리
        lines = []

        for line in text.splitlines():

            line = re.sub(
                r"[ \t]+",
                " ",
                line
            ).strip()

            if line:
                lines.append(line)

        text = "\n".join(lines)

        if not text:
            return None

        return text

    # =====================================================
    # 내용 해시
    # =====================================================

    def make_hash(self, text):

        normalized = re.sub(
            r"\s+",
            " ",
            text
        ).strip()

        return hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()

    # =====================================================
    # Discord 메시지 분할
    # =====================================================

    def split_text(
        self,
        text,
        limit=1900
    ):

        chunks = []

        while len(text) > limit:

            # 가능한 한 줄바꿈 기준으로 자르기
            cut = text.rfind(
                "\n",
                0,
                limit
            )

            if cut < 500:
                cut = limit

            chunks.append(
                text[:cut]
            )

            text = text[cut:].lstrip()

        if text:
            chunks.append(text)

        return chunks

    # =====================================================
    # 새 공지 Discord 전송
    # =====================================================

    async def create_notice(
        self,
        channel_id,
        title,
        content,
        url
    ):

        channel = self.bot.get_channel(
            channel_id
        )

        if channel is None:

            try:
                channel = await self.bot.fetch_channel(
                    channel_id
                )
            except Exception as e:

                print(
                    f"❌ Discord 채널을 찾을 수 없습니다: {e}",
                    flush=True
                )

                return None

        # 부모 메시지
        embed = discord.Embed(
            title=title[:256],
            url=url,
            description=(
                "🍁 **메이플플래닛 새로운 공지사항이 등록되었습니다.**\n\n"
                "아래 스레드에서 공지 내용을 확인해주세요."
            ),
            color=discord.Color.orange()
        )

        embed.set_footer(
            text="MaplePlanet 자동 공지 알림"
        )

        parent_message = await channel.send(
            embed=embed
        )

        # 스레드 생성
        thread = await parent_message.create_thread(
            name=title[:90],
            auto_archive_duration=1440
        )

        # 본문 전송
        chunks = self.split_text(content)

        for index, chunk in enumerate(chunks):

            if index == 0:

                await thread.send(
                    chunk
                )

            else:

                await thread.send(
                    chunk
                )

        # 원본 링크
        await thread.send(
            f"🔗 **원본 공지:** {url}"
        )

        print(
            f"📢 공지 Discord 전송 완료: {title}",
            flush=True
        )

        return parent_message, thread

    # =====================================================
    # 기존 공지 수정 반영
    # =====================================================

    async def update_notice(
        self,
        data,
        title,
        content,
        url
    ):

        channel_id = data.get(
            "channel_id"
        )

        message_id = data.get(
            "message_id"
        )

        if not channel_id or not message_id:
            return False

        try:

            channel = self.bot.get_channel(
                channel_id
            )

            if channel is None:

                channel = await self.bot.fetch_channel(
                    channel_id
                )

            parent_message = await channel.fetch_message(
                message_id
            )

        except Exception as e:

            print(
                f"⚠️ 기존 공지 메시지를 찾지 못했습니다: {e}",
                flush=True
            )

            return False

        thread = parent_message.thread

        if thread is None:

            print(
                "⚠️ 기존 공지의 스레드를 찾지 못했습니다.",
                flush=True
            )

            return False

        # 스레드가 보관되어 있다면 다시 열기
        try:

            if thread.archived:

                await thread.edit(
                    archived=False
                )

        except Exception:
            pass

        # 수정 알림
        await thread.send(
            "⚠️ **이 공지가 수정되었습니다.**\n"
            "아래 내용은 수정된 최신 공지입니다."
        )

        # 수정된 내용
        chunks = self.split_text(
            content
        )

        for chunk in chunks:

            await thread.send(
                chunk
            )

        await thread.send(
            f"🔗 **수정된 원본 공지:** {url}"
        )

        # 부모 Embed도 수정
        embed = discord.Embed(
            title=title[:256],
            url=url,
            description=(
                "⚠️ **이 공지가 수정되었습니다.**\n\n"
                "아래 스레드에서 최신 내용을 확인해주세요."
            ),
            color=discord.Color.yellow()
        )

        embed.set_footer(
            text="MaplePlanet 자동 공지 알림 · 수정됨"
        )

        try:

            await parent_message.edit(
                embed=embed
            )

        except Exception:
            pass

        print(
            f"✏️ 수정된 공지 반영 완료: {title}",
            flush=True
        )

        return True

    # =====================================================
    # 공지 하나 검사
    # =====================================================

    async def check_notice(
        self,
        key,
        list_url,
        channel_id
    ):

        latest = await self.get_latest_post(
            list_url
        )

        if not latest:
            return

        url, title = latest

        content = await self.get_article(
            url
        )

        if not content:
            return

        content_hash = self.make_hash(
            content
        )

        state = self.load_state()

        previous = state.get(
            key,
            {}
        )

        # -------------------------------------------------
        # 처음 보는 공지
        # -------------------------------------------------

        if not previous:

            state[key] = {
                "url": url,
                "title": title,
                "hash": content_hash,
                "channel_id": channel_id,
                "message_id": None
            }

            self.save_state(
                state
            )

            print(
                f"📌 최초 기준점 저장: {title}",
                flush=True
            )

            return

        # -------------------------------------------------
        # 완전히 새로운 공지
        # -------------------------------------------------

        if previous.get("url") != url:

            print(
                f"🆕 새로운 공지 발견: {title}",
                flush=True
            )

            result = await self.create_notice(
                channel_id,
                title,
                content,
                url
            )

            if result:

                parent_message, thread = result

                state[key] = {
                    "url": url,
                    "title": title,
                    "hash": content_hash,
                    "channel_id": channel_id,
                    "message_id": parent_message.id,
                    "thread_id": thread.id
                }

                self.save_state(
                    state
                )

            return

        # -------------------------------------------------
        # 같은 공지인데 내용이 수정됨
        # -------------------------------------------------

        if previous.get("hash") != content_hash:

            print(
                f"✏️ 공지 수정 발견: {title}",
                flush=True
            )

            updated = await self.update_notice(
                previous,
                title,
                content,
                url
            )

            if updated:

                previous["title"] = title
                previous["hash"] = content_hash

                state[key] = previous

                self.save_state(
                    state
                )

            return

    # =====================================================
    # 자동 감시 루프
    # =====================================================

    async def notice_loop(self):

        # Cog가 완전히 로드될 때까지 잠깐 대기
        await asyncio.sleep(5)

        while True:

            try:

                # 점검 공지 확인
                await self.check_notice(
                    "maintenance",
                    MAINTENANCE_LIST_URL,
                    MAINTENANCE_CHANNEL_ID
                )

                # 패치노트 확인
                await self.check_notice(
                    "patchnote",
                    PATCHNOTE_LIST_URL,
                    PATCHNOTE_CHANNEL_ID
                )

            except asyncio.CancelledError:

                raise

            except Exception as e:

                print(
                    f"⚠️ 공지 감시 중 오류: {e}",
                    flush=True
                )

            await asyncio.sleep(
                CHECK_INTERVAL
            )

    # =====================================================
    # 🧪 관리자 테스트 - 최신 점검 공지
    # =====================================================

    @commands.command(
        name="공지테스트"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def notice_test(
        self,
        ctx
    ):

        await ctx.send(
            "🔎 최신 점검 공지를 가져오는 중입니다..."
        )

        latest = await self.get_latest_post(
            MAINTENANCE_LIST_URL
        )

        if not latest:

            await ctx.send(
                "❌ 최신 점검 공지를 찾지 못했습니다."
            )

            return

        url, title = latest

        content = await self.get_article(
            url
        )

        if not content:

            await ctx.send(
                "❌ 공지 본문을 가져오지 못했습니다."
            )

            return

        result = await self.create_notice(
            MAINTENANCE_CHANNEL_ID,
            f"🧪 [테스트] {title}",
            content,
            url
        )

        if result:

            await ctx.send(
                "✅ 최신 점검 공지를 테스트 전송했습니다!"
            )

        else:

            await ctx.send(
                "❌ 테스트 전송에 실패했습니다."
            )

    # =====================================================
    # 🧪 관리자 테스트 - 최신 패치노트
    # =====================================================

    @commands.command(
        name="패치노트테스트"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def patchnote_test(
        self,
        ctx
    ):

        await ctx.send(
            "🔎 최신 패치노트를 가져오는 중입니다..."
        )

        latest = await self.get_latest_post(
            PATCHNOTE_LIST_URL
        )

        if not latest:

            await ctx.send(
                "❌ 최신 패치노트를 찾지 못했습니다."
            )

            return

        url, title = latest

        content = await self.get_article(
            url
        )

        if not content:

            await ctx.send(
                "❌ 패치노트 본문을 가져오지 못했습니다."
            )

            return

        result = await self.create_notice(
            PATCHNOTE_CHANNEL_ID,
            f"🧪 [테스트] {title}",
            content,
            url
        )

        if result:

            await ctx.send(
                "✅ 최신 패치노트를 테스트 전송했습니다!"
            )

        else:

            await ctx.send(
                "❌ 테스트 전송에 실패했습니다."
            )

    # =====================================================
    # 관리자 권한 오류
    # =====================================================

    @notice_test.error
    async def notice_test_error(
        self,
        ctx,
        error
    ):

        if isinstance(
            error,
            commands.MissingPermissions
        ):

            await ctx.send(
                "❌ 이 명령어는 관리자만 사용할 수 있습니다."
            )

        else:

            print(
                f"⚠️ 공지테스트 오류: {error}",
                flush=True
            )

    @patchnote_test.error
    async def patchnote_test_error(
        self,
        ctx,
        error
    ):

        if isinstance(
            error,
            commands.MissingPermissions
        ):

            await ctx.send(
                "❌ 이 명령어는 관리자만 사용할 수 있습니다."
            )

        else:

            print(
                f"⚠️ 패치노트테스트 오류: {error}",
                flush=True
            )


# =========================================================
# Extension setup
# =========================================================

async def setup(bot):

    await bot.add_cog(
        MapleNotice(bot)
    )