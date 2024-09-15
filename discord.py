import nextcord
from nextcord import Interaction, SlashOption, ButtonStyle, ChannelType, SelectOption
from nextcord.ext import tasks
import json
import sqlite3
import time
import ollama
import datetime
import requests

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


def google_search(text):
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': google_search_api,
        'cx': google_search_cx,
        'q': text
    }
    response = requests.get(url, params=params)
    return response.json()


async def main(message):
    database = sqlite3.connect('ollama_users_discord.db')
    cursor = database.cursor()
    current_time = time.time()
    last_request_time = last_request_list.get(message.author.id, 0)

    if current_time - last_request_time < delay_on_requests:
        await message.channel.send("You're sending requests too quickly. Please wait a bit before sending another request.")
        return
    
    last_request_list[message.author.id] = current_time
    
    try:
        cursor.execute("SELECT user_discord_id, used_count FROM users WHERE user_discord_id = ?", (message.author.id,))
        result = cursor.fetchone()
        
        if result is None:
            cursor.execute("INSERT INTO users (user_name, user_discord_id, model, used_count, temperature) VALUES (?, ?, ?, ?, ?)", 
                            (message.author.name, message.author.id, 'llama3.1', 1, 0.7))
            database.commit()
            database.close()
            await message.channel.send(f"Hello {message.author.name}, I'm llama. I'm working on llama model maded by Meta. If you have any questions for me, ask me and wait.")
            return
        else:
            cursor.execute("UPDATE users SET used_count = used_count + 1 WHERE user_discord_id = ?", (message.author.id,))
            cursor.execute("SELECT model FROM users WHERE user_discord_id = ?", (message.author.id,))
            model = cursor.fetchone()
            model = model[0]
            cursor.execute("SELECT temperature FROM users WHERE user_discord_id = ?", (message.author.id,))
            temperature = cursor.fetchone()
            temperature = temperature[0]
            database.commit()
            database.close()
    except sqlite3.Error as e:
        print(f"Error in database: {e}")
        return
    
    first_message = await message.channel.send('Wait until llama responds to you!')
    print(f'Request from: {message.author.name} ({message.author.id}). Content: {message.content}')
    request = user_request(message.content, model, temperature)
    print(f'llama response: State: {request[0]}. Content: {request[1]}')

    if request[0] is False:
        await first_message.delete()
        await message.channel.send(f'Something went wrong, please try again. Error: {request[1]}')
        return
    
    embed = nextcord.Embed(title='llama responde:', color=0xffffff)
    embed.add_field(name=f'Model: ', value='Meta ' + model, inline=False)
    if len(request[1]) > 1024:
        content_parts = [request[1][i:i + 1024] for i in range(0, len(request[1]), 1024)]
        
        for i, part in enumerate(content_parts):
            embed.add_field(name=f'Content Part {i+1}:', value=part, inline=False)
    else:
        embed.add_field(name=f'Content: ', value=request[1], inline=False)

    embed.add_field(name=f'When: ', value=f'<t:{int(datetime.datetime.now().timestamp())}:F>', inline=False)
    embed.set_footer(text=f'Request from: {message.author.name}. \nElapsed: {time.time() - current_time:.2f}s',
                        icon_url=message.author.avatar.url)
    if request[0] is not None:
        await first_message.delete()
        await message.channel.send(embed=embed)
        return


def user_request(request, model, temperature):
    try:
        response = ollama.chat(model=model, messages=[{
            'role': 'user',
            'content': request,
            'max_tokens': 4096,
            'temperature': temperature
        }])
        return True, response['message']['content']
    except Exception as e:
        return False, e


@client_discord.event
async def on_ready():
    database = sqlite3.connect('ollama_users_discord.db')
    cursor = database.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT NOT NULL,
            user_discord_id INTEGER NOT NULL UNIQUE,
            model TEXT NOT NULL DEFAULT 'llama3.1',
            used_count INTEGER NOT NULL DEFAULT 0,
            temperature FLOAT NOT NULL DEFAULT 0.7
        )
    """)
    database.commit()
    database.close()
    print(f'Logged as {client_discord.user}')

@client_discord.event
async def on_message(message):
    if message.author != client_discord.user:
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
                    description='pick model what you need',
                    choices=['llama3.1:8b', 'llama3.1:70b', 'llama2:7b', 'llama2:70b']
                )):
    database = sqlite3.connect('ollama_users_discord.db')
    cursor = database.cursor()
    cursor.execute("SELECT user_discord_id FROM users WHERE user_discord_id = ?", (interaction.user.id,))
    
    if cursor.fetchone() is not None:
        cursor.execute('''UPDATE users
                          SET model = ?, used_count = ?
                          WHERE user_discord_id = ?''', (picked_model, 1, interaction.user.id))
        database.commit()
        await interaction.response.send_message(f'Model has been updated to {picked_model}.', ephemeral=True)
    else:
        await interaction.response.send_message(f'Please make 1 request to the bot before selecting a model.', ephemeral=True)

    database.close()


@client_discord.slash_command(name='set_temperature', description='You can set temperature of the model')
async def temperature(interaction: Interaction,
                      temperature: str = SlashOption(
                        description='enter temperature what u need'
                      )):
    database = sqlite3.connect('ollama_users_discord.db')
    cursor = database.cursor()
    cursor.execute("SELECT user_discord_id FROM users WHERE user_discord_id = ?", (interaction
    .user.id,))

    if cursor.fetchone() is not None:
            cursor.execute('''UPDATE users
                            SET temperature = ?, used_count = ?
                            WHERE user_discord_id = ?''', (temperature, 1, interaction.user.id))
            database.commit()
            await interaction.response.send_message(f'temperature has been updated to {temperature}.', ephemeral=True)
    else:
        await interaction.response.send_message(f'Please make 1 request to the bot before selecting a model.', ephemeral=True)

    database.close()


@client_discord.slash_command(name='search', description='Use this if you want the bot to respond with data from the internet')
async def search(interaction: Interaction,
                 query: str = SlashOption(description='Enter your query')):
    database = sqlite3.connect(f'ollama_users_discord.db')
    cursor = database.cursor()
    temperature = cursor.execute("SELECT temperature FROM users WHERE user_discord_id = ?", (interaction.user.id,)).fetchone()[0]
    model = cursor.execute("SELECT model FROM users WHERE user_discord_id = ?", (interaction.user.id,
                                                                         )).fetchone()[0]
    database.close()
    current_time = time.time()
    results = google_search(query)
    results_text = ''
    for item in results.get('items', []):
        results_text += f"Title: {item['title']}\nLink: {item['link']}\n\n"
    if not results_text:
        results_text = "Ничего не найдено"
        await interaction.response.send_message(results_text, ephemeral=True)
        return

    llama_request_text = f"Основываясь на информации из поиска:\n{results_text}\n\nПожалуйста, предоставь резюме или ответ на основе этой информации."
    first_message = await interaction.response.send_message('Wait until llama responds to you!')
    print(f'Request from: {interaction.user}. Content: {llama_request_text}')
    request = user_request(llama_request_text, model, temperature)
    print(f'llama response: State: {request[0]}. Content: {request[1]}')

    if request[0] is False:
        await first_message.delete()
        await interaction.channel.send(f'Something went wrong, please try again. Error: {request[1]}')
        return
    
    embed = nextcord.Embed(title='llama responde:', color=0xffffff)
    embed.set_thumbnail(url='https://djeqr6to3dedg.cloudfront.net/repo-logos/ollama/ollama/live/logo-1701412810306.png')
    embed.add_field(name=f'Model: ', value='Meta ' + model, inline=False)
    if len(request[1]) > 1024:
        content_parts = [request[1][i:i + 1024] for i in range(0, len(request[1]), 1024)]
        
        for i, part in enumerate(content_parts):
            embed.add_field(name=f'Content Part {i+1}:', value=part, inline=False)
    else:
        embed.add_field(name=f'Content: ', value=request[1], inline=False)

    embed.add_field(name=f'When: ', value=f'<t:{int(datetime.datetime.now().timestamp())}:F>', inline=False)
    embed.set_footer(text=f'Request from: {interaction.user}. \nElapsed: {time.time() - current_time:.2f}s',
                        icon_url=interaction.user.avatar.url)
    if request[0] is not None:
        await first_message.delete()
        await interaction.channel.send(embed=embed)
        return

client_discord.run(TOKEN)
