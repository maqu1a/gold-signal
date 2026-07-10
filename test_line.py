# -*- coding: utf-8 -*-
import os, urllib.request, urllib.parse, json

LINE_TOKEN = os.environ.get("LINE_TOKEN", "")

# --- LINE Messaging API テスト（パターンB） ---
def test_messaging_api(text):
    print("LINE Messaging APIの接続テストを開始します...")
    url = "[https://api.line.me/v2/bot/message/broadcast](https://api.line.me/v2/bot/message/broadcast)"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"messages": [{"type": "text", "text": text}]}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=10)
        print("🟢 Messaging API 送信成功！スマホを確認してください。")
    except Exception as e:
        print("❌ Messaging API 送信失敗:", e)

if __name__ == "__main__":
    if not LINE_TOKEN:
        print("⚠️ エラー: LINE_TOKENが環境変数に設定されていません。")
    else:
        # テストメッセージ
        test_msg = "これはGitHub ActionsからのLINEボット疎通テストメッセージです。"
        
        # ※お使いのトークンの種類に合わせて、どちらか一方のコメントアウトを外して実行してください
        test_notify(test_msg)        # LINE Notify の場合
        # test_messaging_api(test_msg) # Messaging API (公式アカウント) の場合
