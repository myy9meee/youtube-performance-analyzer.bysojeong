import io
import re
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st


# ---------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------
st.set_page_config(
    page_title="유튜브 채널 성과 분석기",
    page_icon="📊",
    layout="wide",
)

st.title("📊 유튜브 채널 성과 분석기")
st.caption(
    "유튜브 스튜디오 고급 모드에서 내려받은 XLSX 또는 CSV를 업로드하면 "
    "채널 성과와 영상별 원인 후보를 분석합니다."
)


# ---------------------------------------------------------
# 유틸리티 함수
# ---------------------------------------------------------
def normalize_text(value) -> str:
    """열 이름과 제목을 비교하기 쉽게 정리합니다."""
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", "", str(value)).lower()


def find_column(columns, candidates):
    """후보 명칭과 가장 비슷한 실제 열 이름을 찾습니다."""
    normalized = {normalize_text(col): col for col in columns}

    # 완전 일치
    for candidate in candidates:
        key = normalize_text(candidate)
        if key in normalized:
            return normalized[key]

    # 부분 일치
    for candidate in candidates:
        candidate_key = normalize_text(candidate)
        for normalized_col, original_col in normalized.items():
            if candidate_key in normalized_col or normalized_col in candidate_key:
                return original_col

    return None


def parse_duration_to_seconds(value):
    """00:03:13, 3:13, 숫자 형태를 초로 변환합니다."""
    if pd.isna(value):
        return np.nan

    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)

    text = str(value).strip()

    try:
        parts = [float(part) for part in text.split(":")]

        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 1:
            return parts[0]
    except (ValueError, TypeError):
        return np.nan

    return np.nan


def seconds_to_mmss(seconds):
    if pd.isna(seconds):
        return "-"
    seconds = int(round(float(seconds)))
    minutes, remaining = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours > 0:
        return f"{hours}:{minutes:02d}:{remaining:02d}"
    return f"{minutes}:{remaining:02d}"


def safe_divide(numerator, denominator):
    numerator = pd.to_numeric(numerator, errors="coerce")
    denominator = pd.to_numeric(denominator, errors="coerce")
    denominator = denominator.replace(0, np.nan)
    return numerator / denominator


def percentile_label(series, value):
    """지표가 채널 내 어느 수준인지 반환합니다."""
    clean = pd.to_numeric(series, errors="coerce").dropna()

    if clean.empty or pd.isna(value):
        return "판단 불가"

    percentile = (clean <= value).mean()

    if percentile >= 0.80:
        return "상위 20%"
    if percentile >= 0.60:
        return "상위 40%"
    if percentile <= 0.20:
        return "하위 20%"
    if percentile <= 0.40:
        return "하위 40%"
    return "중간 수준"


def compare_to_median(value, median, metric_name, reverse=False):
    """
    중앙값과 비교한 문장을 만듭니다.
    reverse=True면 값이 낮을수록 좋은 지표에 사용합니다.
    """
    if pd.isna(value) or pd.isna(median) or median == 0:
        return None

    difference = ((value - median) / abs(median)) * 100

    if abs(difference) < 10:
        return f"{metric_name}은 비교군 중앙값과 비슷합니다."

    if reverse:
        direction = "낮아 긍정적" if difference < 0 else "높아 주의 필요"
    else:
        direction = "높습니다" if difference > 0 else "낮습니다"

    return (
        f"{metric_name}이 비교군 중앙값보다 "
        f"{abs(difference):.0f}% {direction}."
    )


# ---------------------------------------------------------
# 제목 기반 주제 분류
# ---------------------------------------------------------
CATEGORY_RULES = {
    "여행": [
        "여행", "휴가", "브이로그 여행", "제주", "부산", "통영", "일본",
        "도쿄", "오사카", "삿포로", "파리", "런던", "미국", "해외",
        "호텔", "호캉스", "캠핑"
    ],
    "음식·맛집": [
        "먹방", "맛집", "라면", "요리", "레시피", "밥", "고기", "술",
        "카페", "디저트", "먹어", "먹는", "식당", "떡볶이", "김치"
    ],
    "뷰티·관리": [
        "관리", "메이크업", "화장", "피부", "동안", "다이어트", "헤어",
        "마사지", "뷰티", "시술", "팩", "운동", "몸매"
    ],
    "패션·쇼핑": [
        "패션", "쇼핑", "옷", "가방", "신발", "명품", "하울", "코디",
        "착장", "주얼리", "브랜드", "플리마켓"
    ],
    "집·일상": [
        "일상", "브이로그", "집", "하루", "주말", "아침", "퇴근",
        "출근", "청소", "정리", "이달의", "근황"
    ],
    "배우·촬영": [
        "배우", "드라마", "영화", "촬영", "현장", "대본", "오디션",
        "연기", "작품", "화보", "시사회", "인터뷰"
    ],
    "토크·Q&A": [
        "q&a", "qna", "질문", "토크", "고민", "상담", "썰", "이상형",
        "연애", "결혼", "밸런스", "인터뷰"
    ],
    "게스트·관계": [
        "친구", "언니", "오빠", "동생", "선배", "후배", "절친",
        "게스트", "엄마", "아빠", "가족", "배우님"
    ],
    "취미·체험": [
        "골프", "테니스", "등산", "운동", "도전", "체험", "배우기",
        "클래스", "취미", "게임", "캠핑"
    ],
}


def classify_title(title):
    text = str(title).lower()
    matched = []

    for category, keywords in CATEGORY_RULES.items():
        if any(keyword.lower() in text for keyword in keywords):
            matched.append(category)

    if not matched:
        return "기타"

    return " · ".join(matched[:3])


def primary_category(category_text):
    if pd.isna(category_text):
        return "기타"
    return str(category_text).split(" · ")[0]


# ---------------------------------------------------------
# 파일 읽기
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def load_file(file_bytes, filename):
    if filename.lower().endswith(".csv"):
        attempts = ["utf-8-sig", "cp949", "utf-8"]

        for encoding in attempts:
            try:
                return pd.read_csv(io.BytesIO(file_bytes), encoding=encoding), "CSV"
            except UnicodeDecodeError:
                continue

        raise ValueError("CSV 파일의 문자 인코딩을 읽지 못했습니다.")

    excel = pd.ExcelFile(io.BytesIO(file_bytes))

    preferred_sheet = None
    for sheet in excel.sheet_names:
        if "표 데이터" in str(sheet):
            preferred_sheet = sheet
            break

    if preferred_sheet is None:
        preferred_sheet = excel.sheet_names[0]

    return pd.read_excel(excel, sheet_name=preferred_sheet), preferred_sheet


def prepare_dataframe(raw_df):
    df = raw_df.copy()

    column_map = {
        "video_id": find_column(
            df.columns,
            ["콘텐츠", "동영상 ID", "영상 ID", "Content"]
        ),
        "title": find_column(
            df.columns,
            ["동영상 제목", "영상 제목", "제목", "Video title"]
        ),
        "published_at": find_column(
            df.columns,
            ["동영상 게시 시간", "게시일", "업로드 날짜", "Video publish time"]
        ),
        "length": find_column(
            df.columns,
            ["길이", "영상 길이", "Duration"]
        ),
        "views": find_column(
            df.columns,
            ["조회수", "Views"]
        ),
        "watch_hours": find_column(
            df.columns,
            ["시청 시간(단위: 시간)", "시청 시간", "Watch time"]
        ),
        "avg_duration": find_column(
            df.columns,
            ["평균 시청 지속 시간", "Average view duration"]
        ),
        "impressions": find_column(
            df.columns,
            ["노출수", "Impressions"]
        ),
        "ctr": find_column(
            df.columns,
            ["노출 클릭률 (%)", "노출 클릭률", "Impressions click-through rate"]
        ),
        "subs_gained": find_column(
            df.columns,
            ["구독자 증가수", "구독자 증가", "Subscribers gained"]
        ),
        "subs_lost": find_column(
            df.columns,
            ["구독자 감소수", "구독자 감소", "Subscribers lost"]
        ),
        "revenue": find_column(
            df.columns,
            ["예상 수익 (USD)", "예상 수익", "Estimated revenue"]
        ),
    }

    required = ["title", "views"]
    missing = [name for name in required if column_map[name] is None]

    if missing:
        raise ValueError(
            "필수 열을 찾지 못했습니다: "
            + ", ".join(missing)
            + "\n\n현재 열: "
            + ", ".join(map(str, df.columns))
        )

    clean = pd.DataFrame()

    for target, source in column_map.items():
        if source is not None:
            clean[target] = df[source]
        else:
            clean[target] = np.nan

    # 유튜브 엑셀 첫 행의 '합계' 제거
    clean["title"] = clean["title"].astype("string")
    clean = clean[
        clean["title"].notna()
        & (clean["title"].str.strip() != "")
        & (~clean["video_id"].astype(str).str.contains("합계", na=False))
    ].copy()

    numeric_columns = [
        "views", "watch_hours", "impressions", "ctr",
        "subs_gained", "subs_lost", "revenue"
    ]

    for col in numeric_columns:
        clean[col] = pd.to_numeric(clean[col], errors="coerce")

    clean["published_at"] = pd.to_datetime(
        clean["published_at"],
        errors="coerce"
    )

    clean["length_seconds"] = clean["length"].apply(parse_duration_to_seconds)
    clean["avg_duration_seconds"] = clean["avg_duration"].apply(
        parse_duration_to_seconds
    )

    clean["avg_percentage_viewed"] = (
        safe_divide(clean["avg_duration_seconds"], clean["length_seconds"]) * 100
    )

    clean["net_subscribers"] = (
        clean["subs_gained"].fillna(0) - clean["subs_lost"].fillna(0)
    )

    clean["net_subscribers_per_1k_views"] = (
        safe_divide(clean["net_subscribers"], clean["views"]) * 1000
    )

    clean["views_per_impression"] = safe_divide(
        clean["views"], clean["impressions"]
    )

    today = pd.Timestamp.today().normalize()
    clean["days_since_publish"] = (
        today - clean["published_at"]
    ).dt.days.clip(lower=1)

    clean["views_per_day"] = safe_divide(
        clean["views"], clean["days_since_publish"]
    )

    clean["publication_year"] = clean["published_at"].dt.year
    clean["publication_month"] = clean["published_at"].dt.to_period("M").astype(
        str
    )

    clean["category"] = clean["title"].apply(classify_title)
    clean["primary_category"] = clean["category"].apply(primary_category)

    return clean, column_map


# ---------------------------------------------------------
# 영상별 진단
# ---------------------------------------------------------
def get_comparison_group(df, row):
    """
    채널 성장과 시기 차이를 줄이기 위해 같은 연도 영상을 우선 비교합니다.
    같은 연도 영상이 너무 적으면 전체 데이터를 사용합니다.
    """
    year = row.get("publication_year")

    if pd.notna(year):
        same_year = df[df["publication_year"] == year]
        if len(same_year) >= 8:
            return same_year

    return df


def diagnose_video(df, row):
    group = get_comparison_group(df, row)

    medians = {
        "views": group["views"].median(),
        "impressions": group["impressions"].median(),
        "ctr": group["ctr"].median(),
        "avg_percentage_viewed": group["avg_percentage_viewed"].median(),
        "avg_duration_seconds": group["avg_duration_seconds"].median(),
        "net_subscribers_per_1k_views":
            group["net_subscribers_per_1k_views"].median(),
    }

    reasons = []

    views = row["views"]
    impressions = row["impressions"]
    ctr = row["ctr"]
    retention = row["avg_percentage_viewed"]
    sub_rate = row["net_subscribers_per_1k_views"]

    if pd.notna(views) and pd.notna(medians["views"]):
        view_ratio = views / medians["views"] if medians["views"] else np.nan
    else:
        view_ratio = np.nan

    if pd.notna(view_ratio):
        if view_ratio >= 1.5:
            performance = "평균보다 매우 높음"
        elif view_ratio >= 1.1:
            performance = "평균보다 높음"
        elif view_ratio <= 0.5:
            performance = "평균보다 매우 낮음"
        elif view_ratio <= 0.9:
            performance = "평균보다 낮음"
        else:
            performance = "평균 수준"
    else:
        performance = "판단 불가"

    # 노출 분석
    if pd.notna(impressions) and pd.notna(medians["impressions"]):
        impression_ratio = (
            impressions / medians["impressions"]
            if medians["impressions"]
            else np.nan
        )

        if impression_ratio >= 1.3:
            reasons.append(
                "노출수가 비교군보다 높아 조회수 확대에 유리했습니다."
            )
        elif impression_ratio <= 0.7:
            reasons.append(
                "노출수가 비교군보다 낮아 도달 범위가 제한됐을 가능성이 큽니다."
            )

    # CTR 분석
    if pd.notna(ctr) and pd.notna(medians["ctr"]):
        ctr_diff = ctr - medians["ctr"]

        if ctr_diff >= 1:
            reasons.append(
                f"CTR이 비교군보다 {ctr_diff:.1f}%p 높아 "
                "제목·썸네일의 클릭 유도가 강했던 것으로 보입니다."
            )
        elif ctr_diff <= -1:
            reasons.append(
                f"CTR이 비교군보다 {abs(ctr_diff):.1f}%p 낮아 "
                "노출 이후 클릭 전환이 약했던 것으로 보입니다."
            )

    # 시청 유지 분석
    if pd.notna(retention) and pd.notna(medians["avg_percentage_viewed"]):
        retention_diff = retention - medians["avg_percentage_viewed"]

        if retention_diff >= 5:
            reasons.append(
                f"평균 조회율이 비교군보다 {retention_diff:.1f}%p 높아 "
                "시청 유지력이 좋았습니다."
            )
        elif retention_diff <= -5:
            reasons.append(
                f"평균 조회율이 비교군보다 {abs(retention_diff):.1f}%p 낮아 "
                "영상 길이 또는 전개 측면의 이탈 가능성이 있습니다."
            )

    # 구독 전환 분석
    if (
        pd.notna(sub_rate)
        and pd.notna(medians["net_subscribers_per_1k_views"])
    ):
        median_sub_rate = medians["net_subscribers_per_1k_views"]
        difference = sub_rate - median_sub_rate

        if difference >= 1:
            reasons.append(
                "조회수 대비 순구독자 전환이 비교군보다 높아 "
                "채널 성장 기여도가 좋았습니다."
            )
        elif difference <= -1:
            reasons.append(
                "조회수 대비 순구독자 전환이 비교군보다 낮아 "
                "신규 구독 유도 효과는 제한적이었습니다."
            )

    # 업로드 시점 주의
    if pd.notna(row["days_since_publish"]) and row["days_since_publish"] < 30:
        reasons.append(
            "업로드 후 30일이 지나지 않아 누적 조회수 평가는 아직 이릅니다."
        )

    if not reasons:
        reasons.append(
            "주요 지표가 비교군 중앙값과 비슷해 특정 단일 원인이 "
            "뚜렷하게 나타나지 않습니다."
        )

    return performance, " ".join(reasons[:4])


def add_diagnoses(df):
    results = df.apply(
        lambda row: diagnose_video(df, row),
        axis=1,
        result_type="expand"
    )

    output = df.copy()
    output["performance_grade"] = results[0]
    output["diagnosis"] = results[1]
    return output


# ---------------------------------------------------------
# 강화·주의 요소
# ---------------------------------------------------------
def category_summary(df):
    grouped = (
        df.groupby("primary_category", dropna=False)
        .agg(
            영상수=("title", "count"),
            조회수_중앙값=("views", "median"),
            CTR_중앙값=("ctr", "median"),
            평균조회율_중앙값=("avg_percentage_viewed", "median"),
            순구독자_전환_중앙값=(
                "net_subscribers_per_1k_views", "median"
            ),
            영상길이_중앙값=("length_seconds", "median"),
        )
        .reset_index()
        .rename(columns={"primary_category": "주제"})
    )

    return grouped


def create_strategy(category_df):
    eligible = category_df[category_df["영상수"] >= 3].copy()

    if eligible.empty:
        return [], [], []

    metric_columns = [
        "조회수_중앙값",
        "CTR_중앙값",
        "평균조회율_중앙값",
        "순구독자_전환_중앙값",
    ]

    for col in metric_columns:
        eligible[f"{col}_순위점수"] = eligible[col].rank(
            pct=True,
            method="average"
        )

    eligible["종합점수"] = eligible[
        [f"{col}_순위점수" for col in metric_columns]
    ].mean(axis=1)

    strengthen = (
        eligible.sort_values("종합점수", ascending=False)
        .head(3)
        .to_dict("records")
    )

    caution = (
        eligible.sort_values("종합점수", ascending=True)
        .head(3)
        .to_dict("records")
    )

    maintain = eligible[
        (eligible["종합점수"] > 0.35)
        & (eligible["종합점수"] < 0.65)
    ].sort_values("영상수", ascending=False).head(3).to_dict("records")

    return strengthen, maintain, caution


# ---------------------------------------------------------
# 무료 데이터 기반 아이템 추천
# ---------------------------------------------------------
ITEM_TEMPLATES = {
    "여행": [
        "{topic} 당일치기: 가장 만족한 곳과 솔직한 비용 공개",
        "계획 없이 떠난 {topic} 여행, 실제로 좋았던 곳만 정리",
        "{topic}에서 하루 동안 꼭 해봐야 할 5가지",
    ],
    "음식·맛집": [
        "요즘 가장 자주 먹는 메뉴 5개, 솔직한 순위 공개",
        "하루 동안 추천받은 맛집만 따라가 보기",
        "가격대별로 비교해 본 최애 메뉴",
    ],
    "뷰티·관리": [
        "한 달 동안 꾸준히 해본 관리, 전후 차이 공개",
        "평소 실제로 하는 관리 루틴과 비용 정리",
        "유명한 관리법 3개 직접 비교해 보기",
    ],
    "패션·쇼핑": [
        "최근 가장 잘 산 아이템과 후회한 아이템",
        "예산을 정해 놓고 완성하는 실제 데일리 코디",
        "오래 사용한 애정템의 가격과 장단점 공개",
    ],
    "집·일상": [
        "한 달의 진짜 일상 중 가장 기억에 남은 순간들",
        "일이 없는 날 실제로 보내는 하루",
        "요즘 달라진 생활 습관과 솔직한 근황",
    ],
    "배우·촬영": [
        "촬영 전날부터 촬영이 끝날 때까지의 실제 과정",
        "배우 생활에서 직접 겪은 예상 밖의 순간들",
        "작품을 준비할 때 실제로 하는 루틴 공개",
    ],
    "토크·Q&A": [
        "가장 많이 받은 질문만 골라 솔직하게 답하기",
        "지금까지 말하지 않았던 일과 생활에 대한 이야기",
        "구독자 고민에 경험을 바탕으로 답해 보기",
    ],
    "게스트·관계": [
        "오래된 지인과 서로의 첫인상부터 현재까지 이야기",
        "친한 사람이 대신 공개하는 의외의 모습",
        "서로 얼마나 잘 아는지 질문으로 확인해 보기",
    ],
    "취미·체험": [
        "처음 도전한 취미, 하루 만에 어디까지 가능할까",
        "전문가에게 제대로 배워본 새로운 취미",
        "한 달 동안 취미를 배운 뒤 실제 결과 공개",
    ],
    "기타": [
        "최근 가장 궁금했던 것을 직접 확인해 보기",
        "구독자 추천 중 가장 많은 의견을 실제로 실행",
        "한 달 동안 바꿔본 습관과 결과 공개",
    ],
}


def extract_title_keywords(df, top_n=15):
    stopwords = {
        "유인영", "인영인영", "sub", "vlog", "브이로그", "영상", "오늘",
        "진짜", "그냥", "그리고", "이번", "저의", "제가", "해봤습니다",
        "합니다", "했어요", "하는", "에서", "으로", "에게", "with",
        "inyoung", "첫번째", "두번째", "편"
    }

    words = []

    for title in df["title"].dropna().astype(str):
        cleaned = re.sub(r"[^가-힣a-zA-Z0-9\s]", " ", title.lower())

        for word in cleaned.split():
            if len(word) >= 2 and word not in stopwords and not word.isdigit():
                words.append(word)

    if not words:
        return []

    return (
        pd.Series(words)
        .value_counts()
        .head(top_n)
        .index
        .tolist()
    )


def generate_recommendations(df, category_df):
    eligible = category_df[category_df["영상수"] >= 2].copy()

    if eligible.empty:
        best_categories = ["집·일상", "음식·맛집", "여행"]
    else:
        metrics = [
            "조회수_중앙값",
            "CTR_중앙값",
            "평균조회율_중앙값",
            "순구독자_전환_중앙값",
        ]

        for metric in metrics:
            eligible[f"{metric}_score"] = eligible[metric].rank(pct=True)

        eligible["score"] = eligible[
            [f"{metric}_score" for metric in metrics]
        ].mean(axis=1)

        best_categories = (
            eligible.sort_values("score", ascending=False)["주제"]
            .head(4)
            .tolist()
        )

    keywords = extract_title_keywords(df)
    topic_word = keywords[0] if keywords else "요즘 관심사"

    recommendations = []
    used_titles = set()

    for category in best_categories:
        templates = ITEM_TEMPLATES.get(category, ITEM_TEMPLATES["기타"])

        category_row = category_df[category_df["주제"] == category]

        if not category_row.empty:
            row = category_row.iloc[0]
            evidence = (
                f"이 채널의 '{category}' 영상 {int(row['영상수'])}편은 "
                f"조회수 중앙값 {row['조회수_중앙값']:,.0f}회, "
                f"CTR 중앙값 {row['CTR_중앙값']:.1f}%, "
                f"평균 조회율 중앙값 "
                f"{row['평균조회율_중앙값']:.1f}%를 기록했습니다."
            )
            recommended_length = row["영상길이_중앙값"]
        else:
            evidence = (
                f"채널의 고성과 주제와 제목 패턴을 바탕으로 "
                f"'{category}' 확장 아이템을 제안합니다."
            )
            recommended_length = df["length_seconds"].median()

        for template in templates:
            title = template.format(topic=topic_word)

            if title in used_titles:
                continue

            used_titles.add(title)

            recommendations.append(
                {
                    "추천 아이템": title,
                    "활용 주제": category,
                    "추천 근거": evidence,
                    "권장 영상 길이": seconds_to_mmss(recommended_length),
                    "기획 포인트": (
                        "제목에서 구체적인 행동과 결과를 먼저 보여주고, "
                        "영상 안에서도 결과가 확인되도록 구성합니다."
                    ),
                }
            )

            if len(recommendations) >= 10:
                return pd.DataFrame(recommendations)

    # 10개가 되지 않을 경우 기타 템플릿 추가
    for template in ITEM_TEMPLATES["기타"]:
        title = template.format(topic=topic_word)

        if title in used_titles:
            continue

        recommendations.append(
            {
                "추천 아이템": title,
                "활용 주제": "기타",
                "추천 근거": (
                    "채널에서 반복적으로 등장한 제목 키워드와 "
                    "성과가 높은 구성 방식을 결합했습니다."
                ),
                "권장 영상 길이": seconds_to_mmss(
                    df["length_seconds"].median()
                ),
                "기획 포인트": (
                    "구체적인 목표와 결과가 보이는 구성으로 제작합니다."
                ),
            }
        )

        if len(recommendations) >= 10:
            break

    return pd.DataFrame(recommendations[:10])


# ---------------------------------------------------------
# 엑셀 다운로드
# ---------------------------------------------------------
def dataframe_to_excel(sheets):
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, dataframe in sheets.items():
            safe_name = str(sheet_name)[:31]
            dataframe.to_excel(writer, sheet_name=safe_name, index=False)

    output.seek(0)
    return output.getvalue()


# ---------------------------------------------------------
# 사이드바와 파일 업로드
# ---------------------------------------------------------
with st.sidebar:
    st.header("분석 설정")

    uploaded_file = st.file_uploader(
        "유튜브 스튜디오 XLSX 또는 CSV",
        type=["xlsx", "xls", "csv"],
        help="고급 모드에서 내보낸 영상별 표 데이터를 업로드하세요.",
    )

    st.divider()

    st.markdown(
        """
        **권장 포함 지표**

        - 동영상 제목
        - 동영상 게시 시간
        - 길이
        - 조회수
        - 시청 시간
        - 평균 시청 지속 시간
        - 노출수
        - 노출 클릭률
        - 구독자 증가·감소
        """
    )


if uploaded_file is None:
    st.info("왼쪽에서 유튜브 스튜디오 엑셀 파일을 업로드하세요.")

    st.subheader("이 사이트에서 확인할 수 있는 것")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("①", "채널 전체 진단")
    col2.metric("②", "영상별 원인 분석")
    col3.metric("③", "강화·주의 요소")
    col4.metric("④", "아이템 10개 추천")

    st.stop()


# ---------------------------------------------------------
# 분석 실행
# ---------------------------------------------------------
try:
    file_bytes = uploaded_file.getvalue()
    raw_df, source_sheet = load_file(file_bytes, uploaded_file.name)
    df, detected_columns = prepare_dataframe(raw_df)
    df = add_diagnoses(df)

except Exception as error:
    st.error("파일을 분석하는 중 문제가 발생했습니다.")
    st.exception(error)
    st.stop()


if df.empty:
    st.warning("분석할 영상 데이터가 없습니다.")
    st.stop()


# ---------------------------------------------------------
# 기간 필터
# ---------------------------------------------------------
valid_dates = df["published_at"].dropna()

with st.sidebar:
    if not valid_dates.empty:
        minimum_date = valid_dates.min().date()
        maximum_date = valid_dates.max().date()

        selected_dates = st.date_input(
            "게시일 범위",
            value=(minimum_date, maximum_date),
            min_value=minimum_date,
            max_value=maximum_date,
        )

        if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
            start_date, end_date = selected_dates

            filtered_df = df[
                (df["published_at"].dt.date >= start_date)
                & (df["published_at"].dt.date <= end_date)
            ].copy()
        else:
            filtered_df = df.copy()
    else:
        filtered_df = df.copy()

    available_categories = sorted(
        filtered_df["primary_category"].dropna().unique().tolist()
    )

    selected_categories = st.multiselect(
        "주제 필터",
        options=available_categories,
        default=available_categories,
    )

    if selected_categories:
        filtered_df = filtered_df[
            filtered_df["primary_category"].isin(selected_categories)
        ].copy()


if filtered_df.empty:
    st.warning("선택한 조건에 해당하는 영상이 없습니다.")
    st.stop()


# ---------------------------------------------------------
# 핵심 지표
# ---------------------------------------------------------
category_df = category_summary(filtered_df)
strengthen, maintain, caution = create_strategy(category_df)
recommendations_df = generate_recommendations(filtered_df, category_df)

video_count = len(filtered_df)
median_views = filtered_df["views"].median()
median_ctr = filtered_df["ctr"].median()
median_retention = filtered_df["avg_percentage_viewed"].median()
median_length = filtered_df["length_seconds"].median()
total_views = filtered_df["views"].sum()
net_subscribers = filtered_df["net_subscribers"].sum()

st.success(
    f"'{source_sheet}' 시트에서 영상 {video_count:,}편을 불러왔습니다."
)

metric_cols = st.columns(6)

metric_cols[0].metric("영상 수", f"{video_count:,}편")
metric_cols[1].metric("총조회수", f"{total_views:,.0f}회")
metric_cols[2].metric("조회수 중앙값", f"{median_views:,.0f}회")
metric_cols[3].metric(
    "CTR 중앙값",
    f"{median_ctr:.2f}%" if pd.notna(median_ctr) else "-"
)
metric_cols[4].metric(
    "평균 조회율 중앙값",
    f"{median_retention:.1f}%" if pd.notna(median_retention) else "-"
)
metric_cols[5].metric(
    "순구독자",
    f"{net_subscribers:,.0f}명"
)


# ---------------------------------------------------------
# 탭
# ---------------------------------------------------------
tabs = st.tabs(
    [
        "채널 전체 분석",
        "영상별 진단",
        "주제별 성과",
        "강화·주의 요소",
        "아이템 추천 10개",
        "데이터 다운로드",
    ]
)


# ---------------------------------------------------------
# 탭 1: 채널 전체 분석
# ---------------------------------------------------------
with tabs[0]:
    st.subheader("채널의 현재 성과 구조")

    col1, col2 = st.columns(2)

    with col1:
        yearly = (
            filtered_df.dropna(subset=["publication_year"])
            .groupby("publication_year")
            .agg(
                영상수=("title", "count"),
                조회수_중앙값=("views", "median"),
                CTR_중앙값=("ctr", "median"),
                평균조회율_중앙값=("avg_percentage_viewed", "median"),
            )
            .reset_index()
        )

        if not yearly.empty:
            fig = px.line(
                yearly,
                x="publication_year",
                y="조회수_중앙값",
                markers=True,
                title="연도별 영상 조회수 중앙값",
                labels={
                    "publication_year": "게시 연도",
                    "조회수_중앙값": "조회수 중앙값",
                },
            )
            st.plotly_chart(fig, width="stretch")

    with col2:
        length_scatter = filtered_df.dropna(
            subset=["length_seconds", "views"]
        ).copy()

        if not length_scatter.empty:
            length_scatter["영상 길이(분)"] = (
                length_scatter["length_seconds"] / 60
            )

            fig = px.scatter(
                length_scatter,
                x="영상 길이(분)",
                y="views",
                hover_name="title",
                title="영상 길이와 조회수의 관계",
                labels={"views": "조회수"},
                trendline=None,
            )
            st.plotly_chart(fig, width="stretch")

    st.subheader("제목 기준 채널 주제 구성")

    composition = (
        filtered_df["primary_category"]
        .value_counts()
        .rename_axis("주제")
        .reset_index(name="영상 수")
    )

    fig = px.bar(
        composition,
        x="주제",
        y="영상 수",
        title="주제별 영상 수",
    )
    st.plotly_chart(fig, width="stretch")

    strongest_category = (
        category_df.sort_values("조회수_중앙값", ascending=False).iloc[0]
        if not category_df.empty
        else None
    )

    most_common_category = (
        category_df.sort_values("영상수", ascending=False).iloc[0]
        if not category_df.empty
        else None
    )

    if strongest_category is not None and most_common_category is not None:
        st.markdown(
            f"""
            ### 자동 요약

            - 가장 많이 제작한 주제는 **{most_common_category['주제']}**
              ({int(most_common_category['영상수'])}편)입니다.
            - 조회수 중앙값이 가장 높은 주제는
              **{strongest_category['주제']}**
              ({strongest_category['조회수_중앙값']:,.0f}회)입니다.
            - 전체 영상 길이 중앙값은
              **{seconds_to_mmss(median_length)}**입니다.
            - 채널 성과 판단에는 평균보다 **중앙값**을 우선 사용했습니다.
            """
        )


# ---------------------------------------------------------
# 탭 2: 영상별 진단
# ---------------------------------------------------------
with tabs[1]:
    st.subheader("영상별 성과 진단")

    search_keyword = st.text_input(
        "영상 제목 검색",
        placeholder="제목의 일부를 입력하세요.",
    )

    diagnosis_df = filtered_df.copy()

    if search_keyword:
        diagnosis_df = diagnosis_df[
            diagnosis_df["title"].str.contains(
                search_keyword,
                case=False,
                na=False
            )
        ]

    display_df = diagnosis_df[
        [
            "title",
            "published_at",
            "primary_category",
            "views",
            "impressions",
            "ctr",
            "avg_percentage_viewed",
            "net_subscribers_per_1k_views",
            "performance_grade",
            "diagnosis",
        ]
    ].copy()

    display_df.columns = [
        "영상 제목",
        "게시일",
        "주제",
        "조회수",
        "노출수",
        "CTR(%)",
        "평균 조회율(%)",
        "조회수 1천 회당 순구독자",
        "성과 등급",
        "진단",
    ]

    display_df = display_df.sort_values("조회수", ascending=False)

    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        column_config={
            "게시일": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "조회수": st.column_config.NumberColumn(format="%d"),
            "노출수": st.column_config.NumberColumn(format="%d"),
            "CTR(%)": st.column_config.NumberColumn(format="%.2f"),
            "평균 조회율(%)": st.column_config.NumberColumn(format="%.1f"),
            "조회수 1천 회당 순구독자":
                st.column_config.NumberColumn(format="%.2f"),
        },
    )

    st.caption(
        "원인 진단은 같은 게시 연도의 영상 중앙값을 우선 비교해 "
        "채널 규모 변화의 영향을 줄였습니다."
    )


# ---------------------------------------------------------
# 탭 3: 주제별 성과
# ---------------------------------------------------------
with tabs[2]:
    st.subheader("제목에서 파악한 주제별 성과")

    st.warning(
        "주제는 영상 제목의 단어를 기준으로 자동 분류합니다. "
        "영상 내용 자체를 직접 분석한 결과는 아닙니다."
    )

    category_display = category_df.copy()

    category_display["영상길이_중앙값"] = category_display[
        "영상길이_중앙값"
    ].apply(seconds_to_mmss)

    category_display.columns = [
        "주제",
        "영상 수",
        "조회수 중앙값",
        "CTR 중앙값(%)",
        "평균 조회율 중앙값(%)",
        "조회수 1천 회당 순구독자 중앙값",
        "영상 길이 중앙값",
    ]

    st.dataframe(
        category_display.sort_values(
            "조회수 중앙값",
            ascending=False
        ),
        width="stretch",
        hide_index=True,
    )

    chart_metric = st.selectbox(
        "그래프로 비교할 지표",
        [
            "조회수_중앙값",
            "CTR_중앙값",
            "평균조회율_중앙값",
            "순구독자_전환_중앙값",
        ],
        format_func={
            "조회수_중앙값": "조회수 중앙값",
            "CTR_중앙값": "CTR 중앙값",
            "평균조회율_중앙값": "평균 조회율 중앙값",
            "순구독자_전환_중앙값": "조회수 1천 회당 순구독자",
        }.get,
    )

    chart_df = category_df.sort_values(chart_metric, ascending=True)

    fig = px.bar(
        chart_df,
        x=chart_metric,
        y="주제",
        orientation="h",
        title=f"주제별 {chart_metric.replace('_', ' ')}",
    )
    st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------
# 탭 4: 강화·주의 요소
# ---------------------------------------------------------
with tabs[3]:
    st.subheader("앞으로 강화하면 좋은 것")

    if strengthen:
        for item in strengthen:
            st.success(
                f"**{item['주제']}** — 영상 {int(item['영상수'])}편, "
                f"조회수 중앙값 {item['조회수_중앙값']:,.0f}회, "
                f"CTR {item['CTR_중앙값']:.1f}%, "
                f"평균 조회율 {item['평균조회율_중앙값']:.1f}%"
            )
    else:
        st.info("판단하기에 충분한 주제별 영상 수가 없습니다.")

    st.subheader("조건부로 유지할 것")

    if maintain:
        for item in maintain:
            st.info(
                f"**{item['주제']}** — 일부 지표는 평균 이상이지만 "
                "모든 성과가 일관되지는 않습니다. 포맷을 바꿔 테스트하세요."
            )
    else:
        st.info("중간 수준으로 분류된 주제가 없습니다.")

    st.subheader("축소하거나 개선할 것")

    if caution:
        for item in caution:
            st.warning(
                f"**{item['주제']}** — 영상 {int(item['영상수'])}편, "
                f"조회수 중앙값 {item['조회수_중앙값']:,.0f}회, "
                f"CTR {item['CTR_중앙값']:.1f}%, "
                f"평균 조회율 {item['평균조회율_중앙값']:.1f}%"
            )
    else:
        st.info("주의 대상으로 판단할 데이터가 부족합니다.")

    st.divider()

    st.markdown(
        """
        **판단 방식**

        한 편의 최고 조회수만 보지 않고, 주제별 영상이 3편 이상일 때
        조회수·CTR·평균 조회율·순구독자 전환의 순위를 함께 비교합니다.
        따라서 한 편의 우연한 성과보다 반복 가능성을 우선합니다.
        """
    )


# ---------------------------------------------------------
# 탭 5: 아이템 추천
# ---------------------------------------------------------
with tabs[4]:
    st.subheader("데이터 기반 아이템 추천 10개")

    st.info(
        "현재 버전은 유료 AI API를 사용하지 않습니다. "
        "채널에서 반복적으로 성과가 높았던 주제·영상 길이·제목 단어를 "
        "결합해 추천합니다."
    )

    for index, row in recommendations_df.iterrows():
        with st.expander(
            f"{index + 1}. {row['추천 아이템']}",
            expanded=index < 3,
        ):
            st.write(f"**활용 주제:** {row['활용 주제']}")
            st.write(f"**권장 영상 길이:** {row['권장 영상 길이']}")
            st.write(f"**기획 포인트:** {row['기획 포인트']}")
            st.write(f"**데이터 근거:** {row['추천 근거']}")


# ---------------------------------------------------------
# 탭 6: 다운로드
# ---------------------------------------------------------
with tabs[5]:
    st.subheader("분석 결과 다운로드")

    download_video_df = filtered_df[
        [
            "video_id",
            "title",
            "published_at",
            "primary_category",
            "views",
            "impressions",
            "ctr",
            "avg_duration_seconds",
            "avg_percentage_viewed",
            "net_subscribers",
            "net_subscribers_per_1k_views",
            "performance_grade",
            "diagnosis",
        ]
    ].copy()

    download_video_df.columns = [
        "영상 ID",
        "영상 제목",
        "게시일",
        "주제",
        "조회수",
        "노출수",
        "CTR(%)",
        "평균 시청 지속 시간(초)",
        "평균 조회율(%)",
        "순구독자",
        "조회수 1천 회당 순구독자",
        "성과 등급",
        "자동 진단",
    ]

    download_category_df = category_df.copy()

    excel_bytes = dataframe_to_excel(
        {
            "영상별 진단": download_video_df,
            "주제별 성과": download_category_df,
            "아이템 추천": recommendations_df,
        }
    )

    st.download_button(
        label="📥 분석 결과 엑셀 다운로드",
        data=excel_bytes,
        file_name=(
            f"youtube_analysis_"
            f"{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        ),
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        width="stretch",
    )


# ---------------------------------------------------------
# 분석 한계
# ---------------------------------------------------------
st.divider()

st.caption(
    "분석 한계: 본 결과는 유튜브 스튜디오 성과 데이터와 영상 제목을 "
    "기반으로 합니다. 썸네일 구성, 실제 영상 내용, 외부 화제성, "
    "광고 집행 여부 등은 확인하지 않으므로 인과관계를 확정하지 않고 "
    "통계적 가능성으로 제시합니다."
)