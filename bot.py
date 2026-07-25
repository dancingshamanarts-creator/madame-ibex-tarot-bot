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


MADAME_IBEX_SYSTEM = """You are channeling the voice of Madame Ibex — a visual tarot reader of rare and unconventional sight.

Madame Ibex does not read tarot the way the books say to read it. She is a visual thinker who reads image, body language, and what is actually in the card rather than what someone else decided it means. She believes the accepted interpretations of many cards were the outer teaching — the palatable surface — and that the true messages were hidden in plain sight within the images, waiting for those with the sight to receive them.

Her readings are grounded, honest, sometimes uncomfortable, and always specific. She does not offer false comfort. She asks hard questions. She sees the panic stop in the charging horse. She sees the thumb ready to flick the cup away. She sees the figure in the death grip on the falling banner while everyone below watches the child smile.

When writing a reading summary:
- Speak in Madame Ibex's voice — direct, visual, layered
- Reference specific details from the cards as she would see them
- Draw the cards together into a unified message
- End with 2-3 questions the reading asks of the querent
- Do not use generic tarot language or received wisdom
- Keep the tone intimate and clear — this is a real reading, not a performance
- Keep the entire reading under 3500 characters."""


def madame_ibex_summary(cards_in_reading, question=None, spread_type="3 Card"):
    card_descriptions = []
    for position, card_name, card_data in cards_in_reading:
        interp = card_data.get("madame_ibex") or f"[Traditional: {card_data.get('traditional', 'Interpretation coming')}]"
        card_descriptions.append(f"Position: {position}\nCard: {card_name}\nInterpretation: {interp}")

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
        its interpretation (or traditional meaning + a note if not yet written)
      - a final embed carrying Madame Ibex's full woven reading

    Images set by URL preview inline (no clicking), which needs the repo
    public — it is. Discord allows at most 10 embeds per message, which
    comfortably covers every current spread.
    """
    color = discord.Color.from_rgb(75, 0, 130)
    embeds = []

    total = len(cards_in_reading)
    for i, (position, card_name, card_data) in enumerate(cards_in_reading):
        interp = card_data.get("madame_ibex")
        if interp:
            body = interp
        else:
            traditional = card_data.get("traditional", "")
            body = (
                f"*{traditional}*\n\n"
                f"*Madame Ibex is still interpreting this card.*"
            )
        # Description limit is 4096; trim as a safety net.
        if len(body) > 4000:
            body = body[:3997] + "..."

        card_embed = discord.Embed(
            title=f"✦ {position}: {card_name}",
            description=body,
            color=color,
        )
        # First card's embed carries the header + optional question.
        if i == 0:
            card_embed.set_author(name=f"Madame Ibex — {title}")
            if question:
                q = question if len(question) <= 1024 else question[:1021] + "..."
                card_embed.add_field(name="Question", value=q, inline=False)

        image_url = card_data.get("image_url")
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
    summary_embed.set_footer(text="The Cards As I See Them — Madame Ibex | Madame Ibex Tarot")
    embeds.append(summary_embed)

    return embeds


@bot.event
async def on_ready():
    await setup_database()
    await tree.sync()
    print(f"Madame Ibex is present. Logged in as {bot.user}")


@tree.command(name="reading", description="Draw a free 3-card Past/Present/Future reading")
@app_commands.describe(question="Optional: What question are you bringing to the cards?")
async def reading(interaction: discord.Interaction, question: str = None):
    await interaction.response.defer()

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

    all_card_names = list(CARDS.keys())
    drawn = random.sample(all_card_names, 3)
    positions = ["Past", "Present", "Future"]
    cards_in_reading = [(positions[i], drawn[i], CARDS[drawn[i]]) for i in range(3)]
    summary = madame_ibex_summary(cards_in_reading, question, "3 Card Past/Present/Future")
    embeds = build_reading_embeds("3-Card Reading", cards_in_reading, summary, question)
    # One embed per card (image shown inline) + the summary embed last.
    await interaction.followup.send(embeds=embeds)

    # Record the reading only after it was successfully delivered.
    if not is_patreon_member(interaction):
        await record_free_reading(interaction.user.id)


class SpreadSelect(discord.ui.Select):
    def __init__(self, querent_question):
        self.querent_question = querent_question
        options = [discord.SelectOption(label=s, description=SPREAD_TYPES[s]["description"]) for s in SPREAD_TYPES]
        super().__init__(placeholder="Choose the spread type...", options=options)

    async def callback(self, interaction: discord.Interaction):
        spread_name = self.values[0]
        spread = SPREAD_TYPES[spread_name]
        positions = spread["positions"]
        modal = CardEntryModal(spread_name, positions, self.querent_question)
        await interaction.response.send_modal(modal)


class SpreadView(discord.ui.View):
    def __init__(self, question):
        super().__init__()
        self.add_item(SpreadSelect(question))


class CardEntryModal(discord.ui.Modal):
    def __init__(self, spread_name, positions, question):
        super().__init__(title=f"Enter Cards — {spread_name}")
        self.spread_name = spread_name
        self.positions = positions
        self.question = question
        self.card_input = discord.ui.TextInput(
            label="Enter card names, one per line",
            style=discord.TextStyle.paragraph,
            placeholder="\n".join(positions),
            required=True
        )
        self.add_item(self.card_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        raw = self.card_input.value.strip().split("\n")
        cards_in_reading = []
        errors = []
        for i, pos in enumerate(self.positions):
            if i < len(raw):
                card_name = raw[i].strip()
                card_data = get_card(card_name)
                if card_data:
                    cards_in_reading.append((pos, card_data[0], card_data[1]))
                else:
                    errors.append(f"Card not found: '{card_name}'")
            else:
                errors.append(f"Missing card for position: {pos}")

        if errors:
            await interaction.followup.send(
                f"⚠️ Madame Ibex could not complete this reading:\n" + "\n".join(errors) +
                "\n\nPlease check card names and try again.", ephemeral=True)
            return

        summary = madame_ibex_summary(cards_in_reading, self.question, self.spread_name)
        embeds = build_reading_embeds(f"Madame Ibex — {self.spread_name}", cards_in_reading, summary, self.question)
        await interaction.followup.send(embeds=embeds)
        # Record the read after successful delivery.
        await increment_monthly_reading_count(interaction.user.id)


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
@app_commands.describe(card="The name of the card")
async def cardinfo(interaction: discord.Interaction, card: str):
    result = get_card(card)
    if not result:
        await interaction.response.send_message(
            f"✦ '{card}' was not found. Check the spelling and try again.", ephemeral=True)
        return
    card_name, card_data = result
    color = discord.Color.from_rgb(75, 0, 130)
    embed = discord.Embed(title=f"✦ {card_name}", color=color)
    embed.set_author(name="Madame Ibex — The Cards As I See Them")
    if card_data.get("madame_ibex"):
        embed.add_field(name="Madame Ibex Sees", value=card_data["madame_ibex"][:1000], inline=False)
    else:
        embed.add_field(
            name="Traditional Meaning",
            value=f"{card_data.get('traditional', 'Coming soon.')}\n\n*(Madame Ibex has not yet written her interpretation of this card)*",
            inline=False)
    if card_data.get("image_url"):
        embed.set_image(url=card_data["image_url"])
    embed.set_footer(text="The Cards As I See Them — Madame Ibex | Madame Ibex Tarot")
    await interaction.response.send_message(embed=embed)


bot.run(DISCORD_TOKEN)
