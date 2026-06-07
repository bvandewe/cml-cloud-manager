# PAv1 vendored schemas

These JSON Schemas are runtime copies of `docs/architecture/content-format/schemas/`.
Vendoring them under the runtime package keeps `lcm_core` self-contained (no
dependency on the documentation tree).

When amending a schema, update **both** copies in the same commit.
