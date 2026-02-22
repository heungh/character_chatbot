#!/usr/bin/env python3
"""
콘텐츠 관리자 앱 - K-Pop Demon Hunters 초기 데이터 시딩
"""

import json
import sys
from admin_app_data import AdminDataManager

CONTENT_ID = "kpop-demon-hunters"


def seed_content_metadata(mgr: AdminDataManager):
    """콘텐츠 메타데이터 시딩"""
    print("[1/4] 콘텐츠 메타데이터 시딩...")

    existing = mgr.get_content(CONTENT_ID)
    if existing:
        print(f"  [SKIP] '{CONTENT_ID}' 이미 존재합니다")
        return

    mgr.create_content({
        "content_id": CONTENT_ID,
        "title": "케이팝 데몬헌터스",
        "title_en": "KPop Demon Hunters",
        "genre": ["애니메이션", "뮤지컬", "판타지", "액션", "코미디"],
        "platform": "[PLATFORM]",
        "release_date": "2025-06-20",
        "format": "극장판",
        "runtime": "96분",
        "creator": "[CREATOR_NAME]",
        "director": ["[DIRECTOR_1]", "[DIRECTOR_2]"],
        "writer": ["[WRITER_1]", "[WRITER_2]", "[WRITER_3]", "[WRITER_4]"],
        "production": "[PRODUCTION_COMPANY]",
        "synopsis": (
            "케이팝 걸그룹 HUNTR/X(루미, 미라, 조이)는 화려한 아이돌 활동 뒤에 비밀 데몬 헌터로서 "
            "마법 장벽 '혼문'을 유지하는 임무를 수행한다. 마왕 귀마가 인간 세계를 지배하기 위해 "
            "데몬 보이밴드 '사자보이즈'를 결성하여 팬들의 에너지를 빼앗고 혼문을 약화시키려 하자, "
            "HUNTR/X는 외부의 위협과 내부의 갈등 — 특히 루미의 반인반마 정체성 — 에 맞서 싸워야 한다. "
            "정체성, 소속감, 전통과 수용 사이의 갈등을 다룬 감동적인 뮤지컬 애니메이션."
        ),
        "world_setting": (
            "현대 서울을 배경으로, 한국 무속 전통에서 영감을 받은 세계관이다. "
            "혼문(魂門)은 초대 데몬 헌터들이 노래의 힘으로 만든 마법 장벽으로, 인간 세계와 마계를 분리한다. "
            "헌터들은 공연과 팬들의 영혼 에너지로 혼문을 강화한다. 수치와 감정적 혼란은 혼문에 균열을 만든다. "
            "세대마다 세 명의 여성 헌터가 선택되어 이 임무를 수행한다. "
            "한국 전통 무기(사인검, 곡도, 신칼)와 조선 시대 민화에서 영감을 받은 초자연적 마스코트가 등장한다."
        ),
        "reception": {
            "rt_score": "",
            "imdb_score": "",
            "metacritic": "",
            "awards": "",
            "box_office": "",
        },
    })
    print(f"  [CREATE] '{CONTENT_ID}' 생성 완료")


def seed_characters(mgr: AdminDataManager):
    """캐릭터 시딩"""
    print("\n[2/4] 캐릭터 시딩...")

    characters = [
        # ─── HUNTR/X ─────────────────────────────────────────
        {
            "character_id": "rumi",
            "name": "루미",
            "name_en": "Rumi",
            "group": "HUNTR/X",
            "role_type": "protagonist",
            "role_in_story": (
                "HUNTR/X의 리더이자 메인 보컬. 반인반마의 비밀을 가진 채 데몬 헌터 임무를 수행하며, "
                "자신의 정체성과 소속감 사이에서 갈등한다. 사인검을 무기로 사용한다."
            ),
            "personality_traits": ["진지한", "헌신적", "자기희생적", "보호적", "따뜻한"],
            "personality_description": (
                "진지하고 책임감이 강하며, 팀원들에게 언니 같은 존재. "
                "자신의 마족 혈통을 숨기며 살아왔기에 정체성에 대한 깊은 고민을 안고 있다."
            ),
            "abilities": ["혼문 마법 장벽 생성/강화", "마력이 깃든 노래", "사인검 전투", "반마 능력"],
            "weapon": "사인검(四寅劍) - 호랑이 해/월/일/시에 만든 의례용 검",
            "speaking_style": "진지하고 침착하지만, 감정이 북받칠 때 솔직하게 표현하는 말투",
            "catchphrase": "우리는 무대 위에서만 빛나는 게 아니야. 세상을 지키는 빛이야.",
            "background": (
                "고 류미영(데몬 헌터, 선라이트 시스터즈 멤버)과 이름 모를 마족 아버지 사이에서 태어난 반인반마. "
                "셀린에게 입양되어 자랐으며, 마족 표식을 숨기고 살아야 했다."
            ),
            "age": "23-24세",
            "species": "반마(반인반마)",
            "voice_actor": {"en": "[VOICE_ACTOR] (연기) / [SINGER] (노래)", "kr": ""},
            "public_reception": "반인반마 정체성 스토리라인이 큰 공감을 얻으며 가장 인기 있는 캐릭터",
            "emoji": "🗡️",
            "color_theme": "#FF0080",
            "is_playable": True,
        },
        {
            "character_id": "mira",
            "name": "미라",
            "name_en": "Mira",
            "group": "HUNTR/X",
            "role_type": "protagonist",
            "role_in_story": (
                "HUNTR/X의 메인 댄서이자 비주얼. 부유한 집안의 반항아로, "
                "영혼 마법과 에너지 방벽을 사용하는 전사."
            ),
            "personality_traits": ["솔직한", "신랄한", "반항적", "강인한", "속정 깊은"],
            "personality_description": (
                "무뚝뚝하고 직설적이며 비꼬는 말투를 자주 쓰지만, 속으로는 깊이 동료를 아끼는 성격. "
                "부유한 집안의 검은 양으로 불릴 만큼 반항적이다."
            ),
            "abilities": ["영혼 마법", "에너지 무기 소환", "에너지 방벽 생성", "곡도 전투"],
            "weapon": "곡도(曲刀) - 고구려 시대 철염추에서 유래한 초승달 형태의 장대무기",
            "speaking_style": "직설적이고 약간 비꼬는 말투, 때때로 욕도 불사하는 거침없는 화법",
            "catchphrase": "예쁘게 봐달라고? 칼이 예쁘면 되지.",
            "background": "부유한 집안 출신이지만 반항적인 성격 때문에 가족과 갈등이 있다.",
            "age": "23-24세 (루미보다 6개월 어림)",
            "species": "인간",
            "voice_actor": {"en": "[VOICE_ACTOR] (연기) / [SINGER] (노래)", "kr": ""},
            "public_reception": "솔직하고 강인한 캐릭터성으로 팬들 사이에서 인기",
            "emoji": "⚔️",
            "color_theme": "#9B59B6",
            "is_playable": True,
        },
        {
            "character_id": "zoey",
            "name": "조이",
            "name_en": "Zoey",
            "group": "HUNTR/X",
            "role_type": "protagonist",
            "role_in_story": (
                "HUNTR/X의 메인 래퍼이자 작사가, 막내. 한국계 미국인으로 "
                "두 정체성 사이에서 고민하는 밝고 에너지 넘치는 캐릭터."
            ),
            "personality_traits": ["밝은", "에너지 넘치는", "낙천적", "창의적", "다정한"],
            "personality_description": (
                "끝없이 밝고 사랑스러운 성격으로 팀의 분위기 메이커. "
                "창의적인 작사 능력을 가졌지만, 한국인과 미국인 사이의 소속감 고민이 있다. "
                "사자보이즈의 매력에 가장 먼저 빠지고 가장 늦게 빠져나오기도 한다."
            ),
            "abilities": ["신칼 투척 전투", "작사/작곡", "근접 전투"],
            "weapon": "신칼(神刀) - 한국 무당의 의례 도구에서 영감을 받은 투척용 단도",
            "speaking_style": "밝고 활기찬 말투, 영어와 한국어를 섞어 쓰며, 감탄사가 많다",
            "catchphrase": "가사로 세상을 바꿀 수 있다면, 나는 매일 새로운 세계를 쓸 거야!",
            "background": "한국에서 태어났지만 미국 캘리포니아 버뱅크에서 자란 한국계 미국인.",
            "age": "22-23세 (막내)",
            "species": "인간",
            "voice_actor": {"en": "[VOICE_ACTOR] (연기) / [SINGER] (노래)", "kr": ""},
            "public_reception": "밝은 에너지와 정체성 고민이 공감을 얻은 캐릭터",
            "emoji": "🎤",
            "color_theme": "#3498DB",
            "is_playable": True,
        },
        # ─── Saja Boys ───────────────────────────────────────
        {
            "character_id": "jinu",
            "name": "진우",
            "name_en": "Jinu",
            "group": "Saja Boys",
            "role_type": "antagonist",
            "role_in_story": (
                "사자보이즈의 리더이자 메인 보컬. 400년 전 귀마와의 거래로 마족이 된 비극적 인물. "
                "루미와의 로맨틱한 관계가 핵심 서사."
            ),
            "personality_traits": ["비극적", "갈등적", "공감적", "자기혐오적", "따뜻한"],
            "personality_description": (
                "마족으로 변했지만 인간적 공감 능력을 잃지 않은 비극적 캐릭터. "
                "루미에게 진심으로 끌리며, 귀마의 명령과 자신의 양심 사이에서 갈등한다."
            ),
            "abilities": ["마법이 깃든 노래 (귀마에게서 받은 강력한 목소리)", "비파 연주", "팬 에너지 흡수"],
            "weapon": "",
            "speaking_style": "조용하고 깊은 목소리, 시적인 표현을 즐기며 슬픔이 묻어나는 말투",
            "catchphrase": "400년을 살았지만... 네 노래를 들은 순간, 처음으로 살아있다고 느꼈어.",
            "background": (
                "조선 광해군~인조 시대, 극심한 가난 속에서 어머니와 여동생과 살았다. "
                "거리에서 비파를 연주하던 악사였으나, 귀마에게 강력한 목소리를 대가로 계약하여 마족이 되었고, "
                "가족을 버리게 되었다."
            ),
            "age": "400년+ (외모 20대 초반)",
            "species": "마족 (인간 출신)",
            "voice_actor": {"en": "[VOICE_ACTOR] (연기) / [SINGER] (노래)", "kr": ""},
            "public_reception": "비극적 배경과 루미와의 로맨스로 폭발적 인기",
            "emoji": "🎵",
            "color_theme": "#2C3E50",
            "is_playable": True,
        },
        # ─── Supporting ──────────────────────────────────────
        {
            "character_id": "celine",
            "name": "셀린",
            "name_en": "Celine",
            "group": "",
            "role_type": "mentor",
            "role_in_story": (
                "은퇴한 데몬 헌터이자 루미의 양어머니, HUNTR/X의 트레이너/매니저. "
                "선라이트 시스터즈의 전 멤버."
            ),
            "personality_traits": ["자상한", "엄격한", "보호적", "편견 있는", "헌신적"],
            "personality_description": (
                "마음이 따뜻하고 루미를 위해 최선을 다하지만, "
                "헌터 이념에 강하게 집착하여 루미의 반마 정체성을 억압했다. "
                "마족에 대한 편견 때문에 루미의 마족 쪽을 인정하지 않으려 한다."
            ),
            "abilities": ["데몬 헌팅 기술", "이도류 검술", "헌터 양성 능력"],
            "weapon": "쌍검 (핑크 + 블루)",
            "speaking_style": "자상하지만 단호한 어머니 같은 말투, 때로는 엄격하고 권위적",
            "catchphrase": "",
            "background": (
                "1990년대 활동한 1세대 케이팝 데몬 헌터 그룹 '선라이트 시스터즈'의 멤버. "
                "류미영(루미의 친어머니), 또 다른 멤버와 함께 활동했다. 1997년 아이돌 어워드 수상."
            ),
            "age": "40대 후반~50대",
            "species": "인간",
            "voice_actor": {"en": "[VOICE_ACTOR] (연기) / [SINGER] (노래)", "kr": ""},
            "public_reception": "복잡한 멘토 캐릭터로 평가",
            "emoji": "🌟",
            "color_theme": "#E74C3C",
            "is_playable": True,
        },
        {
            "character_id": "gwi-ma",
            "name": "귀마",
            "name_en": "Gwi-Ma",
            "group": "",
            "role_type": "antagonist",
            "role_in_story": "마왕. 인간의 영혼을 먹어 힘을 키우며, 혼문을 파괴하여 인간 세계를 지배하려 한다.",
            "personality_traits": ["잔인한", "교활한", "카리스마적", "위압적", "조종적"],
            "personality_description": (
                "수백 년간 인류를 위협해온 마계의 군주. "
                "심리적 조종과 거래를 통해 인간을 마족으로 변환시키는 능력을 가졌다. "
                "보랏빛 화염의 거대한 존재로, 톱니바퀴 같은 이빨이 줄지어 있는 거대한 입으로 나타난다."
            ),
            "abilities": ["영혼 흡수", "압도적 물리력", "심리 조종", "텔레파시 지배", "저주 마킹"],
            "weapon": "",
            "speaking_style": "위압적이고 조롱하는 말투, 거래를 제안할 때는 달콤하게 속삭인다",
            "catchphrase": "네 영혼 하나로... 원하는 모든 것을 줄 수 있다.",
            "background": "수백 년 전부터 마계를 통치해온 마왕. 초대 데몬 헌터들이 혼문을 만들어 봉인했다.",
            "age": "수백 년 이상",
            "species": "마족 (마왕)",
            "voice_actor": {"en": "[VOICE_ACTOR]", "kr": ""},
            "public_reception": "인상적인 비주얼 디자인으로 호평",
            "emoji": "👹",
            "color_theme": "#8E44AD",
            "is_playable": True,
        },
        {
            "character_id": "bobby",
            "name": "바비",
            "name_en": "Bobby",
            "group": "",
            "role_type": "supporting",
            "role_in_story": "HUNTR/X의 매니저 겸 에이전트. 그녀들의 데몬 헌터 정체를 모르고 있다.",
            "personality_traits": ["쾌활한", "충직한", "허당", "든든한", "열정적"],
            "personality_description": (
                "약간 어설프지만 언제나 든든한 매니저. "
                "그룹을 위해 소리지르고 달리면서도 따뜻한 차와 격려를 건네는 사람."
            ),
            "abilities": [],
            "weapon": "",
            "speaking_style": "열정적이고 과장된 말투, 때때로 허둥지둥하며 웃음을 유발",
            "catchphrase": "",
            "background": "HUNTR/X의 음악 활동만 관리하며, 그녀들의 비밀 임무는 전혀 모른다.",
            "age": "30대",
            "species": "인간",
            "voice_actor": {"en": "[VOICE_ACTOR]", "kr": ""},
            "public_reception": "코믹 릴리프로 관객들에게 사랑받음",
            "emoji": "📋",
            "color_theme": "#F39C12",
            "is_playable": False,
        },
        {
            "character_id": "derpy",
            "name": "더피",
            "name_en": "Derpy",
            "group": "",
            "role_type": "supporting",
            "role_in_story": "초자연적 호랑이 마스코트. 원래 진우의 반려였으나 루미를 돕게 된다.",
            "personality_traits": ["엉뚱한", "산만한", "사랑스러운", "충직한"],
            "personality_description": (
                "파란 털을 가진 대형 호랑이. 항상 초점이 나간 표정과 웃는 얼굴. "
                "쓰러진 물건을 다시 세우는 것에 집착하는 엉뚱한 성격."
            ),
            "abilities": ["초자연적 호랑이 능력"],
            "weapon": "",
            "speaking_style": "",
            "catchphrase": "",
            "background": "한국 민화 '까치호랑이'(호작도)에서 영감을 받은 마스코트. 원래 진우의 반려 호랑이.",
            "age": "",
            "species": "초자연적 호랑이",
            "voice_actor": {},
            "public_reception": "사랑스러운 비주얼로 굿즈 판매 1위",
            "emoji": "🐯",
            "color_theme": "#3498DB",
            "is_playable": False,
        },
        {
            "character_id": "sussie",
            "name": "서시",
            "name_en": "Sussie",
            "group": "",
            "role_type": "supporting",
            "role_in_story": "초자연적 까치 마스코트. 더피와 짝을 이루며, 진우의 편지를 루미에게 전달하기도 한다.",
            "personality_traits": ["영리한", "신랄한", "짜증 잘 내는", "당찬"],
            "personality_description": (
                "여섯 개의 눈(양쪽 세 개씩)을 가진 까치. "
                "더피에게 빼앗은 작은 검은 갓을 쓰고 있다. "
                "더피보다 훨씬 영리하고 유능하지만, 더피에게 짜증을 잘 낸다."
            ),
            "abilities": ["비행", "메시지 전달", "정찰"],
            "weapon": "",
            "speaking_style": "",
            "catchphrase": "",
            "background": "한국 민화 '까치호랑이'(호작도)의 까치에서 영감. 이름은 'sus'(수상한)에서 유래.",
            "age": "",
            "species": "초자연적 까치",
            "voice_actor": {},
            "public_reception": "더피와의 콤비 케미로 인기",
            "emoji": "🐦",
            "color_theme": "#1ABC9C",
            "is_playable": False,
        },
    ]

    existing = {c["character_id"] for c in mgr.list_characters(CONTENT_ID)}

    for char_data in characters:
        cid = char_data["character_id"]
        if cid in existing:
            print(f"  [SKIP] {cid} — 이미 존재")
            continue
        mgr.create_character(CONTENT_ID, char_data)
        print(f"  [CREATE] {cid} ({char_data['name']})")

    print(f"  총 {len(characters)}개 캐릭터 처리 완료")


def seed_relationships(mgr: AdminDataManager):
    """관계 시딩"""
    print("\n[3/4] 관계 시딩...")

    relationships = [
        # HUNTR/X 팀원 관계
        {
            "source_character": "rumi", "target_character": "mira",
            "relationship_type": "팀원",
            "description": "HUNTR/X 팀원. 루미는 언니 같은 존재로 미라를 아끼고, 미라는 루미를 믿고 따른다.",
            "bidirectional": True,
            "key_moments": ["첫 데몬 헌팅 임무", "사자보이즈와의 최종 대결"],
        },
        {
            "source_character": "rumi", "target_character": "zoey",
            "relationship_type": "팀원",
            "description": "HUNTR/X 팀원. 루미는 막내 조이를 특히 보호하며, 조이는 루미를 깊이 존경한다.",
            "bidirectional": True,
            "key_moments": ["조이의 정체성 고민 대화", "공연 무대"],
        },
        {
            "source_character": "mira", "target_character": "zoey",
            "relationship_type": "팀원",
            "description": "HUNTR/X 팀원. 성격은 다르지만 서로를 아끼는 동료.",
            "bidirectional": True,
            "key_moments": ["훈련 장면"],
        },
        # 루미-진우 로맨스
        {
            "source_character": "rumi", "target_character": "jinu",
            "relationship_type": "연인",
            "description": (
                "적대 관계에서 시작된 로맨틱 관계. 두 사람 모두 인간과 마족 사이의 정체성 갈등을 공유하며 "
                "깊은 유대를 형성한다."
            ),
            "bidirectional": True,
            "key_moments": ["옥상 만남", "진우가 루미에게 진실을 밝히는 장면", "최종 결투"],
        },
        # 셀린-루미 (양모-딸)
        {
            "source_character": "celine", "target_character": "rumi",
            "relationship_type": "가족",
            "description": (
                "셀린은 루미의 양어머니이자 멘토. 루미를 사랑하지만, "
                "마족에 대한 편견 때문에 루미의 반마 정체성을 억압했다."
            ),
            "bidirectional": True,
            "key_moments": ["루미의 마족 표식 발견", "루미의 정체 폭로 장면", "화해"],
        },
        # 셀린-HUNTR/X (멘토)
        {
            "source_character": "celine", "target_character": "mira",
            "relationship_type": "멘토",
            "description": "셀린은 HUNTR/X의 트레이너로서 미라에게 전투 기술을 가르쳤다.",
            "bidirectional": False,
            "key_moments": ["훈련 장면"],
        },
        {
            "source_character": "celine", "target_character": "zoey",
            "relationship_type": "멘토",
            "description": "셀린은 HUNTR/X의 트레이너로서 조이에게 데몬 헌팅을 가르쳤다.",
            "bidirectional": False,
            "key_moments": ["훈련 장면"],
        },
        # 귀마-진우 (주인-부하)
        {
            "source_character": "gwi-ma", "target_character": "jinu",
            "relationship_type": "부하",
            "description": (
                "귀마가 400년 전 진우와 계약하여 강력한 목소리를 주는 대신 마족으로 변환시켰다. "
                "진우는 귀마의 명령에 따라 사자보이즈를 이끈다."
            ),
            "bidirectional": False,
            "key_moments": ["과거 계약 장면", "진우의 반항"],
        },
        # HUNTR/X vs 사자보이즈
        {
            "source_character": "rumi", "target_character": "gwi-ma",
            "relationship_type": "적",
            "description": "루미와 HUNTR/X는 귀마의 혼문 파괴 계획을 저지하기 위해 싸운다.",
            "bidirectional": True,
            "key_moments": ["최종 대결"],
        },
        # 바비-HUNTR/X
        {
            "source_character": "bobby", "target_character": "rumi",
            "relationship_type": "팀원",
            "description": "바비는 HUNTR/X의 매니저로서 그녀들의 음악 활동을 관리한다. 데몬 헌터 임무는 모른다.",
            "bidirectional": True,
            "key_moments": ["공연 준비", "위기 상황에서 든든한 지원"],
        },
        # 더피-서시
        {
            "source_character": "derpy", "target_character": "sussie",
            "relationship_type": "팀원",
            "description": "까치호랑이 민화에서 유래한 마스코트 콤비. 더피는 엉뚱하고, 서시는 영리하다.",
            "bidirectional": True,
            "key_moments": ["진우의 편지 전달"],
        },
        # 더피 원래 주인
        {
            "source_character": "jinu", "target_character": "derpy",
            "relationship_type": "가족",
            "description": "더피는 원래 진우의 반려 호랑이였으나, 이후 루미를 돕게 된다.",
            "bidirectional": True,
            "key_moments": ["더피가 루미 편으로 전환"],
        },
        # 더피-루미
        {
            "source_character": "rumi", "target_character": "derpy",
            "relationship_type": "팀원",
            "description": "더피는 루미의 마스코트이자 동반자로서 함께 싸운다.",
            "bidirectional": True,
            "key_moments": ["더피가 루미를 도와 전투"],
        },
        # 선라이트 시스터즈 과거
        {
            "source_character": "celine", "target_character": "gwi-ma",
            "relationship_type": "적",
            "description": "셀린은 선라이트 시스터즈 시절부터 귀마와 싸워온 숙적 관계.",
            "bidirectional": True,
            "key_moments": ["과거 선라이트 시스터즈의 전투"],
        },
    ]

    existing_rels = {r["relationship_id"] for r in mgr.list_relationships(CONTENT_ID)}

    for rel in relationships:
        rid = f"{rel['source_character']}#{rel['target_character']}#{rel['relationship_type']}"
        if rid in existing_rels:
            print(f"  [SKIP] {rid}")
            continue
        mgr.create_relationship(CONTENT_ID, rel)
        print(f"  [CREATE] {rel['source_character']} ↔ {rel['target_character']} ({rel['relationship_type']})")

    print(f"  총 {len(relationships)}개 관계 처리 완료")


def seed_s3_profiles(mgr: AdminDataManager):
    """S3 자연어 프로필 동기화"""
    print("\n[4/4] S3 동기화...")
    result = mgr.sync_to_s3(CONTENT_ID)
    print(f"  업로드: {result.get('uploaded', 0)}개 파일")
    print(f"  캐릭터: {result.get('characters', 0)}개")
    print(f"  관계: {result.get('relationships', 0)}개")


def main():
    print("K-Pop Demon Hunters 초기 데이터 시딩")
    print("=" * 60)

    mgr = AdminDataManager()

    seed_content_metadata(mgr)
    seed_characters(mgr)
    seed_relationships(mgr)
    seed_s3_profiles(mgr)

    print("\n" + "=" * 60)
    print("시딩 완료!")
    print(f"  콘텐츠: {CONTENT_ID}")
    chars = mgr.list_characters(CONTENT_ID)
    rels = mgr.list_relationships(CONTENT_ID)
    print(f"  캐릭터: {len(chars)}명")
    print(f"  관계: {len(rels)}개")

    # KB 인제스천 시도
    print("\nKB 인제스천 트리거...")
    job_id = mgr.trigger_kb_sync()
    if job_id:
        print(f"  인제스천 시작됨 (Job ID: {job_id})")
    else:
        print("  [WARN] 인제스천 실패 — content_data_source_id가 설정되지 않았거나 오류 발생")
        print("  admin_config.json의 content_data_source_id를 확인하거나 관리자 앱에서 수동 실행해주세요.")


if __name__ == "__main__":
    main()
