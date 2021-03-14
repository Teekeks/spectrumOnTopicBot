import discord
import json
import asyncio
from typing import Any
import datetime
import logging
import collections

with open('settings.json', 'r') as f:
    cfg = json.load(f)


logging.basicConfig(level=logging.INFO)

TOPIC_COMMAND = cfg['prefix'] + cfg['commands']['topic']

CHANNEL_MODERATION: discord.TextChannel = None
CHANNEL_TOPIC: discord.TextChannel = None

client = discord.Client()

COOLDOWN = datetime.timedelta(hours=cfg['cooldown']['hours'],
                              minutes=cfg['cooldown']['minutes'],
                              seconds=cfg['cooldown']['seconds'])

cooldown_till: datetime.datetime = None


def save_state():
    with open('state.json', 'w') as fi:
        json.dump({'cooldown': cooldown_till.isoformat() if cooldown_till is not None else None}, fi)


def load_state():
    global cooldown_till
    data = {}
    try:
        with open('state.json', 'r') as fi:
            data = json.load(fi)
    except:
        pass
    datestr = data.get('cooldown', None)
    cooldown_till = datestr if datestr is None else datetime.datetime.fromisoformat(datestr)


def build_embed(title: str = None,
                color: Any = discord.Color.blue(),
                body: str = None,
                footer: str = None,
                fields: Any = None):
    embed = discord.Embed(color=color)
    if title is not None:
        embed.title = title
    if body is not None:
        embed.description = body
    if footer is not None:
        embed.set_footer(text=footer)
    if fields is not None:
        for field in fields:
            embed.add_field(name=field['name'],
                            value=field['value'],
                            inline=field.get('inline', False))
    return embed


async def topic_approve(topic: str,
                        author_mention: str,
                        msg_id: int):
    logging.info(f'Topic "{topic}" got approved')
    global cooldown_till
    embed_text = f'**{topic}**\n\n{TOPIC_COMMAND} is now on cooldown!'
    embed = build_embed(title='Topic Approved',
                        body=embed_text,
                        color=discord.Color.green())
    message = await CHANNEL_TOPIC.fetch_message(msg_id)
    if message is not None:
        await message.reply(embed=embed)
    else:
        # message was deleted, mention the user without reply
        await CHANNEL_TOPIC.send(content=author_mention,
                                 embed=embed)
    await CHANNEL_TOPIC.edit(topic=f'{cfg["topic_channel_prefix"]}{topic}')
    await CHANNEL_MODERATION.send(embed=build_embed(title='Topic approved',
                                                    color=discord.Color.green(),
                                                    body=topic))
    cooldown_till = datetime.datetime.now() + COOLDOWN
    save_state()


async def topic_denied(topic: str,
                       author_mention: str,
                       msg_id: int):
    logging.info(f'Topic "{topic}" got denied')
    embed = build_embed(title='Your topic was rejected',
                        color=discord.Color.red())
    message = await CHANNEL_TOPIC.fetch_message(msg_id)
    if message is not None:
        await message.reply(embed=embed)
    else:
        # message was deleted, mention the user without reply
        await CHANNEL_TOPIC.send(content=author_mention,
                                 embed=embed)
    await CHANNEL_MODERATION.send(embed=build_embed(title='Topic denied',
                                                    color=discord.Color.red(),
                                                    body=topic))


@client.event
async def on_ready():
    logging.info("bot ready")
    # fetch channel for later use
    global CHANNEL_TOPIC, CHANNEL_MODERATION
    CHANNEL_TOPIC = await client.fetch_channel(cfg['channels']['topic'])
    CHANNEL_MODERATION = await client.fetch_channel(cfg['channels']['moderation'])
    if any([CHANNEL_TOPIC is None, CHANNEL_MODERATION is None]):
        logging.error('could not fetch channel!')
        exit(1)
    pass


@client.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    if any([
            # ignore all reactions that are made by bot
            user == client.user,
            # ignore if not on a post from the bot
            reaction.message.author != client.user,
            # ignore reactions outside moderation channel
            reaction.message.channel.id != CHANNEL_MODERATION.id,
            # ignore reactions that do not have a embed
            len(reaction.message.embeds) == 0,
            # ignore if bot has not reacted with this themself
            not reaction.me
            ]):
        return
    embed: discord.Embed = reaction.message.embeds[0]
    topic = embed.description
    author = embed.fields[0].value
    remove_own = False
    if str(reaction) == cfg['reacts']['approve']:
        await topic_approve(topic, author, int(embed.footer.text))
        remove_own = True
    elif str(reaction) == cfg['reacts']['deny']:
        await topic_denied(topic, author, int(embed.footer.text))
        remove_own = True
    if remove_own:
        # remove own reactions
        for re in reaction.message.reactions:
            if re.me:
                await re.remove(client.user)
    # ignore all other reacts


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        # do not process own messages
        return
    # only allow in topic channel
    if all([
                message.channel.id == cfg['channels']['topic'],
                message.content.startswith(f'{TOPIC_COMMAND} '),
                len(message.content) > (len(TOPIC_COMMAND) + 1)
            ]):
        topic = message.content[len(TOPIC_COMMAND) + 1:].strip()
        if cooldown_till is not None:
            # cant request new topic while cooldown is going
            await message.reply(embed=build_embed(title=f'{TOPIC_COMMAND} is on cooldown!',
                                                  color=discord.Color.red()))
            logging.info(f'cant send topic "{topic}" for approval while on cooldown!')
            return
        logging.info(f'new topic send to review: "{topic}"')
        # handle new topic
        # send confirmation
        confirm_embed = build_embed(title='Topic sent for review',
                                    # body=topic,
                                    color=discord.Color.blurple())
        await message.reply(embed=confirm_embed)
        # send test message
        mod_embed = build_embed(title='New discussion Topic',
                                body=topic,
                                fields=[
                                    {'name': 'Author',
                                     'value': message.author.mention},
                                    {'name': 'Message URL',
                                     'value': f'[Message]({message.jump_url})'}
                                ],
                                footer=str(message.id))
        msg = await CHANNEL_MODERATION.send(embed=mod_embed)
        await msg.add_reaction(cfg['reacts']['approve'])
        await msg.add_reaction(cfg['reacts']['deny'])


async def check_cooldown():
    global cooldown_till
    while True:
        await asyncio.sleep(10)
        if cooldown_till is not None:
            if datetime.datetime.now() >= cooldown_till:
                # cooldown reached!
                cooldown_till = None
                save_state()
                logging.info('cooldown reached')
                await CHANNEL_MODERATION.send(embed=build_embed(title='Cooldown elapsed'))
                await CHANNEL_TOPIC.send(embed=build_embed(title='Topic submissions are now open'))


# start bot
async def start_bot():
    try:
        await client.start(cfg['token'])
    finally:
        if not client.is_closed():
            await client.close()


asyncio.ensure_future(start_bot())
asyncio.ensure_future(check_cooldown())

logging.info('loading state')
load_state()

logging.info('starting up')
asyncio.get_event_loop().run_forever()
