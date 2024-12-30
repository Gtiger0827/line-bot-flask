from flask import Flask, request, abort, jsonify
from linebot.v3.webhook import WebhookHandler, MessageEvent
from linebot.v3.messaging import MessagingApi, ReplyMessageRequest, TextMessage, ImageMessage
from linebot.v3.exceptions import InvalidSignatureError

import openai
import yfinance as yf
import numpy as np
import datetime as dt
import matplotlib.pyplot as plt
import requests
import os
import threading
import pandas as pd
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# 讀取環境變數
load_dotenv()

# 環境變數設置與檢查
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET or not OPENAI_API_KEY:
    raise EnvironmentError("缺少必要的環境變數，請檢查 .env 文件設置是否正確")

# 初始化
client = openai.Client(api_key=OPENAI_API_KEY)
app = Flask(__name__)

line_bot_api = MessagingApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

os.makedirs("static", exist_ok=True)


@app.route("/", methods=["GET"])
def home():
    return "Hello from LINE Bot!"


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    if not signature or not body:
        abort(400, "Missing signature or body")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400, "Invalid signature")
    except Exception as e:
        print(f"Webhook Error: {str(e)}")
        abort(500, description=f"Internal Server Error: {str(e)}")

    return "OK", 200


# 股票價格資料
def stock_price(stock_id="大盤", days=90):
    if stock_id == "大盤":
        stock_id = "^TWII"
    else:
        stock_id += ".TW"

    end = dt.date.today()
    start = end - dt.timedelta(days=days)

    try:
        stock_data = yf.download(stock_id, start=start, end=end)
        if stock_data.empty:
            return {"message": "查無資料"}

        stock_data['date'] = stock_data.index.strftime('%Y-%m-%d')

        # 繪製股價走勢圖
        plt.figure(figsize=(10, 5))
        plt.plot(stock_data['Close'], label='Closing Price')
        plt.title(f"{stock_id} Stock Price (Last {days} Days)")
        plt.xlabel("Date")
        plt.ylabel("Price (TWD)")
        plt.legend()
        plt.grid(True)
        plt.savefig(f"./static/{stock_id}_price_chart.png")
        plt.close()

        return stock_data[['date', 'Open', 'High', 'Low', 'Close', 'Volume']].tail(30).to_dict('list')
    except Exception as e:
        return {"message": f"股價資料獲取失敗: {str(e)}"}


# 基本面資料
def stock_fundamental(stock_id="大盤"):
    if stock_id == "大盤":
        return {"message": "大盤無基本面資訊"}

    stock_id += ".TW"
    stock = yf.Ticker(stock_id)

    try:
        quarterly_eps = np.round(
            stock.quarterly_financials.loc["Basic EPS"].dropna().tolist(), 2
        )

        dates = [date.strftime('%Y-%m-%d') for date in stock.quarterly_financials.columns]

        # 繪製 EPS 圖
        plt.figure(figsize=(10, 5))
        plt.bar(dates, quarterly_eps)
        plt.title(f"{stock_id} EPS Analysis")
        plt.xlabel("Quarter")
        plt.ylabel("EPS")
        plt.grid(True)
        plt.savefig(f"./static/{stock_id}_eps_chart.png")
        plt.close()

        return {"EPS": quarterly_eps, "日期": dates}
    except Exception as e:
        return {"message": "基本面資料獲取失敗", "error": str(e)}


# 新聞爬蟲
def stock_news(stock_name="大盤"):
    data = []
    try:
        stock_name = "台股" if stock_name == "大盤" else stock_name
        json_data = requests.get(
            f'https://ess.api.cnyes.com/ess/api/v1/news/keyword?q={stock_name}&limit=5&page=1'
        ).json()

        items = json_data['data']['items']
        for item in items:
            title = item["title"]
            publish_at = dt.datetime.utcfromtimestamp(item["publishAt"]).strftime('%Y-%m-%d')
            data.append(f"{publish_at}: {title}")
    except Exception as e:
        print(f"新聞獲取失敗: {str(e)}")

    return data[:3] if data else [{"message": "查無新聞"}]


# 股票名稱查詢
def stock_name():
    response = requests.get('https://isin.twse.com.tw/isin/C_public.jsp?strMode=2')
    url_data = BeautifulSoup(response.text, 'html.parser')
    stock_company = url_data.find_all('tr')

    data = [
        (row.find_all('td')[0].text.split('\u3000')[0].strip(),
         row.find_all('td')[0].text.split('\u3000')[1])
        for row in stock_company[2:] if len(row.find_all('td')) > 4
    ]

    return pd.DataFrame(data, columns=['股號', '股名'])


name_df = stock_name()


def get_stock_name(stock_id):
    try:
        return name_df.set_index('股號').loc[stock_id, '股名']
    except KeyError:
        return "未知股票"


# 生成報告並發送至 LINE
def generate_report(stock_id, user_id):
    price_chart = stock_price(stock_id)
    eps_chart = stock_fundamental(stock_id)
    news_data = stock_news(stock_id)

    gpt_analysis = stock_gpt(stock_id)

    messages = [TextMessage(text=gpt_analysis)]

    for chart in [f"{stock_id}_price_chart.png", f"{stock_id}_eps_chart.png"]:
        url = f"https://line-bot-flask.onrender.com/static/{chart}"
        messages.append(ImageMessage(original_content_url=url, preview_image_url=url))

    line_bot_api.push_message(user_id, messages)


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id

    line_bot_api.reply_message(event.reply_token, ReplyMessageRequest(messages=[TextMessage(text="報告生成中...")]))
    threading.Thread(target=generate_report, args=(user_message, user_id)).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

