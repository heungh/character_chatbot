#!/usr/bin/env python3
"""
케이팝 데몬헌터스 Knowledge Base 설정 및 데이터 동기화
"""

import boto3
import json
import time
from pathlib import Path

class KnowledgeBaseSetup:
    def __init__(self):
        self.bedrock_agent_client = boto3.client(
            "bedrock-agent",
            region_name="us-east-1"
        )
        self.s3_client = boto3.client("s3", region_name="us-east-1")
        
    def create_knowledge_base(self, name: str, bucket_name: str, collection_name: str = "bedrock-knowledge-base", index_name: str = "vector-index") -> str:
        """Knowledge Base 생성"""
        try:
            response = self.bedrock_agent_client.create_knowledge_base(
                name=name,
                description="케이팝 데몬헌터스 캐릭터 정보 Knowledge Base",
                roleArn=f"arn:aws:iam::{boto3.client('sts').get_caller_identity()['Account']}:role/AmazonBedrockExecutionRoleForKnowledgeBase",
                knowledgeBaseConfiguration={
                    'type': 'VECTOR',
                    'vectorKnowledgeBaseConfiguration': {
                        'embeddingModelArn': 'arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v1'
                    }
                },
                storageConfiguration={
                    'type': 'OPENSEARCH_SERVERLESS',
                    'opensearchServerlessConfiguration': {
                        'collectionArn': f"arn:aws:aoss:us-east-1:{boto3.client('sts').get_caller_identity()['Account']}:collection/{collection_name}",
                        'vectorIndexName': index_name,
                        'fieldMapping': {
                            'vectorField': 'vector',
                            'textField': 'text',
                            'metadataField': 'metadata'
                        }
                    }
                }
            )
            
            knowledge_base_id = response['knowledgeBase']['knowledgeBaseId']
            print(f"Knowledge Base 생성 완료: {knowledge_base_id}")
            return knowledge_base_id
            
        except Exception as e:
            print(f"Knowledge Base 생성 오류: {str(e)}")
            return None
    
    def create_data_source(self, knowledge_base_id: str, bucket_name: str) -> str:
        """데이터 소스 생성"""
        try:
            response = self.bedrock_agent_client.create_data_source(
                knowledgeBaseId=knowledge_base_id,
                name="kpop-demon-hunters-data",
                description="케이팝 데몬헌터스 캐릭터 데이터",
                dataSourceConfiguration={
                    'type': 'S3',
                    's3Configuration': {
                        'bucketArn': f"arn:aws:s3:::{bucket_name}",
                        'inclusionPrefixes': ['characters/']
                    }
                }
            )
            
            data_source_id = response['dataSource']['dataSourceId']
            print(f"데이터 소스 생성 완료: {data_source_id}")
            return data_source_id
            
        except Exception as e:
            print(f"데이터 소스 생성 오류: {str(e)}")
            return None
    
    def upload_character_data(self, bucket_name: str):
        """캐릭터 데이터를 S3에 업로드"""
        character_data = {
            "저승사자": {
                "name": "저승사자",
                "role": "영혼 인도자",
                "personality": "냉정하지만 따뜻한 마음을 가진 캐릭터. 죽음과 삶의 경계에서 영혼들을 올바른 길로 인도하는 역할을 담당한다.",
                "abilities": ["영혼 감지", "차원 이동", "시간 조작"],
                "hobbies": ["명상", "고전 음악 감상", "서예"],
                "background": "수천 년간 저승과 이승을 오가며 영혼들을 인도해온 신비로운 존재. 최근 데몬들의 활동이 활발해지면서 케이팝 아이돌들과 협력하게 되었다.",
                "catchphrase": "모든 영혼에게는 갈 곳이 있다."
            },
            "아이돌리더": {
                "name": "아이돌 그룹 리더",
                "role": "케이팝 아이돌이자 데몬헌터 팀 리더",
                "personality": "밝고 긍정적이며 팀을 이끄는 강한 카리스마를 가졌다. 무대에서는 완벽한 퍼포먼스를, 전투에서는 뛰어난 리더십을 보여준다.",
                "abilities": ["음파 공격", "팀워크 강화", "무대 마법"],
                "hobbies": ["작사작곡", "댄스 연습", "팬들과의 소통"],
                "background": "데뷔 3년차 케이팝 아이돌로, 우연히 데몬과 마주치면서 숨겨진 능력을 각성했다. 이후 팀원들과 함께 데몬헌터로 활동하며 세상을 지키고 있다.",
                "catchphrase": "우리의 음악으로 세상을 밝게 만들어요!"
            },
            "까치": {
                "name": "까치",
                "role": "정보 수집 및 전달 전문가",
                "personality": "재치있고 똑똑하며 호기심이 많다. 작은 체구지만 용감하고, 항상 유용한 정보를 가져다준다.",
                "abilities": ["고속 비행", "정보 수집", "언어 번역"],
                "hobbies": ["반짝이는 물건 수집", "소문 듣기", "하늘 산책"],
                "background": "원래는 평범한 까치였지만, 신비한 힘에 의해 지능과 특별한 능력을 얻게 되었다. 데몬헌터 팀의 정보원 역할을 담당한다.",
                "catchphrase": "까악! 중요한 정보가 있어요!"
            },
            "호랑이": {
                "name": "호랑이",
                "role": "강력한 전투력을 가진 수호신",
                "personality": "용맹하고 정의로우며 보호본능이 강하다. 평소에는 온순하지만 동료가 위험에 처하면 무서운 힘을 발휘한다.",
                "abilities": ["초인적 힘", "번개 속도", "수호 결계"],
                "hobbies": ["낮잠", "자연 감상", "명상"],
                "background": "한국의 산신령으로부터 힘을 받은 신성한 호랑이. 인간 세계에 나타난 데몬들을 물리치기 위해 데몬헌터 팀에 합류했다.",
                "catchphrase": "정의는 반드시 승리한다!"
            }
        }
        
        story_data = {
            "main_story": """
            케이팝 데몬헌터스는 현대 한국을 배경으로 한 판타지 액션 스토리입니다.
            
            어느 날 갑자기 나타난 데몬들이 인간 세계를 위협하기 시작했습니다. 
            이들은 인간의 부정적인 감정을 먹고 자라며, 점점 더 강해져 갔습니다.
            
            그런 중에 한 케이팝 아이돌 그룹이 우연히 데몬과 마주치게 되고, 
            그들의 음악과 긍정적인 에너지가 데몬을 물리칠 수 있다는 것을 발견합니다.
            
            이후 저승사자, 까치, 호랑이 등 다양한 존재들이 합류하여 
            '케이팝 데몬헌터스'라는 팀을 결성하게 됩니다.
            
            그들은 음악의 힘과 각자의 특별한 능력을 조합하여 
            데몬들로부터 세상을 지키는 모험을 펼쳐나갑니다.
            """,
            "world_setting": """
            세계관:
            - 현대 한국 (서울 중심)
            - 인간 세계와 영적 세계가 공존
            - 케이팝 문화가 특별한 힘을 가진 세계
            - 데몬들은 부정적 감정에서 태어남
            - 음악과 긍정적 에너지가 데몬을 물리치는 힘
            
            주요 장소:
            - 연습실: 팀의 본거지
            - 한강공원: 자주 등장하는 전투 장소
            - 홍대: 데몬들이 자주 나타나는 곳
            - 남산타워: 최종 보스전 장소
            """
        }
        
        try:
            # 캐릭터 데이터 업로드
            for character_name, data in character_data.items():
                key = f"characters/{character_name}.json"
                self.s3_client.put_object(
                    Bucket=bucket_name,
                    Key=key,
                    Body=json.dumps(data, ensure_ascii=False, indent=2),
                    ContentType='application/json'
                )
                print(f"{character_name} 데이터 업로드 완료")
            
            # 스토리 데이터 업로드
            self.s3_client.put_object(
                Bucket=bucket_name,
                Key="characters/story.json",
                Body=json.dumps(story_data, ensure_ascii=False, indent=2),
                ContentType='application/json'
            )
            print("스토리 데이터 업로드 완료")
            
        except Exception as e:
            print(f"데이터 업로드 오류: {str(e)}")

def main():
    setup = KnowledgeBaseSetup()
    
    # S3 버킷 이름 (admin_config.json 또는 환경변수에서 로드)
    import os
    bucket_name = os.environ.get("S3_BUCKET_NAME", "")
    if not bucket_name:
        try:
            with open(Path(__file__).parent / "admin_config.json", "r") as f:
                bucket_name = json.load(f).get("bucket_name", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    if not bucket_name:
        print("ERROR: S3_BUCKET_NAME 환경변수 또는 admin_config.json의 bucket_name을 설정하세요.")
        return
    
    print("1. 캐릭터 데이터를 S3에 업로드 중...")
    setup.upload_character_data(bucket_name)
    
    print("\n2. Knowledge Base 생성 중...")
    knowledge_base_id = setup.create_knowledge_base("KPop-Demon-Hunters-KB", bucket_name)
    
    if knowledge_base_id:
        print(f"\n3. 데이터 소스 생성 중...")
        data_source_id = setup.create_data_source(knowledge_base_id, bucket_name)
        
        if data_source_id:
            print(f"\n설정 완료!")
            print(f"Knowledge Base ID: {knowledge_base_id}")
            print(f"Data Source ID: {data_source_id}")
            print(f"\n챗봇 파일에서 knowledge_base_id를 '{knowledge_base_id}'로 업데이트하세요.")

if __name__ == "__main__":
    main()
