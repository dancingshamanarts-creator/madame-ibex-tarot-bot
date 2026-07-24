import discord
from discord import app_commands
from discord.ext import commands
import random
import os
import anthropic
from card_data import CARDS, get_card, SPREAD_TYPES

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
PATREON_ROLE_NAME = os.environ.get("PATREON_ROLE_NAME", "Patreon")

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

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


def build_reading_embed(title, cards_in_reading, summary, question=None):
    color = discord.Color.from_rgb(75, 0, 130)

    # The reading summary goes in the embed DESCRIPTION (limit 4096),
    # not a field (limit 1024). Trimmed to 4000 as a hard safety net so
    # an unusually long reading can never crash the message again.
    safe_summary = summary.strip()
    if len(safe_summary) > 4000:
        safe_summary = safe_summary[:3997] + "..."

    embed = discord.Embed(
        title=f"🔮 {title}",
        description=safe_summary,
        color=color,
    )
    embed.set_author(name="Madame Ibex — Madame Ibex Tarot")

    if question:
        # A field, so also protected by the 1024 limit.
        q = question if len(question) <= 1024 else question[:1021] + "..."
        embed.add_field(name="Question", value=q, inline=False)

    embed.add_field(name="\u200b", value="─" * 40, inline=False)

    for position, card_name, card_data in cards_in_reading:
        interp = card_data.get("madame_ibex")
        if interp:
            label = f"✦ {position}: {card_name}"
            short = interp[:300] + "..." if len(interp) > 300 else interp
        else:
            label = f"✦ {position}: {card_name}"
            short = f"*{card_data.get('traditional', 'Interpretation coming from Madame Ibex...')}*\n*(Traditional meaning — Madame Ibex has not yet written her interpretation of this card)*"
        # Every field value is capped at 1024 by Discord — trim to be safe.
        if len(short) > 1024:
            short = short[:1021] + "..."
        embed.add_field(name=label, value=short, inline=False)

    embed.set_footer(text="The Cards As I See Them — Madame Ibex | Madame Ibex Tarot")
    return embed


@bot.event
async def on_ready():
    await tree.sync()
    print(f"Madame Ibex is present. Logged in as {bot.user}")


@tree.command(name="reading", description="Draw a free 3-card Past/Present/Future reading")
@app_commands.describe(question="Optional: What question are you bringing to the cards?")
async def reading(interaction: discord.Interaction, question: str = None):
    await interaction.response.defer()
    all_card_names = list(CARDS.keys())
    drawn = random.sample(all_card_names, 3)
    positions = ["Past", "Present", "Future"]
    cards_in_reading = [(positions[i], drawn[i], CARDS[drawn[i]]) for i in range(3)]
    summary = madame_ibex_summary(cards_in_reading, question, "3 Card Past/Present/Future")
    embed = build_reading_embed("3-Card Reading", cards_in_reading, summary, question)
    images = [CARDS[name].get("image_url") for name in drawn if CARDS[name].get("image_url")]
    if images:
        embed.set_image(url=images[0])
    await interaction.followup.send(embed=embed)


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
        embed = build_reading_embed(f"✦ Madame Ibex — {self.spread_name}", cards_in_reading, summary, self.question)
        await interaction.followup.send(embed=embed)


@tree.command(name="myreading", description="Madame Ibex reads your cards personally — Patreon members only")
@app_commands.describe(question="The question or situation you are bringing to Madame Ibex")
async def myreading(interaction: discord.Interaction, question: str = None):
    patreon_role = discord.utils.get(interaction.guild.roles, name=PATREON_ROLE_NAME)
    if patreon_role is None or patreon_role not in interaction.user.roles:
        await interaction.response.send_message(
            "✦ Personal readings with Madame Ibex are available to Patreon supporters.\n"
            "Visit our Patreon to unlock this and support Madame Ibex's work.",
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
