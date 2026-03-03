# Project Objectives

## Overview

Lablet Cloud Manager is a web application that enables users to manage AWS EC2-hosted Cisco Modeling Lab (CML) instances through a secure, role-based interface.

## Core Objectives

### 1. EC2 Instance Management

The application provides users with streamlined access to CML instances hosted on AWS EC2:

- **Connect to Running Instances**: Users can connect to an existing, running CML instance via HTTPS
- **Create New Instances**: Users can request creation of a new EC2 instance if one doesn't exist
- **Start Stopped Instances**: Users can request to start an EC2 instance that exists but is stopped
- **Monitor Availability**: The app collects EC2 instance details and monitors HTTPS service availability, enabling seamless connection when ready

### 2. Cisco Modeling Lab Integration

The EC2 instances host Cisco Modeling Lab hypervisors:

- **Development Labs**: Users host their network development lab(s) on the CML instance
- **Lab Access**: Users can access their assigned labs once the CML instance is operational
- **Strong API Integration**: The app leverages CML's comprehensive API for management tasks

### 3. Role-Based Access Control (RBAC)

Strong RBAC is implemented locally within the application:

#### Admin Capabilities

- Grant users access to existing labs hosted in the CML instance
- Manage user permissions and lab assignments
- Perform administrative tasks on CML instance

#### User Restrictions

Regular users are restricted to essential operations only:

- Check EC2 instance status
- Request instance creation (if authorized)
- Request instance start
- Connect to CML via HTTPS when available

### 4. Lifecycle Automation

The application automates EC2 instance lifecycle management:

- **Telemetry Collection**: Monitors CML instance usage and activity
- **Idle Detection**: Tracks instance idle time
- **Auto-Shutdown**: Automatically stops EC2 instance after configurable idle duration
- **Cost Optimization**: Reduces AWS costs by managing instance uptime based on actual usage

### 5. CML Administrative Tasks

The application performs administrative operations via CML's API:

- **License Management**: Register and manage CML licenses
- **Instance Configuration**: Configure CML instance settings
- **System Administration**: Perform other administrative tasks as needed

### 6. Cross-Account AWS Architecture

The application supports flexible AWS deployment:

- **Separate AWS Accounts**: May be hosted in a different AWS account from the CML instance
- **Credential-Based Access**: Uses provided AWS credentials to interact with EC2
- **Boto3 Integration**: Leverages boto3 for all AWS EC2 operations

## Technical Requirements

### Authentication & Authorization

- OAuth2/OIDC integration (Keycloak)
- Role-based access control at application layer
- Session management with Redis

### AWS Integration

- boto3 for EC2 operations
- Cross-account IAM role support
- Instance state management (create, start, stop, monitor)

### CML Integration

- HTTPS connectivity monitoring
- CML API client integration
- Telemetry collection
- Administrative task automation

### Monitoring & Observability

- Instance state tracking
- User activity logging
- Idle time detection
- Service availability monitoring

## User Workflows

### Workflow 1: Access Existing Running Instance

1. User logs in
2. App checks EC2 instance status
3. If running, app verifies HTTPS availability
4. User connects to CML via provided HTTPS link

### Workflow 2: Start Stopped Instance

1. User logs in
2. App detects instance exists but is stopped
3. User requests instance start
4. App monitors startup and HTTPS availability
5. User connects when ready

### Workflow 3: Create New Instance

1. User logs in (with appropriate permissions)
2. App detects no instance exists
3. User requests instance creation
4. App provisions EC2 instance with CML
5. App monitors initialization
6. User connects when ready

### Workflow 4: Automatic Shutdown

1. App continuously monitors CML telemetry
2. Detects idle period exceeds threshold
3. Automatically stops EC2 instance
4. Logs action and notifies relevant parties

## Success Criteria

- ✅ Users can seamlessly connect to CML instances via HTTPS
- ✅ Instance lifecycle is automated based on usage
- ✅ Strong RBAC ensures appropriate access controls
- ✅ Administrative tasks can be performed via CML API
- ✅ Cross-account AWS architecture is supported
- ✅ AWS costs are optimized through intelligent instance management
