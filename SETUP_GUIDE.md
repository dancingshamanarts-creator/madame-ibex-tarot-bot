# Madame Ibex Tarot Bot — Setup Guide
*Written for someone who has never deployed a bot before. Every step numbered. Every click described.*

---

## What You Will Need
- 20–30 minutes
- Your Discord server (Tarot Corner)
- A free GitHub account (to store the code)
- A free Railway account (to run the bot 24/7)
- A free Discord Developer account
- Your Anthropic API key (from claude.ai settings)

---

## PART 1 — Create Your Discord Bot

1. Go to **https://discord.com/developers/applications**
2. Click the blue **New Application** button (top right)
3. Name it **Madame Ibex** — click **Create**
4. On the left menu click **Bot**
5. Click **Add Bot** — confirm yes
6. Under **Token** click **Reset Token** — copy and save this somewhere safe. This is your `DISCORD_TOKEN`. **Do not share it with anyone.**
7. Scroll down to **Privileged Gateway Intents**
8. Turn ON **Server Members Intent** (the bot needs this to check Patreon roles)
9. Click **Save Changes**

**Now invite the bot to your server:**
10. On the left menu click **OAuth2** then **URL Generator**
11. Under Scopes check: `bot` and `applications.commands`
12. Under Bot Permissions check: `Send Messages`, `Embed Links`, `Read Message History`, `Use Slash Commands`
13. Copy the generated URL at the bottom — paste it in your browser
14. Select **Tarot Corner** from the dropdown — click **Authorize**

Your bot is now in your server (it will show as offline until we finish setup).

---

## PART 2 — Connect Patreon to Discord

*This makes Patreon subscribers automatically get a role in your Discord.*

1. Go to **https://www.patreon.com** and log in
2. Click your profile icon — go to **Creator Settings**
3. Click **Apps** in the left menu
4. Find **Discord** and click **Connect**
5. Log into Discord when prompted — authorize the connection
6. Go back to Patreon — under the Discord app, click **Set up Discord roles**
7. For your paid tier, assign the role name **Patreon** (must match exactly — capital P)
8. Save

From now on, anyone who subscribes to your Patreon will automatically receive the **Patreon** role in Tarot Corner within a few minutes. When they cancel, it is removed automatically.

---

## PART 3 — Put the Code on GitHub

1. Go to **https://github.com** and create a free account (or log in)
2. Click the **+** icon (top right) — **New repository**
3. Name it `madame-ibex-tarot-bot`
4. Set it to **Private** (important — your bot token stays safe)
5. Click **Create repository**
6. On the next page click **uploading an existing file**
7. Upload all four files: `bot.py`, `card_data.py`, `requirements.txt`, `railway.toml`
8. Click **Commit changes**

---

## PART 4 — Deploy on Railway (This Runs the Bot 24/7)

1. Go to **https://railway.app** and sign up with your GitHub account
2. Click **New Project**
3. Click **Deploy from GitHub repo**
4. Select `madame-ibex-tarot-bot`
5. Railway will detect the files and start setting up — click **Deploy Now**
6. Before it finishes, click **Variables** in the left panel
7. Add these three variables one at a time (click **New Variable** for each):

   | Variable Name | Value |
   |---|---|
   | `DISCORD_TOKEN` | Your bot token from Part 1 Step 6 |
   | `ANTHROPIC_API_KEY` | Your Anthropic API key |
   | `PATREON_ROLE_NAME` | Patreon |

8. Click **Deploy** after adding the variables

Railway will build and start the bot. This takes about 2 minutes. When you see a green **Active** status, Madame Ibex is live.

---

## PART 5 — Test It

Go to any channel in Tarot Corner and type:

`/reading`

You should see Madame Ibex respond with a 3-card automatic reading.

To test the paid reading, temporarily give yourself the Patreon role in Discord server settings, then type:

`/myreading`

You should see a spread selection menu appear.

Remove the test role from yourself when done.

---

## Bot Commands Summary

| Command | Who Can Use It | What It Does |
|---|---|---|
| `/reading` | Everyone | Free automatic 3-card Past/Present/Future reading |
| `/myreading` | Patreon subscribers only | Personal reading — you enter the cards Madame Ibex pulled |
| `/cardinfo` | Everyone | Look up Madame Ibex's interpretation of any specific card |

---

## Adding New Interpretations

As Madame Ibex completes more cards in *The Cards As I See Them*, update the `card_data.py` file:

1. Find the card in the file (they are organized by suit)
2. Replace `"madame_ibex": None` with her written interpretation
3. Upload the updated `card_data.py` to GitHub (same steps as Part 3)
4. Railway will automatically redeploy with the new content within a minute

---

## Troubleshooting

**Bot shows as offline:** Check Railway — look for error messages in the deployment log. Usually means a variable is missing or mistyped.

**Slash commands not showing up:** Wait up to 1 hour after first deployment for Discord to register them globally. Or go to the bot's Discord Developer page and re-invite it.

**Patreon role not working:** Make sure the role name in Railway variables matches exactly what Patreon assigned — capital P, no extra spaces.

**Card not found error:** The bot accepts partial names and is not case sensitive. Try `knight swords` or `page cups` without "of" if the full name isn't working.

---

*Questions about setup — bring them to Claude. Questions about the cards — bring them to Madame Ibex.*
