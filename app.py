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

# 가격 히스토리 저장용 (차트용)
price_history = []

# Gemini AI 초기화
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")
if GENAI_API_KEY:
    try:
        genai.configure(api_key=GENAI_API_KEY)
        # 404 에러 방지를 위해 모델 경로를 더 명확히 지정하거나 안정적인 모델 사용
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        print(f"AI 초기화 오류: {e}")
        model = None
else:
    model = None

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
        
        result = {
            "binance": float(binance['price']),
            "upbit": float(upbit[0]['trade_price']),
            "bithumb": float(bithumb[0]['trade_price']),
            "usd_krw": fx['rates']['KRW']
        }
        
        # 히스토리 추가
        price_history.append({
            "time": time.strftime("%H:%M:%S"),
            "upbit": result["upbit"],
            "bithumb": result["bithumb"],
            "premium_up": ((result["upbit"] / (result["binance"] * result["usd_krw"])) - 1) * 100
        })
        if len(price_history) > 50: price_history.pop(0)
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/price-history")
async def get_price_history():
    return price_history

@app.get("/api/rules")
async def get_rules():
    try:
        if db:
            res = db.table("trading_rules").select("*").order("created_at", desc=True).limit(20).execute()
            return res.data
    except Exception as e:
        print(f"DB Error: {e}")
    return [{"name": "기본 김프 매매 (관찰 중)", "status": "수익률: +0.00%"}]

@app.post("/api/rules")
async def add_rule(rule: dict):
    if db:
        # source가 없으면 '수동'이 기본값
        source = rule.get('source', '사용자 추가')
        db.table("trading_rules").insert({
            "name": rule['name'], 
            "status": f"대기 중 (출처: {source})",
            "created_at": "now()"
        }).execute()
        return {"status": "success"}
    return {"status": "error", "message": "DB 미연결"}

@app.get("/api/ai-suggestion")
async def get_ai_suggestion():
    if not model:
        return {"suggestion": "제미나이 API 키가 설정되지 않았습니다."}
    
    # 실시간 데이터 수집
    market_data = monitor.get_combined_data()
    
    # 프롬프트 생성
    prompt = f"""
    당신은 전문 가상자산 트레이딩 AI입니다. 현재 시장 상황과 내 잔고를 분석해서 최적의 김치 프리미엄 전략을 한 문장으로 제안해 주세요.
    바이낸스 BTC: ${market_data['prices']['binance']:,}, 업비트 BTC: ₩{market_data['prices']['upbit']:,}, 환율: ₩{market_data['fx_rate']:,}
    현재 프리미엄: 업비트 {(((market_data['prices']['upbit'] / (market_data['prices']['binance'] * market_data['fx_rate'])) - 1) * 100):.2f}%
    
    형식: "[액션] 이유 (예상 수익: +N%)"
    """
    
    try:
        response = model.generate_content(prompt)
        return {"suggestion": response.text.strip()}
    except Exception as e:
        return {"suggestion": f"AI 분석 중 오류 발생: {str(e)}"}

@app.post("/api/extract-rule")
async def extract_rule(data: dict):
    if not model or not db:
        return {"status": "error", "message": "AI 키 또는 DB 미연결"}
    
    raw_text = data.get('text', '')
    if not raw_text: return {"status": "error", "message": "입력된 내용이 없습니다."}
    
    prompt = f"""
    아래 내용에서 '구체적인 가상자산 매매 규칙'을 추출해서 20자 이내로 요약해 주세요.
    내용: {raw_text}
    요약 결과:
    """
    
    try:
        response = model.generate_content(prompt)
        summarized_rule = response.text.strip()
        db.table("trading_rules").insert({"name": summarized_rule, "status": "대기 중 (AI 추출)", "created_at": "now()"}).execute()
        return {"status": "success", "extracted": summarized_rule}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/ai-chat")
async def ai_chat(data: dict):
    model_type = data.get('model_type', 'gemini')
    user_msg = data.get('message', '')
    
    # 실시간 데이터 및 자산 현황 수집 (학습 데이터 보강)
    market_data = monitor.get_combined_data()
    kimpi = ((market_data['prices']['upbit'] / (market_data['prices']['binance'] * market_data['fx_rate'])) - 1) * 100
    upbit_bal = api_handler.get_upbit_balance()
    mock_bal = await get_mock_wallet() # 모의투자 잔고도 포함
    
    system_prompt = f"""
    당신은 전 세계 상위 1% '알파 헌터(Alpha Hunter)' 트레이딩 매니저입니다.
    사용자에게 아주 '특별하고 남다른' 아이디어를 제공하는 것이 당신의 목표입니다.
    
    [당신의 특수 지식 (2025 최신)]
    1. RWA(실물자산) 코인 순환매: 블랙록 등 기관이 진입하는 RWA 섹터의 자금 흐름 분석.
    2. 고래(Whale) 이동 추적: 대형 지갑이 거래소로 입금될 때의 프리미엄 변동성 이용.
    3. 델타 중립(Delta Neutral): 해외 1배 숏 + 국내 매수로 가격 하락 리스크를 0으로 만들고 '김프+펀딩비'만 챙기기.
    4. 거래소 간 스테이블 코인 역프리미엄: USDT 테더의 거래소별 미세한 차이를 이용한 무위험 차익.

    현재 김프: {kimpi:.2f}% / 내 잔고: {upbit_bal} (Real)
    
    위의 특수 지식을 활용하여 지금 이 순간 가장 '남다른' 돈 되는 아이디어를 제안하세요.
    반드시 [RULE: 규칙명] 형식을 포함해야 자동 연동됩니다.
    """

    reply = ""
    try:
        if model_type == 'gemini' and model:
            response = model.generate_content(system_prompt + "\n사용자: " + user_msg)
            reply = response.text.strip()
        else:
            # Meta (Llama 3) 또는 GPT (OpenAI 호환 API 사용)
            # 렌더 환경변수에서 OPENROUTER_API_KEY 등을 가져와서 처리 가능하도록 구조만 추가
            api_key = os.getenv("EXTERNAL_AI_API_KEY") # 통합 키 사용 가정
            if api_key:
                # 여기에 OpenAI SDK 또는 requests로 멀티 모델 연동 가능
                reply = f"(알림: {model_type} 모델 연동 준비 중입니다. 현재는 제미나이로 응답합니다.)\n"
                response = model.generate_content(system_prompt + "\n사용자: " + user_msg)
                reply += response.text.strip()
            else:
                response = model.generate_content(system_prompt + "\n사용자: " + user_msg)
                reply = response.text.strip()
        
        # 규칙 자동 감지 및 저장 (기존 로직 유지)
        if "[RULE:" in reply and db:
            rule_part = reply.split("[RULE:")[1].split("]")[0].strip()
            db.table("trading_rules").insert({
                "name": f"[{model_type.upper()} 제안] {rule_part}",
                "status": "대기 중 (채팅 자동등록)",
                "created_at": "now()"
            }).execute()
            reply = reply.replace(f"[RULE: {rule_part}]", "").replace(f"[RULE:{rule_part}]", "") + f"\n\n✅ '{rule_part}' 규칙이 {model_type.upper()}를 통해 등록되었습니다!"

        return {"reply": reply}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# AI의 '생각' 기록용 (UI 표시용)
ai_thought_log = []

async def autonomous_rule_generation():
    if not model or not db: return

    try:
        # 1. 과거 규칙들을 더 많이 불러와서 '장기 기억'으로 사용 (학습 범위 확대)
        existing_rules = []
        if db:
            res = db.table("trading_rules").select("name").limit(15).execute()
            existing_rules = [r['name'] for r in res.data]

        market_data = monitor.get_combined_data()
        kimpi = ((market_data['prices']['upbit'] / (market_data['prices']['binance'] * market_data['fx_rate'])) - 1) * 100
        upbit_bal = api_handler.get_upbit_balance()
        mock_bal = await get_mock_wallet()

        # 2. 자율 진화 프롬프트 (자산 기반 맞춤형 학습)
        prompt = f"""
        당신은 '2주간의 시장 흐름을 학습 중인' 트레이딩 전문가입니다. 
        현재 김프: {kimpi:.2f}%
        보유 자산: {upbit_bal} (실전), {mock_bal['krw']}원 (모의)
        과거 15개 규칙 기록: {existing_rules}
        
        [학습 지침]
        - 위 기록들을 2주간의 '빅데이터'로 간주하고, 중복되지 않으면서도 수익률이 점진적으로 개선되는 '숙성된' 규칙 1개를 제안하세요.
        - 시장의 변동성을 고려하여 장기적으로 안정적인 수익을 낼 수 있는 전략을 우선시합니다.
        
        형식: {{"name": "2주 숙성 전략", "thought": "과거 {len(existing_rules)}개 기록을 분석하여 개선한 포인트"}}
        """
        
        response = model.generate_content(prompt)
        text = response.text.replace('```json', '').replace('```', '').strip()
        result = json.loads(text)
        
        # 3. DB 저장 및 로그 추가
        rule_name = f"[자율진화] {result['name']}"
        db.table("trading_rules").insert({
            "name": rule_name,
            "status": "AI 자율 학습 가동 중",
            "created_at": "now()"
        }).execute()
        
        log_msg = f"🤖 **AI 생각:** {result['thought']}\n➡️ 신규 규칙 '{result['name']}'을 스스로 학습하여 등록했습니다."
        ai_thought_log.append({"time": time.strftime("%H:%M:%S"), "msg": log_msg})
        if len(ai_thought_log) > 10: ai_thought_log.pop(0)

        print(f"AI 자율 진화 완료: {rule_name}")
    except Exception as e:
        print(f"AI 자율 진화 오류: {str(e)}")

@app.get("/api/ai-thoughts")
async def get_ai_thoughts():
    return ai_thought_log

async def autonomous_loop():
    # 서버 시작 직후 바로 한 번 실행하도록 지연 시간 단축
    await asyncio.sleep(5) 
    while True:
        try:
            await autonomous_rule_generation()
        except Exception as e:
            print(f"Loop Error: {e}")
        await asyncio.sleep(3600) # 1시간마다 실행

import asyncio
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(autonomous_loop())

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
    
    # 빗썸 응답 구조 표준화
    bithumb_balances = []
    if isinstance(bithumb_raw, list):
        bithumb_balances = bithumb_raw
    elif isinstance(bithumb_raw, dict) and 'data' in bithumb_raw:
        for curr, val in bithumb_raw['data'].items():
            if curr != 'total_krw':
                bithumb_balances.append({"currency": curr, "balance": val})

    # API 키가 연동되지 않았을 때의 메시지 처리 (필요시)
    messages = []
    if not upbit_raw and (not os.getenv("UPBIT_ACCESS_KEY")):
        messages.append("업비트 API 키가 설정되지 않았습니다.")
    if not bithumb_balances and (not os.getenv("BITHUMB_ACCESS_KEY")):
        messages.append("빗썸 API 키가 설정되지 않았습니다.")

    return {
        "upbit": upbit_raw,
        "bithumb": bithumb_balances,
        "messages": messages
    }

@app.get("/", response_class=HTMLResponse)
async def read_index(token: str = Depends(authenticate)):
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/manual", response_class=HTMLResponse)
async def read_manual():
    with open("manual.html", "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
