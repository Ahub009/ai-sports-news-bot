import os
import json
import time
import requests
import feedparser
from datetime import datetime
import re
import urllib.parse
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL')

# 1. 해외 뉴스 (구글 뉴스 RSS - 영어/Global)
RSS_QUERIES_GLOBAL = [
    "Artificial Intelligence business trends",
    "Generative AI computer vision startup",
    "Football analytics technology",
    "Sports revenue model innovation",
    "Physical AI robotics market"
]

# 2. 국내 정책 뉴스 (구글 뉴스 RSS - 한국어/Domestic Policy)
# 네이버 뉴스 스크래핑으로는 '정책'만 콕 집어내기 어려워서 키워드 기반 RSS 사용
RSS_QUERIES_KR_POLICY = [
    "과학기술정보통신부 AI 산업 육성",
    "범정부 AI 국가전략",
    "문화체육관광부 스포츠산업 지원",
    "스포츠 테크 투자 펀드 정책",
    "데이터 산업 진흥 로드맵",
    "AI 스타트업 규제 샌드박스"
]

# 3. 국내 일반 뉴스 (네이버 뉴스 섹션 스크래핑)
NAVER_SECTIONS = [
    {"id": "105", "name": "IT/과학"},
    {"id": "101", "name": "경제"}
]

def get_google_news_rss_url(query, region='US'):
    """구글 뉴스 RSS URL 생성 (지역/언어 설정 가능)"""
    encoded_query = urllib.parse.quote(query)
    
    if region == 'KR':
        # 한국어/한국
        base_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"
    else:
        # 영어/미국 (기본)
        base_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
        
    return base_url

def fetch_google_rss_items(queries, region='US', source_label="Google News"):
    """구글 RSS 기반 뉴스 수집 (공통 함수)"""
    items = []
    seen_links = set()
    print(f"📡 [{source_label}] RSS 수집 중... (Region: {region})")
    
    for query in queries:
        url = get_google_news_rss_url(query, region)
        try:
            feed = feedparser.parse(url)
            # 키워드별 상위 3~5개만 가져와서 후보군 구성
            limit = 5 if region == 'US' else 3 
            for entry in feed.entries[:limit]:
                if entry.link not in seen_links:
                    items.append({
                        "title": entry.title,
                        "link": entry.link,
                        "source": source_label,
                        "snippet": entry.get("description", "")[:200]
                    })
                    seen_links.add(entry.link)
        except Exception as e:
            print(f"Error fetching RSS for {query}: {e}")
            
    return items

def fetch_naver_news():
    """네이버 뉴스 섹션 크롤링 (IT/과학, 경제)"""
    items = []
    seen_links = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    print("📡 [국내] 네이버 뉴스(IT/경제) 수집 중...")
    
    for section in NAVER_SECTIONS:
        url = f"https://news.naver.com/section/{section['id']}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            links = soup.find_all("a", href=True)
            
            count = 0
            for link in links:
                href = link['href']
                title = link.get_text(strip=True)
                
                if "/mnews/article/" in href and title and len(title) > 10:
                    if href not in seen_links:
                        items.append({
                            "title": title,
                            "link": href,
                            "source": f"Naver News ({section['name']})",
                            "snippet": "" 
                        })
                        seen_links.add(href)
                        count += 1
                        if count >= 8: # 섹션당 개수 조절
                            break
        except Exception as e:
            print(f"Naver Fetch Error ({section['name']}): {e}")
            
    return items

def analyze_and_filter_news(news_items):
    if not news_items:
        return []

    print(f"🧠 총 {len(news_items)}개의 후보 기사 분석 및 선별 중...")
    
    model_name = "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    
    # 토큰 절약을 위한 간소화
    simplified_items = []
    for item in news_items:
        simplified_items.append({
            "t": item['title'],
            "l": item['link'],
            "s": item['source']
        })
        
    news_text = json.dumps(simplified_items, ensure_ascii=False)
    
    prompt = f"""
    너는 '비주얼 AI(Computer Vision) & 스포츠 테크' 스타트업의 CEO야.
    제공된 뉴스 후보군(JSON)에서 우리 사업과 관련된 **핵심 뉴스**와 **중요 정부 정책**을 큐레이션해줘.

    [후보군 데이터]:
    {news_text}

    [선별 기준 (우선순위 순)]:
    1. **정부 정책**: 대한민국 과학기술정보통신부(AI)나 문화체육관광부(스포츠)의 지원 사업, 규제 변화, 펀드 조성 등 스타트업에 직접적 영향을 주는 정책 뉴스 (발견 즉시 포함).
    2. **기술 트렌드**: AI, 피지컬 컴퓨팅, 로봇, 비전 기술의 새로운 돌파구나 적용 사례.
    3. **시장 동향**: 스포츠 산업의 디지털 전환, 투자 소식.
    4. **제외 대상**: 단순 경기 스코어, 연예인 가십, 정치 싸움, 너무 일반적인 주가 변동.

    [작성 지침]:
    - **수량**: 7~10개 내외. (정책 뉴스는 가급적 포함)
    - **언어**: 해외 뉴스는 반드시 **한국어로 번역**해서 요약.
    - **요약문**: "정부의 AI 예산이 증액되어 우리 R&D 과제 지원이 유리해질 전망입니다" 처럼 스타트업 입장에서 서술.

    [출력 포맷 - JSON Array Only]:
    [
      {{
        "title": "기사 제목",
        "summary": "핵심 인사이트 (한국어)",
        "original_link": "링크",
        "source": "출처 표기 (예: [정책], [해외], [네이버])"
      }}
    ]
    """
    
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            text = response.json().get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '[]')
            clean_text = re.sub(r"```json|```", "", text).strip()
            # JSON 파싱 시도 (대괄호 찾기)
            match = re.search(r'\[.*\]', clean_text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return json.loads(clean_text)
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return []
    
    return []

def send_discord_report(news_list):
    if not DISCORD_WEBHOOK_URL:
        print("디스코드 웹훅 URL 없음")
        return
    if not news_list:
        print("전송할 뉴스가 없음")
        return

    today = datetime.now().strftime("%Y년 %m월 %d일")
    
    embed = {
        "title": f"📰 {today} AI·스포츠 스타트업 데일리 브리핑",
        "description": "국내외 산업 동향 및 주요 정부 정책 모니터링",
        "color": 0x00ff00,
        "fields": [],
        "footer": {
            "text": "Powered by Gemini Agent",
        }
    }
    
    for news in news_list:
        # 소스에 따라 아이콘이나 태그를 다르게 할 수도 있음
        source_display = news.get('source', '뉴스')
        # AI가 source를 덮어쓰지 않았다면 원본 source 사용
        if '[' not in source_display and 'Google' in source_display and 'KR' in source_display:
             source_display = "[정책]"
        elif '[' not in source_display and 'Google' in source_display:
             source_display = "[해외]"
        elif '[' not in source_display and 'Naver' in source_display:
             source_display = "[국내]"
             
        embed["fields"].append({
            "name": f"{source_display} {news['title']}",
            "value": f"{news['summary']}\n[🔗 기사 읽기]({news['original_link']})",
            "inline": False
        })
        
    payload = {"embeds": [embed]}
    
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
        print("✅ 디스코드 전송 완료")
    except Exception as e:
        print(f"디스코드 전송 실패: {e}")

if __name__ == "__main__":
    # 1. 수집
    # 1-1. 해외 (영어)
    overseas_items = fetch_google_rss_items(RSS_QUERIES_GLOBAL, region='US', source_label="[해외]")
    
    # 1-2. 국내 정책 (한국어 키워드 검색)
    policy_items = fetch_google_rss_items(RSS_QUERIES_KR_POLICY, region='KR', source_label="[정책]")
    
    # 1-3. 국내 일반 (네이버 섹션)
    domestic_items = fetch_naver_news()
    
    all_items = overseas_items + policy_items + domestic_items
    
    if all_items:
        # 2. 분석
        selected = analyze_and_filter_news(all_items)
        if selected:
            print(f"👉 최종 선별된 뉴스: {len(selected)}건")
            send_discord_report(selected)
        else:
            print("🤔 조건에 맞는 뉴스가 없어 전송하지 않았습니다.")
    else:
        print("❌ 수집된 뉴스가 없습니다.")
