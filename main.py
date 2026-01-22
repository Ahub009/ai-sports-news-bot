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

# 1. 해외 뉴스 (구글 뉴스 RSS - 다국어/글로벌)
# 영어 쿼리지만, 각국 구글 뉴스 에디션에 던지면 해당 국가의 관련 기사(자국어 포함)가 나옴
RSS_QUERIES_GLOBAL = [
    "Artificial Intelligence business", # AI 비즈니스
    "Sports technology startups",       # 스포츠 테크
    "Football analytics",               # 축구 분석
    "Generative AI trends"              # 생성형 AI
]

# 2. 국내 정책 뉴스 (구글 뉴스 RSS - 한국어/Domestic Policy)
RSS_QUERIES_KR_POLICY = [
    "과학기술정보통신부 AI 산업 육성",
    "범정부 AI 국가전략",
    "문화체육관광부 스포츠산업 지원",
    "스포츠 테크 투자 펀드 정책",
    "데이터 산업 진흥 로드맵"
]

# 3. 국내 일반 뉴스 (네이버 뉴스 섹션 스크래핑)
NAVER_SECTIONS = [
    {"id": "105", "name": "IT/과학"},
    {"id": "101", "name": "경제"}
]

# 국가별 구글 뉴스 설정
REGION_CONFIGS = {
    'US': {'gl': 'US', 'hl': 'en-US', 'ceid': 'US:en', 'name': '미국/글로벌'},
    'GB': {'gl': 'GB', 'hl': 'en-GB', 'ceid': 'GB:en', 'name': '영국/유럽'},
    'JP': {'gl': 'JP', 'hl': 'ja',    'ceid': 'JP:ja', 'name': '일본'},
    'HK': {'gl': 'HK', 'hl': 'en-HK', 'ceid': 'HK:en', 'name': '중국/아시아'} # 중국 본토 대용
}

def get_google_news_rss_url(query, region_code='US'):
    """구글 뉴스 RSS URL 생성 (국가별 설정 적용)"""
    encoded_query = urllib.parse.quote(query)
    config = REGION_CONFIGS.get(region_code, REGION_CONFIGS['US'])
    
    base_url = f"https://news.google.com/rss/search?q={encoded_query}&hl={config['hl']}&gl={config['gl']}&ceid={config['ceid']}"
    return base_url, config['name']

def fetch_google_rss_items(queries, target_regions=['US'], source_label_prefix="[해외]"):
    """구글 RSS 기반 뉴스 수집 (다중 국가 지원)"""
    items = []
    seen_links = set()
    
    for region in target_regions:
        print(f"📡 {source_label_prefix} 뉴스 수집 중... (Region: {region})")
        for query in queries:
            url, region_name = get_google_news_rss_url(query, region)
            try:
                feed = feedparser.parse(url)
                # 키워드별 상위 개수 조절 (미국 비중 확대)
                limit = 8 if region == 'US' else 3 
                for entry in feed.entries[:limit]:
                    if entry.link not in seen_links:
                        items.append({
                            "title": entry.title,
                            "link": entry.link,
                            "source": f"{source_label_prefix} {region_name} (Google)",
                            "snippet": entry.get("description", "")[:200]
                        })
                        seen_links.add(entry.link)
            except Exception as e:
                print(f"Error fetching RSS for {query} in {region}: {e}")
            
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

def get_usable_model_name():
    """API에 직접 물어봐서 진짜로 사용 가능한 모델 이름을 가져옵니다."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"⚠️ 모델 목록 조회 실패: {response.text}")
            return None
            
        data = response.json()
        if 'models' not in data:
            print("⚠️ 모델 목록이 비어있습니다.")
            return None

        # 사용 가능한 모델 찾기
        candidates = []
        for model in data['models']:
            name = model['name'].replace('models/', '')
            methods = model.get('supportedGenerationMethods', [])
            
            if 'generateContent' in methods:
                candidates.append(name)
        
        print(f"📋 내 키로 접근 가능한 모델들: {candidates}")
        
        preferred = [
            'gemini-1.5-flash',
            'gemini-1.5-flash-latest',
            'gemini-1.5-pro',
            'gemini-1.0-pro',
            'gemini-pro'
        ]
        
        for p in preferred:
            if p in candidates:
                return p
                
        # 차선책
        for c in candidates:
            if 'gemini' in c and 'vision' not in c:
                return c
                
        if candidates:
            return candidates[0]
            
        return None

    except Exception as e:
        print(f"⚠️ 모델 검색 중 오류: {e}")
        return None

def analyze_and_filter_news(news_items):
    if not news_items:
        return []

    print(f"🧠 총 {len(news_items)}개의 후보 기사 분석 및 선별 중...")
    
    # 동적으로 모델 찾기
    model_name = get_usable_model_name()
    if not model_name:
        print("❌ 사용 가능한 모델을 찾지 못해 기본값(gemini-pro)으로 시도합니다.")
        model_name = "gemini-pro"
        
    print(f"✨ 선택된 모델: {model_name}")
    
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
    너는 'AI 산업 전반'과 '스포츠 비즈니스'를 모두 다루는 스타트업의 리서치 팀장이야.
    우리는 너무 엄격한 기준보다는, **넓은 시야의 산업 동향**을 파악하고 싶어.
    
    제공된 뉴스 후보군(JSON)에서 우리에게 도움이 될 만한 뉴스를 선별해줘.

    [후보군 데이터]:
    {news_text}

    [선별 기준 (상당히 관대하게 적용)]:
    1. **지역 우선순위**: **[해외] 미국/글로벌 뉴스**는 가장 선진적인 트렌드이므로 **반드시 3개 이상 포함**하도록 노력해. 영국/일본/중국 뉴스는 정말 중요한 내용이 있을 때만 포함해(없으면 과감히 생략).
    2. **정부 정책**: 한국 정부(과기부/문체부)의 지원 사업/정책은 발견 즉시 **무조건 포함**.
    3. **산업 분야**: AI(비주얼, 생성형, 로봇, 반도체) 및 스포츠 비즈니스 전반.
    4. **제외 대상**: 오직 '단순 경기 스코어(누가 이겼다)'와 '연예인 가십'만 제외해.

    [작성 지침]:
    - **수량**: **최소 5개 ~ 최대 10개**. (기준이 조금 애매해도 연관성 있으면 과감하게 포함해서 개수를 채울 것!)
    - **언어**: 해외 뉴스는 반드시 **한국어로 번역**해서 요약.
    - **요약**: "관련 산업군에 긍정적/부정적 요인으로 작용할 예정" 등의 비즈니스 톤앤매너.

    [출력 포맷 - JSON Array Only]:
    [
      {{
        "title": "기사 제목",
        "summary": "핵심 인사이트 (한국어)",
        "original_link": "링크",
        "source": "출처 표기"
      }}
    ]
    """
    
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            text = response.json().get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '[]')
            clean_text = re.sub(r"```json|```", "", text).strip()
            
            # 디버깅: 원본이 너무 짧거나 이상하면 출력
            if len(clean_text) < 10:
                print(f"⚠️ Gemini 응답이 비정상적으로 짧음: {clean_text}")

            # JSON 파싱 시도 (대괄호 찾기)
            match = re.search(r'\[.*\]', clean_text, re.DOTALL)
            final_text = match.group(0) if match else clean_text
            
            try:
                result = json.loads(final_text)
                if not result:
                    print(f"⚠️ Gemini가 빈 리스트([])를 반환했습니다. 원본 텍스트:\n{text[:500]}...")
                return result
            except json.JSONDecodeError as je:
                print(f"⚠️ JSON 파싱 실패. 원본 응답:\n{text}")
                return []
                
        else:
            print(f"Gemini API Error Status: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"Gemini API Request Error: {e}")
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
    
    # 1-1. 해외 (미국, 유럽, 일본, 아시아)
    # 영어 쿼리를 각국 구글 뉴스에 던져서 지역별 관련 뉴스 수집 (일본은 일어 기사도 잡힘)
    overseas_items = fetch_google_rss_items(
        RSS_QUERIES_GLOBAL, 
        target_regions=['US', 'GB', 'JP', 'HK'], 
        source_label_prefix="[해외]"
    )
    
    # 1-2. 국내 정책 (한국어 키워드 - 한국 리전 고정)
    # fetch_google_rss_items 재활용
    REGION_CONFIGS['KR'] = {'gl': 'KR', 'hl': 'ko', 'ceid': 'KR:ko', 'name': '한국/정책'}
    
    policy_items = fetch_google_rss_items(
        RSS_QUERIES_KR_POLICY, 
        target_regions=['KR'], 
        source_label_prefix="[정책]"
    )
    
    # 1-3. 국내 일반 (네이버 섹션)
    domestic_items = fetch_naver_news()
    
    all_items = overseas_items + policy_items + domestic_items
    
    if all_items:
        # 2. 분석
        print(f"📦 총 수집된 뉴스 후보: {len(all_items)}개")
        selected = analyze_and_filter_news(all_items)
        if selected:
            print(f"👉 최종 선별된 뉴스: {len(selected)}건")
            send_discord_report(selected)
        else:
            print("🤔 조건에 맞는 뉴스가 없어 전송하지 않았습니다.")
    else:
        print("❌ 수집된 뉴스가 없습니다.")
