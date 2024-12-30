from flask import Flask, request, abort, jsonify
from linebot.v3.webhook import WebhookHandler, MessageEvent
from linebot.v3.messaging import MessagingApi, ReplyMessageRequest, TextMessage, ImageMessage
from linebot.v3.exceptions import InvalidSignatureError

import openai
import yfinance as yf
import pandas as pd
import numpy as np
import datetime as dt
import matplotlib.pyplot as plt
import requests
import os
import threading
from dotenv import load_dotenv

# 讀取環境變數
load_dotenv()

# 環境變數設置與檢查
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 檢查環境變數是否存在
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET or not OPENAI_API_KEY:
    raise EnvironmentError("缺少必要的環境變數，請檢查 .env 文件設置是否正確")

# 初始化 OpenAI 客戶端
client = openai.Client(api_key=OPENAI_API_KEY)
app = Flask(__name__)

# 啟動 LINE Bot 設定
line_bot_api = MessagingApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 建立靜態目錄
os.makedirs("static", exist_ok=True)


# Home Route - 測試 Flask 啟動
@app.route("/", methods=["GET"])
def home():
    return "Hello from LINE Bot!"


# Webhook 接收處理
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)

    # 如果簽名或請求內容不存在，則拒絕請求
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


# 股票數據處理
def stock_price(stock_id="^TWII", days=90):
    end = dt.date.today()
    start = end - dt.timedelta(days=days)

    try:
        stock_data = yf.download(stock_id, start=start, end=end)
        if stock_data.empty:
            return None

        plt.figure(figsize=(10, 5))
        plt.plot(stock_data['Close'], label='收盤價')
        plt.title(f"{stock_id} 最近 {days} 天股價")
        plt.xlabel("日期")
        plt.ylabel("股價 (TWD)")
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


def stock_fundamental(stock_id="^TWII"):
    stock = yf.Ticker(stock_id)
    try:
        eps_data = np.round(stock.quarterly_financials.loc["Basic EPS"].dropna().tolist(), 2)
        dates = [col.strftime('%Y-%m-%d') for col in stock.quarterly_financials.columns]

        plt.figure(figsize=(10, 5))
        plt.bar(dates, eps_data)
        plt.title(f"{stock_id} EPS 成長")
        plt.xlabel("季度")
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


def stock_news(stock_name="台股"):
    try:
        response = requests.get(
            f'https://ess.api.cnyes.com/ess/api/v1/news/keyword?q={stock_name}&limit=5'
        ).json()
        news = [
            f"{item['title']} - {dt.datetime.utcfromtimestamp(item['publishAt']).strftime('%Y-%m-%d')}"
            for item in response['data']['items']
        ]
        return "\n".join(news) if news else "查無新聞"
    except Exception as e:
        print(f"新聞獲取失敗: {str(e)}")
        return "查無新聞"


def stock_gpt_analysis(stock_name):
    news_data = stock_news(stock_name)
    messages = [
        {"role": "system", "content": "你是一位專業的股票分析師，撰寫中文報告。"},
        {"role": "user", "content": f"請分析 {stock_name} 的新聞。\n{news_data}"}
    ]

    try:
        response = client.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
        return response.choices[0].message.content
    except Exception as e:
        return f"分析報告失敗: {str(e)}"


# 生成分析報告
def generate_report(stock_id, user_id):
    price_chart = stock_price(stock_id)
    eps_chart = stock_fundamental(stock_id)
    news = stock_news(stock_id)

    report_text = f"{stock_id} 分析報告:\n{news}\n請參考圖表。"
    messages = [TextMessage(text=report_text)]

    for chart in [price_chart, eps_chart]:
        if chart:
            url = f"https://your-domain.com/static/{os.path.basename(chart)}"
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
