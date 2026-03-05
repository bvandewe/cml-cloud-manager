#!/usr/bin/env python3
"""Update Keycloak lcm-backend client redirect URIs to include localhost:8030."""

import requests

# Get admin token
token_resp = requests.post("http://localhost:8041/realms/master/protocol/openid-connect/token", data={"username": "admin", "password": "admin", "grant_type": "password", "client_id": "admin-cli"})
resp_json = token_resp.json()
if "access_token" not in resp_json:
    print(f"Failed to get admin token: {resp_json}")
    exit(1)
token = resp_json["access_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Get client by clientId
clients_resp = requests.get("http://localhost:8041/admin/realms/aix/clients?clientId=lcm-backend", headers=headers)
client = clients_resp.json()[0]
client_uuid = client["id"]
print(f"Found lcm-backend client: {client_uuid}")

# Update redirect URIs
client["redirectUris"] = ["http://localhost:8020/*", "http://localhost:8030/*", "http://localhost:8020/api/docs/oauth2-redirect", "http://localhost:8030/api/docs/oauth2-redirect"]
client["webOrigins"] = ["http://localhost:8020", "http://localhost:8030"]

update_resp = requests.put(f"http://localhost:8041/admin/realms/aix/clients/{client_uuid}", headers=headers, json=client)

if update_resp.status_code == 204:
    print("✅ Successfully updated lcm-backend redirect URIs to include localhost:8030")
else:
    print(f"❌ Error: {update_resp.status_code} - {update_resp.text}")
