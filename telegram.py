import telebot
import json
import sqlite3
import time
import ollama
import requests

delay_on_requests = 15
last_request_list = {}
whitelist = []
use_whitelist = False

try:
    with open('settings.json', 'r', encoding='utf-8') as file:
        settings = json.load(file)
        TOKEN = settings["telegram_token"]
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

telegram_client = telebot.TeleBot(TOKEN)

database = sqlite3.connect('ollama_users_telegram.db')
cursor = database.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_name TEXT NOT NULL,
        user_telegram_id INTEGER NOT NULL,
        model TEXT NOT NULL DEFAULT 'llama3.1',
        used_count INTEGER NOT NULL DEFAULT 0,
        temperature FLOAT NOT NULL DEFAULT 0.7
    )
""")
database.commit()
database.close()
print(f'Logged in as {telegram_client.get_me().first_name}')

@telegram_client.message_handler(commands=['start'])
def start(message):
    database = sqlite3.connect('ollama_users_telegram.db')
    cursor = database.cursor()
    try:
        cursor.execute("SELECT user_telegram_id FROM users WHERE user_telegram_id = ?", (message.from_user.id,))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO users (user_name, user_telegram_id) VALUES (?, ?)", (message.from_user.first_name, message.from_user.id))
            database.commit()
            database.close()
            telegram_client.send_message(message.chat.id, f"Hello {message.from_user.first_name}, I'm llama. I'm working on the llama 3.1 model. If you have any questions for me, ask and wait.")
    except sqlite3.Error as e:
        print(f"Database error: {e}")


def google_search(text):
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': google_search_api,
        'cx': google_search_cx,
        'q': text
    }
    response = requests.get(url, params=params)
    return response.json()


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


def main(message):
    try:
        current_time = time.time()
        last_request_time = last_request_list.get(message.from_user.id, 0)

        if current_time - last_request_time < delay_on_requests:
            telegram_client.send_message(message.chat.id, "You're sending requests too quickly. Please wait a bit before sending another request.")
            return

        last_request_list[message.from_user.id] = current_time

        database = sqlite3.connect('ollama_users_telegram.db')
        cursor = database.cursor()

        try:
            cursor.execute("SELECT model, used_count, temperature FROM users WHERE user_telegram_id = ?", (message.from_user.id,))
            result = cursor.fetchone()

            if result is None:
                cursor.execute("INSERT INTO users (user_name, user_telegram_id, model, used_count, temperature) VALUES (?, ?, ?, ?, ?)", 
                                (message.from_user.name, message.from_user.id, 'llama3.1', 1, 0.7))
                database.commit()
                database.close()
                telegram_client.send_message(message.chat.id, f"Hello {message.from_user.name}, I'm llama. I'm working on llama model maded by Meta. If you have any questions for me, ask me and wait.")
                return
            else:
                cursor.execute("UPDATE users SET used_count = used_count + 1 WHERE user_telegram_id = ?", (message.from_user.id,))
                cursor.execute("SELECT model FROM users WHERE user_telegram_id = ?", (message.from_user.id,))
                model = cursor.fetchone()
                model = model[0]
                cursor.execute("SELECT temperature FROM users WHERE user_telegram_id = ?", (message.from_user.id,))
                temperature = cursor.fetchone()
                temperature = temperature[0]
                database.commit()
                database.close()

        except sqlite3.Error as e:
            print(f"Database error: {e}")
            return

        if message.text.lower().startswith('.search '):
            search_query = message.text[len('.search '):]
            results = google_search(search_query)
            results_text = ''
            for item in results.get('items', []):
                results_text += f"Title: {item['title']}\nLink: {item['link']}\n\n"
            if not results_text:
                results_text = "Ничего не найдено"

            llama_request_text = f"Основываясь на информации из поиска:\n{results_text}\n\nПожалуйста, предоставь резюме или ответ на основе этой информации."
            first_message = telegram_client.send_message(message.chat.id, 'Wait until llama responds to you!')
            print(f'Request from: {message.from_user.first_name}. Content: {llama_request_text}')
            request = user_request(llama_request_text, model, temperature)
            print(f'llama response: State: {request[0]}. Content: {request[1]}')

            if request[0] is False:
                telegram_client.delete_message(message.chat.id, first_message.message_id)
                telegram_client.send_message(message.chat.id,
                                            f'Something went wrong, please try again. Error: {request[1]}')
                return

            telegram_client.delete_message(message.chat.id, first_message.message_id)
            if len(request[1]) > 4096:
                for i in range(0, len(request[1]), 4096):
                    telegram_client.send_message(message.chat.id, request[1][i:i + 4096], parse_mode='Markdown')
            else:
                telegram_client.send_message(message.chat.id, request[1], parse_mode='Markdown')
            return

        first_message = telegram_client.send_message(message.chat.id, 'Wait until llama responds to you!')
        print(f'Request from: {message.from_user.first_name}. Content: {message.text}')
        request = user_request(message.text, model, temperature)
        print(f'llama response: State: {request[0]}. Content: {request[1]}')

        if request[0] is False:
            telegram_client.delete_message(message.chat.id, first_message.message_id)
            telegram_client.send_message(message.chat.id, f'Something went wrong, please try again. Error: {request[1]}')
            return

        telegram_client.delete_message(message.chat.id, first_message.message_id)
        if len(request[1]) > 4096:
            for i in range(0, len(request[1]), 4096):
                telegram_client.send_message(message.chat.id, request[1][i:i+4096])
        else:
            telegram_client.send_message(message.chat.id, request[1], parse_mode='Markdown')
        return
    except telebot.apihelper.ApiTelegramException:
        telegram_client.send_message(message.chat.id, 'Something went wrong, please try again. Later, contact: @Ivan_kem.')
        return



@telegram_client.message_handler(func=lambda message: True)
def on_message(message):
    if message.from_user.id != telegram_client.get_me().id:
        if use_whitelist == False:
            main(message)
        elif use_whitelist == True and message.from_user.id in whitelist:
            main(message)
        else:
            telegram_client.send_message(message.chat.id, f"You're not whitelisted!")
            return
    else:
        return


@telegram_client.message_handler(commands=['select_model'])
def select_model(message):
    markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add('llama3.1:8b', 'llama3.1:70b', 'llama2:7b', 'llama2:70b')
    
    msg = telegram_client.send_message(message.chat.id, "Pick the model you need:", reply_markup=markup)
    telegram_client.register_next_step_handler(msg, process_model_choice)

def process_model_choice(message):
    picked_model = message.text
    database = sqlite3.connect('ollama_users_telegram.db')
    cursor = database.cursor()

    cursor.execute("SELECT user_telegram_id FROM users WHERE user_telegram_id = ?", (message.from_user.id,))
    
    if cursor.fetchone() is not None:
        cursor.execute('''UPDATE users
                          SET model = ?, used_count = 1
                          WHERE user_telegram_id = ?''', (picked_model, message.from_user.id))
        database.commit()
        telegram_client.send_message(message.chat.id, f'Model has been updated to {picked_model}.')
    else:
        telegram_client.send_message(message.chat.id, 'Please make at least 1 request to the bot before selecting a model.')
    
    database.close()


@telegram_client.message_handler(commands=['set_temperature'])
def set_temperature(message):
    msg = telegram_client.send_message(message.chat.id, "Enter the temperature you need:")
    telegram_client.register_next_step_handler(msg, process_temperature)

def process_temperature(message):
    temperature = message.text
    database = sqlite3.connect('ollama_users_telegram.db')
    cursor = database.cursor()

    cursor.execute("SELECT user_telegram_id FROM users WHERE user_telegram_id = ?", (message.from_user.id,))
    
    if cursor.fetchone() is not None:
        cursor.execute('''UPDATE users
                          SET temperature = ?, used_count = 1
                          WHERE user_telegram_id = ?''', (temperature, message.from_user.id))
        database.commit()
        telegram_client.send_message(message.chat.id, f'Temperature has been updated to {temperature}.')
    else:
        telegram_client.send_message(message.chat.id, 'Please make at least 1 request to the bot before setting a temperature.')
    
    database.close()
telegram_client.polling()
