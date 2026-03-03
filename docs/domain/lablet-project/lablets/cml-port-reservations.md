# CML Lablets Port Reservations

## Purpose

The following port numbers allow inbound remote access to Lab's internal nodes (TCP/UDP to console/VNC/Any) using the CML PATty tool.

**Documentation**: [PATty Tool Overview](https://developer.cisco.com/docs/modeling-labs/patty-tool-overview/)

## Usage Instructions

In CML, add "smart annotation(s)" to nodes as per the templates below:

- `serial:{console_port_number}` - For console access
- `vnc:{vnc_port_number}` - For VNC access
- `pat:{external_port_number}:{internal_port_number}` - For port address translation

!!! info "Port Requirements"
Port numbers must be in range **2000-7999** and **MUST BE UNIQUE** across ALL LABS

## Port Reservations Table

Click on column headers to sort the table. Use Ctrl+F (or Cmd+F) to search within the page.

<div class="table-controls">
    <div class="search-box">
        <label for="table-search">🔍 Quick Search:</label>
        <input type="text" id="table-search" placeholder="Search ports, devices, labs..." onkeyup="filterMarkdownTable()">
    </div>
    <small>💡 <strong>Tip:</strong> Click on column headers to sort. Table is searchable using the browser's built-in search (Ctrl+F / Cmd+F).</small>
</div>

<script>
function filterMarkdownTable() {
    var input = document.getElementById("table-search");
    if (!input) return;

    var filter = input.value.toLowerCase();
    var tables = document.querySelectorAll("table");

    tables.forEach(function(table) {
        // Only filter the port reservations table (skip the legend table)
        if (table.rows.length > 10) { // Port table has more rows
            var rows = table.getElementsByTagName("tr");

            for (var i = 1; i < rows.length; i++) { // Skip header row
                var row = rows[i];
                var shouldShow = false;
                var cells = row.getElementsByTagName("td");

                for (var j = 0; j < cells.length; j++) {
                    var cellText = cells[j].textContent || cells[j].innerText;
                    if (cellText.toLowerCase().indexOf(filter) > -1) {
                        shouldShow = true;
                        break;
                    }
                }

                row.style.display = shouldShow ? "" : "none";
            }
        }
    });
}
</script>

| Port | Type                                   | Lab Name                             | Device Name    | Notes                      |
| ---- | -------------------------------------- | ------------------------------------ | -------------- | -------------------------- |
| 5001 | <span class="port-type-ser">SER</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | DC1            | Console access             |
| 5002 | <span class="port-type-ser">SER</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | DC2            | Console access             |
| 5003 | <span class="port-type-ser">SER</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | ISP            | Console access             |
| 5004 | <span class="port-type-ser">SER</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | SW1            | Console access             |
| 5005 | <span class="port-type-ser">SER</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | SW2            | Console access             |
| 5006 | <span class="port-type-ser">SER</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | FTD1           | Console access             |
| 5007 | <span class="port-type-ser">SER</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | FMC1           | Console access             |
| 5008 | <span class="port-type-ser">SER</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | PC10           | Console access             |
| 5009 | <span class="port-type-ser">SER</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | PC20           | Console access             |
| 5010 | <span class="port-type-ser">SER</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | DMZSRV1        | Console access             |
| 5011 | <span class="port-type-vnc">VNC</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | PC10           | VNC access                 |
| 5012 | <span class="port-type-vnc">VNC</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | PC20           | VNC access                 |
| 5013 | <span class="port-type-vnc">VNC</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | DMZSRV1        | VNC access                 |
| 5014 | <span class="port-type-vnc">VNC</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | MGMT-PC        | VNC access                 |
| 5015 | <span class="port-type-ser">SER</span> | 350-701 LAB-2.4.1a MBhatti SCOR V1.1 | MGMT-PC        | Console access             |
| 5031 | <span class="port-type-ser">SER</span> | 350-601 LAB-1.1a                     | N9K1-1         | Console access             |
| 5032 | <span class="port-type-ser">SER</span> | 350-601 LAB-1.1a                     | N9K1-2         | Console access             |
| 5033 | <span class="port-type-ser">SER</span> | 350-601 LAB-1.1a                     | N9K1-3         | Console access             |
| 5034 | <span class="port-type-ser">SER</span> | 350-601 LAB-1.1a                     | N9K1-4         | Console access             |
| 5035 | <span class="port-type-ser">SER</span> | 350-601 LAB-1.1a                     | N9K1-ACCESS    | Console access             |
| 5036 | <span class="port-type-ser">SER</span> | 350-601 LAB-1.1a                     | Internet       | Console access             |
| 5037 | <span class="port-type-ser">SER</span> | 350-601 LAB-1.1a                     | ubuntu0        | Console access             |
| 5040 | <span class="port-type-pat">PAT</span> | 200-901 LAB-2.5.1                    | vmanage-mock   | External port for SSH (22) |
| 5041 | <span class="port-type-ser">SER</span> | 200-901 LAB-2.5.1                    | vmanage-mock   | Console access             |
| 5042 | <span class="port-type-ser">SER</span> | 200-901 LAB-2.5.1                    | ubuntu-desktop | Console access             |
| 5043 | <span class="port-type-ser">SER</span> | 200-901 LAB-2.5.1                    | gateway        | Console access             |
| 5044 | <span class="port-type-vnc">VNC</span> | 200-901 LAB-2.5.1                    | ubuntu-desktop | VNC access                 |
| 5045 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.1.1                    | rtr01          | Console access             |
| 5046 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.1.1                    | rtr02          | Console access             |
| 5047 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.1.1                    | mgt-rtr03      | Console access             |
| 5048 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.1.1                    | sw01           | Console access             |
| 5049 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.1.1                    | sw02           | Console access             |
| 5050 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.1.1                    | workstation    | Console access             |
| 5051 | <span class="port-type-vnc">VNC</span> | 350-901 LAB-1.1.1                    | workstation    | VNC access                 |
| 5052 | <span class="port-type-pat">PAT</span> | 350-901 LAB-1.1.1                    | workstation    | External port for SSH (22) |
| 5053 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.2.1                    | rtr01          | Console access             |
| 5054 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.2.1                    | rtr02          | Console access             |
| 5055 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.2.1                    | mgt-rtr03      | Console access             |
| 5056 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.2.1                    | sw01           | Console access             |
| 5057 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.2.1                    | sw02           | Console access             |
| 5058 | <span class="port-type-ser">SER</span> | 350-901 LAB-1.2.1                    | workstation    | Console access             |
| 5059 | <span class="port-type-vnc">VNC</span> | 350-901 LAB-1.2.1                    | workstation    | VNC access                 |
| 5060 | <span class="port-type-pat">PAT</span> | 350-901 LAB-1.2.1                    | workstation    | External port for SSH (22) |

## Port Type Legend

| Type    | Description               | Usage                                      |
| ------- | ------------------------- | ------------------------------------------ |
| **SER** | Serial Console            | Direct console access to device CLI        |
| **VNC** | Virtual Network Computing | Remote desktop access for GUI devices      |
| **PAT** | Port Address Translation  | External port mapping to internal services |

## Quick Reference

- **Total Ports Reserved**: 35 ports across 4 lab environments
- **Port Range Used**: 5001-5060
- **Lab Coverage**: SECCOR 350-701, DCCOR 350-601, DEVASC 200-901, DEVCORE 350-901
- **Device Types**: Routers, Switches, Firewalls, Management Systems, Workstations

## Lab Summary

### 350-701 SECCOR LAB-2.4.1a (Ports 5001-5015)

**11 devices** - Security-focused lab with DC infrastructure, switches, firewall, and management systems

### 350-601 DCCOR LAB-1.1a (Ports 5031-5037)

**7 devices** - Data center lab with Nexus 9K switches and Ubuntu systems

### 200-901 DEVASC LAB-2.5.1 (Ports 5040-5044)

**4 ports across 3 devices** - Development lab with SD-WAN management and desktop systems

### 350-901 DEVCORE LAB-1.1.1 (Ports 5045-5052)

**8 ports across 5 devices** - Core development lab with routers, switches, and workstation

### 350-901 DEVCORE LAB-1.2.1 (Ports 5053-5060)

**8 ports across 5 devices** - Extended development lab environment
