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

load_dotenv()

print(
    os.environ['SMTP_SERVER'],
    os.environ['SENDER_EMAIL'],
    os.environ['RECEIVER_EMAIL'],
    os.environ['ROOT_URL'],
    os.environ['SEARCH_URL']
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
    return response.json()


context = ssl.create_default_context()
page = s.get(os.environ['SEARCH_URL'])
soup = BeautifulSoup(page.text, "html.parser")
engine = create_engine(os.environ['DATABASE_URL'])
conn = engine.connect()

extractedtitles = []
lastfumlist = []

df = pd.read_sql_table('ibs_manga', conn)
df = df.dropna()
if not df.empty:
    for index, row in df.iterrows():
        # print(row["title"])
        lastfumlist.append((row["title"], row["url"]))

print(df)

# Gets the number of pages
pagesDiv = soup.find(class_="cc-content-pages")
print(pagesDiv)
pagesDivUL = pagesDiv.find("ul")
print(pagesDivUL)
pagesNumbers = pagesDivUL.find_all("a", class_="cc-page-number")
print(pagesNumbers)
maxPageNumber = int(pagesNumbers[-1].text.strip())
print(maxPageNumber)

# Goes through all the pages, requesting them and putting titles and urls (removing query strings) as tuple (title, url) in the "extractedtitles" list
for enum in list(range(1, maxPageNumber + 1)):
    page = s.get(f'{os.environ["SEARCH_URL"]}&page={enum}')
    print(page.text)
    soup = BeautifulSoup(page.text, "html.parser")
    elementsList = soup.find("div", class_="cc-listing-items")
    print(elementsList)
    titleElements = elementsList.find_all(class_="cc-product-list-item")
    print(titleElements)
    print(enum)
    print(len(titleElements))
    for div in titleElements:
        # print(div.a)
        url = div.a.get("href").split("?")[0]
        tup = (div.a.text, root + url)
        extractedtitles.append(tup)

# Converts extracted titles and urls in a pandas dataframe, and saves it as csv
extractedDataframe = pd.DataFrame(extractedtitles, columns=["title", "url"])
affected_rows = extractedDataframe.to_sql(name='ibs_manga', con=engine, if_exists='replace', index=False)
# print(extractedDataframe)
print(affected_rows)

# same as above, but saves the elements that are present only in the "extractedtitles" list
newcomicsList = sorted(list(set(extractedtitles) - set(lastfumlist)), key=lambda x: x[0])
newcomicsDF = pd.DataFrame(newcomicsList, columns=["title", "url"])
affected_rows = newcomicsDF.to_sql(name='ibs_manga_new', con=engine, if_exists='replace', index=False)

print(affected_rows)

telegram_messages = []
telegram_message = "Subject: Fumetti nuovi scontati su ibs\n\n"
email_message = "Subject: Fumetti nuovi scontati su ibs\n\n"
# Regexs Needed for telegram API to properly accept the message with the Inline URL
telegramTitleEscape = r"([\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!])"
telegramUrlEscape = r"([\)\\])"

# Composes the messages that gets sent to the user, via email and telegram (Telegram has a character limit)
if not newcomicsDF.empty:
    for index, row in newcomicsDF.iterrows():
        if row["title"] == 0:
            continue
        email_message = email_message + \
            row["title"] + " - " + row["url"] + "\n"
        # Builds the telegram message by using MarkdownV2 (https://core.telegram.org/bots/api#formatting-options) and escaping the characters in titles and urls as required
        link_to_append = "[{}]({})\n".format(re.sub(telegramTitleEscape, r'\\\1', row["title"]), re.sub(telegramUrlEscape, r'\\\1', row["url"]))

        if (len(telegram_message + link_to_append) > 4096):
            telegram_messages.append(telegram_message)
            telegram_message = link_to_append

        else:
            telegram_message += link_to_append
telegram_messages.append(telegram_message)

# Sends the message to both the designed email address through Gmail SMTP, and through Telegram Bot API
if not newcomicsDF.empty:
    with smtplib.SMTP(smtp_server, port) as server:
        server.ehlo()  # Can be omitted
        server.starttls(context=context)
        server.ehlo()  # Can be omitted
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, email_message.encode())

    for message in telegram_messages:
        test = telegram_bot_sendtext(str(message.replace("Subject: ", '')))
        print(test)
        time.sleep(1.5)
