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
    {"id": "100", "name": "정치"},    # Politics (Policy)
    {"id": "105", "name": "IT/과학"}, # Science/IT
    {"id": "101", "name": "경제"}     # Economy
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

def analyze_news_group(news_items, category_name, limit=10):
    """특정 그룹(국내/해외)의 뉴스 중 Top N 선별"""
    if not news_items:
        return []

    print(f"🧠 '{category_name}' 분야 후보 {len(news_items)}개 분석 및 선별 중 (목표: Top {limit})...")
    
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
    너는 'AI/스포츠 스타트업 리서치 팀장'이야.
    이번 작업은 **[{category_name}]** 관련 뉴스 중 우리에게 가장 가치 있는 **Top {limit}**을 선정하는 거야.

    [후보군 데이터]:
    {news_text}

    [선별 가이드라인]:
    1. **{category_name}** 관점에서 가장 중요한 소식을 우선해.
    2. **국내**인 경우: 정부 정책(과기부/문체부), 대기업의 AI/스포츠 투자, 규제 이슈 집중. (단순 정쟁/가십 절대 제외)
    3. **해외**인 경우: 글로벌 AI 트렌드, 빅테크 움직임, 해외 스포츠 비즈니스 모델. (반드시 한국어로 번역/요약)
    4. **공통**: 경기 스코어, 연예인 이슈 컷.

    [작성 양식]:
    - **수량**: 중요도 순으로 **정확히 {limit}개** 추천해줘. 만약 후보가 너무 부족하면 최소 3개는 선정해.
    - **순서**: 가장 중요한 뉴스가 1번에 오도록 배치해.
    - **요약**: 비즈니스 인사이트가 담긴 1-2줄 요약.

    [출력 포맷 - JSON Array Only]:
    [
      {{
        "title": "기사 제목",
        "summary": "핵심 인사이트",
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
            
            # 디버깅
            if len(clean_text) < 10:
                print(f"⚠️ Gemini 응답이 비정상적으로 짧음: {clean_text}")

            match = re.search(r'\[.*\]', clean_text, re.DOTALL)
            final_text = match.group(0) if match else clean_text
            
            try:
                return json.loads(final_text)
            except json.JSONDecodeError as je:
                print(f"⚠️ JSON 파싱 실패. 원본 응답:\n{text}")
                return []
                
        else:
            print(f"Gemini API Error Status: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"Gemini API Request Error: {e}")
        return []
    
    return []

def send_discord_report(domestic_list, overseas_list):
    if not DISCORD_WEBHOOK_URL:
        print("디스코드 웹훅 URL 없음")
        return
    if not domestic_list and not overseas_list:
        print("전송할 뉴스가 아예 없음")
        return

    today = datetime.now().strftime("%Y년 %m월 %d일")
    
    def send_single_embed(title, desc, items, color):
        """임베드 하나를 전송하는 헬퍼 함수"""
        if not items:
            return

        embed = {
            "title": title,
            "description": desc,
            "color": color,
            "fields": [],
            "footer": {
                "text": "Strategy Team Agent via Gemini",
            }
        }
        
        for i, news in enumerate(items):
            # 요약이 너무 길면 잘라서 전송 오류 방지
            summary = news['summary']
            if len(summary) > 300:
                summary = summary[:297] + "..."
            
            # Top 1 별도 표기
            is_top_one = (i == 0)
            title_prefix = "⭐ [MUST READ] " if is_top_one else "🔹 "
            
            value_text = (
                f"**분류**: {news.get('source','[기타]')}\n"
                f"**기사제목**: {news['title']}\n"
                f"**내용요약**: {summary}\n"
                f"**원문링크**: [🔗 기사 전문 보기]({news['original_link']})\n"
                f"\u200b" # 투명 문자로 간격 확보
            )
            
            embed["fields"].append({
                "name": f"{title_prefix} {'TOP 1' if is_top_one else f'News {i+1}'}",
                "value": value_text,
                "inline": False
            })
            
        payload = {"embeds": [embed]}
        
        try:
            response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
            if response.status_code in [200, 204]:
                print(f"✅ 디스코드 전송 완료: {title}")
            else:
                print(f"❌ 디스코드 오류 ({response.status_code}): {response.text}")
        except Exception as e:
            print(f"디스코드 요청 중 예외 발생: {e}")

    # 1. 국내 파트 전송
    if domestic_list:
        send_single_embed(
            f"🇰🇷 {today} 국내 AI/스포츠 정책 & 산업",
            "정부 지원 사업 및 네이버 뉴스 요약",
            domestic_list,
            0x00ff00 # Green
        )
        time.sleep(1) # 순서 보장 및 레이트 리밋 방지

    # 2. 해외 파트 전송
    if overseas_list:
        send_single_embed(
            f"🌎 {today} 해외 글로벌 테크 트렌드",
            "미국, 유럽, 아시아 주요 뉴스 번역 리포트",
            overseas_list,
            0x3498db # Blue
        )

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
    
    # 2. 그룹별 분리 및 분석
    
    # A. 해외 그룹 (미국/영국/일본/홍콩)
    print(f"📦 해외 뉴스 후보: {len(overseas_items)}개")
    final_overseas = analyze_news_group(overseas_items, "해외(Global Top 7)", limit=7)

    # B. 국내 그룹 (정책 + 네이버 일반)
    domestic_total = policy_items + domestic_items
    print(f"📦 국내 뉴스 후보: {len(domestic_total)}개 (정책 {len(policy_items)} + 일반 {len(domestic_items)})")
    final_domestic = analyze_news_group(domestic_total, "국내(정책/산업 Top 5)", limit=5)
    
    # 3. 통합 리포트 전송
    if final_overseas or final_domestic:
        print(f"👉 최종 선별: 해외 {len(final_overseas)}건, 국내 {len(final_domestic)}건")
        send_discord_report(final_domestic, final_overseas)
    else:
        print("🤔 선별된 뉴스가 하나도 없습니다.")
