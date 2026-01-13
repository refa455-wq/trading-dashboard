from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import os
import time
import jwt
import uuid
import requests
import json
import google.generativeai as genai
from dotenv import load_dotenv
from monitor import KimchiPremiumMonitor

from supabase import create_client, Client

# Supabase 초기화
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") # 관리자 권한 키 사용
db: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

monitor = KimchiPremiumMonitor()
load_dotenv()

# 보안 설정 (단순 비밀번호)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "1234") # 기본값은 1234
security = HTTPBasic()

def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

app = FastAPI()

class ExchangeAPI:
    def __init__(self):
        self.upbit_access = os.getenv("UPBIT_ACCESS_KEY")
        self.upbit_secret = os.getenv("UPBIT_SECRET_KEY")
        self.bithumb_access = os.getenv("BITHUMB_ACCESS_KEY")
        self.bithumb_secret = os.getenv("BITHUMB_SECRET_KEY")

    def get_upbit_balance(self):
        if not self.upbit_access or not self.upbit_secret: return []
        payload = {'access_key': self.upbit_access, 'nonce': str(uuid.uuid4())}
        token = jwt.encode(payload, self.upbit_secret)
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get("https://api.upbit.com/v1/accounts", headers=headers)
        return res.json() if res.status_code == 200 else []

    def get_bithumb_balance(self):
        if not self.bithumb_access or not self.bithumb_secret: return []
        payload = {'access_key': self.bithumb_access, 'nonce': str(uuid.uuid4()), 'timestamp': int(time.time() * 1000)}
        token = jwt.encode(payload, self.bithumb_secret, algorithm='HS256')
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get("https://api.bithumb.com/v1/accounts", headers=headers)
        return res.json() if res.status_code == 200 else []

api_handler = ExchangeAPI()

@app.get("/api/market-data")
async def get_market_data():
    try:
        # Binance Price (BTC)
        binance = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT").json()
        # Upbit Price (BTC)
        upbit = requests.get("https://api.upbit.com/v1/ticker?markets=KRW-BTC").json()
        # Bithumb Price (BTC)
        bithumb = requests.get("https://api.bithumb.com/v1/ticker?markets=KRW-BTC").json()
        # Exchange Rate
        fx = requests.get("https://api.exchangerate-api.com/v4/latest/USD").json()
        
        return {
            "binance": float(binance['price']),
            "upbit": float(upbit[0]['trade_price']),
            "bithumb": float(bithumb[0]['trade_price']),
            "usd_krw": fx['rates']['KRW']
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/rules")
async def get_rules():
    if db:
        res = db.table("trading_rules").select("*").order("created_at").execute()
        return res.data
    return [{"name": "기본 김프 매매 (DB 미연결)", "status": "수익률: +0.00%"}]

@app.post("/api/rules")
async def add_rule(rule: dict):
    if db:
        db.table("trading_rules").insert({"name": rule['name'], "status": "대기 중..."}).execute()
        return {"status": "success"}
    return {"status": "error", "message": "DB 미연결"}

@app.get("/api/ai-suggestion")
async def get_ai_suggestion():
    if not model:
        return {"suggestion": "제미나이 API 키가 설정되지 않았습니다."}
    
    # 실시간 데이터 수집
    market_data = monitor.get_combined_data()
    upbit_bal = api_handler.get_upbit_balance()
    bithumb_bal = api_handler.get_bithumb_balance()
    
    # 프롬프트 생성 (더 구체적으로 변경)
    prompt = f"""
    당신은 전문 가상자산 트레이딩 AI입니다. 현재 시장 상황과 내 잔고를 분석해서 최적의 김치 프리미엄 전략을 한국어로 제안해 주세요.
    
    [통계]
    - 바이낸스 BTC: ${market_data['prices']['binance']:,}
    - 업비트 BTC: ₩{market_data['prices']['upbit']:,}
    - 빗썸 BTC: ₩{market_data['prices']['bithumb']:,}
    - 환율: ₩{market_data['fx_rate']:,}
    - 현재 프리미엄: 업비트 {(((market_data['prices']['upbit'] / (market_data['prices']['binance'] * market_data['fx_rate'])) - 1) * 100):.2f}%, 빗썸 {(((market_data['prices']['bithumb'] / (market_data['prices']['binance'] * market_data['fx_rate'])) - 1) * 100):.2f}%
    
    한 문장으로 아주 구체적으로 무엇을 살지 팔지 제안하세요.
    """
    
    try:
        response = model.generate_content(prompt)
        return {"suggestion": response.text.strip()}
    except Exception as e:
        return {"suggestion": f"AI 분석 중 오류 발생: {str(e)}"}

@app.get("/api/mock-wallet")
async def get_mock_wallet():
    if db:
        res = db.table("mock_wallet").select("*").eq("id", 1).maybe_single().execute()
        if res.data:
            return res.data
        # 데이터가 없으면 초기화
        initial = {"id": 1, "krw": 10000000, "assets": {}}
        db.table("mock_wallet").insert(initial).execute()
        return initial
    return {"krw": 0, "assets": {}, "message": "DB 미연결"}

@app.post("/api/mock-trade")
async def mock_trade(order: dict):
    if not db: return {"status": "error", "message": "DB 미연결"}
    
    res = db.table("mock_wallet").select("*").eq("id", 1).single().execute()
    wallet = res.data
    
    market_data = monitor.get_combined_data()
    current_price = market_data['prices']['upbit']
    
    if order['side'] == 'buy':
        if wallet['krw'] < order['amount_krw']:
            return {"status": "error", "message": "잔액 부족"}
        coin_amount = order['amount_krw'] / current_price
        wallet['krw'] -= order['amount_krw']
        wallet['assets'][order['symbol']] = wallet['assets'].get(order['symbol'], 0) + coin_amount
    else: # sell
        coin_amount = wallet['assets'].get(order['symbol'], 0)
        if coin_amount <= 0: return {"status": "error", "message": "보유 수량 부족"}
        wallet['krw'] += coin_amount * current_price
        wallet['assets'][order['symbol']] = 0

    db.table("mock_wallet").update(wallet).eq("id", 1).execute()
    return {"status": "success", "wallet": wallet}

@app.get("/api/balances")
async def get_balances():
    upbit_raw = api_handler.get_upbit_balance()
    bithumb_raw = api_handler.get_bithumb_balance()
    
    # 빗썸 응답 구조 표준화 (업비트와 유사하게)
    bithumb_balances = []
    if isinstance(bithumb_raw, list): # 신규 API v2.1 기준
        bithumb_balances = bithumb_raw
    elif isinstance(bithumb_raw, dict) and 'data' in bithumb_raw: # 구 API v2.0 기준 대비 안전장치
        for curr, val in bithumb_raw['data'].items():
            if curr != 'total_krw':
                bithumb_balances.append({"currency": curr, "balance": val})

    return {
        "upbit": upbit_raw,
        "bithumb": bithumb_balances
    }

@app.get("/", response_class=HTMLResponse)
async def read_index(token: str = Depends(authenticate)):
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
