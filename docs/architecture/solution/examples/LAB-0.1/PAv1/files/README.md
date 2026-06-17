# Packaged payloads (`files/`)

Binary payloads that primitives push into the POD live here. They are referenced from
job steps through the **`content.*`** scope (read-only) — never by absolute path.

In this sample, `jobs/post_init.yaml` seeds the candidate desktop with:

```yaml
- id: push_package
  uses: copy@v1
  target: workstation_22
  with:
    source: "${ content.files.desktop_package }"   # resolves to PAv1/files/desktop_package.tgz
    dest: "/home/cisco/Desktop/tmp/desktop_package.tgz"
    via_port: "${ runtime_env.devices.workstation.pat_port }"
```

The real lablet ships the actual archive here (legacy
`RCUv1/desktop_package.tgz`). It is omitted from this documentation sample to keep the
repository free of binaries; the `content.files.desktop_package` reference points at this
folder.
