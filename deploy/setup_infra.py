#!/usr/bin/env python3
"""
ECS Fargate + ALB + CloudFront 인프라 구축
- VPC 기본 서브넷 사용
- ECS 클러스터 + 태스크 정의 + 서비스
- ALB + Target Group (Sticky Session)
- CloudFront (앱용, CachingDisabled)
"""

import boto3
import json
import time
import sys
from pathlib import Path

REGION = "us-east-1"
CLUSTER_NAME = "character-chatbot-cluster"
SERVICE_NAME = "character-chatbot-service"
TASK_FAMILY = "character-chatbot-task"
ECR_REPO_NAME = "character-chatbot"
CONTAINER_NAME = "chatbot"
CONTAINER_PORT = 8501

ALB_NAME = "chatbot-alb"
TG_NAME = "chatbot-tg"
SG_NAME = "chatbot-alb-sg"
TASK_SG_NAME = "chatbot-task-sg"
TASK_ROLE_NAME = "chatbot-ecs-task-role"
EXECUTION_ROLE_NAME = "chatbot-ecs-execution-role"

APP_CF_COMMENT = "Character Chatbot App CDN"


def get_account_id() -> str:
    return boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]


def get_default_vpc_and_subnets():
    """기본 VPC와 퍼블릭 서브넷 조회"""
    ec2 = boto3.client("ec2", region_name=REGION)

    vpcs = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        print("ERROR: No default VPC found. Create one or modify this script.")
        sys.exit(1)
    vpc_id = vpcs[0]["VpcId"]

    subnets = ec2.describe_subnets(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}, {"Name": "default-for-az", "Values": ["true"]}]
    )["Subnets"]
    subnet_ids = [s["SubnetId"] for s in subnets]

    print(f"  VPC: {vpc_id}")
    print(f"  Subnets: {subnet_ids}")
    return vpc_id, subnet_ids


def create_security_groups(vpc_id: str):
    """ALB용 + ECS Task용 보안 그룹 생성"""
    ec2 = boto3.client("ec2", region_name=REGION)

    # 기존 SG 검색
    existing = ec2.describe_security_groups(
        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}, {"Name": "group-name", "Values": [SG_NAME, TASK_SG_NAME]}]
    )["SecurityGroups"]
    sg_map = {sg["GroupName"]: sg["GroupId"] for sg in existing}

    # ALB Security Group
    if SG_NAME in sg_map:
        alb_sg_id = sg_map[SG_NAME]
        print(f"  ALB SG already exists: {alb_sg_id}")
    else:
        resp = ec2.create_security_group(
            GroupName=SG_NAME, Description="ALB for character chatbot", VpcId=vpc_id
        )
        alb_sg_id = resp["GroupId"]
        ec2.authorize_security_group_ingress(
            GroupId=alb_sg_id,
            IpPermissions=[{"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}],
        )
        print(f"  Created ALB SG: {alb_sg_id}")

    # Task Security Group
    if TASK_SG_NAME in sg_map:
        task_sg_id = sg_map[TASK_SG_NAME]
        print(f"  Task SG already exists: {task_sg_id}")
    else:
        resp = ec2.create_security_group(
            GroupName=TASK_SG_NAME, Description="ECS tasks for character chatbot", VpcId=vpc_id
        )
        task_sg_id = resp["GroupId"]
        # ALB → Task 포트 허용
        ec2.authorize_security_group_ingress(
            GroupId=task_sg_id,
            IpPermissions=[
                {"IpProtocol": "tcp", "FromPort": CONTAINER_PORT, "ToPort": CONTAINER_PORT,
                 "UserIdGroupPairs": [{"GroupId": alb_sg_id}]},
            ],
        )
        print(f"  Created Task SG: {task_sg_id}")

    return alb_sg_id, task_sg_id


def create_iam_roles(account_id: str, bucket_name: str = ""):
    """ECS Task Role + Execution Role 생성"""
    if not bucket_name:
        import os as _os
        bucket_name = _os.environ.get("S3_BUCKET_NAME", "")
        if not bucket_name:
            try:
                with open(Path(__file__).resolve().parent.parent / "admin_config.json", "r") as f:
                    bucket_name = json.load(f).get("bucket_name", "")
            except (FileNotFoundError, json.JSONDecodeError):
                pass
    iam = boto3.client("iam", region_name=REGION)

    # Task Execution Role (ECR pull + CloudWatch logs)
    execution_role_arn = f"arn:aws:iam::{account_id}:role/{EXECUTION_ROLE_NAME}"
    try:
        iam.get_role(RoleName=EXECUTION_ROLE_NAME)
        print(f"  Execution role already exists: {execution_role_arn}")
    except iam.exceptions.NoSuchEntityException:
        iam.create_role(
            RoleName=EXECUTION_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}],
            }),
        )
        iam.attach_role_policy(
            RoleName=EXECUTION_ROLE_NAME,
            PolicyArn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
        )
        print(f"  Created execution role: {execution_role_arn}")

    # Task Role (Bedrock, S3, DDB, Cognito)
    task_role_arn = f"arn:aws:iam::{account_id}:role/{TASK_ROLE_NAME}"
    try:
        iam.get_role(RoleName=TASK_ROLE_NAME)
        print(f"  Task role already exists: {task_role_arn}")
    except iam.exceptions.NoSuchEntityException:
        iam.create_role(
            RoleName=TASK_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Principal": {"Service": "ecs-tasks.amazonaws.com"}, "Action": "sts:AssumeRole"}],
            }),
        )
        # Inline policy for Bedrock, S3, DDB, Cognito
        iam.put_role_policy(
            RoleName=TASK_ROLE_NAME,
            PolicyName="chatbot-task-policy",
            PolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                        "Resource": "*",
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["bedrock:Retrieve"],
                        "Resource": f"arn:aws:bedrock:{REGION}:{account_id}:knowledge-base/*",
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject", "s3:ListBucket", "s3:PutObject"],
                        "Resource": [
                            f"arn:aws:s3:::{bucket_name}",
                            f"arn:aws:s3:::{bucket_name}/*",
                        ],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                                   "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"],
                        "Resource": [
                            f"arn:aws:dynamodb:{REGION}:{account_id}:table/character_chatbot",
                            f"arn:aws:dynamodb:{REGION}:{account_id}:table/character_chatbot/index/*",
                        ],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["cognito-idp:AdminGetUser", "cognito-idp:ListUsers"],
                        "Resource": f"arn:aws:cognito-idp:{REGION}:{account_id}:userpool/*",
                    },
                ],
            }),
        )
        print(f"  Created task role: {task_role_arn}")

    return execution_role_arn, task_role_arn


def create_log_group():
    """CloudWatch Logs 그룹 생성"""
    logs = boto3.client("logs", region_name=REGION)
    log_group = f"/ecs/{TASK_FAMILY}"
    try:
        logs.create_log_group(logGroupName=log_group)
        logs.put_retention_policy(logGroupName=log_group, retentionInDays=7)
        print(f"  Created log group: {log_group}")
    except logs.exceptions.ResourceAlreadyExistsException:
        print(f"  Log group already exists: {log_group}")
    return log_group


def create_alb(subnet_ids: list, alb_sg_id: str, vpc_id: str):
    """ALB + Target Group 생성"""
    elbv2 = boto3.client("elbv2", region_name=REGION)

    # 기존 ALB 확인
    albs = elbv2.describe_load_balancers()["LoadBalancers"]
    for alb in albs:
        if alb["LoadBalancerName"] == ALB_NAME:
            alb_arn = alb["LoadBalancerArn"]
            alb_dns = alb["DNSName"]
            print(f"  ALB already exists: {alb_dns}")

            # TG 확인
            tgs = elbv2.describe_target_groups()["TargetGroups"]
            tg_arn = None
            for tg in tgs:
                if tg["TargetGroupName"] == TG_NAME:
                    tg_arn = tg["TargetGroupArn"]
                    break

            # 리스너 존재 확인 — 없으면 보안 리스너 생성 (403 default + CF header rule)
            listeners = elbv2.describe_listeners(LoadBalancerArn=alb_arn)["Listeners"]
            if not listeners and tg_arn:
                _create_secure_listener(elbv2, alb_arn, tg_arn)
                print("  Recreated HTTP:80 listener (default=403, CF header rule)")
            else:
                print(f"  Listener OK ({len(listeners)} listener(s))")

            return alb_arn, alb_dns, tg_arn

    # Target Group 생성
    tg_resp = elbv2.create_target_group(
        Name=TG_NAME,
        Protocol="HTTP",
        Port=CONTAINER_PORT,
        VpcId=vpc_id,
        TargetType="ip",
        HealthCheckProtocol="HTTP",
        HealthCheckPath="/_stcheck",
        HealthCheckIntervalSeconds=30,
        HealthCheckTimeoutSeconds=10,
        HealthyThresholdCount=2,
        UnhealthyThresholdCount=3,
    )
    tg_arn = tg_resp["TargetGroups"][0]["TargetGroupArn"]
    print(f"  Created Target Group: {TG_NAME}")

    # Sticky Session 활성화
    elbv2.modify_target_group_attributes(
        TargetGroupArn=tg_arn,
        Attributes=[
            {"Key": "stickiness.enabled", "Value": "true"},
            {"Key": "stickiness.type", "Value": "lb_cookie"},
            {"Key": "stickiness.lb_cookie.duration_seconds", "Value": "86400"},
        ],
    )

    # ALB 생성
    alb_resp = elbv2.create_load_balancer(
        Name=ALB_NAME,
        Subnets=subnet_ids,
        SecurityGroups=[alb_sg_id],
        Scheme="internet-facing",
        Type="application",
        IpAddressType="ipv4",
    )
    alb_arn = alb_resp["LoadBalancers"][0]["LoadBalancerArn"]
    alb_dns = alb_resp["LoadBalancers"][0]["DNSName"]
    print(f"  Created ALB: {alb_dns}")

    # ALB 준비 대기
    print("  Waiting for ALB to become active...")
    waiter = elbv2.get_waiter("load_balancer_available")
    waiter.wait(LoadBalancerArns=[alb_arn])

    # HTTP:80 리스너 (보안: 403 default + CF header rule)
    _create_secure_listener(elbv2, alb_arn, tg_arn)
    print("  Created HTTP:80 listener (default=403, CF header rule)")

    return alb_arn, alb_dns, tg_arn


def _create_secure_listener(elbv2, alb_arn: str, tg_arn: str):
    """ALB 리스너 생성: 기본 403 + X-CF-Secret 헤더 매칭 시에만 forward"""
    import os as _os
    cf_secret = _os.environ.get("CF_ALB_SECRET", "")
    if not cf_secret:
        # config에서 시도
        try:
            config_path = Path(__file__).resolve().parent.parent / "admin_config.json"
            with open(config_path, "r") as f:
                cf_secret = json.load(f).get("cf_alb_secret", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    if not cf_secret:
        print("  WARNING: CF_ALB_SECRET not set. Creating plain forward listener.")
        elbv2.create_listener(
            LoadBalancerArn=alb_arn,
            Protocol="HTTP",
            Port=80,
            DefaultActions=[{"Type": "forward", "TargetGroupArn": tg_arn}],
        )
        return

    # 기본 action: 403 Forbidden
    listener_resp = elbv2.create_listener(
        LoadBalancerArn=alb_arn,
        Protocol="HTTP",
        Port=80,
        DefaultActions=[{
            "Type": "fixed-response",
            "FixedResponseConfig": {
                "StatusCode": "403",
                "ContentType": "text/plain",
                "MessageBody": "Forbidden",
            },
        }],
    )
    listener_arn = listener_resp["Listeners"][0]["ListenerArn"]

    # Rule: X-CF-Secret 헤더 매칭 시 forward
    elbv2.create_rule(
        ListenerArn=listener_arn,
        Priority=1,
        Conditions=[{
            "Field": "http-header",
            "HttpHeaderConfig": {
                "HttpHeaderName": "X-CF-Secret",
                "Values": [cf_secret],
            },
        }],
        Actions=[{"Type": "forward", "TargetGroupArn": tg_arn}],
    )


def create_ecs_cluster():
    """ECS 클러스터 생성"""
    ecs = boto3.client("ecs", region_name=REGION)
    try:
        resp = ecs.describe_clusters(clusters=[CLUSTER_NAME])
        active = [c for c in resp["clusters"] if c["status"] == "ACTIVE"]
        if active:
            print(f"  Cluster already exists: {CLUSTER_NAME}")
            return active[0]["clusterArn"]
    except Exception:
        pass

    resp = ecs.create_cluster(clusterName=CLUSTER_NAME)
    arn = resp["cluster"]["clusterArn"]
    print(f"  Created cluster: {arn}")
    return arn


def register_task_definition(account_id: str, execution_role_arn: str, task_role_arn: str, log_group: str):
    """ECS Task Definition 등록"""
    ecs = boto3.client("ecs", region_name=REGION)
    ecr_uri = f"{account_id}.dkr.ecr.{REGION}.amazonaws.com/{ECR_REPO_NAME}:latest"

    resp = ecs.register_task_definition(
        family=TASK_FAMILY,
        networkMode="awsvpc",
        requiresCompatibilities=["FARGATE"],
        cpu="512",
        memory="1024",
        executionRoleArn=execution_role_arn,
        taskRoleArn=task_role_arn,
        containerDefinitions=[
            {
                "name": CONTAINER_NAME,
                "image": ecr_uri,
                "essential": True,
                "portMappings": [{"containerPort": CONTAINER_PORT, "protocol": "tcp"}],
                "logConfiguration": {
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": log_group,
                        "awslogs-region": REGION,
                        "awslogs-stream-prefix": "chatbot",
                    },
                },
                "healthCheck": {
                    "command": ["CMD-SHELL", f"curl -f http://localhost:{CONTAINER_PORT}/_stcheck || exit 1"],
                    "interval": 30,
                    "timeout": 10,
                    "retries": 3,
                    "startPeriod": 30,
                },
            }
        ],
    )
    task_def_arn = resp["taskDefinition"]["taskDefinitionArn"]
    print(f"  Registered task definition: {task_def_arn}")
    return task_def_arn


def create_ecs_service(cluster_arn: str, task_def_arn: str, tg_arn: str, subnet_ids: list, task_sg_id: str):
    """ECS Fargate Service 생성"""
    ecs = boto3.client("ecs", region_name=REGION)

    # 기존 서비스 확인
    try:
        resp = ecs.describe_services(cluster=cluster_arn, services=[SERVICE_NAME])
        active = [s for s in resp["services"] if s["status"] == "ACTIVE"]
        if active:
            print(f"  Service already exists: {SERVICE_NAME}")
            # 태스크 정의 업데이트
            ecs.update_service(
                cluster=cluster_arn,
                service=SERVICE_NAME,
                taskDefinition=task_def_arn,
                forceNewDeployment=True,
            )
            print("  Updated service with new task definition")
            return
    except Exception:
        pass

    ecs.create_service(
        cluster=cluster_arn,
        serviceName=SERVICE_NAME,
        taskDefinition=task_def_arn,
        desiredCount=1,
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subnet_ids,
                "securityGroups": [task_sg_id],
                "assignPublicIp": "ENABLED",
            }
        },
        loadBalancers=[
            {
                "targetGroupArn": tg_arn,
                "containerName": CONTAINER_NAME,
                "containerPort": CONTAINER_PORT,
            }
        ],
    )
    print(f"  Created service: {SERVICE_NAME}")


def create_app_cloudfront(alb_dns: str):
    """앱용 CloudFront 배포 생성 (동적 콘텐츠, 캐싱 비활성화)"""
    cf = boto3.client("cloudfront", region_name=REGION)

    # 기존 배포 확인
    paginator = cf.get_paginator("list_distributions")
    for page in paginator.paginate():
        for dist in page.get("DistributionList", {}).get("Items", []):
            if dist.get("Comment") == APP_CF_COMMENT:
                domain = dist["DomainName"]
                print(f"  App CF already exists: {domain}")
                return domain, dist["Id"]

    caller_ref = f"chatbot-app-{int(time.time())}"

    resp = cf.create_distribution(
        DistributionConfig={
            "CallerReference": caller_ref,
            "Comment": APP_CF_COMMENT,
            "Enabled": True,
            "Origins": {
                "Quantity": 1,
                "Items": [
                    {
                        "Id": "ALB-origin",
                        "DomainName": alb_dns,
                        "CustomOriginConfig": {
                            "HTTPPort": 80,
                            "HTTPSPort": 443,
                            "OriginProtocolPolicy": "http-only",
                            "OriginReadTimeout": 60,
                            "OriginKeepaliveTimeout": 5,
                        },
                    }
                ],
            },
            "DefaultCacheBehavior": {
                "TargetOriginId": "ALB-origin",
                "ViewerProtocolPolicy": "redirect-to-https",
                "AllowedMethods": {
                    "Quantity": 7,
                    "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
                    "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
                },
                "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",  # CachingDisabled
                "OriginRequestPolicyId": "b689b0a8-53d0-40ab-baf2-68738e2966ac",  # AllViewerExceptHostHeader
                "Compress": True,
            },
            "ViewerCertificate": {
                "CloudFrontDefaultCertificate": True,
            },
            "PriceClass": "PriceClass_200",
            "HttpVersion": "http2and3",
        }
    )
    dist = resp["Distribution"]
    domain = dist["DomainName"]
    dist_id = dist["Id"]
    print(f"  Created App CF: {domain} (ID: {dist_id})")
    return domain, dist_id


def save_infra_config(app_cf_domain: str, app_cf_id: str, alb_dns: str):
    """인프라 정보를 admin_config.json에 저장"""
    config_path = Path(__file__).resolve().parent.parent / "admin_config.json"
    config = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    config["app_cloudfront_domain"] = f"https://{app_cf_domain}"
    config["app_cloudfront_distribution_id"] = app_cf_id
    config["alb_dns"] = alb_dns
    config["ecs_cluster"] = CLUSTER_NAME
    config["ecs_service"] = SERVICE_NAME

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"  Saved infra config to {config_path}")


def main():
    account_id = get_account_id()
    print(f"Account: {account_id}")
    print(f"Region: {REGION}")
    print()

    # 1. VPC + Subnets
    print("[1/8] Getting VPC and subnets...")
    vpc_id, subnet_ids = get_default_vpc_and_subnets()

    # 2. Security Groups
    print("\n[2/8] Creating security groups...")
    alb_sg_id, task_sg_id = create_security_groups(vpc_id)

    # 3. IAM Roles
    print("\n[3/8] Creating IAM roles...")
    execution_role_arn, task_role_arn = create_iam_roles(account_id)

    # 4. CloudWatch Logs
    print("\n[4/8] Creating log group...")
    log_group = create_log_group()

    # 5. ALB + Target Group
    print("\n[5/8] Creating ALB and Target Group...")
    alb_arn, alb_dns, tg_arn = create_alb(subnet_ids, alb_sg_id, vpc_id)

    # 6. ECS Cluster
    print("\n[6/8] Creating ECS cluster...")
    cluster_arn = create_ecs_cluster()

    # 7. Task Definition + Service
    print("\n[7/8] Registering task definition and creating service...")
    task_def_arn = register_task_definition(account_id, execution_role_arn, task_role_arn, log_group)
    create_ecs_service(cluster_arn, task_def_arn, tg_arn, subnet_ids, task_sg_id)

    # 8. App CloudFront
    print("\n[8/8] Creating app CloudFront distribution...")
    app_cf_domain, app_cf_id = create_app_cloudfront(alb_dns)

    # Save config
    print("\nSaving infrastructure configuration...")
    save_infra_config(app_cf_domain, app_cf_id, alb_dns)

    print("\n" + "=" * 60)
    print("Infrastructure setup complete!")
    print(f"  ALB DNS:        http://{alb_dns}")
    print(f"  App CloudFront: https://{app_cf_domain}")
    print()
    print("Next steps:")
    print("  1. Build and push Docker image: deploy/deploy.sh")
    print("  2. Wait for ECS service to stabilize (~2-3 min)")
    print("  3. Access app via CloudFront URL above")
    print("=" * 60)


if __name__ == "__main__":
    main()
