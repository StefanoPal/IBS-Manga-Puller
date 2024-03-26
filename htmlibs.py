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

print(os.environ['SMTP_SERVER'], os.environ['SENDER_EMAIL'], os.environ['RECEIVER_EMAIL'], os.environ['ROOT_URL'], os.environ['SEARCH_URL'])
port = 587  # For starttls
smtp_server = os.environ['SMTP_SERVER']
sender_email = os.environ['SENDER_EMAIL']
receiver_email = os.environ['RECEIVER_EMAIL']
password = os.environ['MAIL_PASSWORD']
root = os.environ['ROOT_URL']

def telegram_bot_sendtext(bot_message):

    bot_token = os.environ['BOT_TOKEN']
    bot_chatID = '-1001423503608'
    send_text = 'https://api.telegram.org/bot' + bot_token + '/sendMessage?chat_id=' + \
        bot_chatID + '&parse_mode=MarkdownV2&text=' + \
        urllib.parse.quote(bot_message)
    response = requests.get(send_text)
    return response.json()


# telegram_bot_sendtext("Stefano&company")
context = ssl.create_default_context()
page = requests.get(os.environ['SEARCH_URL'])
soup = BeautifulSoup(page.text, "html.parser")
# filename = "nuovi_fum.csv"
# titles = soup.find("div", class_="cc-listing-items").find_all(class_="cc-product-list-item")
# for elem in titles:
# print(elem.find(class_="cc-content-title").a.text)
# root + elem.find(class_="cc-content-title").a.get("href"))
engine = create_engine(os.environ['DATABASE_URL'])
conn = engine.connect()
# print(titles)
extractedtitles = []
#lista2 = []
lastfumlist = []

# Reads comics and urls that were detected last run through Pandas
# df = pd.read_csv('/home/pi/Desktop/Ibs/fumetti.csv',
#                  encoding="utf-8", na_values="NaN", index_col=0)

df = pd.read_sql_table('ibs_manga', conn)
df = df.dropna()
#df = pd.DataFrame()
# Moves dataframe in a list with tuples -> (title, url)
if not df.empty:
    for index, row in df.iterrows():
        # print(row["title"])
        lastfumlist.append((row["title"], row["url"]))

print(df)
# for div in titles:
#     lista2.append(div.find(class_="cc-content-title").a.text)

# Gets the number of pages
numeropag = int(
    soup.find(class_="cc-plp-pagination").ul.find_all("li")[-1].text.strip())
print(numeropag)

#numeropag = int(lista2[0].split()[1])
# Goes through all the pages, requesting them and putting titles and urls (removing query strings) as tuple (title, url) in the "extractedtitles" list
for enum in list(range(1, numeropag + 1)):
    page = requests.get(f'{os.environ["SEARCH_URL"]}&page={enum}')
    soup = BeautifulSoup(page.text, "html.parser")
    titleElements = soup.find(
        "div", class_="cc-listing-items").find_all(class_="cc-product-list-item")
        
    print(len(titleElements))
    for div in titleElements:
        # print(div.a)
        url = div.a.get("href").split("?")[0]
        tup = (div.a.text, root + url)
        extractedtitles.append(tup)

# print(extractedtitles)

# Converts extracted titles and urls in a pandas dataframe, and saves it as csv
extractedDataframe = pd.DataFrame(extractedtitles, columns=["title", "url"])
# extractedDataframe.to_csv('/home/pi/Desktop/Ibs/fumetti.csv', encoding='utf-8')
affected_rows = extractedDataframe.to_sql(name='ibs_manga', con=engine, if_exists='replace', index=False)
# print(extractedDataframe)
print(affected_rows)

# same as above, but saves the elements that are present only in the "extractedtitles" list
newcomicsList = sorted(list(set(extractedtitles) - set(lastfumlist)), key=lambda x: x[0])
newcomicsDF = pd.DataFrame(newcomicsList, columns=["title", "url"])
# newcomicsList.to_csv('/home/pi/Desktop/Ibs/Nuovi_fum.csv', encoding='utf-8')
affected_rows = newcomicsDF.to_sql(name='ibs_manga_new', con=engine, if_exists='replace', index=False)

# print(newcomicsList)
print(affected_rows)

telegram_messages = []
telegram_message = "Subject: Fumetti nuovi scontati su ibs\n\n"
messaggioemail = "Subject: Fumetti nuovi scontati su ibs\n\n"
# Regexs Needed for telegram API to properly accept the message with the Inline URL
telegramTitleEscape = r"([\_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!])"
telegramUrlEscape = r"([\)\\])"

# Composes the messages that gets sent to the user, via email and telegram (Telegram has a character limit)
if not newcomicsDF.empty:
    for index, row in newcomicsDF.iterrows():
        if row["title"] == 0:
            continue
        messaggioemail = messaggioemail + \
            row["title"] + " - " + row["url"] + "\n"
        # Builds the telegram message by using MarkdownV2 (https://core.telegram.org/bots/api#formatting-options) and escaping the characters in titles and urls as required
        link_to_append = "[{}]({})\n".format(re.sub(telegramTitleEscape, r'\\\1', row["title"]), re.sub(telegramUrlEscape, r'\\\1', row["url"]))
        
        if(len(telegram_message + link_to_append) > 4096):
            telegram_messages.append(telegram_message)
            telegram_message = link_to_append
            
        else:
            telegram_message += link_to_append
        
        
telegram_messages.append(telegram_message)

# print(messaggioemail)
# print(messaggiotel)
# Sends the message to both the designed email address through Gmail SMTP, and through Telegram Bot API
if not newcomicsDF.empty:
    with smtplib.SMTP(smtp_server, port) as server:
        server.ehlo()  # Can be omitted
        server.starttls(context=context)
        server.ehlo()  # Can be omitted
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, messaggioemail.encode())

    for message in telegram_messages:
        test = telegram_bot_sendtext(str(message.replace("Subject: ", '')))
        print(test)
        time.sleep(1.5)
