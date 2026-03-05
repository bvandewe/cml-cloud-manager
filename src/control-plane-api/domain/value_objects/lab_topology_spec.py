"""LabTopologySpec value object for LabRecord aggregate.

Captures the full topology snapshot of a CML lab: nodes, links,
annotations, and raw YAML. Provides a SHA-256 checksum for
topology change detection (used by Lab Discovery V2, Phase 9).

Architecture ref: §4.1 Value Objects.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TopologyNode:
    """A node within a lab topology."""

    label: str
    node_definition: str
    x: int = 0
    y: int = 0
    tags: dict[str, str] = field(default_factory=dict)
    configuration: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "node_definition": self.node_definition,
            "x": self.x,
            "y": self.y,
            "tags": dict(self.tags),
            "configuration": self.configuration,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TopologyNode":
        return TopologyNode(
            label=data["label"],
            node_definition=data["node_definition"],
            x=data.get("x", 0),
            y=data.get("y", 0),
            tags=dict(data.get("tags", {})),
            configuration=data.get("configuration"),
        )


@dataclass(frozen=True)
class TopologyLink:
    """A link between two nodes in a lab topology."""

    source_node: str
    source_interface: str
    target_node: str
    target_interface: str
    label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_node": self.source_node,
            "source_interface": self.source_interface,
            "target_node": self.target_node,
            "target_interface": self.target_interface,
            "label": self.label,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TopologyLink":
        return TopologyLink(
            source_node=data["source_node"],
            source_interface=data["source_interface"],
            target_node=data["target_node"],
            target_interface=data["target_interface"],
            label=data.get("label"),
        )


@dataclass(frozen=True)
class TopologyAnnotation:
    """An annotation (text/shape) on the lab topology canvas."""

    text: str
    x: int = 0
    y: int = 0
    annotation_type: str = "text"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "x": self.x,
            "y": self.y,
            "annotation_type": self.annotation_type,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TopologyAnnotation":
        return TopologyAnnotation(
            text=data["text"],
            x=data.get("x", 0),
            y=data.get("y", 0),
            annotation_type=data.get("annotation_type", "text"),
        )


@dataclass(frozen=True)
class LabTopologySpec:
    """Full topology snapshot of a CML lab.

    Attributes:
        version: Topology format version.
        title: Lab title.
        description: Lab description.
        nodes: Parsed node definitions.
        links: Parsed link definitions.
        annotations: Canvas annotations.
        metadata: Additional topology metadata.
        raw_yaml: The original CML topology YAML (cached for import/export).
    """

    version: str | None = None
    title: str | None = None
    description: str | None = None
    nodes: tuple[TopologyNode, ...] = ()
    links: tuple[TopologyLink, ...] = ()
    annotations: tuple[TopologyAnnotation, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_yaml: str | None = None

    @property
    def node_count(self) -> int:
        """Return the number of nodes."""
        return len(self.nodes)

    @property
    def link_count(self) -> int:
        """Return the number of links."""
        return len(self.links)

    def checksum(self) -> str:
        """Compute SHA-256 checksum of canonical topology representation.

        Uses sorted JSON of nodes and links (excluding raw_yaml and annotations)
        for deterministic hashing regardless of element ordering.
        """
        canonical = {
            "version": self.version,
            "nodes": sorted(
                [{"label": n.label, "node_definition": n.node_definition, "tags": n.tags} for n in self.nodes],
                key=lambda n: n["label"],
            ),
            "links": sorted(
                [
                    {
                        "source_node": link.source_node,
                        "source_interface": link.source_interface,
                        "target_node": link.target_node,
                        "target_interface": link.target_interface,
                    }
                    for link in self.links
                ],
                key=lambda link: (link["source_node"], link["source_interface"]),
            ),
        }
        json_bytes = json.dumps(canonical, sort_keys=True).encode("utf-8")
        return hashlib.sha256(json_bytes).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "nodes": [n.to_dict() for n in self.nodes],
            "links": [link.to_dict() for link in self.links],
            "annotations": [a.to_dict() for a in self.annotations],
            "metadata": dict(self.metadata),
            "raw_yaml": self.raw_yaml,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "LabTopologySpec":
        """Create from dictionary."""
        return LabTopologySpec(
            version=data.get("version"),
            title=data.get("title"),
            description=data.get("description"),
            nodes=tuple(TopologyNode.from_dict(n) for n in data.get("nodes", [])),
            links=tuple(TopologyLink.from_dict(link) for link in data.get("links", [])),
            annotations=tuple(TopologyAnnotation.from_dict(a) for a in data.get("annotations", [])),
            metadata=dict(data.get("metadata", {})),
            raw_yaml=data.get("raw_yaml"),
        )

    @staticmethod
    def empty() -> "LabTopologySpec":
        """Create an empty topology spec."""
        return LabTopologySpec()
