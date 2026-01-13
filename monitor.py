import os
import time
import requests
import json
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

class KimchiPremiumMonitor:
    def __init__(self):
        self.upbit_url = "https://api.upbit.com/v1/ticker"
        self.bithumb_url = "https://api.bithumb.com/v1/ticker"
        self.binance_url = "https://api.binance.com/api/v3/ticker/price"
        self.fx_url = "https://api.exchangerate-api.com/v4/latest/USD" # 무료 환율 API 예시

    def get_exchange_rate(self):
        """달러 환율 가져오기"""
        try:
            response = requests.get(self.fx_url)
            data = response.json()
            return data['rates']['KRW']
        except Exception as e:
            print(f"환율 조회 실패: {e}")
            return 1350.0  # 기본값

    def get_binance_price(self, symbol="BTCUSDT"):
        """바이낸스 현재가 조회"""
        try:
            response = requests.get(f"{self.binance_url}?symbol={symbol}")
            return float(response.json()['price'])
        except Exception as e:
            print(f"바이낸스 조회 실패: {e}")
            return 0.0

    def get_upbit_price(self, symbol="KRW-BTC"):
        """업비트 현재가 조회"""
        try:
            response = requests.get(f"{self.upbit_url}?markets={symbol}")
            return float(response.json()[0]['trade_price'])
        except Exception as e:
            print(f"업비트 조회 실패: {e}")
            return 0.0

    def get_bithumb_price(self, symbol="KRW-BTC"):
        """빗썸 현재가 조회"""
        try:
            response = requests.get(f"{self.bithumb_url}?markets={symbol}")
            return float(response.json()[0]['trade_price'])
        except Exception as e:
            print(f"빗썸 조회 실패: {e}")
            return 0.0

    def calculate_premium(self, local_price, binance_price, exchange_rate):
        """김치 프리미엄 계산"""
        if binance_price == 0 or exchange_rate == 0:
            return 0.0
        foreign_price_krw = binance_price * exchange_rate
        premium = ((local_price / foreign_price_krw) - 1) * 100
        return premium

    def get_combined_data(self, btc_symbol="KRW-BTC"):
        """모든 시장 데이터를 한 번에 수집"""
        usd_krw = self.get_exchange_rate()
        binance_p = self.get_binance_price("BTCUSDT")
        upbit_p = self.get_upbit_price(btc_symbol)
        bithumb_p = self.get_bithumb_price(btc_symbol)
        
        return {
            "prices": {
                "binance": binance_p,
                "upbit": upbit_p,
                "bithumb": bithumb_p
            },
            "fx_rate": usd_krw,
            "premiums": {
                "upbit": self.calculate_premium(upbit_p, binance_p, usd_krw),
                "bithumb": self.calculate_premium(bithumb_p, binance_p, usd_krw)
            }
        }

    def run(self, symbol_pair=("BTCUSDT", "KRW-BTC")):
        print(f"=== {symbol_pair[1]} 김치 프리미엄 모니터링 시작 ===")
        print("시간 | 업비트 김프 | 빗썸 김프 | 업비트-빗썸 차이")
        print("-" * 50)
        
        while True:
            usd_krw = self.get_exchange_rate()
            binance_p = self.get_binance_price(symbol_pair[0])
            upbit_p = self.get_upbit_price(symbol_pair[1])
            bithumb_p = self.get_bithumb_price(symbol_pair[1])
            
            upbit_prem = self.calculate_premium(upbit_p, binance_p, usd_krw)
            bithumb_prem = self.calculate_premium(bithumb_p, binance_p, usd_krw)
            gap = upbit_prem - bithumb_prem
            
            curr_time = time.strftime("%H:%M:%S", time.localtime())
            
            print(f"[{curr_time}] {upbit_prem:6.2f}% | {bithumb_prem:6.2f}% | {gap:6.2f}%")
            
            time.sleep(5)  # 5초 간격

if __name__ == "__main__":
    monitor = KimchiPremiumMonitor()
    monitor.run()
