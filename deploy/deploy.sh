#!/bin/bash
set -euo pipefail

# Configuration
AWS_REGION="us-east-1"
ECR_REPO_NAME="character-chatbot"
ECS_CLUSTER="character-chatbot-cluster"
ECS_SERVICE="character-chatbot-service"
IMAGE_TAG="${1:-latest}"
CF_ALB_SECRET="${CF_ALB_SECRET:?ERROR: CF_ALB_SECRET 환경변수가 설정되지 않았습니다. export CF_ALB_SECRET=your_secret_value}"

# Get AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

echo "=== Character Chatbot Deploy ==="
echo "Account:  ${ACCOUNT_ID}"
echo "Region:   ${AWS_REGION}"
echo "ECR Repo: ${ECR_URI}"
echo "Tag:      ${IMAGE_TAG}"
echo ""

# 1. Create ECR repository if not exists
echo "[1/7] Ensuring ECR repository exists..."
aws ecr describe-repositories --repository-names "${ECR_REPO_NAME}" --region "${AWS_REGION}" 2>/dev/null || \
    aws ecr create-repository --repository-name "${ECR_REPO_NAME}" --region "${AWS_REGION}" \
        --image-scanning-configuration scanOnPush=true

# 2. Login to ECR
echo "[2/7] Logging in to ECR..."
aws ecr get-login-password --region "${AWS_REGION}" | \
    docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# 3. Build Docker image
echo "[3/7] Building Docker image..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
docker build -t "${ECR_REPO_NAME}:${IMAGE_TAG}" "${PROJECT_DIR}"

# 4. Tag and push to ECR
echo "[4/7] Pushing to ECR..."
docker tag "${ECR_REPO_NAME}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:${IMAGE_TAG}"

# 5. Update ECS service (force new deployment + ensure desired count >= 1)
echo "[5/7] Updating ECS service..."
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

# 6. Wait for deployment to stabilize (up to 5 min)
echo "[6/7] Waiting for deployment to stabilize..."
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

# 7. Verify ALB listener + target health
echo "[7/7] Verifying ALB listener and target health..."
ALB_ARN=$(aws elbv2 describe-load-balancers --names chatbot-alb --region "${AWS_REGION}" --query 'LoadBalancers[0].LoadBalancerArn' --output text 2>/dev/null || echo "")
if [ -n "${ALB_ARN}" ] && [ "${ALB_ARN}" != "None" ]; then
    TG_ARN=$(aws elbv2 describe-target-groups --names chatbot-tg --region "${AWS_REGION}" --query 'TargetGroups[0].TargetGroupArn' --output text)

    # Listener check/recreate (default=403, forward only with CF secret header)
    LISTENER_COUNT=$(aws elbv2 describe-listeners --load-balancer-arn "${ALB_ARN}" --region "${AWS_REGION}" --query 'length(Listeners)' --output text)
    if [ "${LISTENER_COUNT}" = "0" ]; then
        LISTENER_ARN=$(aws elbv2 create-listener \
            --load-balancer-arn "${ALB_ARN}" \
            --protocol HTTP --port 80 \
            --default-actions 'Type=fixed-response,FixedResponseConfig={StatusCode=403,ContentType=text/plain,MessageBody=Forbidden}' \
            --region "${AWS_REGION}" --query 'Listeners[0].ListenerArn' --output text)
        # Add rule: forward only if X-CF-Secret header matches
        aws elbv2 create-rule \
            --listener-arn "${LISTENER_ARN}" \
            --priority 1 \
            --conditions "Field=http-header,HttpHeaderConfig={HttpHeaderName=X-CF-Secret,Values=[\"${CF_ALB_SECRET}\"]}" \
            --actions "Type=forward,TargetGroupArn=${TG_ARN}" \
            --region "${AWS_REGION}" > /dev/null
        echo "  Recreated HTTP:80 listener (default=403, CF header rule added)"
    else
        echo "  Listener OK (${LISTENER_COUNT} listener(s))"
    fi

    # Target health check
    TARGET_STATE=$(aws elbv2 describe-target-health --target-group-arn "${TG_ARN}" --region "${AWS_REGION}" --query 'TargetHealthDescriptions[0].TargetHealth.State' --output text 2>/dev/null || echo "none")
    if [ "${TARGET_STATE}" = "healthy" ]; then
        echo "  Target health: healthy"
    else
        echo "  Target health: ${TARGET_STATE} (may need a moment to become healthy)"
    fi
fi

echo ""
echo "Deploy complete. Monitor with:"
echo "  aws ecs describe-services --cluster ${ECS_CLUSTER} --services ${ECS_SERVICE} --query 'services[0].deployments' --output table"
