#!/usr/bin/env bash
# One-time provisioning: key pair, security group, Ubuntu 24.04 instance, Elastic IP. Idempotent by Name tag.
set -euo pipefail
cd "$(dirname "$0")"
export AWS_PROFILE="${AWS_PROFILE:-zc}"
NAME=z-computer
TYPE="${INSTANCE_TYPE:-t3.small}"
PUB="${SSH_PUBKEY:-$HOME/.ssh/id_ed25519.pub}"

if ! aws ec2 describe-key-pairs --key-names "$NAME" >/dev/null 2>&1; then
  aws ec2 import-key-pair --key-name "$NAME" --public-key-material "fileb://$PUB" >/dev/null
  echo "imported key pair $NAME from $PUB"
fi

VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SG=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$NAME" "Name=vpc-id,Values=$VPC" \
     --query 'SecurityGroups[0].GroupId' --output text)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name "$NAME" --description "z-computer ssh + web" --vpc-id "$VPC" --query GroupId --output text)
  for port in 22 80 443; do
    aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port "$port" --cidr 0.0.0.0/0 >/dev/null
  done
  echo "created security group $SG"
fi

ID=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
     --query 'Reservations[0].Instances[0].InstanceId' --output text)
if [ "$ID" = "None" ]; then
  AMI=$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text)
  ID=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$TYPE" --key-name "$NAME" --security-group-ids "$SG" \
       --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":20,"VolumeType":"gp3"}}]' \
       --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
       --query 'Instances[0].InstanceId' --output text)
  echo "launched $TYPE instance $ID"
fi
aws ec2 wait instance-running --instance-ids "$ID"

ALLOC=$(aws ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME" --query 'Addresses[0].AllocationId' --output text)
if [ "$ALLOC" = "None" ]; then
  ALLOC=$(aws ec2 allocate-address --domain vpc --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" --query AllocationId --output text)
fi
aws ec2 associate-address --instance-id "$ID" --allocation-id "$ALLOC" >/dev/null
IP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].PublicIp' --output text)

cat > instance.env <<ENV
INSTANCE_ID=$ID
HOST=$IP
SITE=${IP//./-}.sslip.io
ENV
echo "instance $ID  ip $IP  site https://${IP//./-}.sslip.io"
