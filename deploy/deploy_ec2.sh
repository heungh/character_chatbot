#!/bin/bash
set -euo pipefail

# ============================================================
# EC2에서 Docker 빌드 → ECR 푸시 → ECS 배포
# Docker Desktop이 로컬에서 사용 불가 시 EC2 빌드 호스트를 사용
# ============================================================

# --- Configuration ---
AWS_REGION="us-east-1"
ECR_REPO_NAME="character-chatbot"
ECS_CLUSTER="character-chatbot-cluster"
ECS_SERVICE="character-chatbot-service"
IMAGE_TAG="${1:-latest}"

# EC2 Build Host (환경변수 또는 기본값)
EC2_KEY="${EC2_KEY:?ERROR: Set EC2_KEY to your SSH key path (e.g. export EC2_KEY=~/my-key.pem)}"
EC2_USER="${EC2_USER:-ec2-user}"
EC2_HOST="${EC2_HOST:?ERROR: Set EC2_HOST to your EC2 IP (e.g. export EC2_HOST=1.2.3.4)}"
EC2_BUILD_DIR="~/chatbot-build"

# Get AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

# Project root (one level up from deploy/)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"

echo "=== EC2-based ECS Deploy ==="
echo "Account:    ${ACCOUNT_ID}"
echo "Region:     ${AWS_REGION}"
echo "ECR Repo:   ${ECR_URI}"
echo "Tag:        ${IMAGE_TAG}"
echo "EC2 Host:   ${EC2_USER}@${EC2_HOST}"
echo "EC2 Key:    ${EC2_KEY}"
echo ""

# Docker 빌드에 필요한 파일 목록 (Dockerfile COPY 기준)
BUILD_FILES=(
    "Dockerfile"
    ".dockerignore"
    "requirements.txt"
    "chatbot_config.json"
    "character_chatbot.py"
    "character_chatbot_auth.py"
    "character_chatbot_memory.py"
    "character_chatbot_scraper.py"
)

# 1. SSH 연결 테스트
echo "[1/5] Testing SSH connection to EC2..."
if ! ssh -i "${EC2_KEY}" -o ConnectTimeout=10 -o StrictHostKeyChecking=no "${EC2_USER}@${EC2_HOST}" "echo 'SSH OK'" 2>/dev/null; then
    echo ""
    echo "ERROR: Cannot connect to EC2. Check:"
    echo "  1. EC2 Security Group allows SSH from your IP"
    echo "  2. EC2 instance is running"
    echo ""
    echo "To add your IP to SG:"
    MY_IP=$(curl -s https://checkip.amazonaws.com)
    echo "  aws ec2 authorize-security-group-ingress --group-id <sg-id> \\"
    echo "    --protocol tcp --port 22 --cidr ${MY_IP}/32"
    exit 1
fi
echo "  SSH connection OK"

# 2. SCP 파일 전송
echo ""
echo "[2/5] Uploading build files to EC2..."
ssh -i "${EC2_KEY}" "${EC2_USER}@${EC2_HOST}" "mkdir -p ${EC2_BUILD_DIR}"

for f in "${BUILD_FILES[@]}"; do
    FILE_PATH="${PROJECT_DIR}/${f}"
    if [ ! -f "${FILE_PATH}" ]; then
        echo "  WARNING: ${f} not found, skipping"
        continue
    fi
    scp -i "${EC2_KEY}" -q "${FILE_PATH}" "${EC2_USER}@${EC2_HOST}:${EC2_BUILD_DIR}/"
    echo "  Uploaded: ${f}"
done

# 3. EC2에서 Docker 빌드 + ECR 푸시
echo ""
echo "[3/5] Building Docker image on EC2 and pushing to ECR..."
ssh -i "${EC2_KEY}" "${EC2_USER}@${EC2_HOST}" << DEPLOY_EOF
set -euo pipefail
cd ${EC2_BUILD_DIR}

echo "  Building Docker image..."
sudo docker build -t ${ECR_REPO_NAME}:${IMAGE_TAG} .

echo "  Logging in to ECR..."
aws ecr get-login-password --region ${AWS_REGION} | \
    sudo docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

echo "  Tagging and pushing..."
sudo docker tag ${ECR_REPO_NAME}:${IMAGE_TAG} ${ECR_URI}:${IMAGE_TAG}
sudo docker push ${ECR_URI}:${IMAGE_TAG}

echo "  Docker build and push complete"
DEPLOY_EOF

# 4. ECS 서비스 업데이트
echo ""
echo "[4/5] Updating ECS service..."
CURRENT_DESIRED=$(aws ecs describe-services --cluster "${ECS_CLUSTER}" --services "${ECS_SERVICE}" --region "${AWS_REGION}" --query 'services[0].desiredCount' --output text)
DESIRED_COUNT="${CURRENT_DESIRED}"
if [ "${CURRENT_DESIRED}" = "0" ] || [ "${CURRENT_DESIRED}" = "None" ]; then
    DESIRED_COUNT=1
    echo "  Service was stopped (desired=0), setting desired=1"
fi
aws ecs update-service \
    --cluster "${ECS_CLUSTER}" \
    --service "${ECS_SERVICE}" \
    --desired-count "${DESIRED_COUNT}" \
    --force-new-deployment \
    --region "${AWS_REGION}" \
    --query 'service.deployments[].{status:status,desired:desiredCount,running:runningCount}' \
    --output table

# 5. 배포 안정화 대기
echo ""
echo "[5/5] Waiting for deployment to stabilize..."
ATTEMPTS=0
MAX_ATTEMPTS=30
while [ ${ATTEMPTS} -lt ${MAX_ATTEMPTS} ]; do
    RUNNING=$(aws ecs describe-services --cluster "${ECS_CLUSTER}" --services "${ECS_SERVICE}" --region "${AWS_REGION}" --query 'services[0].deployments[?status==`PRIMARY`].runningCount | [0]' --output text)
    ROLLOUT=$(aws ecs describe-services --cluster "${ECS_CLUSTER}" --services "${ECS_SERVICE}" --region "${AWS_REGION}" --query 'services[0].deployments[?status==`PRIMARY`].rolloutState | [0]' --output text)
    if [ "${ROLLOUT}" = "COMPLETED" ] && [ "${RUNNING}" -ge 1 ] 2>/dev/null; then
        echo "  Deployment completed (running=${RUNNING})"
        break
    fi
    ATTEMPTS=$((ATTEMPTS + 1))
    echo "  Waiting... (${ATTEMPTS}/${MAX_ATTEMPTS}, rollout=${ROLLOUT}, running=${RUNNING})"
    sleep 10
done
if [ ${ATTEMPTS} -ge ${MAX_ATTEMPTS} ]; then
    echo "  WARNING: Deployment did not stabilize within timeout. Check manually."
fi

echo ""
echo "Deploy complete. Monitor with:"
echo "  aws ecs describe-services --cluster ${ECS_CLUSTER} --services ${ECS_SERVICE} --query 'services[0].deployments' --output table"
