# Standard Images Catalog

This catalog maintains the official **Cisco Lablet Standard Images** approved for use across certification lab environments.

**Quick Reference**:

- ✅ = Official Standard (Approved for certification labs)
- 🚧 = In Development
- ⚠️ = Deprecated

## Custom Node Definitions

| Node Name          | Status               | Version | Images                                                                   | Use Cases                                       | Documentation                              |
| ------------------ | -------------------- | ------- | ------------------------------------------------------------------------ | ----------------------------------------------- | ------------------------------------------ |
| **Mock API**       | ✅ Official Standard | 1.0     | `basic` (HTTP:8080)<br/>`vmanage` (HTTP:8000)                            | SCOR (HTTP endpoints)<br/>DEVASC (API with MFA) | [📋 Details](node-definitions/mock-api.md) |
| **Lablet Desktop** | ✅ Official Standard | v0.1.0  | `simple desktop with devasc and scor bookmarks`<br/>`automation desktop` | API client<br/>End-user Workstation             | 📋 _Coming Soon_                           |

---

## Standard VM Images Catalog

**Reference**: [CML v2.9 VM Images Documentation](https://developer.cisco.com/docs/modeling-labs/2-9/vm-images-for-cml-labs/#vm-images-for-cml-labs)

CML v2.9 provides access to various Cisco VM images and open source VM images through the refplat ISO file. These VM images are specially built for virtualization (not emulation) and are optimized for software-based network simulation.

### Cisco Reference Platform Images

**Current Status**: ✅ Available in CML v2.9
**License**: Only for use within Cisco Modeling Labs
**Characteristics**: Rate-limited, software-based feature implementation

#### Routing and Switching

- **[ASAv](https://developer.cisco.com/docs/modeling-labs/2-9/asav)** - Adaptive Security Appliance Virtual
- **[CAT 8000V](https://developer.cisco.com/docs/modeling-labs/2-9/cat-8000v)** - Catalyst 8000V Edge Platform
- **[CAT 9000v](https://developer.cisco.com/docs/modeling-labs/2-9/cat-9000v)** - Catalyst 9000v (Beta)
- **[CSR 1000v](https://developer.cisco.com/docs/modeling-labs/2-9/csr-1000v)** - Cloud Services Router 1000V
- **[IOL](https://developer.cisco.com/docs/modeling-labs/2-9/iol)** - IOS on Linux
- **[IOL-L2](https://developer.cisco.com/docs/modeling-labs/2-9/iol-l2)** - Layer 2 IOS on Linux
- **[IOL (Serial)](https://developer.cisco.com/docs/modeling-labs/2-9/iol-serial)** - Serial IOL
- **[IOSv](https://developer.cisco.com/docs/modeling-labs/2-9/iosv)** - IOS Virtual Router
- **[IOSvL2](https://developer.cisco.com/docs/modeling-labs/2-9/iosvl2)** - IOS Virtual Layer 2 Switch
- **[IOS XRv 9000](https://developer.cisco.com/docs/modeling-labs/2-9/ios-xrv-9000)** - IOS XRv 9000 Series
- **[NX-OS 9000](https://developer.cisco.com/docs/modeling-labs/2-9/nx-os-9000)** - Nexus 9000 Series

#### Security Platforms

- **[FMCv](https://developer.cisco.com/docs/modeling-labs/2-9/fmcv)** - Firepower Management Center Virtual
- **[FTDv](https://developer.cisco.com/docs/modeling-labs/2-9/ftdv)** - Firepower Threat Defense Virtual

#### SD-WAN and Wireless

- **[Catalyst SD-WAN](https://developer.cisco.com/docs/modeling-labs/2-9/catalyst-sd-wan)** - Manager, Controller, Validator, vEdge, Cisco Edge
- **[Catalyst 9800-CL](https://developer.cisco.com/docs/modeling-labs/2-9/catalyst-9800-cl)** - Wireless LAN Controller

#### Deprecated (Still Available)

- **[IOS XRv](https://developer.cisco.com/docs/modeling-labs/2-9/ios-xrv)** - Legacy IOS XRv
- **[NX-OS](https://developer.cisco.com/docs/modeling-labs/2-9/nx-os)** - Legacy Nexus OS

### Open Source VM Images

**License Status**: Do not count toward licensed node limits (except CML-Free)
**Purpose**: Host nodes, traffic generation, network troubleshooting

| Image                                                                               | Base OS         | Description                   | Use Case                    |
| ----------------------------------------------------------------------------------- | --------------- | ----------------------------- | --------------------------- |
| **[Server](https://developer.cisco.com/docs/modeling-labs/2-9/server)**             | Tiny Core Linux | Lightweight host node         | Basic endpoint simulation   |
| **[Alpine](https://developer.cisco.com/docs/modeling-labs/2-9/alpine)**             | Alpine Linux    | Network troubleshooting tools | Traffic generation, testing |
| **[Desktop](https://developer.cisco.com/docs/modeling-labs/2-9/desktop)**           | Alpine Linux    | Graphical desktop via VNC     | User interface testing      |
| **[Ubuntu](https://developer.cisco.com/docs/modeling-labs/2-9/ubuntu)**             | Ubuntu Linux    | Cloud-init support            | Modern Linux workloads      |
| **[Trex](https://developer.cisco.com/docs/modeling-labs/2-9/trex)**                 | Alpine Linux    | Trex traffic generator        | Performance testing         |
| **[WAN Emulator](https://developer.cisco.com/docs/modeling-labs/2-9/wan-emulator)** | Alpine Linux    | WanEM pre-installed           | WAN simulation              |

### Community Extensions

**Source**: [CML Community Repository](https://github.com/CiscoDevNet/cml-community)
**Support**: Best effort, community-maintained
**Examples**:

- Cisco virtual Wireless LAN Controller (AireOS)
- Cisco Identity Services Engine (ISE)
- Cisco UCS Platform Emulator (UCSPE)

### Key Considerations

**Virtualization vs Emulation**

- CML uses virtualization, not hardware emulation
- Software-based features work as on physical devices
- Hardware/ASIC features may have software implementations
- Rate-limited performance, not suitable for throughput testing

**Configuration Compatibility**

- Production configurations may require adjustment for CML
- Control and management plane features fully supported
- Data plane features implemented in software where possible
