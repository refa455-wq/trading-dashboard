import os
import json
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_KEY")
supabase: Client = create_client(url, key)

def setup_database():
    print("=== 슈파베이스 데이터베이스 자동 구축 시작 ===")
    
    # 1. 매매 규칙(rules) 데이터 이관
    if os.path.exists("rules.json"):
        with open("rules.json", "r", encoding="utf-8") as f:
            rules = json.load(f)
            
        print(f"매매 규칙 {len(rules)}개 발견. 클라우드로 이관 중...")
        for rule in rules:
            try:
                # 테이블이 없을 경우를 대비해 RPC 대신 직접 삽입 시도 (PostgREST 자동 생성 활용)
                supabase.table("trading_rules").upsert({
                    "name": rule['name'],
                    "description": rule.get('description', ''),
                    "status": rule.get('status', '대기 중...')
                }).execute()
            except Exception as e:
                print(f"규칙 이관 중 알림: {e} (테이블이 아직 없거나 설정이 필요할 수 있습니다)")

    # 2. 가상 지갑(wallet) 데이터 이관
    if os.path.exists("wallet.json"):
        with open("wallet.json", "r", encoding="utf-8") as f:
            wallet = json.load(f)
            
        print("가상 지갑 데이터 이관 중...")
        try:
            supabase.table("mock_wallet").upsert({
                "id": 1, # 단일 지갑
                "krw": wallet.get("krw", 10000000),
                "assets": json.dumps(wallet.get("assets", {}))
            }).execute()
        except Exception as e:
            print(f"지갑 이관 중 알림: {e}")

    print("=== 구축 완료! 이제 도메인 서버가 이 데이터를 사용합니다. ===")

if __name__ == "__main__":
    setup_database()
