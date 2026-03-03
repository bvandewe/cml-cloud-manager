# AWS IAM Setup for CML Worker Management

This document describes how to provision AWS credentials with the appropriate IAM permissions for the Lablet Cloud Manager to manage CML Worker EC2 instances.

## Overview

The Lablet Cloud Manager uses AWS SDK (boto3) to interact with AWS services for managing CML Worker instances. The application requires programmatic access credentials (Access Key ID and Secret Access Key) with specific IAM permissions.

---

## Required AWS Services

The application interacts with the following AWS services:

1. **Amazon EC2** - Create, start, stop, terminate, and monitor EC2 instances
2. **Amazon CloudWatch** - Retrieve CPU and memory utilization metrics

---

## IAM User Setup

### Step 1: Create IAM User

1. Sign in to the [AWS IAM Console](https://console.aws.amazon.com/iam/)
2. Navigate to **Users** → **Add users**
3. Enter a username (e.g., `lablet-cloud-manager-service`)
4. Select **Access key - Programmatic access** (not console access)
5. Click **Next: Permissions**

### Step 2: Create Custom IAM Policy

Create a custom policy with the minimum required permissions for CML Worker management.

**Policy Name:** `CMLWorkerManagementPolicy`

**Policy JSON:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2InstanceManagement",
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:StartInstances",
        "ec2:StopInstances",
        "ec2:TerminateInstances",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus",
        "ec2:DescribeImages",
        "ec2:DescribeRegions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "EC2TagManagement",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateTags",
        "ec2:DeleteTags",
        "ec2:DescribeTags"
      ],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchMetricsRead",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:GetMetricStatistics"
      ],
      "Resource": "*"
    }
  ]
}
```

### Step 3: Attach Policy to User

1. In the IAM user creation wizard, select **Attach policies directly**
2. Click **Create policy** (opens in new tab)
3. Paste the JSON policy above
4. Review and create the policy
5. Return to the user creation wizard and attach the newly created policy
6. Complete the user creation

### Step 4: Generate Access Keys

1. After creating the user, navigate to the **Security credentials** tab
2. Click **Create access key**
3. Select **Application running outside AWS**
4. Optionally add a description tag (e.g., "Lablet Cloud Manager Production")
5. **Download the credentials** - you'll only see the secret key once!

---

## Required IAM Permissions (Detailed)

### EC2 Permissions

| Permission | Purpose | Used In |
|------------|---------|---------|
| `ec2:RunInstances` | Create new EC2 instances for CML Workers | `create_instance()` |
| `ec2:StartInstances` | Start stopped CML Worker instances | `start_instance()` |
| `ec2:StopInstances` | Stop running CML Worker instances | `stop_instance()` |
| `ec2:TerminateInstances` | Permanently terminate CML Worker instances | `terminate_instance()` |
| `ec2:DescribeInstances` | Query instance details, state, and metadata | `get_instance_details()`, `get_all_instances()` |
| `ec2:DescribeInstanceStatus` | Check instance status checks (system/instance) | `get_instance_status()` |
| `ec2:DescribeImages` | Query AMI details and search AMIs by name | `get_ami_ids_by_name()` |
| `ec2:DescribeRegions` | List available AWS regions (health check) | `health()` |

### EC2 Tag Permissions

| Permission | Purpose | Used In |
|------------|---------|---------|
| `ec2:CreateTags` | Add or update tags on instances | `update_instance_tags()` |
| `ec2:DeleteTags` | Remove tags from instances | `delete_instance_tags()` |
| `ec2:DescribeTags` | Query existing tags on instances | `get_instance_tags()` |

### CloudWatch Permissions

| Permission | Purpose | Used In |
|------------|---------|---------|
| `cloudwatch:GetMetricStatistics` | Retrieve CPU and memory utilization metrics | `get_instance_resources_utilization()` |

---

## Resource Restrictions (Optional Security Hardening)

For production environments, consider restricting permissions to specific resources:

### Restrict to Specific Regions

```json
{
  "Sid": "EC2InstanceManagementRegionRestricted",
  "Effect": "Allow",
  "Action": [
    "ec2:RunInstances",
    "ec2:StartInstances",
    "ec2:StopInstances",
    "ec2:TerminateInstances",
    "ec2:DescribeInstances",
    "ec2:DescribeInstanceStatus",
    "ec2:DescribeImages"
  ],
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "ec2:Region": [
        "us-east-1",
        "us-west-2"
      ]
    }
  }
}
```

### Restrict to Tagged Instances

Require all CML Worker instances to have a specific tag:

```json
{
  "Sid": "EC2InstanceManagementTagRestricted",
  "Effect": "Allow",
  "Action": [
    "ec2:StartInstances",
    "ec2:StopInstances",
    "ec2:TerminateInstances"
  ],
  "Resource": "arn:aws:ec2:*:*:instance/*",
  "Condition": {
    "StringEquals": {
      "ec2:ResourceTag/ManagedBy": "lablet-cloud-manager"
    }
  }
}
```

### Restrict RunInstances Parameters

Limit instance types and AMIs that can be launched:

```json
{
  "Sid": "EC2RunInstancesRestricted",
  "Effect": "Allow",
  "Action": "ec2:RunInstances",
  "Resource": "arn:aws:ec2:*:*:instance/*",
  "Condition": {
    "StringLike": {
      "ec2:InstanceType": [
        "c5.*",
        "c6i.*",
        "m5.*"
      ]
    }
  }
}
```

---

## Environment Configuration

After generating the AWS access keys, configure them in your environment:

### Docker Compose / .env File

```bash
# ============================================================================
# AWS Settings
# ============================================================================
AWS_ACCESS_KEY_ID=AKIA6G....
AWS_SECRET_ACCESS_KEY=4mQiit....
```

### Kubernetes Secret

```bash
kubectl create secret generic aws-credentials \
  --from-literal=AWS_ACCESS_KEY_ID='AKIA...' \
  --from-literal=AWS_SECRET_ACCESS_KEY='...' \
  --namespace=lablet-cloud-manager
```

### Environment Variables (Direct)

```bash
export AWS_ACCESS_KEY_ID='AKIA...'
export AWS_SECRET_ACCESS_KEY='...'
```

---

## Security Best Practices

### 1. Use Least Privilege

- Only grant the minimum permissions required
- Restrict by region, instance tags, or instance types when possible
- Regularly audit and remove unused permissions

### 2. Credential Rotation

- Rotate access keys every 90 days
- Use AWS Secrets Manager or similar for automatic rotation
- Monitor for unused credentials

### 3. Enable CloudTrail

Enable AWS CloudTrail to audit all API calls made by the service account:

```bash
aws cloudtrail create-trail \
  --name cml-worker-management-audit \
  --s3-bucket-name my-audit-bucket
```

### 4. Use IAM Roles (When Possible)

If running on AWS infrastructure (EC2, ECS, EKS), use IAM roles instead of access keys:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

Then attach the `CMLWorkerManagementPolicy` to the role.

### 5. Monitor Credential Usage

Set up CloudWatch alarms for unusual API activity:

- High number of `RunInstances` calls
- `TerminateInstances` calls outside business hours
- Failed authentication attempts

---

## Testing Credentials

After configuring credentials, test them using the health check endpoint:

```bash
curl -X GET http://localhost:8030/health
```

Check the application logs for AWS connectivity:

```bash
docker logs lablet-cloud-manager-app-1 | grep "AWS EC2"
```

Expected output:

```
INFO  ✅ AWS EC2 connection successful
INFO  ✅ AWS EC2 Client registered in DI container
```

If credentials are invalid:

```
WARNING  ⚠️ AWS EC2 health check failed: Error while verifying access to EC2: An error occurred (AuthFailure)
WARNING  ⚠️ AWS operations may fail at runtime
```

---

## Troubleshooting

### Issue: "AuthFailure" Error

**Cause:** Invalid or expired credentials

**Solution:**

1. Verify credentials are correctly set in `.env`
2. Check if the IAM user is active (not deleted)
3. Verify access keys haven't been rotated or disabled
4. Test credentials with AWS CLI:

   ```bash
   aws ec2 describe-regions --profile cml-manager
   ```

### Issue: "UnauthorizedOperation" Error

**Cause:** Missing IAM permissions

**Solution:**

1. Review the IAM policy attached to the user
2. Ensure all required permissions from the policy above are included
3. Check for explicit Deny statements in other policies
4. Verify resource restrictions aren't blocking operations

### Issue: CloudWatch Metrics Return "Unknown"

**Cause:** Missing CloudWatch permissions or metrics not enabled

**Solution:**

1. Verify `cloudwatch:GetMetricStatistics` permission is granted
2. Enable detailed monitoring on EC2 instances
3. Install CloudWatch agent on instances for memory metrics
4. Check CloudWatch service availability in the region

---

## Additional Resources

- [AWS IAM Best Practices](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [AWS EC2 API Reference](https://docs.aws.amazon.com/AWSEC2/latest/APIReference/)
- [AWS CloudWatch Metrics for EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/viewing_metrics_with_cloudwatch.html)
- [Boto3 EC2 Documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html)

---

## Policy Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-11-16 | Initial policy with EC2 and CloudWatch permissions |

---

## Contact

For questions about AWS IAM setup or permissions issues, contact the infrastructure team or refer to the application logs for detailed error messages.
