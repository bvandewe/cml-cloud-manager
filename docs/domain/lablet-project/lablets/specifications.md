# Lablet Specifications

This document defines the comprehensive specifications for Cisco CML Lablets, establishing the standards and requirements for all certification lab experiences.

## Core Lablet Architecture

### Definition

A **Lablet** is a containerized, standardized certification lab experience that combines:

- **CML Topology**: Network simulation environment
- **Grading Engine**: Automated assessment and scoring
- **Content Framework**: Instructions, tasks, and validation
- **Resource Management**: Dynamic allocation and cleanup

### Lablet Lifecycle Integration

Every Lablet must integrate with the [11-State Lifecycle System](ops/state-management.md):

- Standardized state transitions
- Hook script extensibility
- Automated resource management
- Comprehensive monitoring and logging

## Technical Specifications

### Infrastructure Requirements

#### Compute Resources

- **Minimum vCPU**: 4 cores per concurrent lablet
- **Memory**: 16GB RAM per concurrent lablet
- **Storage**: 50GB persistent + 20GB ephemeral per lablet
- **Network**: 1Gbps bandwidth per 10 concurrent lablets

#### Software Dependencies

- **CML Version**: 2.9+ (latest stable)
- **Python Runtime**: 3.9+ for grading scripts
- **Container Runtime**: Docker 24.0+ or containerd 1.7+
- **Storage Backend**: MinIO/S3 compatible object storage

### Performance Standards

#### Initialization Benchmarks

- **Cold Start**: < 5 minutes from scheduled to ready-for-user
- **Warm Start**: < 2 minutes from pending to ready-for-user
- **Resource Allocation**: < 30 seconds for resource assignment
- **Topology Deployment**: < 3 minutes for network startup

#### Runtime Performance

- **Concurrent Users**: 100+ simultaneous lab sessions
- **Response Time**: < 2 seconds for candidate interactions
- **Availability Target**: 99.5% during scheduled exam windows
- **Recovery Time**: < 5 minutes for automatic failure recovery

### Security Requirements

#### Access Control

- **Authentication**: Integration with PVUE identity system
- **Authorization**: Role-based access (candidate, proctor, admin)
- **Network Isolation**: Secure tenant separation per lab session
- **Data Protection**: Encryption at rest and in transit (AES-256, TLS 1.3)

#### Compliance Standards

- **Data Retention**: Configurable retention policies (default 90 days)
- **Audit Logging**: Comprehensive activity tracking and forensics
- **Privacy**: GDPR/CCPA compliant candidate data handling
- **Certification**: SOC 2 Type II security controls

## Content Specifications

### Topology Design Standards

#### Network Architecture

- **Scalability**: Support 2-50 network devices per lablet
- **Flexibility**: Multiple vendor support (Cisco, generic Linux)
- **Realism**: Production-like network scenarios and challenges
- **Modularity**: Reusable topology components and templates

#### Image Management

- **Standard Images**: Curated catalog of certified node images
- **Custom Images**: Support for lablet-specific customizations
- **Version Control**: Immutable image versioning and rollback
- **Security Updates**: Automated security patching workflow

### Assessment Framework

#### Grading Specifications

- **Automated Scoring**: Python-based grading engine
- **Rubric System**: Weighted scoring with partial credit
- **Verification Methods**: Multi-modal validation (config, state, behavior)
- **Feedback Generation**: Detailed candidate feedback and explanations

#### Quality Assurance

- **Validation Testing**: Automated regression testing
- **Field Testing**: Beta testing with external reviewers
- **Performance Monitoring**: Continuous quality metrics
- **Content Review**: SME validation and approval workflow

## Integration Specifications

### ALII Protocol Compliance

All Lablets must support the [ALII Protocol](../integration/alii-protocol.md) endpoints:

- **S1 - Initialize**: Lab environment initialization
- **S2 - Access**: Secure lab URL provisioning
- **S3 - Grade**: Automated grading and score retrieval

### PVUE Integration

- **Session Management**: Seamless candidate session handling
- **Score Reporting**: Real-time score transmission
- **Incident Handling**: Automated failure notifications
- **Audit Trail**: Complete examination audit logs

### CML Platform Integration

- **Resource Management**: Dynamic CML worker allocation
- **Topology Lifecycle**: Automated deployment and cleanup
- **Monitoring Integration**: Health checks and performance metrics
- **Error Handling**: Graceful failure modes and recovery

## Lablet Categories

### By Certification Track

- **CCNA**: Entry-level networking fundamentals
- **CCNP**: Professional-level routing, switching, security
- **CCIE**: Expert-level advanced networking
- **DevNet**: Network programmability and automation
- **Security**: Cybersecurity and threat management

### By Technology Focus

- **Routing & Switching**: Traditional network infrastructure
- **Security**: Firewall, VPN, and security appliances
- **Wireless**: Wi-Fi and wireless networking
- **Data Center**: Nexus, ACI, and DC technologies
- **Service Provider**: SP routing and MPLS
- **Automation**: Python, APIs, and network programming

### By Complexity Level

- **Basic**: Single technology, linear workflow (30-60 minutes)
- **Intermediate**: Multi-technology, decision trees (60-120 minutes)
- **Advanced**: Complex scenarios, troubleshooting (120-180 minutes)
- **Expert**: Open-ended design and optimization (180+ minutes)

## Development Workflow

### Content Creation Process

1. **Requirements Analysis**: Learning objectives and assessment goals
2. **Topology Design**: CML network architecture and device selection
3. **Task Development**: Scenario creation and instruction writing
4. **Grading Implementation**: Automated scoring and validation logic
5. **Testing & Validation**: Quality assurance and field testing
6. **Production Deployment**: Release to certification delivery platform

### Version Management

- **Semantic Versioning**: Major.Minor.Patch versioning scheme
- **Change Control**: Formal change management process
- **Rollback Capability**: Ability to revert to previous versions
- **A/B Testing**: Gradual rollout and performance comparison

### Continuous Improvement

- **Performance Analytics**: Usage patterns and success rates
- **Candidate Feedback**: Post-exam surveys and suggestions
- **Technical Metrics**: System performance and reliability data
- **Content Updates**: Regular refresh and technology updates

This specification ensures consistent, high-quality lablet experiences that meet Cisco's certification standards while leveraging the full capabilities of the CML platform.
