# Deploying to AWS EC2

This guide describes how to deploy the Lablet Cloud Manager production stack to an AWS EC2 instance.

## Prerequisites

- **AWS Account**: Access to create EC2 instances and Security Groups.
- **SSH Key Pair**: For accessing the EC2 instance.
- **Domain Name (Optional)**: If you want to access the application via a domain name instead of the IP address.

## 1. Launch EC2 Instance

1. **Instance Type**: Recommended `t3.medium` or larger (2 vCPU, 4GB RAM) to handle the multiple containers (API, Worker, MongoDB, Keycloak, Observability stack).
2. **AMI**: Ubuntu Server 24.04 LTS or Amazon Linux 2023.
3. **Storage**: At least 20GB GP3 root volume.
4. **Security Group**:
    - Allow **SSH (22)** from your IP.
    - Allow **HTTP (80)** from Anywhere (0.0.0.0/0).
    - Allow **HTTPS (443)** from Anywhere (0.0.0.0/0).

## 2. Install Docker & Docker Compose on Ubuntu

SSH into your instance and install Docker.

```bash
# Update packages
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add the repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add user to docker group (avoid sudo for docker commands)
sudo usermod -aG docker $USER
newgrp docker
```

## 3. Deploy Application

You can either clone the repository or copy the necessary files.

### Option A: Clone Repository (Recommended)

If your repository is public or you have configured SSH keys/tokens:

```bash
git clone https://github.com/bvandewe/lablet-cloud-manager.git
cd lablet-cloud-manager
```

### Option B: Copy Files

If you don't want to clone the full repo, you only need the `deployment/` directory and `Makefile`.

```bash
# On your local machine
scp -r deployment/ Makefile user@your-ec2-ip:~/lablet-cloud-manager/
```

## 4. Configuration

1. Navigate to the project directory:

    ```bash
    cd lablet-cloud-manager
    ```

2. Create/Edit the production environment file:

    ```bash
    nano deployment/docker-compose/.env.prod
    ```

3. **Critical Settings to Update**:

    - **Security**: Change all passwords and secrets!
        - `JWT_SECRET_KEY`
        - `KEYCLOAK_ADMIN_PASSWORD`
        - `MONGODB_ROOT_PASSWORD`
        - `CML_WORKER_API_PASSWORD`
    - **AWS Credentials**:
        - `AWS_ACCESS_KEY_ID`
        - `AWS_SECRET_ACCESS_KEY`
    - **CML Worker Config**:
        - `CML_WORKER_SECURITY_GROUP_IDS`
        - `CML_WORKER_SUBNET_ID`
        - `CML_WORKER_KEY_NAME`
    - **Image Tag**:
        - `IMAGE_TAG=latest` (or specific version like `v1.0.0`)

## 5. Start the Stack

Use the Makefile to start the production stack:

```bash
make prod-up
```

This command uses `docker-compose` with the production file and environment variables.

## 6. Verify Deployment

1. **Check Containers**:

    ```bash
    make prod-ps
    ```

    Ensure all containers are `Up`.

2. **Check Logs**:

    ```bash
    make prod-logs
    ```

3. **Access Application**:
    Open your browser and navigate to your EC2 instance's public IP or domain.
    - **UI**: `http://<your-ec2-ip>/`
    - **Keycloak**: `http://<your-ec2-ip>/auth/`
    - **Grafana**: `http://<your-ec2-ip>/grafana/`

## Maintenance

- **Update Images**:

    ```bash
    make prod-pull
    make prod-up  # Recreates containers with new images
    ```

- **Restart Services**:

    ```bash
    make prod-restart
    ```

- **Restart Single Service**:

    ```bash
    make prod-restart-service SERVICE=nginx
    ```

- **Stop Services**:

    ```bash
    make prod-down
    ```
