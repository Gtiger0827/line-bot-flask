from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

LINE_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
HF_API_URL = 'https://你的-space名稱.hf.space'  # 替換成你的 Hugging Face Space 網址

# 首頁路由，避免 404
@app.route("/")
def home():
    return "Hello from Flask! Webhook is ready."

# 處理 LINE Webhook 路由
@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.json
    for event in body['events']:
        if event['type'] == 'message':
            reply_token = event['replyToken']
            message = event['message']['text']
            
            # 調用 Hugging Face 模型 API
            response = requests.post(HF_API_URL, json={'inputs': message})
            reply_text = response.json().get('generated_text', '發生錯誤')
            
            # 回傳訊息到 LINE
            reply_to_line(reply_token, reply_text)
    
    return jsonify(status=200)

def reply_to_line(reply_token, text):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    data = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}]
    }
    requests.post('https://api.line.me/v2/bot/message/reply', headers=headers, json=data)

if __name__ == "__main__":
    app.run(port=5000)
