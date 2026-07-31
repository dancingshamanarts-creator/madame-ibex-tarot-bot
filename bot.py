import discord
from discord import app_commands
from discord.ext import commands
import random
import os
import anthropic
import asyncpg
from datetime import datetime, timezone, timedelta
from card_data import CARDS, get_card, SPREAD_TYPES

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
PATREON_ROLE_NAME = os.environ.get("PATREON_ROLE_NAME", "Patreon")
DATABASE_URL = os.environ.get("DATABASE_URL")

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ─── DATABASE (free-reading daily limit) ────────────────────────────
# One free /reading per non-Patreon user per calendar day (UTC).
# We store the date of each user's most recent free reading; if it's
# already today, they're asked to come back tomorrow.
db_pool = None


async def setup_database():
    """Create the connection pool and both tracking tables if missing."""
    global db_pool
    if not DATABASE_URL:
        print("WARNING: DATABASE_URL not set — free-reading limit is OFF.")
        return
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    async with db_pool.acquire() as conn:
        # Free /reading — one per day per non-Patreon user
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS free_readings (
                user_id BIGINT PRIMARY KEY,
                last_reading_date DATE NOT NULL
            )
        """)
        # Paid /myreading — monthly count per Patreon user
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS patreon_readings (
                user_id BIGINT NOT NULL,
                year    SMALLINT NOT NULL,
                month   SMALLINT NOT NULL,
                count   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, year, month)
            )
        """)
    print("Database ready — free-reading limit is ON.")


async def get_monthly_reading_count(user_id):
    """Return how many /myreading reads this user has used this month."""
    if db_pool is None:
        return 0
    now = datetime.now(timezone.utc)
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT count FROM patreon_readings WHERE user_id=$1 AND year=$2 AND month=$3",
            user_id, now.year, now.month,
        )
    return row["count"] if row else 0


async def increment_monthly_reading_count(user_id):
    """Add one to this user's /myreading count for the current month."""
    if db_pool is None:
        return
    now = datetime.now(timezone.utc)
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO patreon_readings (user_id, year, month, count)
            VALUES ($1, $2, $3, 1)
            ON CONFLICT (user_id, year, month)
            DO UPDATE SET count = patreon_readings.count + 1
            """,
            user_id, now.year, now.month,
        )


async def has_used_free_reading_today(user_id):
    """True if this user already had a free reading today (UTC)."""
    if db_pool is None:
        return False  # No DB configured → don't block anyone.
    today = datetime.now(timezone.utc).date()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_reading_date FROM free_readings WHERE user_id = $1",
            user_id,
        )
    return row is not None and row["last_reading_date"] == today


async def record_free_reading(user_id):
    """Stamp this user's free reading as happening today (UTC)."""
    if db_pool is None:
        return
    today = datetime.now(timezone.utc).date()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO free_readings (user_id, last_reading_date)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET last_reading_date = $2
            """,
            user_id, today,
        )


# ─── PATREON TIERS ──────────────────────────────────────────────────
# Maps each Discord role name to its monthly /myreading limit.
# None means unlimited.
TIER_LIMITS = {
    "Oracle":  None,   # $20/mo — unlimited
    "Devotee": 15,     # $10/mo — 15 reads/month
    "Seeker":  5,      # $5/mo  —  5 reads/month
}


def get_patreon_tier(interaction):
    """Return the name of the user's highest Patreon tier, or None if
    they have no Patreon role at all.  Oracle > Devotee > Seeker."""
    if interaction.guild is None:
        return None
    for tier in ("Oracle", "Devotee", "Seeker"):
        role = discord.utils.get(interaction.guild.roles, name=tier)
        if role and role in interaction.user.roles:
            return tier
    return None


def is_patreon_member(interaction):
    """True if the user holds any Patreon tier role."""
    return get_patreon_tier(interaction) is not None


MADAME_IBEX_SYSTEM = """You are Madame Ibex. You read tarot in a room off a courtyard in the French Quarter, New Orleans. You are Haitian. The sight came through your mother's line, and you have never once had to ask whether it was real.

VOICE — the most important thing:
Your voice lives in rhythm and syntax, never in misspelled words. Never write dialect phonetically — no dropped letters, no apostrophes standing in for sounds. The music comes from structure:
- Short sentences landing after long ones.
- Repetition when something matters. Say it. Then say it again, differently.
- Statements where another reader would put a question.
- Present tense that carries the past inside it.
- French or Kreyòl only where it arrives on its own. Never as decoration.

HOW YOU READ:
You do not hunt for hidden details in the picture. That is a parlor trick. You read what a card is — its nature, its weight, what it carries, what it wants. A card is not a puzzle to be solved. It is a presence that has entered the room.

You read the cards against each other. What one begins, another answers or refuses. A spread is a conversation, not a list.

You know the difference between what a person asks and what they came to find out. You answer the second one.

WHEN A CARD COMES REVERSED:
A turned card has not become its opposite. That is bookkeeping, not sight. A turned card is the same presence arriving another way — held back, turned inward, refused, spent, or not yet ready to give what it carries. Sometimes it means the thing is happening to the person instead of through them. Sometimes it means they are standing in its way. Read which. Say it plainly. Do not announce "this is reversed" like a weather report — let it change what you say about the card.

WHAT YOU DO NOT DO:
- You do not comfort falsely. Ever.
- You do not soften a hard card to be liked.
- You do not use received tarot language — no "energies," no "the universe," no "manifesting."
- You do not perform. People come to the Quarter wanting a show. You give them the truth instead. Some never come back. That is fine.

TEXTURE:
The river. Heat that settles into a room and will not leave. Iron balconies. Graves above ground because the water allows nothing else. Use these rarely — only when a card calls one up.

WRITING A READING:
- Speak directly to the person. You are sitting across from them.
- Draw the cards into one message, not three separate verdicts.
- End with two or three questions the reading puts to them. Real ones. Hard ones.
- Keep the whole reading under 3500 characters."""


def draw_cards(positions):
    """Draw one card per position, each randomly upright or reversed.
    Returns a list of (position, card_name, card_data, is_reversed)."""
    drawn = random.sample(list(CARDS.keys()), len(positions))
    return [
        (positions[i], drawn[i], CARDS[drawn[i]], random.choice([True, False]))
        for i in range(len(positions))
    ]


def card_image_url(card_data, is_reversed):
    """Return the image URL for a card in the given orientation.

    The rotated copies live beside the originals in the repo, prefixed
    "reversed-" (e.g. reversed-major-00-the-fool.jpg). Shared by readings
    and /cardinfo so a turned card looks the same everywhere.
    """
    image_url = card_data.get("image_url")
    if image_url and is_reversed:
        base, _, filename = image_url.rpartition("/")
        image_url = f"{base}/reversed-{filename}"
    return image_url


def card_body(card_data, is_reversed):
    """Madame Ibex's interpretation, marked when the card came turned."""
    body = card_data["madame_ibex"]
    if is_reversed:
        body = "**The card came turned.**\n\n" + body
    # Embed description limit is 4096; trim as a safety net.
    if len(body) > 4000:
        body = body[:3997] + "..."
    return body


def madame_ibex_summary(cards_in_reading, question=None, spread_type="3 Card"):
    card_descriptions = []
    for position, card_name, card_data, is_reversed in cards_in_reading:
        interp = card_data["madame_ibex"]
        orientation = "REVERSED" if is_reversed else "upright"
        card_descriptions.append(
            f"Position: {position}\nCard: {card_name} ({orientation})\nInterpretation: {interp}"
        )

    prompt = f"Spread: {spread_type}\n"
    if question:
        prompt += f"Question asked: {question}\n"
    prompt += "\nCards in this reading:\n\n" + "\n\n".join(card_descriptions)
    prompt += "\n\nWrite a unified reading summary in Madame Ibex's voice."

    response = anthropic_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=MADAME_IBEX_SYSTEM,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def build_reading_embeds(title, cards_in_reading, summary, question=None):
    """Build a LIST of embeds:
      - one embed per card, showing that card's image inline (by URL) plus
        Madame Ibex's interpretation of it
      - a final embed carrying Madame Ibex's full woven reading

    Images set by URL preview inline (no clicking), which needs the repo
    public — it is. Discord allows at most 10 embeds per message, which
    comfortably covers every current spread.
    """
    color = discord.Color.from_rgb(75, 0, 130)
    embeds = []

    total = len(cards_in_reading)
    for i, (position, card_name, card_data, is_reversed) in enumerate(cards_in_reading):
        body = card_body(card_data, is_reversed)

        card_embed = discord.Embed(
            title=f"✦ {position}: {card_name}" + (" — Reversed" if is_reversed else ""),
            description=body,
            color=color,
        )
        # First card's embed carries the header + optional question.
        if i == 0:
            card_embed.set_author(name=f"Madame Ibex — {title}")
            if question:
                q = question if len(question) <= 1024 else question[:1021] + "..."
                card_embed.add_field(name="Question", value=q, inline=False)

        image_url = card_image_url(card_data, is_reversed)
        if image_url:
            card_embed.set_image(url=image_url)

        card_embed.set_footer(text=f"Card {i+1} of {total}")
        embeds.append(card_embed)

    # Final embed: the full woven reading.
    safe_summary = summary.strip()
    if len(safe_summary) > 4000:
        safe_summary = safe_summary[:3997] + "..."
    summary_embed = discord.Embed(
        title="✦ Madame Ibex Reads the Spread",
        description=safe_summary,
        color=color,
    )
    summary_embed.set_footer(
        text="The Cards As I See Them — Madame Ibex | Madame Ibex Tarot\n"
             "For entertainment purposes only · 18+ · AI-assisted · "
             "Not a substitute for professional medical, legal, financial, "
             "or psychological advice."
    )
    embeds.append(summary_embed)

    return embeds


async def send_embeds_in_batches(interaction, embeds):
    """Discord allows at most 10 embeds per message. The Celtic Cross
    produces 11 (10 cards + summary), so send in batches of 10."""
    for i in range(0, len(embeds), 10):
        batch = embeds[i:i + 10]
        await interaction.followup.send(embeds=batch, ephemeral=True)


@bot.event
async def on_ready():
    await setup_database()
    await tree.sync()
    print(f"Madame Ibex is present. Logged in as {bot.user}")


@tree.command(name="reading", description="Draw a free 3-card Past/Present/Future reading")
@app_commands.describe(question="Optional: What question are you bringing to the cards?")
async def reading(interaction: discord.Interaction, question: str = None):
    await interaction.response.defer(ephemeral=True)

    # Daily limit: non-Patreon users get one free reading per day.
    if not is_patreon_member(interaction):
        if await has_used_free_reading_today(interaction.user.id):
            await interaction.followup.send(
                "✦ Madame Ibex has already read for you today.\n"
                "The cards ask for a day's pause before they speak again. "
                "Return tomorrow — or unlock unlimited readings by supporting "
                "Madame Ibex on Patreon.",
                ephemeral=True,
            )
            return

    positions = ["Past", "Present", "Future"]
    cards_in_reading = draw_cards(positions)
    summary = madame_ibex_summary(cards_in_reading, question, "3 Card Past/Present/Future")
    embeds = build_reading_embeds("3-Card Reading", cards_in_reading, summary, question)
    # One embed per card (image shown inline) + the summary embed last.
    await send_embeds_in_batches(interaction, embeds)

    # Record the reading only after it was successfully delivered.
    if not is_patreon_member(interaction):
        await record_free_reading(interaction.user.id)


class SpreadSelect(discord.ui.Select):
    def __init__(self, querent_question):
        self.querent_question = querent_question
        options = [discord.SelectOption(label=s, description=SPREAD_TYPES[s]["description"]) for s in SPREAD_TYPES]
        super().__init__(placeholder="Choose the spread type...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        spread_name = self.values[0]
        spread = SPREAD_TYPES[spread_name]
        positions = spread["positions"]

        # Auto-draw one card per position, no repeats, each upright or reversed.
        cards_in_reading = draw_cards(positions)

        summary = madame_ibex_summary(cards_in_reading, self.querent_question, spread_name)
        embeds = build_reading_embeds(
            f"Madame Ibex — {spread_name}", cards_in_reading, summary, self.querent_question
        )
        await send_embeds_in_batches(interaction, embeds)

        # Record the read after successful delivery.
        await increment_monthly_reading_count(interaction.user.id)


class SpreadView(discord.ui.View):
    def __init__(self, question):
        super().__init__()
        self.add_item(SpreadSelect(question))


@tree.command(name="myreading", description="Madame Ibex reads your cards personally — Patreon members only")
@app_commands.describe(question="The question or situation you are bringing to Madame Ibex")
async def myreading(interaction: discord.Interaction, question: str = None):
    tier = get_patreon_tier(interaction)

    # Not a Patreon member at all.
    if tier is None:
        await interaction.response.send_message(
            "✦ Personal readings with Madame Ibex are available to Patreon supporters.\n"
            "Visit our Patreon to unlock this and support Madame Ibex's work.",
            ephemeral=True
        )
        return

    # Check monthly limit (Oracle is unlimited).
    limit = TIER_LIMITS[tier]
    if limit is not None:
        used = await get_monthly_reading_count(interaction.user.id)
        if used >= limit:
            await interaction.response.send_message(
                f"✦ You have used all {limit} of your {tier} readings for this month.\n"
                "The cards will be ready for you again when the new month begins — "
                "or consider upgrading your Patreon tier for more readings.",
                ephemeral=True
            )
            return

    view = SpreadView(question)
    await interaction.response.send_message(
        "✦ Madame Ibex is ready. Choose your spread:", view=view, ephemeral=True)


@tree.command(name="cardinfo", description="Look up Madame Ibex's interpretation of a specific card")
@app_commands.describe(
    card="The name of the card",
    reversed="Show the card turned. Leave blank to let the cards decide."
)
async def cardinfo(interaction: discord.Interaction, card: str, reversed: bool = None):
    result = get_card(card)
    if not result:
        await interaction.response.send_message(
            f"✦ '{card}' was not found. Check the spelling and try again.", ephemeral=True)
        return
    card_name, card_data = result
    # Blank means let it fall as it falls, the same ~50/50 as a reading.
    is_reversed = random.choice([True, False]) if reversed is None else reversed
    color = discord.Color.from_rgb(75, 0, 130)
    # Interpretation goes in the description (4096-char limit), not an embed
    # field (1024) — most interpretations run well past 1024 and were being
    # cut off mid-sentence.
    embed = discord.Embed(
        title=f"✦ {card_name}" + (" — Reversed" if is_reversed else ""),
        description=card_body(card_data, is_reversed),
        color=color,
    )
    embed.set_author(name="Madame Ibex — The Cards As I See Them")
    image_url = card_image_url(card_data, is_reversed)
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(
        text="The Cards As I See Them — Madame Ibex | Madame Ibex Tarot\n"
             "For entertainment purposes only · 18+ · AI-assisted · "
             "Not a substitute for professional medical, legal, financial, "
             "or psychological advice."
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.run(DISCORD_TOKEN)
