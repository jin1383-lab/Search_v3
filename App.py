import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import isodate  # ISO 8601 기간 포맷(PT1M15S 등)을 파싱하기 위해 필요 (pip install isodate)

# 페이지 설정
st.set_page_config(page_title="YouTube 비디오 헌터", layout="wide")
st.title("🎬 YouTube 동영상 분석기 (롱폼/숏폼 필터)")

# 1. 사이드바 - API 설정 및 검색 조건
st.sidebar.header("⚙️ 검색 설정")

# Secrets 활용 혹은 수동 입력
if "YOUTUBE_API_KEY" in st.secrets:
    api_key = st.secrets["YOUTUBE_API_KEY"]
else:
    api_key = st.sidebar.text_input("YouTube API Key를 입력하세요", type="password")

keyword = st.sidebar.text_input("검색어 입력", value="모터사이클 스턴트")

# 국가 코드 필터
region_options = {"전체": "any", "한국": "KR", "미국": "US", "일본": "JP", "브라질": "BR"}
selected_region = st.sidebar.selectbox("대상 국가", list(region_options.keys()))
region_code = region_options[selected_region]

# ★ [핵심 추가] 동영상 길이(포맷) 필터
duration_options = {
    "전체 (Any)": "any",
    "숏폼 위주 (4분 미만 - Short)": "short",
    "일반 영상 (4분~20분 - Medium)": "medium",
    "장편/롱폼 (20분 초과 - Long)": "long"
}
selected_duration_label = st.sidebar.radio("동영상 형태 선택", list(duration_options.keys()))
video_duration_param = duration_options[selected_duration_label]

max_results = st.sidebar.slider("가져올 결과 개수", 5, 50, 20)

# API 호출 및 분석 함수
def fetch_youtube_data(key, q, region, duration, max_res):
    try:
        youtube = build("youtube", "v3", developerKey=key)
        
        # 1단계: 검색 요청 (Search API)
        search_params = {
            "q": q,
            "part": "snippet",
            "type": "video",
            "maxResults": max_res,
            "order": "relevance"
        }
        
        # 특정 국가 필터 적용
        if region != "any":
            search_params["regionCode"] = region
            
        # ★ 동영상 길이 필터 적용
        if duration != "any":
            search_params["videoDuration"] = duration
            
        search_response = youtube.search().list(**search_params).execute()
        
        video_ids = [item["id"]["videoId"] for item in search_response.get("items", [])]
        if not video_ids:
            return None, "검색 결과가 없습니다."
            
        # 2단계: 상세 데이터 획득 (Videos API - 조회수, 정확한 재생시간 파싱용)
        videos_response = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(video_ids)
        ).execute()
        
        parsed_data = []
        for item in videos_response.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            details = item.get("contentDetails", {})
            
            # ISO 8601 기간 포맷(예: PT3M45S)을 보기 좋은 형태(03:45)로 변환
            raw_duration = details.get("duration", "PT0S")
            try:
                duration_sec = isodate.parse_duration(raw_duration).total_seconds()
                mins, secs = divmod(int(duration_sec), 60)
                hours, mins = divmod(mins, 60)
                duration_str = f"{hours:02d}:{mins:02d}:{secs:02d}" if hours > 0 else f"{mins:02d}:{secs:02d}"
            except:
                duration_str = "알 수 없음"
                duration_sec = 0

            # 숏폼(완전한 60초 미만 Shorts)을 더 깐깐하게 필터링하고 싶을 경우의 팁:
            # 만약 API의 'short'(4분 미만)가 너무 길다면, 가져온 데이터 중 duration_sec <= 60 인 것만 코드 단에서 한 번 더 걸러낼 수도 있습니다.

            parsed_data.append({
                "동영상 제목": snippet.get("title"),
                "채널명": snippet.get("channelTitle"),
                "재생 시간": duration_str,
                "재생시간(초)": duration_sec,
                "조회수": int(stats.get("viewCount", 0)),
                "좋아요수": int(stats.get("likeCount", 0)),
                "댓글수": int(stats.get("commentCount", 0)),
                "게시일": snippet.get("publishedAt")[:10],
                "URL": f"https://www.youtube.com/watch?v={item['id']}"
            })
            
        return pd.DataFrame(parsed_data), None

    except HttpError as e:
        if e.resp.status == 429:
            return None, "⚠️ API 할당량이 초과되었습니다. 내일 다시 시도하거나 다른 키를 사용해 주세요."
        return None, f"⚠️ API 에러 발생: {e}"
    except Exception as e:
        return None, f"⚠️ 알 수 없는 오류 발생: {e}"

# 2. 메인 화면 로직
if st.sidebar.button("🔍 데이터 수집 시작"):
    if not api_key:
        st.warning("API Key를 입력하거나 secrets.toml에 설정해 주세요.")
    else:
        with st.spinner("YouTube에서 분석 데이터를 수집 중입니다..."):
            df, error_msg = fetch_youtube_data(api_key, keyword, region_code, video_duration_param, max_results)
            
            if error_msg:
                st.error(error_msg)
            elif df is not None:
                st.success(f"총 {len(df)}개의 영상을 성공적으로 분석했습니다! (필터: {selected_duration_label})")
                
                # 정렬 옵션 제공
                sort_by = st.selectbox("정렬 기준", ["조회수", "좋아요수", "댓글수", "재생시간(초)"], index=0)
                df = df.sort_values(by=sort_by, ascending=False).reset_index(drop=True)
                
                # 데이터프레임 출력 및 다운로드 버튼
                st.dataframe(
                    df.drop(columns=["재생시간(초)"]), 
                    column_config={"URL": st.column_config.LinkColumn("링크")}
                )
                
                csv = df.to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    label="📥 CSV 파일로 내보내기",
                    data=csv,
                    file_name=f"youtube_{keyword}_{video_duration_param}.csv",
                    mime="text/csv"
                )
