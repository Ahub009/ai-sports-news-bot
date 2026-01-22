import os
import json
import time
import requests
import feedparser
from datetime import datetime
import re
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL')

# RSS 피드 검색어 설정 (구글 뉴스 RSS 사용)
# URL 인코딩은 feedparser나 requests가 일부 처리하지만, 기본적으로 검색어 조합
RSS_QUERIES = [
    "site:kr.acrofan.com OR site:aitimes.com OR site:ciokorea.com AI 산업 비즈니스", # AI 전문지 위주
    "피지컬 AI 로봇",
    "대한민국 스포츠 산업 비즈니스",
    "축구 데이터 분석 기술 스타트업",
    "스포츠 테크 투자"
]

def get_google_news_rss(query):
    """구글 뉴스 RSS에서 검색어로 뉴스 가져오기"""
    encoded_query = urllib.parse.quote(query)
    base_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    return base_url

def fetch_rss_items():
    """여러 키워드의 RSS를 수집하여 통합 리스트 반환"""
    all_items = []
    seen_links = set()
    
    print("📡 뉴스 데이터 수집 중...")
    
    for query in RSS_QUERIES:
        url = get_google_news_rss(query)
        feed = feedparser.parse(url)
        
        for entry in feed.entries[:10]: # 키워드 당 최신 10개로 증가 (Top 10 선별을 위해 후보군 확보)
            if entry.link not in seen_links:
                all_items.append({
                    "title": entry.title,
                    "link": entry.link,
                    "published": entry.get("published", ""),
                    "snippet": entry.get("description", "")[:200] # 너무 길면 자름
                })
                seen_links.add(entry.link)
    
    print(f"✅ 총 {len(all_items)}개의 뉴스 후보 수집 완료")
    return all_items

def analyze_and_filter_news(news_items):
    """Gemini를 사용하여 뉴스 필터링 및 요약"""
    if not news_items:
        return []

    print("🧠 Gemini가 뉴스 분석 및 선별 중...")
    
    # 모델 선택 (기존 로직 활용)
    model_name = "gemini-1.5-flash" # 가성비 모델 고정
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    
    # 프롬프트 구성
    news_text = json.dumps(news_items, ensure_ascii=False)
    
    prompt = f"""
    너는 '비주얼 AI 기술'과 '축구'를 접목한 스타트업의 전략 기획 담당자야.
    아래 제공된 뉴스 리스트(JSON)를 보고, 우리 사업에 도움이 될 만한 중요한 뉴스를 **최대 10개** 선별해줘.

    [핵심 기준]:
    1. **경기 결과(스코어, 승패), 단순 선수 이적, 연예 가십 조항은 무조건 제외해.** (가장 중요)
    2. AI 기술 트렌드, 피지컬 AI, 스포츠 산업 동향, 스포츠 테크 투자, 축구 비즈니스 인사이트가 담긴 기사를 우선해.
    3. 만약 적합한 기사가 없다면 개수를 줄여도 좋아. 억지로 채우지 마.
    4. **해외 뉴스(영어 등)는 반드시 한국어로 자연스럽게 번역해서 요약해.**

    [출력 양식]:
    결과는 반드시 순수한 JSON 배열(Array) 형식이어야 해.
    각 항목은 다음 키를 가져야 함:
    - 'title': 기사 제목 (핵심만 요약해서 30자 이내로 깔끔하게 수정)
    - 'summary': 기사 내용 요약 (우리 스타트업 입장에서 왜 중요한지, 핵심 인사이트 위주로 2~3문장)
    - 'original_link': 제공된 뉴스 링크
    
    [뉴스 리스트]:
    {news_text}
    """
    
    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            text = response.json().get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '[]')
            # 마크다운 제거
            clean_text = re.sub(r"```json|```", "", text).strip()
            # 대괄호 추출
            match = re.search(r'\[.*\]', clean_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            else:
                return json.loads(clean_text)
    except Exception as e:
        print(f"Gemini API 오류: {e}")
        return []
        
    return []

def send_discord_report(news_list):
    if not DISCORD_WEBHOOK_URL:
        print("디스코드 웹훅 URL 없음")
        return
        
    if not news_list:
        print("전송할 뉴스가 없습니다.")
        return

    # 오늘 날짜
    today = datetime.now().strftime("%Y년 %m월 %d일")
    
    embed = {
        "title": f"📰 {today} AI & 스포츠 테크 리포트",
        "description": "스타트업을 위한 오늘의 핵심 산업 뉴스 요약입니다.",
        "color": 0x00ff00, # Green
        "fields": [],
        "footer": {
            "text": "Auto-curated by Gemini Team Agent",
        },
        "url": "https://news.google.com"
    }
    
    for news in news_list:
        embed["fields"].append({
            "name": f"🔹 {news['title']}",
            "value": f"{news['summary']}\n[🔗 기사 전문 보기]({news['original_link']})",
            "inline": False
        })
        
    payload = {"embeds": [embed]}
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
        print("✅ 디스코드 리포트 전송 완료")
    except Exception as e:
        print(f"디스코드 전송 실패: {e}")

if __name__ == "__main__":
    items = fetch_rss_items()
    if items:
        # 2단계: AI 선별
        selected_news = analyze_and_filter_news(items)
        if selected_news:
             # 3단계: 전송
            print(f"🔍 선별된 뉴스 {len(selected_news)}건 전송 시도")
            send_discord_report(selected_news)
        else:
            print("🤔 AI가 판단하기에 중요한 뉴스가 없습니다.")
    else:
        print("수집된 뉴스가 없습니다.")
