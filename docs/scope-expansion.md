# LabRecord vs LabletInstance

- Expand the architecture documents about the new concept of "LabRecord" as **a separate aggregateroot from LabletInstance**!! This dramatically improve resource utilisation, initialization delay, efficiency of workload scheduling!
- A LabRecord is an abstrct LabTopology with its unique id, running in a specific RuntimeEnvironmentType (CML, POD, AWS, K8s)  and RuntimeWorker (CmlWorker.LabId, DC.Racks, Account.InstanceId, Cluster.Namespace.App). It can be created from a simple yaml definition, and represents a set of nodes/links and a set of external interfaces (protocol.ports). It may be versioned, started/edited/wiped/paused/resumed/stopped/cloned/saved/exported/archived, and represents a CML network topology reference as a canvas including nodes, links/edges, annotations, metadata, external_interfaces.
- A LabletInstance may include multiple LabRecords (especially if different CML labs may be interconnected! i.e "multi-lab" labs, with eg. new network sites or new subset of devices/nodes!), and any LabRecord may support multiple lablets, though probably only one at any point in time (i.e. wiping nodes and reset lab is a lot faster than start a fresh copy of a common lab definition! )

- Expand the scope of the Lablet-controller service to discover unknown LabRecords (each representing a CML Lab record with a globally unique ID) and enable users to link to a (new or existing) lablet instance(s), similarly to how workers are periodically discovered;

- Design an extensive backend API that enables full management of the Lablet instances, definitions, and their optional relationship(s) with LabRecord(s); and vice versa: management of LabRecords instances, revisions, runs (past jobs), optional relationship(s) with LabletInstance(s)
- Anticipate reasonable methods required to fully integrate LabletInstance Lifecycle and LabRecord (CML vs POD timeslot) Lifecycle
- Identify implementation gaps and plan for full stack frontend coverage in Bootstrap 5 and aligning to established event-driven and reactive patterns in both backend and frontend
