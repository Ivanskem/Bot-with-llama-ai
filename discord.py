import nextcord
from nextcord import Interaction, SlashOption, ButtonStyle, ChannelType, SelectOption
from nextcord.ext import tasks
import json
import aiosqlite
import sqlite3
import time
from ollama import AsyncClient
import datetime
import aiohttp
import os

intents = nextcord.Intents.default()
intents.invites = True
intents.message_content = True
intents.members = True
intents.guilds = True
intents.bans = True
intents.moderation = True

client_discord = nextcord.Client(intents=intents)

delay_on_requests = 15
last_request_list = {}

whitelist = []

use_whitelist = False

try:
    with open('settings.json', 'r', encoding='utf-8') as file:
        settings = json.load(file)
        TOKEN = settings["discord_token"]
        google_search_api = settings['google_search_api']
        google_search_cx = settings['google_search_cx']
except FileNotFoundError:
    new_json = {
        "telegram_token": "telegram_token",
        "discord_token": "discord_token",
        "google_search_api": "enter you're google search API",
        "google_search_cx": "enter you're google search CX"
    }
    with open("settings.json", 'w', encoding='utf-8') as file:
        json.dump(new_json, file, indent=4)


async def google_search(text):
    params = {
        'key': google_search_api,
        'cx': google_search_cx,
        'q': text
    }
    url = "https://www.googleapis.com/customsearch/v1"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            data = await response.json()
            return data
    

async def user_request(request, model, temperature):
    try:
        response = await AsyncClient().chat(model=model, messages=[{
            'role': 'user',
            'content': request,
            'max_tokens': 4096,
            'temperature': temperature
        }])
        return True, response['message']['content']
    except Exception as e:
        return False, e


async def main(message):
    async with aiosqlite.connect('ollama_users_discord.db') as database:
        async with database.cursor() as cursor:
            request_at = time.time()
            last_request_time = last_request_list.get(message.author.id, 0)
            if request_at - last_request_time < delay_on_requests:
                await message.channel.send(f"Hello it's llama please make requests a bit slower", reference=message)
                return
            
            last_request_list[message.author.id] = request_at

            try:
                await cursor.execute("SELECT user_discord_id, used_count FROM users WHERE user_discord_id = ?", (message.author.id,))

                if await cursor.fetchone() is None:
                    await cursor.execute("INSERT INTO users (user_name, user_discord_id, model, used_count, temperature) VALUES (?, ?, ?, ?, ?)",
                                         (message.author.name, message.author.id, 'llama3.1:8b', 1, 0.7))
                    
                    await database.commit()
                else:
                    await cursor.execute("UPDATE users SET used_count = used_count + 1 WHERE user_discord_id = ?", (message.author.id,))
                    await cursor.execute("SELECT model FROM users WHERE user_discord_id = ?", (message.author.id,))
                    model = await cursor.fetchone()
                    model = model[0]
                    await cursor.execute("SELECT temperature FROM users WHERE user_discord_id = ?", (message.author.id,))
                    temperature = await cursor.fetchone()
                    temperature = temperature[0]
                    await database.commit()
                
            except aiosqlite.Error as error:
                await message.channel.send(f'Some shit was happend. Error: {error}')
                print(f'Some shit was happend. Error: {error}')
                return
            
    first_message = await message.channel.send('Wait until llama responds to you!')
    request = await user_request(message.content, model, temperature)

    if request[0] is False:
        await first_message.delete()
        await message.channel.send(f'Something went wrong, please try again. Error: {request[1]}')
        return
    
    embed = nextcord.Embed(title='llama responde:', color=0xffffff)
    embed.set_thumbnail(url=client_discord.user.avatar.url)
    embed.add_field(name=f'Model: ', value='Meta ' + model, inline=False)
    if len(request[1]) > 1024:
        content_parts = [request[1][i:i + 1024] for i in range(0, len(request[1]), 1024)]
        
        for i, part in enumerate(content_parts):
            embed.add_field(name=f'Content Part {i+1}:', value=f'{part}\n', inline=False)
    else:
        embed.add_field(name=f'Content: ', value=f'{request[1]}\n', inline=False)

    embed.add_field(name=f'When: ', value=f'<t:{int(datetime.datetime.now().timestamp())}:F>', inline=False)
    embed.set_footer(text=f'Request from: {message.author.global_name}. \nElapsed: {time.time() - request_at:.2f}s',
                        icon_url=message.author.avatar.url)
    if request[0] is not None:
        await first_message.delete()
        await message.channel.send(embed=embed)
        return


@client_discord.event
async def on_ready():
    if not os.path.isfile('ollama_users_discord.db'):
        async with aiosqlite.connect('ollama_users_discord.db') as database:
            async with database.cursor() as cursor:
                await cursor.execute("""
                            CREATE TABLE IF NOT EXISTS  users (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_name TEXT NOT NULL,
                            user_discord_id INTEGER NOT NULL UNIQUE,
                            model TEXT NOT NULL DEFAULT 'llama3.1',
                            used_count INTEGER NOT NULL DEFAULT 0,
                            temperature FLOAT NOT NULL DEFAULT 0.7
                                    )
                                """)
                await database.commit()
    print(f'Logged as {client_discord.user}')

@client_discord.event
async def on_message(message):
    if message.author != client_discord.user:
        if message.channel.type != nextcord.ChannelType.private:
            return
        if use_whitelist == False:
            await main(message)
        elif use_whitelist == True and message.author.id in whitelist:
            await main(message)
        else:
            await message.channel.send(f"You're not whitelisted!")
            return
    else:
        return

@client_discord.slash_command(name='select_model', description='Type model from list')
async def model(interaction: Interaction,
                picked_model: str = SlashOption(
                    description='Pick the model you need',
                    choices=['llama3.1:8b',
                             'llama3.1:70b',
                             'llama3.1:405b',
                             'llama3.2:1b',
                             'llama3.2:3b']
                )):
    try:
        async with aiosqlite.connect('ollama_users_discord.db') as database:
            async with database.cursor() as cursor:
                await cursor.execute("SELECT user_discord_id FROM users WHERE user_discord_id = ?", (interaction.user.id,))
                result = await cursor.fetchone()
                if result is not None:
                    old_model = result[0]
                    await cursor.execute('''UPDATE users
                                            SET model = ?, used_count = ?
                                            WHERE user_discord_id = ?''', 
                                            (picked_model, 1, interaction.user.id))
                    await database.commit()
                    embed = nextcord.Embed(title='Model type change', color=0xffffff)
                    embed.set_thumbnail(url=client_discord.user.avatar.url)
                    embed.add_field(name='Changes', value=f'Change from ~~{old_model}~~ to {model}', inline=False)
                    embed.set_footer(text=f'Requested at: {interaction.created_at.ctime()}')
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message('Please make 1 request to the bot before selecting a model.', ephemeral=True)

    except aiosqlite.Error as error:
                await interaction.response.send_message(f'Some shit was happend. Error: {error} \nif this error continues contact <@1166025936148365508>', ephemeral=True)
                print(f'Some shit was happend. Error: {error}')
                return



@client_discord.slash_command(name='set_temperature', description='You can set temperature of the model')
async def temperature(interaction: Interaction,
                      temperature: str = SlashOption(
                        description='enter temperature what u need'
                      )):
    try:
        async with aiosqlite.connect('ollama_users_discord.db') as database:
            async with database.cursor() as cursor:
                await cursor.execute("SELECT temperature FROM users WHERE user_discord_id = ?", (
                    interaction.user.id,))
                result = await cursor.fetchone()
                if result is not None:
                    old_temperature = result[0]
                    await cursor.execute('''UPDATE users
                                        SET temperature = ?, used_count = ?
                                        WHERE user_discord_id = ?''', (temperature, 1, interaction.user.id))
                    await database.commit()
                    embed = nextcord.Embed(title='Model temperature change', color=0xffffff)
                    embed.set_thumbnail(url=client_discord.user.avatar.url)
                    embed.add_field(name='Changes', value=f'Change from ~~{old_temperature}~~ to {temperature}', inline=False)
                    embed.set_footer(text=f'Requested at: {interaction.created_at.ctime()}')
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                else:
                    await interaction.response.send_message(f'Please make 1 request to the bot before changing temperature mode, if this message continues contact <@1166025936148365508>', ephemeral=True)
    except aiosqlite.Error as error:
                await interaction.response.send_message(f'Some shit was happend. Error: {error} \nif this error continues contact <@1166025936148365508>', ephemeral=True)
                print(f'Some shit was happend. Error: {error}')
                return



@client_discord.slash_command(name='search', description='Use this if you want the bot to respond with data from the internet')
async def search(interaction: Interaction,
                 query: str = SlashOption(description='Enter your query')):
    request_at = time.time()
    try:
        async with aiosqlite.connect('ollama_users_discord.db') as database:
            async with database.cursor() as cursor:
                await cursor.execute("SELECT temperature FROM users WHERE user_discord_id = ?", (interaction.user.id,
                                                                         ))
                temperature = await cursor.fetchone()
                if temperature is None:
                    await interaction.response.send_message(f'Please make 1 request to the bot before searching information mode, if this message continues contact <@1166025936148365508>', ephemeral=True)
                temperature = temperature[0]
                model = await cursor.execute("SELECT model FROM users WHERE user_discord_id = ?", (interaction.user.id,
                                                                         ))
                model = await cursor.fetchone()
                if model is None:
                    await interaction.response.send_message(f'Please make 1 request to the bot before searching information mode, if this message continues contact <@1166025936148365508>', ephemeral=True)
                model = model[0]
    except aiosqlite.Error as error:
                await interaction.response.send_message(f'Some shit was happend. Error: {error} \nIf this error continues contact <@1166025936148365508>', ephemeral=True)
                print(f'Some shit was happend. Error: {error}')
                return
    
    results = await google_search(query)
    results_text = ''
    for item in results.get('items', []):
        results_text += f"Title: {item['title']}\nLink: {item['link']}\n\n"
    if not results_text:
        results_text = "Ничего не найдено"
        await interaction.response.send_message(results_text, ephemeral=True)
        return

    llama_request_text = f"Основываясь на информации из поиска:\n{results_text}\n\nПожалуйста, предоставь резюме или ответ на основе этой информации."
    first_message = await interaction.response.send_message('Wait until llama responds to you!')
    request = await user_request(llama_request_text, model, temperature)

    if request[0] is False:
        await first_message.delete()
        await interaction.channel.send(f'Something went wrong, please try again. Error: {request[1]}')
        return
    
    embed = nextcord.Embed(title='llama responde:', color=0xffffff)
    embed.set_thumbnail(url=client_discord.user.avatar.url)
    embed.add_field(name=f'Model: ', value='Meta ' + model, inline=False)
    if len(request[1]) > 1024:
        content_parts = [request[1][i:i + 1024] for i in range(0, len(request[1]), 1024)]
        
        for i, part in enumerate(content_parts):
            embed.add_field(name=f'Content Part {i+1}:', value=part, inline=False)
    else:
        embed.add_field(name=f'Content: ', value=request[1], inline=False)

    embed.add_field(name=f'When: ', value=f'<t:{int(datetime.datetime.now().timestamp())}:F>', inline=False)
    embed.set_footer(text=f'Request from: {interaction.user}. \nElapsed: {time.time() - request_at:.2f}s',
                        icon_url=interaction.user.avatar.url)
    if request[0] is not None:
        await first_message.delete()
        await interaction.channel.send(embed=embed)
        return

client_discord.run(TOKEN)
