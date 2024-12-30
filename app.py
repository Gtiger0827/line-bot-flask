!pip install flask line-bot-sdk yfinance beautifulsoup4 openai matplotlib pandas python-dotenv

import openai
import yfinance as yf
import numpy as np
import datetime as dt
import matplotlib.pyplot as plt
import requests
import os
import pandas as pd
from bs4 import BeautifulSoup
from flask import Flask, request, abort, jsonify
from linebot.v3.webhook import WebhookHandler, MessageEvent
from linebot.v3.messaging import MessagingApi, ReplyMessageRequest, TextMessage, ImageMessage
from linebot.v3.exceptions import InvalidSignatureError
from dotenv import load_dotenv

# 讀取環境變數
load_dotenv()

# 環境變數設置
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


# 股票分析與圖表繪製
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
            return None

        stock_data['date'] = stock_data.index.strftime('%Y-%m-%d')
        stock_data = stock_data.sort_index(ascending=True)  # 日期由舊到新排序

        plt.figure(figsize=(10, 5))
        plt.plot(stock_data['Close'], label='Closing Price')
        plt.title(f"{stock_id} Stock Price (Last {days} Days)")
        plt.xlabel("Date")
        plt.ylabel("Price (TWD)")
        plt.legend()
        plt.grid(True)

        filename = f"{stock_id}_price_chart.png"
        filepath = f"./static/{filename}"
        plt.savefig(filepath)
        plt.close()
        return filepath
    except Exception as e:
        print(f"股價資料獲取失敗: {str(e)}")
        return None


def stock_fundamental(stock_id="大盤"):
    if stock_id == "大盤":
        return None

    stock_id += ".TW"
    stock = yf.Ticker(stock_id)

    try:
        eps = stock.quarterly_financials.loc["Basic EPS"].dropna()
        dates = [col.strftime('%Y-%m-%d') for col in stock.quarterly_financials.columns]

        plt.figure(figsize=(10, 5))
        plt.bar(dates[:len(eps)], eps)
        plt.title(f"{stock_id} EPS 成長")
        plt.xlabel("Quarter")
        plt.ylabel("EPS")
        plt.grid(True)

        filename = f"{stock_id}_eps_chart.png"
        filepath = f"./static/{filename}"
        plt.savefig(filepath)
        plt.close()
        return filepath
    except Exception as e:
        print(f"基本面資料獲取失敗: {str(e)}")
        return None


# LINE Bot Webhook 處理
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


# LINE 訊息事件處理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id

    line_bot_api.reply_message(
        event.reply_token,
        ReplyMessageRequest(messages=[TextMessage(text="分析中，請稍候...")])
    )

    threading.Thread(target=generate_report, args=(user_message, user_id)).start()


def generate_report(stock_id, user_id):
    price_chart = stock_price(stock_id)
    eps_chart = stock_fundamental(stock_id)

    messages = [TextMessage(text=f"{stock_id} 分析報告已生成")]

    for chart in [price_chart, eps_chart]:
        if chart:
            url = f"https://your-domain.com/static/{os.path.basename(chart)}"
            messages.append(ImageMessage(original_content_url=url, preview_image_url=url))

    line_bot_api.push_message(user_id, messages)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)


