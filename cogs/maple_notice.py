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
# 📢 메이플플래닛 공지 자동 알림
# =========================================================

MAINTENANCE_CHANNEL_ID = 1557841882095030302
PATCHNOTE_CHANNEL_ID = 1557841935593513032

MAINTENANCE_LIST_URL = "https://mapleplanet.co.kr/news/notices?status=maintenance"
PATCHNOTE_LIST_URL = "https://mapleplanet.co.kr/news/updates"

BASE_URL = "https://mapleplanet.co.kr"

# 확인 주기
CHECK_INTERVAL = 60

# 상태 저장 파일
STATE_FILE = Path("maple_notice_state.json")


class MapleNotice(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.session = None
        self.notice_task = None

    # =====================================================
    # Cog 로드
    # =====================================================

    async def cog_load(self):
        self.session = aiohttp.ClientSession(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 "
                    "(KHTML, like Gecko) "
                    "Chrome/140.0 Safari/537.36"
                )
            }
        )

        self.notice_task = asyncio.create_task(
            self.notice_loop()
        )

        print("📢 메이플플래닛 공지 감시 시작")

    # =====================================================
    # Cog 종료
    # =====================================================

    async def cog_unload(self):

        if self.notice_task:
            self.notice_task.cancel()

        if self.session:
            await self.session.close()

    # =====================================================
    # 상태 파일
    # =====================================================

    def load_state(self):

        if not STATE_FILE.exists():
            return {
                "maintenance": None,
                "patchnote": None
            }

        try:
            with open(
                STATE_FILE,
                "r",
                encoding="utf-8"
            ) as f:
                return json.load(f)

        except Exception:
            return {
                "maintenance": None,
                "patchnote": None
            }

    def save_state(self, state):

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

    # =====================================================
    # 웹 페이지 가져오기
    # =====================================================

    async def fetch_html(self, url):

        try:

            async with self.session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as response:

                if response.status != 200:
                    print(
                        f"⚠️ 웹 요청 실패: "
                        f"{response.status} / {url}"
                    )
                    return None

                return await response.text()

        except Exception as e:

            print(
                f"⚠️ 웹 요청 오류: {e}"
            )

            return None

    # =====================================================
    # 게시글 ID 추출
    # =====================================================

    def get_post_id(self, url):

        match = re.search(
            r"/news/(?:notices|updates)/(\d+)",
            url
        )

        if not match:
            return 0

        return int(match.group(1))

    # =====================================================
    # 최신 게시글 찾기
    # =====================================================

    async def get_latest_post(
        self,
        list_url,
        post_type
    ):

        html = await self.fetch_html(list_url)

        if not html:
            return None

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        posts = {}

        if post_type == "maintenance":

            pattern = r"/news/notices/(\d+)"

        else:

            pattern = r"/news/updates/(\d+)"

        for a in soup.find_all("a"):

            href = a.get("href")

            if not href:
                continue

            full_url = urljoin(
                BASE_URL,
                href
            )

            match = re.search(
                pattern,
                full_url
            )

            if not match:
                continue

            post_id = int(match.group(1))

            title = a.get_text(
                " ",
                strip=True
            )

            posts[post_id] = {
                "id": post_id,
                "url": full_url,
                "title": title
            }

        if not posts:
            print(
                f"⚠️ 최신 {post_type} 게시글을 찾지 못했습니다."
            )
            return None

        # 게시글 번호가 가장 큰 것을 최신으로 판단
        latest_id = max(posts.keys())

        return posts[latest_id]

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

        # 불필요한 영역 제거
        for tag in soup([
            "script",
            "style",
            "noscript",
            "header",
            "footer",
            "nav"
        ]):
            tag.decompose()

        # 게시글 본문 후보
        article = (
            soup.find("article")
            or soup.find("main")
        )

        if article is None:
            article = soup.body

        if article is None:
            return None

        # 제목 제거
        for heading in article.find_all(
            ["h1", "h2"],
            limit=2
        ):
            heading.decompose()

        title = soup.find("h1")

        if title:
            title_text = title.get_text(
                " ",
                strip=True
            )
        else:
            title_text = "메이플플래닛 공지"

        # 텍스트 추출
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

        # 사이트 하단 고정 문구 제거
        remove_texts = [
            "메이플플래닛은 MapleStory Worlds 플랫폼에서 즐길 수 있는 클래식 메이플스토리 RPG 게임입니다.",
            "'MapleStory' 및 관련 지식재산권은 NEXON Korea Corp.",
            "© 2026 Planet Games."
        ]

        for remove_text in remove_texts:
            text = text.replace(
                remove_text,
                ""
            )

        text = text.strip()

        return {
            "title": title_text,
            "content": text
        }

    # =====================================================
    # 본문 해시
    # =====================================================

    def make_hash(self, content):

        normalized = re.sub(
            r"\s+",
            " ",
            content
        ).strip()

        return hashlib.sha256(
            normalized.encode("utf-8")
        ).hexdigest()

    # =====================================================
    # Discord 메시지 찾기
    # =====================================================

    async def get_message(
        self,
        channel_id,
        message_id
    ):

        if not message_id:
            return None

        channel = self.bot.get_channel(
            channel_id
        )

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(
                    channel_id
                )
            except Exception:
                return None

        try:
            return await channel.fetch_message(
                message_id
            )

        except Exception:
            return None

    # =====================================================
    # 본문 Discord 전송
    # =====================================================

    async def send_content(
        self,
        thread,
        content
    ):

        # Discord 메시지 최대 2000자
        chunks = [
            content[i:i + 1900]
            for i in range(
                0,
                len(content),
                1900
            )
        ]

        for chunk in chunks:

            await thread.send(chunk)

            await asyncio.sleep(0.2)

    # =====================================================
    # 새 공지 등록
    # =====================================================

    async def create_notice(
        self,
        post,
        article,
        channel_id,
        notice_type
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
                    f"❌ 채널을 찾을 수 없습니다: "
                    f"{channel_id} / {e}"
                )

                return None

        if notice_type == "maintenance":

            emoji = "🔧"
            color = discord.Color.orange()
            type_name = "라이브 점검"

        else:

            emoji = "📜"
            color = discord.Color.blue()
            type_name = "패치노트"

        embed = discord.Embed(
            title=f"{emoji} {article['title']}",
            description=(
                f"새로운 **{type_name}**가 등록되었습니다.\n\n"
                f"아래 스레드에서 자세한 내용을 확인해주세요."
            ),
            color=color,
            url=post["url"]
        )

        embed.set_footer(
            text="메이플플래닛 공식 홈페이지"
        )

        parent_message = await channel.send(
            embed=embed
        )

        # 스레드 생성
        thread = await parent_message.create_thread(
            name=article["title"][:90],
            auto_archive_duration=1440
        )

        # 본문
        await self.send_content(
            thread,
            article["content"]
        )

        # 원문 링크
        await thread.send(
            f"🔗 **원문:** {post['url']}"
        )

        print(
            f"📢 새 {notice_type} 등록: "
            f"{article['title']}"
        )

        return {
            "url": post["url"],
            "title": article["title"],
            "content_hash": self.make_hash(
                article["content"]
            ),
            "message_id": parent_message.id,
            "thread_id": thread.id
        }

    # =====================================================
    # 수정된 공지 처리
    # =====================================================

    async def update_notice(
        self,
        old_data,
        post,
        article,
        channel_id,
        notice_type
    ):

        thread = None
        parent_message = None

        # 부모 메시지
        if old_data.get("message_id"):

            parent_message = await self.get_message(
                channel_id,
                old_data["message_id"]
            )

        # 스레드
        if old_data.get("thread_id"):

            try:

                thread = self.bot.get_channel(
                    old_data["thread_id"]
                )

                if thread is None:

                    thread = await self.bot.fetch_channel(
                        old_data["thread_id"]
                    )

            except Exception:

                thread = None

        # =================================================
        # 스레드가 정상적으로 존재하는 경우
        # =================================================

        if thread:

            await thread.send(
                "⚠️ **이 공지가 수정되었습니다.**\n"
                "아래는 수정된 최신 내용입니다."
            )

            await self.send_content(
                thread,
                article["content"]
            )

            await thread.send(
                f"🔗 **최신 원문:** {post['url']}"
            )

        # =================================================
        # 부모 메시지 Embed 업데이트
        # =================================================

        if parent_message:

            if notice_type == "maintenance":

                color = discord.Color.orange()
                emoji = "🔧"

            else:

                color = discord.Color.blue()
                emoji = "📜"

            embed = discord.Embed(
                title=f"{emoji} {article['title']}",
                description=(
                    "⚠️ **수정된 공지입니다.**\n\n"
                    "본문이 수정되었습니다. "
                    "스레드에서 최신 내용을 확인해주세요."
                ),
                color=color,
                url=post["url"]
            )

            embed.set_footer(
                text="메이플플래닛 공식 홈페이지"
            )

            try:

                await parent_message.edit(
                    embed=embed
                )

            except Exception as e:

                print(
                    f"⚠️ 부모 메시지 수정 실패: {e}"
                )

        print(
            f"✏️ 수정된 {notice_type}: "
            f"{article['title']}"
        )

        return {
            "url": post["url"],
            "title": article["title"],
            "content_hash": self.make_hash(
                article["content"]
            ),
            "message_id": old_data.get(
                "message_id"
            ),
            "thread_id": old_data.get(
                "thread_id"
            )
        }

    # =====================================================
    # 공지 하나 검사
    # =====================================================

    async def check_notice(
        self,
        state,
        notice_type,
        list_url,
        channel_id
    ):

        latest = await self.get_latest_post(
            list_url,
            notice_type
        )

        if not latest:
            return

        article = await self.get_article(
            latest["url"]
        )

        if not article:
            return

        current_hash = self.make_hash(
            article["content"]
        )

        old_data = state.get(
            notice_type
        )

        # =================================================
        # 최초 실행
        # =================================================

        if old_data is None:

            state[notice_type] = {
                "url": latest["url"],
                "title": article["title"],
                "content_hash": current_hash,
                "message_id": None,
                "thread_id": None
            }

            print(
                f"📌 최초 실행 - 현재 {notice_type} 저장: "
                f"{article['title']}"
            )

            return

        # =================================================
        # 새로운 게시글
        # =================================================

        if old_data.get("url") != latest["url"]:

            new_data = await self.create_notice(
                latest,
                article,
                channel_id,
                notice_type
            )

            if new_data:
                state[notice_type] = new_data

            return

        # =================================================
        # 같은 게시글인데 본문 수정
        # =================================================

        if old_data.get(
            "content_hash"
        ) != current_hash:

            new_data = await self.update_notice(
                old_data,
                latest,
                article,
                channel_id,
                notice_type
            )

            if new_data:
                state[notice_type] = new_data

    # =====================================================
    # 주기적으로 검사
    # =====================================================

    async def notice_loop(self):

        await self.bot.wait_until_ready()

        state = self.load_state()

        while not self.bot.is_closed():

            try:

                # 점검 공지
                await self.check_notice(
                    state,
                    "maintenance",
                    MAINTENANCE_LIST_URL,
                    MAINTENANCE_CHANNEL_ID
                )

                # 패치노트
                await self.check_notice(
                    state,
                    "patchnote",
                    PATCHNOTE_LIST_URL,
                    PATCHNOTE_CHANNEL_ID
                )

                self.save_state(state)

            except asyncio.CancelledError:

                break

            except Exception as e:

                print(
                    f"❌ 메이플 공지 감시 오류: {e}"
                )

            await asyncio.sleep(
                CHECK_INTERVAL
            )


# =========================================================
# Cog 등록
# =========================================================

async def setup(bot):

    await bot.add_cog(
        MapleNotice(bot)
    )