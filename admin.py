"""
老師自訂介面：在 Discord 用斜線指令調整機器人，不用碰程式或檔案

  /語氣 查看      看目前的語氣設定（附檔案）
  /語氣 修改      跳出編輯視窗直接改
  /語氣 上傳      上傳改好的 .md 整份取代
  /語氣 還原      回到之前的版本（每次修改前都會自動備份）
  /用詞 列表      看「送出前自動替換／刪除」的用詞
  /用詞 新增      例：把「問老師」換成「問小樽」；改成留空白 = 直接刪掉（例如「妥妥的」）
  /用詞 刪除
  /試答          用目前的設定試答一題（只有自己看得到，不會開討論串、不會上網查）

- 只有 .env 的 REVIEWER_IDS 裡的人，或伺服器有「管理伺服器」權限的人能用；學生看不到這些指令
- 所有回覆都只有下指令的人看得到
- 設定存在 persona/ 資料夾，改了下一題就生效，不用重開機器人
"""
import datetime
import io
import os
import re
import shutil

import discord
from discord import app_commands

BASE = os.path.dirname(os.path.abspath(__file__))
PERSONA_DIR = os.path.join(BASE, "persona")
HISTORY_DIR = os.path.join(PERSONA_DIR, "歷史")
REPLACE_FILE = os.path.join(PERSONA_DIR, "用詞替換.txt")

VERSIONS = {
    "full": ("小樽_完整.md", "完整版（Gemini 用，網路查詢・截圖・備援）"),
    "short": ("小樽_精簡.md", "精簡版（本地模型用，大部分的回答）"),
}
VERSION_CHOICES = [app_commands.Choice(name=label, value=key) for key, (_, label) in VERSIONS.items()]
MODAL_MAX = 4000   # Discord 編輯視窗的字數上限

REPLACE_HEADER = """# 用詞替換：機器人送出回答前，會把左邊的字換成右邊的字（每行一條）
# 右邊空白 = 直接刪掉。可以用 Discord 的 /用詞 指令改，也可以直接改這個檔案，存檔馬上生效
# 格式：原本 => 改成
"""
DEFAULT_REPLACEMENTS = [("妥妥的", ""), ("莫慌莫慌", ""), ("莫慌", ""),
                        ("問老師", "問小樽"), ("找老師", "找小樽")]


# ───────────── 用詞替換 ─────────────

def load_replacements():
    """回傳 [(原本, 改成), ...]，長的排前面（「莫慌莫慌」要比「莫慌」先換）"""
    if not os.path.exists(REPLACE_FILE):
        save_replacements(DEFAULT_REPLACEMENTS)
    pairs = []
    try:
        with open(REPLACE_FILE, encoding="utf-8-sig") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                m = re.match(r"^(.*?)\s*(?:=>|→)\s*(.*)$", line)
                src, dst = m.groups() if m else (line, "")
                if src.strip():
                    pairs.append((src.strip(), dst.strip()))
    except OSError:
        pairs = list(DEFAULT_REPLACEMENTS)
    return sorted(pairs, key=lambda p: len(p[0]), reverse=True)


def save_replacements(pairs):
    os.makedirs(PERSONA_DIR, exist_ok=True)
    with open(REPLACE_FILE, "w", encoding="utf-8") as f:
        f.write(REPLACE_HEADER + "\n")
        for src, dst in pairs:
            f.write(f"{src} => {dst}\n")


def apply_replacements(text):
    for src, dst in load_replacements():
        if dst:
            text = text.replace(src, dst)
        else:   # 刪掉，順便清掉後面接的驚嘆號、波浪號
            text = re.sub(re.escape(src) + r"[！!~～。.]*", "", text)
    return text


# ───────────── 語氣檔與備份 ─────────────

def persona_path(key):
    return os.path.join(PERSONA_DIR, VERSIONS[key][0])


def read_persona(key):
    try:
        with open(persona_path(key), encoding="utf-8-sig") as f:
            return f.read()
    except OSError:
        return ""


def backups(key):
    """這個版本的備份，新的在前面"""
    stem = os.path.splitext(VERSIONS[key][0])[0]
    if not os.path.isdir(HISTORY_DIR):
        return []
    return sorted((n for n in os.listdir(HISTORY_DIR) if n.startswith(stem + "_") and n.endswith(".md")),
                  reverse=True)


def write_persona(key, text, who):
    """先把目前的檔案備份到 persona/歷史/，再寫入新內容"""
    path = persona_path(key)
    if os.path.exists(path):
        os.makedirs(HISTORY_DIR, exist_ok=True)
        stem = os.path.splitext(VERSIONS[key][0])[0]
        shutil.copy2(path, os.path.join(HISTORY_DIR, f"{stem}_{datetime.datetime.now():%Y%m%d_%H%M%S}.md"))
    text = text.replace("\r\n", "\n").strip() + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"[自訂] {who} 修改了 {VERSIONS[key][0]}")


def backup_label(name):
    m = re.search(r"_(\d{8})_(\d{6})\.md$", name)
    if not m:
        return name
    d, t = m.groups()
    return f"{d[:4]}/{d[4:6]}/{d[6:]} {t[:2]}:{t[2:4]}:{t[4:]}"


# ───────────── Discord 指令 ─────────────

def register(tree, *, reviewer_ids, try_answer, split_for_chat):
    """把指令加到 CommandTree。try_answer(問題) → (回答, 模型, 參考資料)"""

    def allowed(inter):
        if inter.user.id in reviewer_ids:
            return True
        perms = getattr(inter.user, "guild_permissions", None)
        return bool(perms and (perms.manage_guild or perms.administrator))

    async def deny(inter):
        await inter.response.send_message("這個指令只有老師／管理員能用唷", ephemeral=True)

    perm = app_commands.default_permissions(manage_guild=True)   # 學生的指令清單裡看不到

    # ── /語氣 ──
    tone = app_commands.Group(name="語氣", description="調整機器人回答的語氣", guild_only=True,
                              default_permissions=discord.Permissions(manage_guild=True))

    @tone.command(name="查看", description="看目前的語氣設定")
    async def tone_view(inter: discord.Interaction):
        if not allowed(inter):
            return await deny(inter)
        files = [discord.File(io.BytesIO(read_persona(k).encode("utf-8")), filename=VERSIONS[k][0])
                 for k in VERSIONS]
        await inter.response.send_message(
            "目前的語氣設定（點開附檔看完整內容）：\n"
            "• **精簡版**：本地模型用，大部分的回答都是它\n"
            "• **完整版**：Gemini 用（網路查詢、看截圖、本地模型失敗時）\n"
            "-# 兩份最好一起改，語氣才會一致。用 `/語氣 修改` 直接改，或改好檔案用 `/語氣 上傳`",
            files=files, ephemeral=True)

    class EditModal(discord.ui.Modal):
        def __init__(self, key):
            super().__init__(title=f"修改語氣：{VERSIONS[key][0]}", timeout=1800)
            self.key = key
            self.body = discord.ui.TextInput(label="語氣設定（第一行 # 開頭的是說明，不會給 AI 看）",
                                             style=discord.TextStyle.paragraph,
                                             default=read_persona(key)[:MODAL_MAX], max_length=MODAL_MAX)
            self.add_item(self.body)

        async def on_submit(self, inter: discord.Interaction):
            write_persona(self.key, self.body.value, inter.user)
            await inter.response.send_message(
                f"✅ 已更新{VERSIONS[self.key][1]}，下一題就生效\n"
                "-# 用 `/試答` 試試看效果；改壞了用 `/語氣 還原`", ephemeral=True)

    @tone.command(name="修改", description="跳出編輯視窗修改語氣設定")
    @app_commands.describe(版本="要改哪一份")
    @app_commands.choices(版本=VERSION_CHOICES)
    async def tone_edit(inter: discord.Interaction, 版本: app_commands.Choice[str]):
        if not allowed(inter):
            return await deny(inter)
        if len(read_persona(版本.value)) > MODAL_MAX:
            return await inter.response.send_message(
                f"這份設定超過 {MODAL_MAX} 字，編輯視窗放不下，請用 `/語氣 查看` 下載、改好後用 `/語氣 上傳`",
                ephemeral=True)
        await inter.response.send_modal(EditModal(版本.value))

    @tone.command(name="上傳", description="上傳改好的 .md 檔，整份取代")
    @app_commands.describe(版本="要取代哪一份", 檔案=".md 或 .txt 檔")
    @app_commands.choices(版本=VERSION_CHOICES)
    async def tone_upload(inter: discord.Interaction, 版本: app_commands.Choice[str], 檔案: discord.Attachment):
        if not allowed(inter):
            return await deny(inter)
        if not 檔案.filename.lower().endswith((".md", ".txt")) or 檔案.size > 200_000:
            return await inter.response.send_message("請上傳 .md 或 .txt 檔（200KB 以內）", ephemeral=True)
        text = (await 檔案.read()).decode("utf-8-sig", "replace")
        if not text.strip():
            return await inter.response.send_message("檔案是空的，沒有更新", ephemeral=True)
        write_persona(版本.value, text, inter.user)
        await inter.response.send_message(f"✅ 已用 `{檔案.filename}` 取代{VERSIONS[版本.value][1]}，下一題就生效",
                                          ephemeral=True)

    async def backup_autocomplete(inter: discord.Interaction, current: str):
        key = getattr(inter.namespace, "版本", None) or "short"
        return [app_commands.Choice(name=backup_label(n), value=n)
                for n in backups(key) if current in backup_label(n)][:25]

    @tone.command(name="還原", description="回到之前的版本（每次修改前都會自動備份）")
    @app_commands.describe(版本="要還原哪一份", 備份="要回到哪個時間的版本（不選 = 上一版）")
    @app_commands.choices(版本=VERSION_CHOICES)
    @app_commands.autocomplete(備份=backup_autocomplete)
    async def tone_restore(inter: discord.Interaction, 版本: app_commands.Choice[str], 備份: str = ""):
        if not allowed(inter):
            return await deny(inter)
        names = backups(版本.value)
        if not names:
            return await inter.response.send_message("這份還沒有修改過，沒有可以還原的版本", ephemeral=True)
        name = 備份 if 備份 in names else names[0]
        with open(os.path.join(HISTORY_DIR, name), encoding="utf-8-sig") as f:
            text = f.read()
        write_persona(版本.value, text, inter.user)   # 現在的版本也會先備份，還原錯了可以再還原回來
        await inter.response.send_message(
            f"↩️ {VERSIONS[版本.value][1]}已還原成 {backup_label(name)} 的版本", ephemeral=True)

    # ── /用詞 ──
    words = app_commands.Group(name="用詞", description="送出回答前自動替換或刪除的用詞", guild_only=True,
                               default_permissions=discord.Permissions(manage_guild=True))

    def word_list_text():
        pairs = load_replacements()
        if not pairs:
            return "（目前沒有設定）"
        return "\n".join(f"• 「{s}」→ " + (f"「{d}」" if d else "（刪掉）") for s, d in pairs)

    @words.command(name="列表", description="看目前的用詞替換清單")
    async def words_list(inter: discord.Interaction):
        if not allowed(inter):
            return await deny(inter)
        await inter.response.send_message(
            "機器人送出回答前，會自動做這些替換：\n" + word_list_text()
            + "\n-# AI 有時候不照語氣設定講話，這裡是最後一道保險", ephemeral=True)

    @words.command(name="新增", description="新增或修改一條替換規則")
    @app_commands.describe(原本="回答裡出現這個字", 改成="換成這個字（留空白 = 直接刪掉）")
    async def words_add(inter: discord.Interaction, 原本: str, 改成: str = ""):
        if not allowed(inter):
            return await deny(inter)
        原本, 改成 = 原本.strip(), 改成.strip()
        if not 原本 or "=>" in 原本 or "→" in 原本:
            return await inter.response.send_message("「原本」不能是空白，也不能有 => 或 →", ephemeral=True)
        pairs = [p for p in load_replacements() if p[0] != 原本] + [(原本, 改成)]
        save_replacements(pairs)
        print(f"[自訂] {inter.user} 用詞：{原本} → {改成 or '（刪掉）'}")
        await inter.response.send_message(
            f"✅ 之後回答裡的「{原本}」會" + (f"換成「{改成}」" if 改成 else "直接刪掉"), ephemeral=True)

    async def words_autocomplete(inter: discord.Interaction, current: str):
        return [app_commands.Choice(name=f"{s} → {d or '（刪掉）'}"[:100], value=s)
                for s, d in load_replacements() if current in s][:25]

    @words.command(name="刪除", description="刪掉一條替換規則")
    @app_commands.describe(原本="要刪掉哪一條")
    @app_commands.autocomplete(原本=words_autocomplete)
    async def words_remove(inter: discord.Interaction, 原本: str):
        if not allowed(inter):
            return await deny(inter)
        pairs = load_replacements()
        if 原本 not in [s for s, _ in pairs]:
            return await inter.response.send_message(f"清單裡沒有「{原本}」", ephemeral=True)
        save_replacements([p for p in pairs if p[0] != 原本])
        await inter.response.send_message(f"🗑️ 已刪掉「{原本}」這條規則", ephemeral=True)

    # ── /試答 ──
    @tree.command(name="試答", description="用目前的語氣設定試答一題（只有你看得到）")
    @app_commands.describe(問題="想測試的學生問題")
    @app_commands.guild_only()
    @perm
    async def try_cmd(inter: discord.Interaction, 問題: str):
        if not allowed(inter):
            return await deny(inter)
        await inter.response.defer(ephemeral=True, thinking=True)
        try:
            answer, engine, source = await try_answer(問題)
        except Exception as e:
            return await inter.followup.send(f"試答失敗：{e!r}"[:1900], ephemeral=True)
        parts = split_for_chat(answer)
        shown = "\n".join(f"> {p}" for p in parts) if parts else answer
        note = "（學生那邊會拆成幾則短訊息連發）" if parts else ""
        text = (f"**問：**{問題}\n\n{shown}\n\n"
                f"-# 🤖 {engine}｜📚 {source}{note}\n"
                "-# 試答不會開討論串、不會上網查、不會記錄；正式回答會多附延伸教學連結")
        await inter.followup.send(text[:2000], ephemeral=True)

    tree.add_command(tone)
    tree.add_command(words)


async def sync_commands(tree, guilds):
    """把指令同步到每個伺服器（伺服器指令是立刻生效的；全域指令要等一小時）"""
    for g in guilds:
        try:
            tree.copy_global_to(guild=g)
            await tree.sync(guild=g)
            print(f"斜線指令已同步：{g.name}（老師可以用 /語氣、/用詞、/試答）")
        except discord.Forbidden:
            print(f"⚠️ {g.name}：機器人沒有建立斜線指令的權限。請用含 applications.commands 的邀請連結重新邀請機器人"
                  "（重新執行 install.bat 會給你連結）")
        except Exception as e:
            print(f"⚠️ {g.name}：斜線指令同步失敗 {e!r}")
