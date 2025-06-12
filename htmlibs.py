import re
import urllib
import ssl
import smtplib
import time
import os
import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from sqlalchemy import create_engine
import pandas as pd

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()

logger.info("Loaded environment variables: SMTP_SERVER=%s, SENDER_EMAIL=%s, RECEIVER_EMAIL=%s, ROOT_URL=%s, SEARCH_URL=%s",
    os.environ.get('SMTP_SERVER'),
    os.environ.get('SENDER_EMAIL'),
    os.environ.get('RECEIVER_EMAIL'),
    os.environ.get('ROOT_URL'),
    os.environ.get('SEARCH_URL')
)

port = 587  # For starttls
smtp_server = os.environ['SMTP_SERVER']
sender_email = os.environ['SENDER_EMAIL']
receiver_email = os.environ['RECEIVER_EMAIL']
password = os.environ['MAIL_PASSWORD']
root = os.environ['ROOT_URL']

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0"
}

s = requests.Session()
s.headers.update(headers)

def telegram_bot_sendtext(bot_message):

    bot_token = os.environ['BOT_TOKEN']
    bot_chatID = '-1001423503608'
    send_text = 'https://api.telegram.org/bot' + bot_token + '/sendMessage?chat_id=' + \
        bot_chatID + '&parse_mode=MarkdownV2&text=' + \
        urllib.parse.quote(bot_message)
    response = s.get(send_text)
    logger.debug("Telegram response: %s", response.text)
    return response.json()


context = ssl.create_default_context()

logger.info("Requesting search URL: %s", os.environ['SEARCH_URL'])
page = s.get(os.environ['SEARCH_URL'])
logger.info("Fetched page with status code: %d", page.status_code)
soup = BeautifulSoup(page.text, "html.parser")


engine = create_engine(os.environ['DATABASE_URL'])
conn = engine.connect()
logger.info("Connected to database.")

extractedtitles = []
lastfumlist = []

try:
    df = pd.read_sql_table('ibs_manga', conn)
    df = df.dropna()
    logger.info("Loaded %d rows from 'ibs_manga' table.", len(df))
except Exception as e:
    logger.warning("Could not load previous manga table: %s", e)
    df = pd.DataFrame()

if not df.empty:
    for index, row in df.iterrows():
        lastfumlist.append((row["title"], row["url"]))
    logger.info("Prepared lastfumlist with %d entries.", len(lastfumlist))

# Gets the number of pages
pagesDiv = soup.find(class_="cc-content-pages")
if not pagesDiv:
    logger.error("Could not find pagination div with class 'cc-content-pages'. Exiting.")
    exit(1)
pagesDivUL = pagesDiv.find("ul")
if not pagesDivUL:
    logger.error("Could not find <ul> inside pagination div.")
    exit(1)
pagesNumbers = pagesDivUL.find_all("a", class_="cc-page-number")
if not pagesNumbers:
    logger.error("No page number links found.")
    exit(1)
maxPageNumber = int(pagesNumbers[-1].text.strip())
logger.info("Detected %d pages in search results.", maxPageNumber)

# Goes through all the pages, requesting them and putting titles and urls (removing query strings) as tuple (title, url) in the "extractedtitles" list
for enum in list(range(1, maxPageNumber + 1)):
    url = f'{os.environ["SEARCH_URL"]}&page={enum}'
    page = s.get(url)
    logger.info("Fetched page %d/%d (status: %d)", enum, maxPageNumber, page.status_code)
    soup = BeautifulSoup(page.text, "html.parser")
    elementsList = soup.find("div", class_="cc-listing-items")
    
    if not elementsList:
        logger.warning("No listing items found on page %d.", enum)
        continue
        
    titleElements = elementsList.find_all(class_="cc-product-list-item")
    logger.info("Found %d manga items on page %d.", len(titleElements), enum)
    for div in titleElements:
        url = div.a.get("href").split("?")[0]
        tup = (div.a.text, root + url)
        extractedtitles.append(tup)

logger.info("Extracted %d unique manga titles.", len(extractedtitles))

# Converts extracted titles and urls in a pandas dataframe, and saves it as csv
extractedDataframe = pd.DataFrame(extractedtitles, columns=["title", "url"])
affected_rows = extractedDataframe.to_sql(name='ibs_manga', con=engine, if_exists='replace', index=False)
logger.info("Wrote %d rows to 'ibs_manga' table.", affected_rows)

# same as above, but saves the elements that are present only in the "extractedtitles" list
newcomicsList = sorted(list(set(extractedtitles) - set(lastfumlist)), key=lambda x: x[0])
newcomicsDF = pd.DataFrame(newcomicsList, columns=["title", "url"])
affected_rows = newcomicsDF.to_sql(name='ibs_manga_new', con=engine, if_exists='replace', index=False)
logger.info("Wrote %d new comics to 'ibs_manga_new' table.", affected_rows)

telegram_messages = []
telegram_message = "Subject: Fumetti nuovi scontati su ibs\n\n"
email_message = "Subject: Fumetti nuovi scontati su ibs\n\n"
# Regexs Needed for telegram API to properly accept the message with the Inline URL
telegramTitleEscape = r"([\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!])"
telegramUrlEscape = r"([\)\\])"

# Composes the messages that gets sent to the user, via email and telegram (Telegram has a character limit)
if not newcomicsDF.empty:
    logger.info("Preparing messages for %d new manga titles.", len(newcomicsDF))
    for index, row in newcomicsDF.iterrows():
        if row["title"] == 0:
            continue
        email_message = email_message + \
            row["title"] + " - " + row["url"] + "\n"
        # Builds the telegram message by using MarkdownV2 (https://core.telegram.org/bots/api#formatting-options) and escaping the characters in titles and urls as required
        link_to_append = "[{}]({})\n".format(re.sub(telegramTitleEscape, r'\\\1', row["title"]), re.sub(telegramUrlEscape, r'\\\1', row["url"]))

        if (len(telegram_message + link_to_append) > 4096):
            logger.warning("Telegram message chunk exceeded 4096 characters, splitting message.")
            telegram_messages.append(telegram_message)
            telegram_message = link_to_append
        else:
            telegram_message += link_to_append
            
    telegram_messages.append(telegram_message)
else:
    logger.info("No new manga titles to notify.")

# Sends the message to both the designed email address through Gmail SMTP, and through Telegram Bot API
if not newcomicsDF.empty:
    try:
        logger.info("Sending email to %s...", receiver_email)
        with smtplib.SMTP(smtp_server, port) as server:
            server.ehlo()  # Can be omitted
            server.starttls(context=context)
            server.ehlo()  # Can be omitted
            server.login(sender_email, password)
            server.sendmail(sender_email, receiver_email, email_message.encode())
        logger.info("Email sent successfully.")
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        
    for idx, message in enumerate(telegram_messages):
        logger.info("Sending Telegram chunk %d/%d", idx+1, len(telegram_messages))
        test = telegram_bot_sendtext(str(message.replace("Subject: ", '')))
        logger.debug("Telegram send response: %s", test)
        time.sleep(1.5)
else:
    logger.info("No new comics found, skipping email/telegram notification.")
