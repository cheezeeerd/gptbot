import textwrap
import os, random
import asyncio, json
import datetime, sqlite3
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

class TelegramBot:
    def __init__(self, token):
        self.token = token  # Telegram bot token
        self.generator = Generator()  # Text generator
        self.db = Database("user_metrics.db", self)  # Database for user metrics
        self.cache = {}  # Cache for user metrics and spam prevention

    # Handle incoming messages, filter spam
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.message.from_user.id
        if user_id not in self.cache:
            self.cache[user_id] = {'count': 0, 'count_pro': 0}
        prompt = update.message.text
        self.logging(update, user_id, prompt)
        algorithm_map = {
            '/a': 'long_gen',
            '/4': 'gpt4_gen',
            '/u': 'grmr_gen' 
            }
        spam_msg = ["Whoa there, speed racer! 🏎️", 
                    "Someone needs a chill pill.💊", 
                    "Easy on the keyboard, friend.", 
                    "Quality over quantity, my friend.", 
                    "Woah! Someones got chatty fingers.", 
                    "My reply speed can't match yours.🐌", 
                    "Spamming at the speed of light, are we?", 
                    "Spam alert! Must... resist... the urge to reply."]
        command_prefix = next((prefix for prefix in algorithm_map if prompt.startswith(prefix)), None)
        if self.cache[user_id]['count'] >= 25 or self.cache[user_id]['count_pro'] >= 10:
            await update.message.reply_text(random.choice(spam_msg))
            print(f'Spam detected from #{user_id}')
            return
        if command_prefix:
            await self.send_message(update, user_id, prompt[len(command_prefix):].strip(), mode=algorithm_map[command_prefix])
        else: 
            await self.send_message(update, user_id, prompt, None)

    # Send a message to the user   
    async def send_message(self, update: Update, user_id, prompt, mode):
        if mode == 'long_gen' or mode == 'gpt4_gen':
            self.cache[user_id]['count_pro'] += 1
        else: self.cache[user_id]['count'] += 1
        api_response = await self.generator.generate_text(prompt, mode, user_id)
        if api_response:
            for chunk in api_response:
                await update.message.reply_text(chunk, parse_mode='Markdown')
        else: 
            await update.message.reply_text("An error occurred. Please try again later.")

    # Log messages from users
    def logging(self, update: Update, user_id, prompt):
        now = datetime.datetime.now()
        formatted_now = now.strftime("%Y-%m-%d %H:%M:%S")
        user_id = update.message.from_user.id    
        log_name = 'message_log.json'
        log_entry = {'user_id': user_id,'message_text': prompt, 'timestamp': formatted_now}
        try:
            with open(log_name, 'r') as file:
                log_data = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            log_data = []
        log_data.append(log_entry)
        with open(log_name, 'w') as file:
            json.dump(log_data, file, indent=4)

    # Handle /start command
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
       await update.message.reply_text(f"~Google gives you _links_~\nGPT bot gives you _solutions_🤖\n\nv2\.0\.2 Get help anytime: /help\.", parse_mode='MarkdownV2')

    # Handle /help command
    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
       user_id = update.message.from_user.id
       if user_id not in self.cache:
            self.cache[user_id] = {'count': 0, 'count_pro': 0}
       count_remaining = 25 - self.cache[user_id]['count']
       count_pro_remaining = 10 - self.cache[user_id]['count_pro']
       await update.message.reply_text(f"*🤖Bot Command Menu🤖*\n\n•To ask a __question__, type it in the chat\.\n•If a __detailed__ response is required, start with /a\.\n•To ask __\GPT\-4__ \(slow but very accurate\), start with /4\.\n•To edit __\grammar__ in your message, use /u\.", parse_mode='MarkdownV2', disable_web_page_preview=True)
       await asyncio.sleep(1)
       await update.message.reply_text(f"\n_Message limits apply to free accounts_🤏\n\nYou have __*{count_remaining}/25*__ simple and __*{count_pro_remaining}/10*__ large GPT\-4 requests left for the hour\.\n\nSubmit [feedback](t.me/yourusername)\nShow this message again \- /help", parse_mode='MarkdownV2', disable_web_page_preview=True)

    # Run the bot
    def run(self):
        application = Application.builder().token(self.token).build()
        application.add_handler(CommandHandler("start", self.start))  
        application.add_handler(CommandHandler("help", self.help)) 
        application.add_handler(MessageHandler(filters.ALL, self.handle_message))
        job_queue = application.job_queue
        job_queue.run_repeating(lambda context: self.db.reset_cache(self.cache), interval=3600, first=1)
        application.run_polling()

class Database:
    def __init__(self, db_path, tgbot):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.create_table()
        self.bot = tgbot

    # Create a new table in the database
    def create_table(self):
        query = '''CREATE TABLE IF NOT EXISTS user_messages (
                 user_id INTEGER PRIMARY KEY,
                 count INTEGER DEFAULT 1,
                 count_pro INTEGER DEFAULT 1)'''
        try:
            self.conn.execute(query)
            self.conn.commit()
            print('Database created')
        except sqlite3.Error as e:
            print(f"Error creating database: {e}")

    # Update the database with user metrics
    def update_database(self, user_id, count, count_pro):
        cursor = self.conn.cursor()
        try:
            cursor.execute(
                "UPDATE user_messages SET count = count + ?, count_pro = count_pro + ? WHERE user_id = ?",
                (count, count_pro, user_id))
            if cursor.rowcount == 0: 
                print("User not found, inserting new row")
                cursor.execute(
                    "INSERT INTO user_messages (user_id, count, count_pro) VALUES (?, ?, ?)", 
                    (user_id, count, count_pro)) 
            self.conn.commit()    
            cursor.execute("SELECT * FROM user_messages")
        except sqlite3.Error as e:
            print(f"Error updating database: {e}")
        print(f"Database state: {cursor.fetchall()}\n")

    # Reset the cache
    async def reset_cache(self, cache):
        for user_id, counts_dict in cache.items():
            count_pro = counts_dict['count_pro']
            count = counts_dict['count']
            self.update_database(user_id, count, count_pro)
            counts_dict['count'] = 0
            counts_dict['count_pro'] = 0

class Generator:
    def __init__(self):
        self.openai = OpenAI()  # OpenAI API client

    # Select the role for the text generation
    async def role_selector(self, prompt, mode):
        print(f"Prompt ({mode}): {prompt}")
        if mode == 'long_gen':
            role = [
                {"role": "system", "content": "You are an expert guide through a wide array of subjects, explaining concepts with precision using the same language. Your task is to clarify complex topics with in-depth analyses including emoji. Your responses should ensure a thorough understanding of the topic."},
                {"role": "user", "content": prompt}  
            ]
        elif mode == 'grmr_gen':
            role = [
                {"role": "system", "content": "Grammar-enhancing bot refining any text it receives. Remove grammatical mistakes from the text, maintain original voice, optimize grammar, and trim redundancies. Reply with just the edited copy of the received text"},
                {"role": "user", "content": prompt}
            ]
        elif mode == 'gpt4_gen':
            role = [
                {"role": "system", "content": "You are an expert guide through a wide array of subjects, explaining concepts using the same language. Your task is to clarify complex topics with analysis, including emoji"},
                {"role": "user", "content": prompt}
            ]
        else: role = [
                {"role": "system", "content": "Expert assistant delivering concise, informative responses. Include emojis, cover principles. Respond using the same language and keep it brief within 100-150 words"},
                {"role": "user", "content": prompt}
       ]
        return role
    
    # Generate text using the OpenAI API
    async def generate_text(self, prompt, mode, user_id):
        role = await self.role_selector(prompt, mode)
        if role == 'gpt4_gen':
            framework = "gpt-4-0125-preview"
        else: framework = "gpt-3.5-turbo-0125"
        completion = self.openai.chat.completions.create(
                model = framework,
                messages = role)
        response = completion.choices[0].message.content
        return self.split_message(response)
    
    # Split the message into chunks
    def split_message(self, text, chunk_size=4096):
        if len(text) > chunk_size:
            return textwrap.wrap(text, width=chunk_size)
        chunks = []
        chunks.append(text)
        return chunks
# Main function
if __name__ == '__main__':
    openai_key = os.getenv('OPENAI_API_KEY')  # OpenAI API key
    telegram_token = os.getenv('TELEGRAM_ALT_KEY')  # Telegram bot token
    bot = TelegramBot(telegram_token)  # Create a new bot instance
    bot.run()  # Run the bot
