"""요양시설 테스트용 PDF 데이터 생성 스크립트.

생성 파일:
  - data/contracts/  : 요양시설 계약서 10개 (PDF)
  - data/care_records/: 생활기록 보고서 10명 × 1주 (PDF)
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

from fpdf import FPDF

FONT_PATH = "C:/Windows/Fonts/malgun.ttf"
CONTRACTS_DIR = Path("data/contracts")
CARE_DIR = Path("data/care_records")

# ── 공통 데이터 ─────────────────────────────────────────────────

FACILITY_NAME = "행복한 요양원"
FACILITY_ADDR = "서울특별시 강남구 역삼로 123"
FACILITY_TEL = "02-1234-5678"
FACILITY_DIRECTOR = "김영수"

PATIENTS = [
    {"name": "박순자", "age": 82, "grade": 3, "guardian": "박민호", "guardian_rel": "아들", "guardian_tel": "010-1111-2222"},
    {"name": "이영희", "age": 78, "grade": 2, "guardian": "이수진", "guardian_rel": "딸", "guardian_tel": "010-2222-3333"},
    {"name": "김말순", "age": 85, "grade": 4, "guardian": "김태영", "guardian_rel": "아들", "guardian_tel": "010-3333-4444"},
    {"name": "정옥순", "age": 79, "grade": 2, "guardian": "정하나", "guardian_rel": "딸", "guardian_tel": "010-4444-5555"},
    {"name": "최복희", "age": 88, "grade": 5, "guardian": "최준혁", "guardian_rel": "손자", "guardian_tel": "010-5555-6666"},
    {"name": "한금자", "age": 81, "grade": 3, "guardian": "한서연", "guardian_rel": "딸", "guardian_tel": "010-6666-7777"},
    {"name": "윤정숙", "age": 76, "grade": 1, "guardian": "윤재민", "guardian_rel": "아들", "guardian_tel": "010-7777-8888"},
    {"name": "장영순", "age": 84, "grade": 3, "guardian": "장미래", "guardian_rel": "손녀", "guardian_tel": "010-8888-9999"},
    {"name": "송옥자", "age": 90, "grade": 4, "guardian": "송현우", "guardian_rel": "아들", "guardian_tel": "010-9999-0000"},
    {"name": "오말이", "age": 77, "grade": 2, "guardian": "오지은", "guardian_rel": "딸", "guardian_tel": "010-0000-1111"},
]

SERVICE_TYPES = [
    "재가방문요양", "주야간보호", "시설입소", "단기보호",
    "재가방문목욕", "재가방문간호",
]


# ── PDF 헬퍼 ────────────────────────────────────────────────────

class KoreanPDF(FPDF):
    """fpdf2 wrapper with Korean font support."""

    def __init__(self) -> None:
        super().__init__()
        self.add_font("malgun", "", FONT_PATH)
        self.add_font("malgun", "B", "C:/Windows/Fonts/malgunbd.ttf")
        self.set_auto_page_break(auto=True, margin=20)

    def title_block(self, text: str) -> None:
        self.set_font("malgun", "B", 16)
        self.cell(0, 12, text, align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(6)

    def subtitle(self, text: str) -> None:
        self.set_font("malgun", "B", 12)
        self.cell(0, 10, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def body_text(self, text: str) -> None:
        self.set_font("malgun", "", 10)
        self.multi_cell(0, 7, text)
        self.ln(2)

    def label_value(self, label: str, value: str) -> None:
        self.set_font("malgun", "B", 10)
        self.cell(40, 7, label)
        self.set_font("malgun", "", 10)
        self.cell(0, 7, value, new_x="LMARGIN", new_y="NEXT")

    def separator(self) -> None:
        self.ln(3)
        y = self.get_y()
        self.line(10, y, 200, y)
        self.ln(5)


# ── 계약서 생성 ─────────────────────────────────────────────────

def generate_contract(patient: dict, index: int) -> None:
    """요양시설 이용 계약서 PDF 생성."""
    pdf = KoreanPDF()
    pdf.add_page()

    service = random.choice(SERVICE_TYPES)
    start_date = datetime(2025, random.randint(1, 6), random.randint(1, 28))
    end_date = start_date + timedelta(days=365)
    monthly_fee = random.choice([800_000, 1_000_000, 1_200_000, 1_500_000, 1_800_000])
    copay_rate = random.choice([15, 20])

    pdf.title_block("장기요양급여 이용 계약서")
    pdf.separator()

    pdf.subtitle("제1조 (계약 당사자)")
    pdf.body_text(
        f"갑 (시설): {FACILITY_NAME}\n"
        f"주소: {FACILITY_ADDR}\n"
        f"전화: {FACILITY_TEL}\n"
        f"대표자: {FACILITY_DIRECTOR}\n\n"
        f"을 (이용자): {patient['name']} (만 {patient['age']}세)\n"
        f"장기요양등급: {patient['grade']}등급\n"
        f"보호자: {patient['guardian']} ({patient['guardian_rel']})\n"
        f"보호자 연락처: {patient['guardian_tel']}"
    )

    pdf.subtitle("제2조 (서비스 내용)")
    pdf.body_text(
        f"1. 서비스 유형: {service}\n"
        f"2. 계약 기간: {start_date.strftime('%Y년 %m월 %d일')} ~ {end_date.strftime('%Y년 %m월 %d일')}\n"
        f"3. 서비스 제공 시간: 매일 08:00 ~ 18:00 (시설입소의 경우 24시간)\n"
        f"4. 서비스 장소: {FACILITY_NAME} ({FACILITY_ADDR})"
    )

    pdf.subtitle("제3조 (비용)")
    pdf.body_text(
        f"1. 월 이용료: {monthly_fee:,}원\n"
        f"2. 본인부담금 비율: {copay_rate}%\n"
        f"3. 본인부담금: 월 {int(monthly_fee * copay_rate / 100):,}원\n"
        f"4. 식대: 월 300,000원 (별도)\n"
        f"5. 납부일: 매월 5일까지 (계좌이체 또는 카드결제)"
    )

    pdf.subtitle("제4조 (시설의 의무)")
    pdf.body_text(
        "1. 시설은 이용자에게 장기요양급여를 성실히 제공한다.\n"
        "2. 이용자의 건강 상태를 정기적으로 확인하고 보호자에게 보고한다.\n"
        "3. 이용자의 안전을 위한 적절한 조치를 취한다.\n"
        "4. 이용자의 개인정보를 보호하고 관련 법규를 준수한다.\n"
        "5. 시설 내 감염 예방 및 위생 관리를 철저히 한다."
    )

    pdf.subtitle("제5조 (이용자 및 보호자의 의무)")
    pdf.body_text(
        "1. 이용자는 시설의 규칙을 준수한다.\n"
        "2. 보호자는 이용료를 기한 내에 납부한다.\n"
        "3. 이용자의 건강 상태 변화 시 즉시 시설에 알린다.\n"
        "4. 계약 해지 시 최소 30일 전에 서면으로 통보한다."
    )

    pdf.subtitle("제6조 (계약 해지)")
    pdf.body_text(
        "1. 양 당사자는 30일 전 서면 통보로 계약을 해지할 수 있다.\n"
        "2. 이용자의 건강 악화로 서비스 제공이 불가능한 경우 즉시 해지 가능하다.\n"
        "3. 이용료 미납 시 시설은 서면 최고 후 계약을 해지할 수 있다."
    )

    pdf.subtitle("제7조 (손해배상)")
    pdf.body_text(
        "1. 시설의 과실로 이용자에게 손해가 발생한 경우 시설이 배상한다.\n"
        "2. 이용자 또는 보호자의 과실로 시설에 손해가 발생한 경우 이용자 측이 배상한다."
    )

    pdf.subtitle("제8조 (개인정보 처리)")
    pdf.body_text(
        "1. 시설은 서비스 제공에 필요한 최소한의 개인정보만 수집한다.\n"
        "2. 수집된 개인정보는 서비스 목적 이외로 사용하지 않는다.\n"
        "3. 개인정보 보유 기간은 계약 종료 후 3년이다."
    )

    pdf.separator()
    pdf.ln(10)
    pdf.body_text(
        f"위 계약 내용에 동의하며 본 계약서를 작성합니다.\n\n"
        f"계약일: {start_date.strftime('%Y년 %m월 %d일')}\n\n"
        f"시설 대표:  {FACILITY_DIRECTOR}  (서명)\n\n"
        f"이용자:  {patient['name']}  (서명)\n\n"
        f"보호자:  {patient['guardian']}  (서명)"
    )

    filename = f"contract_{index + 1:02d}_{patient['name']}.pdf"
    pdf.output(str(CONTRACTS_DIR / filename))
    print(f"  [계약서] {filename}")


# ── 생활기록 생성 ───────────────────────────────────────────────

def generate_care_record(patient: dict, index: int) -> None:
    """주간 생활기록 보고서 PDF 생성."""
    pdf = KoreanPDF()
    pdf.add_page()

    # 보고 기간: 최근 1주일 기준
    end_date = datetime(2026, 3, 14)
    start_date = end_date - timedelta(days=6)

    pdf.title_block("주간 생활기록 보고서")
    pdf.separator()

    pdf.label_value("시설명:", FACILITY_NAME)
    pdf.label_value("이용자:", f"{patient['name']} (만 {patient['age']}세, {patient['grade']}등급)")
    pdf.label_value("보호자:", f"{patient['guardian']} ({patient['guardian_rel']})")
    pdf.label_value("보고 기간:", f"{start_date.strftime('%Y.%m.%d')} ~ {end_date.strftime('%Y.%m.%d')}")
    pdf.label_value("작성일:", end_date.strftime("%Y년 %m월 %d일"))
    pdf.separator()

    # 체중 변화
    base_weight = random.uniform(40.0, 70.0)
    pdf.subtitle("1. 체중 변화")
    weights = []
    for i in range(7):
        day = start_date + timedelta(days=i)
        w = round(base_weight + random.uniform(-0.5, 0.5), 1)
        weights.append(w)
        pdf.body_text(f"  {day.strftime('%m/%d(%a)')}: {w} kg")
    avg_w = round(sum(weights) / len(weights), 1)
    trend = "안정" if abs(weights[-1] - weights[0]) < 1.0 else ("증가" if weights[-1] > weights[0] else "감소")
    pdf.body_text(f"  → 주간 평균: {avg_w} kg / 추세: {trend}")

    # 식사
    pdf.subtitle("2. 식사 상태")
    meal_statuses = ["양호", "보통", "양호", "양호", "보통", "양호", "양호"]
    random.shuffle(meal_statuses)
    for i in range(7):
        day = start_date + timedelta(days=i)
        meal = meal_statuses[i]
        portion = random.choice(["전량 섭취", "2/3 섭취", "1/2 섭취", "전량 섭취", "전량 섭취"])
        pdf.body_text(f"  {day.strftime('%m/%d(%a)')}: {meal} ({portion})")
    pdf.body_text(f"  → 특이사항: {random.choice(['없음', '죽식 선호', '간식 요청 있음', '없음', '없음'])}")

    # 수면
    pdf.subtitle("3. 수면 상태")
    for i in range(7):
        day = start_date + timedelta(days=i)
        hours = random.choice([5, 6, 7, 7, 8, 8, 6])
        quality = "양호" if hours >= 7 else "보통"
        pdf.body_text(f"  {day.strftime('%m/%d(%a)')}: {hours}시간 ({quality})")
    pdf.body_text(f"  → 특이사항: {random.choice(['없음', '야간 1회 기상', '없음', '수면 보조제 복용 중', '없음'])}")

    # 활동
    pdf.subtitle("4. 일상 활동")
    activities = [
        "산책 (시설 내 정원)", "체조 프로그램 참여",
        "미술 치료 참여", "음악 감상", "가족 영상통화",
        "물리치료", "종교 활동 참여",
    ]
    random.shuffle(activities)
    for i in range(7):
        day = start_date + timedelta(days=i)
        acts = random.sample(activities, k=random.randint(1, 3))
        pdf.body_text(f"  {day.strftime('%m/%d(%a)')}: {', '.join(acts)}")

    # 건강 상태
    pdf.subtitle("5. 건강 상태")
    bp_sys = random.randint(110, 145)
    bp_dia = random.randint(65, 90)
    temp = round(random.uniform(36.0, 36.8), 1)
    pulse = random.randint(60, 85)
    pdf.body_text(
        f"  혈압: {bp_sys}/{bp_dia} mmHg (주간 평균)\n"
        f"  체온: {temp}°C\n"
        f"  맥박: {pulse}회/분\n"
        f"  복용 약물: {random.choice(['혈압약, 당뇨약', '혈압약', '관절약, 수면보조제', '혈압약, 소화제'])}\n"
        f"  병원 방문: {random.choice(['없음', '정기 검진 (3/12)', '없음', '치과 방문 (3/10)'])}"
    )

    # 특이사항 및 종합 소견
    pdf.subtitle("6. 특이사항 및 종합 소견")
    observations = [
        "전반적으로 안정적인 상태이며 프로그램 참여도가 높습니다.",
        "식사량이 약간 줄었으나 건강에 큰 영향은 없습니다.",
        "활동량이 늘어 컨디션이 좋아 보입니다.",
        "야간 수면이 다소 불안정하여 관찰 중입니다.",
        "체중이 소폭 감소하여 영양 관리에 주의하고 있습니다.",
        "보호자 면회 후 기분이 좋아져 활동 참여도가 높아졌습니다.",
    ]
    pdf.body_text(random.choice(observations))

    pdf.separator()
    pdf.ln(5)
    pdf.body_text(
        f"작성자: {random.choice(['김은지', '박서현', '이지영', '정민수'])} "
        f"({random.choice(['사회복지사', '간병인', '요양보호사'])})\n"
        f"시설장: {FACILITY_DIRECTOR}"
    )

    filename = f"care_record_{index + 1:02d}_{patient['name']}.pdf"
    pdf.output(str(CARE_DIR / filename))
    print(f"  [생활기록] {filename}")


# ── 메인 ────────────────────────────────────────────────────────

def main() -> None:
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    CARE_DIR.mkdir(parents=True, exist_ok=True)

    random.seed(42)

    print("=== 요양시설 계약서 생성 (10개) ===")
    for i, patient in enumerate(PATIENTS):
        generate_contract(patient, i)

    print()
    print("=== 주간 생활기록 보고서 생성 (10명) ===")
    for i, patient in enumerate(PATIENTS):
        generate_care_record(patient, i)

    print()
    print(f"완료! contracts: {len(list(CONTRACTS_DIR.glob('*.pdf')))}개, "
          f"care_records: {len(list(CARE_DIR.glob('*.pdf')))}개")


if __name__ == "__main__":
    main()
