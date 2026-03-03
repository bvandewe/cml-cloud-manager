
40 files reformatted, 76 files left unchanged.

isort....................................................................Failed

- hook id: isort
- files were modified by this hook

Fixing /Users/bvandewe/Documents/Work/Systems/Mozart/src/microservices/lablet-cloud-manager/src/application/services/worker_monitoring_scheduler.py
Fixing /Users/bvandewe/Documents/Work/Systems/Mozart/src/microservices/lablet-cloud-manager/src/integration/models/cml_host_dto.py

flake8...................................................................Failed

- hook id: flake8
- exit code: 1

src/application/mapping/profile.py:32:21: F841 local variable 'map' is assigned to but never used
src/integration/enums/**init**.py:1:1: F401 '.aws_regions.AwsRegion' imported but unused
src/integration/enums/**init**.py:2:1: F401 '.cisco_certs.TrackLevel' imported but unused
src/integration/enums/**init**.py:2:1: F401 '.cisco_certs.TrackType' imported but unused
src/integration/enums/**init**.py:3:1: F401 '.ec2_instance.Ec2InstanceResourcesUtilizationRelativeStartTime' imported but unused
src/integration/enums/**init**.py:3:1: F401 '.ec2_instance.Ec2InstanceStatus' imported but unused
src/integration/enums/**init**.py:3:1: F401 '.ec2_instance.Ec2InstanceType' imported but unused

prettier.................................................................Failed

- hook id: prettier
- files were modified by this hook

deployment/otel-collector-config.yaml
docker-compose.yml


markdownlint.............................................................Failed

- hook id: markdownlint
- exit code: 1
- files were modified by this hook

notes/APSCHEDULER_REFACTORING_SUMMARY.md:291:1 MD029/ol-prefix Ordered list item prefix [Expected: 1; Actual: 2; Style: 1/2/3]
notes/APSCHEDULER_REFACTORING_SUMMARY.md:306:1 MD029/ol-prefix Ordered list item prefix [Expected: 1; Actual: 3; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:532:1 MD029/ol-prefix Ordered list item prefix [Expected: 1; Actual: 5; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:533:1 MD029/ol-prefix Ordered list item prefix [Expected: 2; Actual: 6; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:534:1 MD029/ol-prefix Ordered list item prefix [Expected: 3; Actual: 7; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:535:1 MD029/ol-prefix Ordered list item prefix [Expected: 4; Actual: 8; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:539:1 MD029/ol-prefix Ordered list item prefix [Expected: 1; Actual: 9; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:540:1 MD029/ol-prefix Ordered list item prefix [Expected: 2; Actual: 10; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:541:1 MD029/ol-prefix Ordered list item prefix [Expected: 3; Actual: 11; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:542:1 MD029/ol-prefix Ordered list item prefix [Expected: 4; Actual: 12; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:543:1 MD029/ol-prefix Ordered list item prefix [Expected: 5; Actual: 13; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:547:1 MD029/ol-prefix Ordered list item prefix [Expected: 1; Actual: 14; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:548:1 MD029/ol-prefix Ordered list item prefix [Expected: 2; Actual: 15; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:549:1 MD029/ol-prefix Ordered list item prefix [Expected: 3; Actual: 16; Style: 1/2/3]
docs/code-review-settings-and-aws-client.md:550:1 MD029/ol-prefix Ordered list item prefix [Expected: 4; Actual: 17; Style: 1/2/3]
docs/observability/tracing.md:884:1 MD029/ol-prefix Ordered list item prefix [Expected: 1; Actual: 2; Style: 1/2/3]
docs/observability/tracing.md:945:1 MD029/ol-prefix Ordered list item prefix [Expected: 1; Actual: 2; Style: 1/2/3]
docs/observability/tracing.md:956:1 MD029/ol-prefix Ordered list item prefix [Expected: 1; Actual: 3; Style: 1/2/3]

yamllint.................................................................Passed
bandit...................................................................Failed

- hook id: bandit
- exit code: 1

[main]  INFO    profile include tests: None
[main]  INFO    profile exclude tests: B101
[main]  INFO    cli include tests: None
[main]  INFO    cli exclude tests: None
[main]  INFO    using config: pyproject.toml
[main]  INFO    running on Python 3.11.11
Working... ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 100% 0:00:00
Run started:2025-11-17 10:59:24.170054


Test results:
>> Issue: [B501:request_with_no_cert_validation] Call to requests with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b501_request_with_no_cert_validation.html
   Location: ./src/utils/cmlctl.py:69:11
68          resp = requests.post(
69              url, json={"username": username, "password": password}, verify=False
70          )
71          resp.raise_for_status()
72          logger.info("Authentication successful")

--------------------------------------------------
>> Issue: [B113:request_without_timeout] Call to requests without timeout
   Severity: Medium   Confidence: Low
   CWE: CWE-400 (https://cwe.mitre.org/data/definitions/400.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b113_request_without_timeout.html
   Location: ./src/utils/cmlctl.py:68:11
67          url = f"https://{cml_server}/api/v0/authenticate"
68          resp = requests.post(
69              url, json={"username": username, "password": password}, verify=False
70          )
71          resp.raise_for_status()

--------------------------------------------------
>> Issue: [B501:request_with_no_cert_validation] Call to requests with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b501_request_with_no_cert_validation.html
   Location: ./src/utils/cmlctl.py:81:15
80          headers = {"Authorization": f"Bearer {token}"}
81          response = requests.get(url, headers=headers, verify=False)
82          response.raise_for_status()

--------------------------------------------------
>> Issue: [B113:request_without_timeout] Call to requests without timeout
   Severity: Medium   Confidence: Low
   CWE: CWE-400 (https://cwe.mitre.org/data/definitions/400.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b113_request_without_timeout.html
   Location: ./src/utils/cmlctl.py:81:15
80          headers = {"Authorization": f"Bearer {token}"}
81          response = requests.get(url, headers=headers, verify=False)
82          response.raise_for_status()

--------------------------------------------------
>> Issue: [B501:request_with_no_cert_validation] Call to requests with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b501_request_with_no_cert_validation.html
   Location: ./src/utils/cmlctl.py:101:15
100             headers = {"Authorization": f"Bearer {token}"}
101             resp = requests.get(url, headers=headers, verify=False)
102             resp.raise_for_status()

--------------------------------------------------
>> Issue: [B113:request_without_timeout] Call to requests without timeout
   Severity: Medium   Confidence: Low
   CWE: CWE-400 (https://cwe.mitre.org/data/definitions/400.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b113_request_without_timeout.html
   Location: ./src/utils/cmlctl.py:101:15
100             headers = {"Authorization": f"Bearer {token}"}
101             resp = requests.get(url, headers=headers, verify=False)
102             resp.raise_for_status()

--------------------------------------------------
>> Issue: [B501:request_with_no_cert_validation] Call to requests with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b501_request_with_no_cert_validation.html
   Location: ./src/utils/cmlctl.py:132:23
131                 headers = {"Authorization": f"Bearer {token}"}
132                 lab_resp = requests.get(lab_url, headers=headers, verify=False)
133                 lab_resp.raise_for_status()

--------------------------------------------------
>> Issue: [B113:request_without_timeout] Call to requests without timeout
   Severity: Medium   Confidence: Low
   CWE: CWE-400 (https://cwe.mitre.org/data/definitions/400.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b113_request_without_timeout.html
   Location: ./src/utils/cmlctl.py:132:23
131                 headers = {"Authorization": f"Bearer {token}"}
132                 lab_resp = requests.get(lab_url, headers=headers, verify=False)
133                 lab_resp.raise_for_status()

--------------------------------------------------
>> Issue: [B501:request_with_no_cert_validation] Call to requests with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b501_request_with_no_cert_validation.html
   Location: ./src/utils/cmlctl.py:138:25
137                 nodes_url = f"https://{cml_server}/api/v0/labs/{lab_id}/nodes?data=true"
138                 nodes_resp = requests.get(nodes_url, headers=headers, verify=False)
139                 nodes_resp.raise_for_status()

--------------------------------------------------
>> Issue: [B113:request_without_timeout] Call to requests without timeout
   Severity: Medium   Confidence: Low
   CWE: CWE-400 (https://cwe.mitre.org/data/definitions/400.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b113_request_without_timeout.html
   Location: ./src/utils/cmlctl.py:138:25
137                 nodes_url = f"https://{cml_server}/api/v0/labs/{lab_id}/nodes?data=true"
138                 nodes_resp = requests.get(nodes_url, headers=headers, verify=False)
139                 nodes_resp.raise_for_status()

--------------------------------------------------
>> Issue: [B501:request_with_no_cert_validation] Call to requests with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b501_request_with_no_cert_validation.html
   Location: ./src/utils/cmlctl.py:164:11
163         headers = {"Authorization": f"Bearer {token}"}
164         resp = requests.get(nodes_url, headers=headers, verify=False)
165         resp.raise_for_status()

--------------------------------------------------
>> Issue: [B113:request_without_timeout] Call to requests without timeout
   Severity: Medium   Confidence: Low
   CWE: CWE-400 (https://cwe.mitre.org/data/definitions/400.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b113_request_without_timeout.html
   Location: ./src/utils/cmlctl.py:164:11
163         headers = {"Authorization": f"Bearer {token}"}
164         resp = requests.get(nodes_url, headers=headers, verify=False)
165         resp.raise_for_status()

--------------------------------------------------
>> Issue: [B501:request_with_no_cert_validation] Call to requests with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b501_request_with_no_cert_validation.html
   Location: ./src/utils/cmlctl.py:179:4
178         headers = {"Authorization": f"Bearer {token}"}
179         requests.put(url, headers=headers, verify=False).raise_for_status()
180         logger.info("Node stopped successfully")

--------------------------------------------------
>> Issue: [B113:request_without_timeout] Call to requests without timeout
   Severity: Medium   Confidence: Low
   CWE: CWE-400 (https://cwe.mitre.org/data/definitions/400.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b113_request_without_timeout.html
   Location: ./src/utils/cmlctl.py:179:4
178         headers = {"Authorization": f"Bearer {token}"}
179         requests.put(url, headers=headers, verify=False).raise_for_status()
180         logger.info("Node stopped successfully")

--------------------------------------------------
>> Issue: [B501:request_with_no_cert_validation] Call to requests with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b501_request_with_no_cert_validation.html
   Location: ./src/utils/cmlctl.py:188:11
187         headers = {"Authorization": f"Bearer {token}"}
188         resp = requests.put(url, headers=headers, verify=False)
189         if resp.status_code != 204:

--------------------------------------------------
>> Issue: [B113:request_without_timeout] Call to requests without timeout
   Severity: Medium   Confidence: Low
   CWE: CWE-400 (https://cwe.mitre.org/data/definitions/400.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b113_request_without_timeout.html
   Location: ./src/utils/cmlctl.py:188:11
187         headers = {"Authorization": f"Bearer {token}"}
188         resp = requests.put(url, headers=headers, verify=False)
189         if resp.status_code != 204:

--------------------------------------------------
>> Issue: [B501:request_with_no_cert_validation] Call to requests with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b501_request_with_no_cert_validation.html
   Location: ./src/utils/cmlctl.py:199:4
198         headers = {"Authorization": f"Bearer {token}"}
199         requests.put(url, headers=headers, verify=False).raise_for_status()
200         logger.info("Node started successfully")

--------------------------------------------------
>> Issue: [B113:request_without_timeout] Call to requests without timeout
   Severity: Medium   Confidence: Low
   CWE: CWE-400 (https://cwe.mitre.org/data/definitions/400.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b113_request_without_timeout.html
   Location: ./src/utils/cmlctl.py:199:4
198         headers = {"Authorization": f"Bearer {token}"}
199         requests.put(url, headers=headers, verify=False).raise_for_status()
200         logger.info("Node started successfully")

--------------------------------------------------
>> Issue: [B501:request_with_no_cert_validation] Call to requests with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b501_request_with_no_cert_validation.html
   Location: ./src/utils/cmlctl.py:227:19
226             try:
227                 resp = requests.get(url, headers=headers, verify=False)
228                 resp.raise_for_status()

--------------------------------------------------
>> Issue: [B113:request_without_timeout] Call to requests without timeout
   Severity: Medium   Confidence: Low
   CWE: CWE-400 (https://cwe.mitre.org/data/definitions/400.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b113_request_without_timeout.html
   Location: ./src/utils/cmlctl.py:227:19
226             try:
227                 resp = requests.get(url, headers=headers, verify=False)
228                 resp.raise_for_status()

--------------------------------------------------
>> Issue: [B501:request_with_no_cert_validation] Call to requests with verify=False disabling SSL certificate checks, security issue.
   Severity: High   Confidence: High
   CWE: CWE-295 (https://cwe.mitre.org/data/definitions/295.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b501_request_with_no_cert_validation.html
   Location: ./src/utils/cmlctl.py:317:23
316                     headers = {"Authorization": f"Bearer {token}"}
317                     resp = requests.get(url, headers=headers, verify=False)
318                     resp.raise_for_status()

--------------------------------------------------
>> Issue: [B113:request_without_timeout] Call to requests without timeout
   Severity: Medium   Confidence: Low
   CWE: CWE-400 (https://cwe.mitre.org/data/definitions/400.html)
   More Info: https://bandit.readthedocs.io/en/0.0.0/plugins/b113_request_without_timeout.html
   Location: ./src/utils/cmlctl.py:317:23
316                     headers = {"Authorization": f"Bearer {token}"}
317                     resp = requests.get(url, headers=headers, verify=False)
318                     resp.raise_for_status()

--------------------------------------------------

Code scanned:
        Total lines of code: 12946
        Total lines skipped (#nosec): 0

Run metrics:
        Total issues (by severity):
                Undefined: 0
                Low: 0
                Medium: 11
                High: 11
        Total issues (by confidence):
                Undefined: 0
                Low: 11
                Medium: 0
                High: 11
Files skipped (0):

Detect secrets...........................................................Failed

- hook id: detect-secrets
- exit code: 3
- files were modified by this hook

ERROR: Potential secrets about to be committed to git repo!

Secret Type: JSON Web Token
Location:    notes/cml_v2.9_openapi.json:352

Secret Type: Hex High Entropy String
Location:    notes/cml_v2.9_openapi.json:6112

Possible mitigations:

- For information about putting your secrets in a safer place, please ask in
    #security
- Mark false positives with an inline `pragma: allowlist secret`
    comment

If a secret has already been committed, visit
https://help.github.com/articles/removing-sensitive-data-from-a-repository
The baseline file was updated.
Probably to keep line numbers of secrets up-to-date.
Please `git add .secrets.baseline`, thank you.


ERROR: Potential secrets about to be committed to git repo!

Secret Type: Secret Keyword
Location:    docs/security/authorization.md:658

Possible mitigations:

- For information about putting your secrets in a safer place, please ask in
    #security
- Mark false positives with an inline `pragma: allowlist secret`
    comment

If a secret has already been committed, visit
https://help.github.com/articles/removing-sensitive-data-from-a-repository
ERROR: Potential secrets about to be committed to git repo!

Secret Type: Secret Keyword
Location:    notes/OAUTH2_CLIENT_CONFIGURATION.md:53

Possible mitigations:

- For information about putting your secrets in a safer place, please ask in
    #security
- Mark false positives with an inline `pragma: allowlist secret`
    comment

If a secret has already been committed, visit
https://help.github.com/articles/removing-sensitive-data-from-a-repository
