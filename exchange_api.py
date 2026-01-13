import os
import time
import jwt
import uuid
import hashlib
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

class ExchangeAPI:
    def __init__(self):
        # 업비트 키
        self.upbit_access = os.getenv("UPBIT_ACCESS_KEY")
        self.upbit_secret = os.getenv("UPBIT_SECRET_KEY")
        
        # 빗썸 키
        self.bithumb_access = os.getenv("BITHUMB_ACCESS_KEY")
        self.bithumb_secret = os.getenv("BITHUMB_SECRET_KEY")

    def get_upbit_balance(self):
        """업비트 잔고 조회 (Private API)"""
        if not self.upbit_access or not self.upbit_secret:
            return "업비트 키가 설정되지 않았습니다."
            
        payload = {
            'access_key': self.upbit_access,
            'nonce': str(uuid.uuid4()),
        }
        jwt_token = jwt.encode(payload, self.upbit_secret)
        headers = {"Authorization": f"Bearer {jwt_token}"}
        
        res = requests.get("https://api.upbit.com/v1/accounts", headers=headers)
        return res.json()

    def get_bithumb_balance(self):
        """빗썸 잔고 조회 (Private API - JWT 방식)"""
        if not self.bithumb_access or not self.bithumb_secret:
            return "빗썸 키가 설정되지 않았습니다."
            
        payload = {
            'access_key': self.bithumb_access,
            'nonce': str(uuid.uuid4()),
            'timestamp': int(time.time() * 1000)
        }
        # 빗썸은 HS256 알고리즘 사용
        jwt_token = jwt.encode(payload, self.bithumb_secret, algorithm='HS256')
        headers = {"Authorization": f"Bearer {jwt_token}"}
        
        res = requests.get("https://api.bithumb.com/v1/accounts", headers=headers)
        return res.json()

# 테스트 실행부
if __name__ == "__main__":
    api = ExchangeAPI()
    print("--- 업비트 잔고 ---")
    print(api.get_upbit_balance())
    print("\n--- 빗썸 잔고 ---")
    print(api.get_bithumb_balance())
