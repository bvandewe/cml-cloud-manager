"""AWS EC2 SPI Client for Worker Controller.

Service Provider Interface (SPI) for AWS EC2 operations.
Handles instance lifecycle and state queries.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None  # type: ignore
    ClientError = Exception  # type: ignore

if TYPE_CHECKING:
    from neuroglia.dependency_injection import ServiceCollection

logger = logging.getLogger(__name__)


@dataclass
class Ec2InstanceState:
    """EC2 instance state information."""

    instance_id: str
    state: str  # pending, running, stopping, stopped, terminated
    state_reason: str | None = None
    public_ip: str | None = None
    private_ip: str | None = None
    instance_type: str | None = None
    launch_time: datetime | None = None
    image_id: str | None = None
    name: str | None = None  # EC2 Name tag


@dataclass
class AwsCredentials:
    """AWS credentials configuration."""

    access_key_id: str
    secret_access_key: str
    region: str = "us-east-1"


class AwsEc2SpiClient:
    """AWS EC2 Service Provider Interface.

    Handles EC2 instance operations for worker lifecycle management.
    """

    def __init__(self, credentials: AwsCredentials):
        """Initialize the EC2 SPI client.

        Args:
            credentials: AWS credentials and region.
        """
        if boto3 is None:
            raise RuntimeError("boto3 is required for AWS EC2 operations")

        self._credentials = credentials
        self._client = None

    def _get_client(self):
        """Get or create boto3 EC2 client."""
        if self._client is None:
            self._client = boto3.client(
                "ec2",
                region_name=self._credentials.region,
                aws_access_key_id=self._credentials.access_key_id,
                aws_secret_access_key=self._credentials.secret_access_key,
            )
        return self._client

    async def _run_async(self, func, *args, **kwargs) -> Any:
        """Run blocking boto3 call in executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def get_ami_ids_by_name(self, ami_name: str) -> list[str]:
        """Get AMI IDs matching a name pattern.

        Args:
            ami_name: AMI name pattern (supports wildcards like "CML-*").

        Returns:
            List of matching AMI IDs.
        """
        try:
            response = await self._run_async(
                self._get_client().describe_images,
                Filters=[{"Name": "name", "Values": [ami_name]}],
                Owners=["self"],  # Only search owned AMIs
            )

            images = response.get("Images", [])
            ami_ids = [img["ImageId"] for img in images]
            logger.info(f"Found {len(ami_ids)} AMIs matching '{ami_name}'")
            return ami_ids
        except ClientError as e:
            logger.error(f"Error searching AMIs by name '{ami_name}': {e}")
            raise

    async def describe_image(self, image_id: str) -> dict[str, Any] | None:
        """Get AMI details by image ID.

        Args:
            image_id: AMI image ID (e.g., "ami-0abcdef1234567890").

        Returns:
            Dictionary with AMI details (name, description, creation_date) or None if not found.
        """
        try:
            response = await self._run_async(
                self._get_client().describe_images,
                ImageIds=[image_id],
            )

            images = response.get("Images", [])
            if not images:
                logger.warning(f"AMI {image_id} not found")
                return None

            image = images[0]
            return {
                "image_id": image.get("ImageId"),
                "name": image.get("Name"),
                "description": image.get("Description"),
                "creation_date": image.get("CreationDate"),
                "state": image.get("State"),
                "architecture": image.get("Architecture"),
            }
        except ClientError as e:
            if "InvalidAMIID" in str(e):
                logger.warning(f"AMI {image_id} not found: {e}")
                return None
            logger.error(f"Error describing AMI {image_id}: {e}")
            raise

    async def list_instances_by_ami(
        self,
        ami_ids: list[str],
        include_terminated: bool = False,
    ) -> list[Ec2InstanceState]:
        """List EC2 instances using specific AMI IDs.

        Args:
            ami_ids: List of AMI IDs to filter by.
            include_terminated: Whether to include terminated instances.

        Returns:
            List of Ec2InstanceState for matching instances.
        """
        if not ami_ids:
            return []

        try:
            filters = [{"Name": "image-id", "Values": ami_ids}]

            if not include_terminated:
                # Exclude terminated and shutting-down instances
                filters.append(
                    {
                        "Name": "instance-state-name",
                        "Values": ["pending", "running", "stopping", "stopped"],
                    }
                )

            response = await self._run_async(
                self._get_client().describe_instances,
                Filters=filters,
            )

            instances = []
            for reservation in response.get("Reservations", []):
                for instance in reservation.get("Instances", []):
                    state = instance.get("State", {})
                    # Extract Name tag from EC2 tags
                    ec2_name = None
                    for tag in instance.get("Tags", []):
                        if tag.get("Key") == "Name":
                            ec2_name = tag.get("Value")
                            break
                    instances.append(
                        Ec2InstanceState(
                            instance_id=instance["InstanceId"],
                            state=state.get("Name", "unknown"),
                            state_reason=state.get("StateReason", {}).get("Message"),
                            public_ip=instance.get("PublicIpAddress"),
                            private_ip=instance.get("PrivateIpAddress"),
                            instance_type=instance.get("InstanceType"),
                            launch_time=instance.get("LaunchTime"),
                            image_id=instance.get("ImageId"),
                            name=ec2_name,
                        )
                    )

            logger.info(f"Found {len(instances)} EC2 instances for AMI IDs {ami_ids}")
            return instances
        except ClientError as e:
            logger.error(f"Error listing instances by AMI: {e}")
            raise

    async def get_instance_state(self, instance_id: str) -> Ec2InstanceState | None:
        """Get current state of an EC2 instance.

        Args:
            instance_id: EC2 instance ID.

        Returns:
            Ec2InstanceState or None if not found.
        """
        try:
            response = await self._run_async(
                self._get_client().describe_instances,
                InstanceIds=[instance_id],
            )

            reservations = response.get("Reservations", [])
            if not reservations or not reservations[0].get("Instances"):
                return None

            instance = reservations[0]["Instances"][0]
            state = instance.get("State", {})

            # Extract Name tag from EC2 tags
            ec2_name = None
            for tag in instance.get("Tags", []):
                if tag.get("Key") == "Name":
                    ec2_name = tag.get("Value")
                    break

            return Ec2InstanceState(
                instance_id=instance_id,
                state=state.get("Name", "unknown"),
                state_reason=state.get("StateReason", {}).get("Message"),
                public_ip=instance.get("PublicIpAddress"),
                private_ip=instance.get("PrivateIpAddress"),
                instance_type=instance.get("InstanceType"),
                launch_time=instance.get("LaunchTime"),
                image_id=instance.get("ImageId"),
                name=ec2_name,
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidInstanceID.NotFound":
                return None
            logger.error(f"Error getting instance state: {e}")
            raise

    async def start_instance(self, instance_id: str) -> bool:
        """Start a stopped EC2 instance.

        Args:
            instance_id: EC2 instance ID.

        Returns:
            True if start initiated successfully.
        """
        try:
            await self._run_async(
                self._get_client().start_instances,
                InstanceIds=[instance_id],
            )
            logger.info(f"Started EC2 instance {instance_id}")
            return True
        except ClientError as e:
            logger.error(f"Error starting instance {instance_id}: {e}")
            raise

    async def stop_instance(self, instance_id: str) -> bool:
        """Stop a running EC2 instance.

        Args:
            instance_id: EC2 instance ID.

        Returns:
            True if stop initiated successfully.
        """
        try:
            await self._run_async(
                self._get_client().stop_instances,
                InstanceIds=[instance_id],
            )
            logger.info(f"Stopped EC2 instance {instance_id}")
            return True
        except ClientError as e:
            logger.error(f"Error stopping instance {instance_id}: {e}")
            raise

    async def terminate_instance(self, instance_id: str) -> bool:
        """Terminate an EC2 instance.

        Args:
            instance_id: EC2 instance ID.

        Returns:
            True if termination initiated successfully.
        """
        try:
            await self._run_async(
                self._get_client().terminate_instances,
                InstanceIds=[instance_id],
            )
            logger.info(f"Terminated EC2 instance {instance_id}")
            return True
        except ClientError as e:
            logger.error(f"Error terminating instance {instance_id}: {e}")
            raise

    async def run_instance(
        self,
        ami_id: str,
        instance_type: str,
        subnet_id: str,
        security_group_ids: list[str],
        key_name: str | None = None,
        tags: dict[str, str] | None = None,
        user_data: str | None = None,
    ) -> str:
        """Launch a new EC2 instance.

        Args:
            ami_id: AMI ID to launch.
            instance_type: EC2 instance type (e.g., m5zn.metal).
            subnet_id: VPC subnet ID.
            security_group_ids: List of security group IDs.
            key_name: SSH key pair name (optional).
            tags: Instance tags (optional).
            user_data: User data script (optional).

        Returns:
            New instance ID.
        """
        run_args = {
            "ImageId": ami_id,
            "InstanceType": instance_type,
            "MinCount": 1,
            "MaxCount": 1,
            "SubnetId": subnet_id,
            "SecurityGroupIds": security_group_ids,
        }

        if key_name:
            run_args["KeyName"] = key_name

        if user_data:
            run_args["UserData"] = user_data

        if tags:
            run_args["TagSpecifications"] = [
                {
                    "ResourceType": "instance",
                    "Tags": [{"Key": k, "Value": v} for k, v in tags.items()],
                }
            ]

        try:
            response = await self._run_async(
                self._get_client().run_instances,
                **run_args,
            )
            instance_id = response["Instances"][0]["InstanceId"]
            logger.info(f"Launched EC2 instance {instance_id}")
            return instance_id
        except ClientError as e:
            logger.error(f"Error launching instance: {e}")
            raise

    @classmethod
    def configure(
        cls,
        services: "ServiceCollection",
        access_key_id: str,
        secret_access_key: str,
        region: str = "us-east-1",
    ) -> None:
        """Configure DI registration.

        Args:
            services: Neuroglia service collection.
            access_key_id: AWS access key ID.
            secret_access_key: AWS secret access key.
            region: AWS region.
        """
        credentials = AwsCredentials(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region=region,
        )
        services.add_singleton(cls, implementation_factory=lambda _: cls(credentials))
