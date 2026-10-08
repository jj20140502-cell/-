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
# 기본 설정
# =========================================================

BASE_URL = "https://mapleplanet.co.kr"

# 디스코드 채널
MAINTENANCE_CHANNEL_ID = 1557841882095030302
PATCHNOTE_CHANNEL_ID = 1557841935593513032

# 메이플플래닛 공식 페이지
MAINTENANCE_LIST_URL = (
    "https://mapleplanet.co.kr/news/notices?status=maintenance"
)

PATCHNOTE_LIST_URL = (
    "https://mapleplanet.co.kr/news/updates"
)

# 자동 확인 주기
CHECK_INTERVAL = 60

# 마지막으로 확인한 공지 저장
STATE_FILE = Path("maple_notice_state.json")


# =========================================================
# Cog
# =========================================================

class MapleNotice(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        self.session = None
        self.notice_task = None

        self.state = {
            "maintenance": {},
            "patchnote": {}
        }

    # -----------------------------------------------------
    # Cog 시작
    # -----------------------------------------------------

    async def cog_load(self):

        print("📢 메이플플래닛 공지 감시 시작", flush=True)

        self.load_state()

        timeout = aiohttp.ClientTimeout(total=20)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,image/webp,"
                "*/*;q=0.8"
            ),
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": BASE_URL + "/",
        }

        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers=headers
        )

        self.notice_task = asyncio.create_task(
            self.notice_loop()
        )

    # -----------------------------------------------------
    # Cog 종료
    # -----------------------------------------------------

    def cog_unload(self):

        if self.notice_task:
            self.notice_task.cancel()

        if self.session:
            asyncio.create_task(
                self.session.close()
            )

    # =====================================================
    # 상태 저장
    # =====================================================

    def load_state(self):

        try:

            if not STATE_FILE.exists():
                print(
                    "ℹ️ 상태 파일이 없어 새로 시작합니다.",
                    flush=True
                )
                return

            with open(
                STATE_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                self.state = json.load(f)

            print(
                "📂 기존 공지 상태를 불러왔습니다.",
                flush=True
            )

        except Exception as e:

            print(
                f"⚠️ 상태 파일 불러오기 실패: {e}",
                flush=True
            )

            self.state = {
                "maintenance": {},
                "patchnote": {}
            }

    # -----------------------------------------------------

    def save_state(self):

        try:

            with open(
                STATE_FILE,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    self.state,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

        except Exception as e:

            print(
                f"⚠️ 상태 저장 실패: {e}",
                flush=True
            )

    # =====================================================
    # 웹페이지 가져오기
    # =====================================================

    async def fetch_html(self, url):

        try:

            print(
                f"🌐 웹페이지 요청: {url}",
                flush=True
            )

            async with self.session.get(
                url,
                allow_redirects=True
            ) as response:

                print(
                    f"🌐 HTTP 상태: {response.status}",
                    flush=True
                )

                final_url = str(response.url)

                print(
                    f"🌐 최종 URL: {final_url}",
                    flush=True
                )

                if response.status != 200:

                    print(
                        f"❌ HTTP 오류 {response.status}",
                        flush=True
                    )

                    return None

                html = await response.text(
                    encoding="utf-8",
                    errors="ignore"
                )

                print(
                    f"📄 HTML 수신 완료: {len(html)} bytes",
                    flush=True
                )

                return html

        except asyncio.CancelledError:

            raise

        except Exception as e:

            print(
                f"❌ 웹페이지 요청 실패: "
                f"{type(e).__name__}: {e}",
                flush=True
            )

            return None

    # =====================================================
    # 최신 게시글 찾기
    # =====================================================

    async def get_latest_post(self, list_url):

        html = await self.fetch_html(list_url)

        if not html:

            print(
                f"❌ 목록 HTML을 가져오지 못했습니다: {list_url}",
                flush=True
            )

            return None

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        posts = []

        # -------------------------------------------------
        # 모든 링크 검사
        # -------------------------------------------------

        for link in soup.find_all(
            "a",
            href=True
        ):

            href = link.get(
                "href",
                ""
            ).strip()

            if not href:
                continue

            absolute_url = urljoin(
                BASE_URL,
                href
            )

            # ---------------------------------------------
            # 게시글 URL 확인
            # ---------------------------------------------

            match = re.search(
                r"/news/(notices|updates)/(\d+)",
                absolute_url
            )

            if not match:
                continue

            board_type = match.group(1)
            post_id = int(match.group(2))

            # ---------------------------------------------
            # 게시판 종류 확인
            # ---------------------------------------------

            if (
                "updates" in list_url
                and board_type != "updates"
            ):
                continue

            if (
                "notices" in list_url
                and board_type != "notices"
            ):
                continue

            # ---------------------------------------------
            # 제목 가져오기
            # ---------------------------------------------

            title = link.get_text(
                " ",
                strip=True
            )

            # 링크 자체에 제목이 없으면 부모에서 가져오기
            if not title:

                parent = link.parent

                if parent:

                    title = parent.get_text(
                        " ",
                        strip=True
                    )

            if not title:

                title = f"메이플플래닛 게시글 {post_id}"

            # ---------------------------------------------
            # 점검 게시판이면 점검 글만 허용
            # ---------------------------------------------

            if "notices" in list_url:

                # 공지사항 / 제재 등 제외
                if "점검" not in title:

                    continue

            posts.append(
                (
                    post_id,
                    absolute_url,
                    title
                )
            )

        # =================================================
        # 링크를 못 찾았을 경우
        # =================================================

        if not posts:

            print(
                "❌ 게시글 링크를 찾지 못했습니다.",
                flush=True
            )

            # 디버깅용
            print(
                "🔎 HTML 안에 /news/ 문자열 존재:",
                "/news/" in html,
                flush=True
            )

            print(
                "🔎 HTML 앞부분:",
                html[:500].replace("\n", " "),
                flush=True
            )

            return None

        # =================================================
        # 중복 제거
        # =================================================

        unique_posts = {}

        for post_id, url, title in posts:

            unique_posts[post_id] = (
                url,
                title
            )

        # 가장 큰 게시글 ID = 최신 게시글
        latest_id = max(
            unique_posts.keys()
        )

        latest_url, latest_title = unique_posts[
            latest_id
        ]

        print(
            f"🔎 최신 게시글 발견: "
            f"[{latest_id}] {latest_title}",
            flush=True
        )

        print(
            f"🔗 URL: {latest_url}",
            flush=True
        )

        return (
            latest_url,
            latest_title
        )

    # =====================================================
    # 게시글 내용 가져오기
    # =====================================================

    async def get_article(self, url):

        html = await self.fetch_html(url)

        if not html:

            return None

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        # -------------------------------------------------
        # 불필요한 태그 제거
        # -------------------------------------------------

        for tag in soup([
            "script",
            "style",
            "noscript",
            "header",
            "footer",
            "nav"
        ]):

            tag.decompose()

        # -------------------------------------------------
        # 본문 후보 찾기
        # -------------------------------------------------

        article = soup.find("article")

        if not article:
            article = soup.find("main")

        if not article:
            article = soup.body

        if not article:

            return None

        # -------------------------------------------------
        # 제목 제거
        # -------------------------------------------------

        for tag in article.find_all([
            "h1",
            "h2"
        ]):

            tag.decompose()

        # -------------------------------------------------
        # 텍스트 추출
        # -------------------------------------------------

        text = article.get_text(
            "\n",
            strip=True
        )

        # 너무 많은 빈 줄 제거
        lines = []

        for line in text.splitlines():

            line = line.strip()

            if not line:
                continue

            lines.append(line)

        text = "\n".join(lines)

        # -------------------------------------------------
        # 사이트 공통 메뉴가 앞에 붙는 경우 제거
        # -------------------------------------------------

        remove_prefixes = [
            "본문 바로가기",
            "플래닛 소식",
            "새로운 모험, 반가운 소식을 만나보세요."
        ]

        for prefix in remove_prefixes:

            if text.startswith(prefix):

                text = text[len(prefix):].strip()

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
    # 긴 글 Discord용 분할
    # =====================================================

    def split_text(
        self,
        text,
        limit=1900
    ):

        chunks = []

        while len(text) > limit:

            cut = text.rfind(
                "\n",
                0,
                limit
            )

            if cut <= 0:

                cut = limit

            chunks.append(
                text[:cut].strip()
            )

            text = text[cut:].strip()

        if text:

            chunks.append(text)

        return chunks

    # =====================================================
    # 새 공지 생성
    # =====================================================

    async def create_notice(
        self,
        channel_id,
        category,
        title,
        url,
        content
    ):

        channel = self.bot.get_channel(
            channel_id
        )

        if not channel:

            print(
                f"❌ 채널을 찾을 수 없습니다: "
                f"{channel_id}",
                flush=True
            )

            return None

        # -------------------------------------------------
        # 임베드
        # -------------------------------------------------

        if category == "maintenance":

            embed_title = "🔧 메이플플래닛 점검 안내"

        else:

            embed_title = "📢 메이플플래닛 패치노트"

        embed = discord.Embed(
            title=embed_title,
            description=title,
            url=url,
            color=discord.Color.blue()
        )

        embed.set_footer(
            text="메이플플래닛 공식 홈페이지"
        )

        # -------------------------------------------------
        # 부모 메시지
        # -------------------------------------------------

        message = await channel.send(
            embed=embed
        )

        print(
            f"📨 디스코드 공지 메시지 생성: "
            f"{message.id}",
            flush=True
        )

        # -------------------------------------------------
        # 스레드 생성
        # -------------------------------------------------

        thread = await message.create_thread(
            name=title[:100],
            auto_archive_duration=10080
        )

        print(
            f"🧵 스레드 생성: {thread.id}",
            flush=True
        )

        # -------------------------------------------------
        # 본문 전송
        # -------------------------------------------------

        chunks = self.split_text(
            content
        )

        for chunk in chunks:

            await thread.send(
                chunk
            )

        # -------------------------------------------------
        # 원문 링크
        # -------------------------------------------------

        await thread.send(
            f"🔗 **공식 원문:**\n{url}"
        )

        return {
            "message_id": message.id,
            "thread_id": thread.id,
            "url": url,
            "title": title,
            "hash": self.make_hash(content)
        }

    # =====================================================
    # 기존 공지 수정
    # =====================================================

    async def update_notice(
        self,
        channel_id,
        data,
        title,
        url,
        content
    ):

        channel = self.bot.get_channel(
            channel_id
        )

        if not channel:

            return

        message_id = data.get(
            "message_id"
        )

        thread_id = data.get(
            "thread_id"
        )

        # -------------------------------------------------
        # 기존 부모 메시지
        # -------------------------------------------------

        message = None

        if message_id:

            try:

                message = await channel.fetch_message(
                    message_id
                )

            except discord.NotFound:

                message = None

            except Exception as e:

                print(
                    f"⚠️ 기존 메시지 조회 실패: {e}",
                    flush=True
                )

        # -------------------------------------------------
        # 스레드
        # -------------------------------------------------

        thread = None

        if thread_id:

            thread = self.bot.get_channel(
                thread_id
            )

            if thread is None:

                try:

                    thread = await self.bot.fetch_channel(
                        thread_id
                    )

                except Exception:

                    thread = None

        # -------------------------------------------------
        # 스레드가 없어졌다면 새로 생성
        # -------------------------------------------------

        if message is None:

            print(
                "⚠️ 기존 공지 메시지를 찾을 수 없어 "
                "새 공지를 생성합니다.",
                flush=True
            )

            new_data = await self.create_notice(
                channel_id,
                "maintenance",
                title,
                url,
                content
            )

            return new_data

        # -------------------------------------------------
        # 스레드가 있으면 수정 내용 전송
        # -------------------------------------------------

        if thread:

            try:

                if thread.archived:

                    await thread.edit(
                        archived=False
                    )

                await thread.send(
                    "⚠️ **이 공지가 수정되었습니다.**"
                )

                await thread.send(
                    "아래는 수정된 최신 내용입니다."
                )

                chunks = self.split_text(
                    content
                )

                for chunk in chunks:

                    await thread.send(
                        chunk
                    )

                await thread.send(
                    f"🔗 **공식 원문:**\n{url}"
                )

            except Exception as e:

                print(
                    f"⚠️ 스레드 업데이트 실패: {e}",
                    flush=True
                )

        # -------------------------------------------------
        # 부모 메시지 Embed도 수정
        # -------------------------------------------------

        try:

            embed = discord.Embed(
                title=(
                    "🔧 메이플플래닛 점검 안내"
                    if "점검" in title
                    else "📢 메이플플래닛 패치노트"
                ),
                description=title,
                url=url,
                color=discord.Color.orange()
            )

            embed.set_footer(
                text="메이플플래닛 공식 홈페이지"
            )

            await message.edit(
                embed=embed
            )

        except Exception as e:

            print(
                f"⚠️ 부모 메시지 수정 실패: {e}",
                flush=True
            )

        # -------------------------------------------------
        # 상태 업데이트
        # -------------------------------------------------

        data["title"] = title
        data["url"] = url
        data["hash"] = self.make_hash(
            content
        )

        return data

    # =====================================================
    # 공지 확인
    # =====================================================

    async def check_notice(
        self,
        category,
        list_url,
        channel_id
    ):

        try:

            latest = await self.get_latest_post(
                list_url
            )

            if not latest:

                print(
                    f"❌ {category} 최신 글을 "
                    f"찾지 못했습니다.",
                    flush=True
                )

                return

            url, title = latest

            # ------------------------------------------------
            # 본문 가져오기
            # ------------------------------------------------

            content = await self.get_article(
                url
            )

            if not content:

                print(
                    f"❌ 본문을 가져오지 못했습니다: "
                    f"{url}",
                    flush=True
                )

                return

            content_hash = self.make_hash(
                content
            )

            previous = self.state.get(
                category,
                {}
            )

            # =================================================
            # 첫 실행
            # =================================================

            if not previous:

                print(
                    f"🟡 {category}: 첫 실행이므로 "
                    f"현재 글을 기준점으로 저장합니다.",
                    flush=True
                )

                self.state[category] = {
                    "url": url,
                    "title": title,
                    "hash": content_hash
                }

                self.save_state()

                return

            # =================================================
            # 새 게시글
            # =================================================

            if previous.get("url") != url:

                print(
                    f"🆕 새로운 {category} 발견!",
                    flush=True
                )

                print(
                    f"제목: {title}",
                    flush=True
                )

                data = await self.create_notice(
                    channel_id,
                    category,
                    title,
                    url,
                    content
                )

                if data:

                    self.state[category] = data

                    self.save_state()

                return

            # =================================================
            # 기존 게시글 수정
            # =================================================

            if previous.get("hash") != content_hash:

                print(
                    f"✏️ {category} 게시글 수정 감지!",
                    flush=True
                )

                updated = await self.update_notice(
                    channel_id,
                    previous,
                    title,
                    url,
                    content
                )

                if updated:

                    self.state[category] = updated

                    self.save_state()

                return

            # =================================================
            # 변화 없음
            # =================================================

            print(
                f"🟢 {category}: 변경 없음",
                flush=True
            )

        except Exception as e:

            print(
                f"❌ {category} 확인 중 오류: "
                f"{type(e).__name__}: {e}",
                flush=True
            )

    # =====================================================
    # 자동 감시 루프
    # =====================================================

    async def notice_loop(self):

        await self.bot.wait_until_ready()

        print(
            "🚀 메이플플래닛 공지 자동 감시 시작",
            flush=True
        )

        while not self.bot.is_closed():

            try:

                print(
                    "\n==============================",
                    flush=True
                )

                print(
                    "🔄 메이플플래닛 공지 확인",
                    flush=True
                )

                print(
                    "==============================",
                    flush=True
                )

                # 점검
                await self.check_notice(
                    "maintenance",
                    MAINTENANCE_LIST_URL,
                    MAINTENANCE_CHANNEL_ID
                )

                # 패치노트
                await self.check_notice(
                    "patchnote",
                    PATCHNOTE_LIST_URL,
                    PATCHNOTE_CHANNEL_ID
                )

            except asyncio.CancelledError:

                raise

            except Exception as e:

                print(
                    f"❌ 공지 감시 루프 오류: {e}",
                    flush=True
                )

            await asyncio.sleep(
                CHECK_INTERVAL
            )

    # =====================================================
    # 수동 점검 테스트
    # =====================================================

    @commands.command(
        name="공지테스트"
    )
    @commands.has_permissions(
        administrator=True
    )
    async def maintenance_test(
        self,
        ctx
    ):

        msg = await ctx.send(
            "🔎 최신 점검 공지를 가져오는 중입니다..."
        )

        latest = await self.get_latest_post(
            MAINTENANCE_LIST_URL
        )

        if not latest:

            await msg.edit(
                content="❌ 최신 점검 공지를 찾지 못했습니다."
            )

            return

        url, title = latest

        content = await self.get_article(
            url
        )

        if not content:

            await msg.edit(
                content="❌ 점검 공지 본문을 가져오지 못했습니다."
            )

            return

        await self.create_notice(
            MAINTENANCE_CHANNEL_ID,
            "maintenance",
            title,
            url,
            content
        )

        await msg.edit(
            content=(
                "✅ 최신 점검 공지를 "
                "디스코드에 테스트 전송했습니다.\n\n"
                f"**{title}**"
            )
        )

    # =====================================================
    # 수동 패치노트 테스트
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

        msg = await ctx.send(
            "🔎 최신 패치노트를 가져오는 중입니다..."
        )

        latest = await self.get_latest_post(
            PATCHNOTE_LIST_URL
        )

        if not latest:

            await msg.edit(
                content="❌ 최신 패치노트를 찾지 못했습니다."
            )

            return

        url, title = latest

        content = await self.get_article(
            url
        )

        if not content:

            await msg.edit(
                content="❌ 패치노트 본문을 가져오지 못했습니다."
            )

            return

        await self.create_notice(
            PATCHNOTE_CHANNEL_ID,
            "patchnote",
            title,
            url,
            content
        )

        await msg.edit(
            content=(
                "✅ 최신 패치노트를 "
                "디스코드에 테스트 전송했습니다.\n\n"
                f"**{title}**"
            )
        )


# =========================================================
# Cog 등록
# =========================================================

async def setup(bot):

    await bot.add_cog(
        MapleNotice(bot)
    )