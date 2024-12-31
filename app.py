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

@app.route("/", methods=["GET"])
def home():
    return "Hello from LINE Bot!"

# 股票價格圖表生成
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
        plt.title(f"{stock_id} 股價走勢圖")
        plt.xlabel("日期")
        plt.ylabel("價格 (TWD)")
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


# 基本面 EPS 圖表生成
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
        plt.title(f"{stock_id} EPS 成長圖")
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
# 新聞爬蟲
def stock_news(stock_name="台股"):
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
        print("新聞資料:")
        print("\n".join(data))
    except Exception as e:
        print(f"新聞獲取失敗: {str(e)}")

    return data[:3] if data else [{"message": "查無新聞"}]


# GPT 股票分析報告生成
def stock_gpt_analysis(stock_id):
    stock_name = "台股" if stock_id == "大盤" else stock_id
    price_data = stock_price(stock_id) or "查無股價資料"
    fund_data = stock_fundamental(stock_id) or "查無基本面資料"
    news_data = stock_news(stock_name) or "查無新聞資料"

    messages = [
        {"role": "system", "content": "你是一位專業的股票分析師，請提供深入的分析報告，並用中文撰寫。"},
        {"role": "user", "content": f"請分析 {stock_name} 的股價與基本面與新聞。\n股價資料:\n{price_data}\n基本面資料:\n{fund_data}\n新聞:\n{news_data}"}
    ]

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        gpt_report = response.choices[0].message.content
        print("GPT 分析報告:")
        print(gpt_report)
        return gpt_report
    except Exception as e:
        print(f"生成分析報告失敗: {str(e)}")
        return "生成分析報告失敗，請稍後再試。"
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
    print(f"生成報告中，股票代號: {stock_id}")
    price_chart = stock_price(stock_id)
    eps_chart = stock_fundamental(stock_id)
    gpt_report = stock_gpt_analysis(stock_id)

    messages = [TextMessage(text=f"{stock_id} 分析報告:\n\n{gpt_report}")]

    for chart in [price_chart, eps_chart]:
        if chart:
            url = f"https://line-bot-flask-oha5.onrender.com/static/{os.path.basename(chart)}"
            messages.append(ImageMessage(original_content_url=url, preview_image_url=url))

    line_bot_api.push_message(user_id, messages)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
