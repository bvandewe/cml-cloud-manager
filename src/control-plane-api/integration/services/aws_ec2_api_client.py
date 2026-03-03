import asyncio
import datetime
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import boto3  # type: ignore
from botocore.exceptions import ClientError, ParamValidationError  # type: ignore

from integration.enums import AwsRegion, Ec2InstanceResourcesUtilizationRelativeStartTime
from integration.exceptions import (
    EC2AuthenticationException,
    EC2InstanceCreationException,
    EC2InstanceNotFoundException,
    EC2InstanceOperationException,
    EC2InvalidParameterException,
    EC2QuotaExceededException,
    EC2StatusCheckException,
    EC2TagOperationException,
    IntegrationException,
)
from integration.models import CMLWorkerInstanceDto
from integration.services.relative_time import relative_time

if TYPE_CHECKING:
    from neuroglia.hosting.web import WebApplicationBuilder

log = logging.getLogger(__name__)
logging.getLogger("botocore").setLevel(logging.INFO)
logging.getLogger("urlib3").setLevel(logging.INFO)


@dataclass
class AwsAccountCredentials:
    aws_access_key_id: str

    aws_secret_access_key: str


@dataclass
class Ec2InstanceDescriptor:
    id: str

    type: str

    state: str

    image_id: str

    name: str

    launch_timestamp: datetime.datetime

    launch_time_relative: str

    public_ip: str | None = None

    private_ip: str | None = None


@dataclass
class Ec2InstanceResourcesUtilization:
    id: str

    region_name: AwsRegion

    relative_start_time: Ec2InstanceResourcesUtilizationRelativeStartTime

    avg_cpu_utilization: float | None  # None if no data available

    avg_memory_utilization: float | None  # None if CloudWatch Agent not installed

    start_time: datetime.datetime

    end_time: datetime.datetime


@dataclass
class AmiDetails:
    """AMI metadata from AWS."""

    ami_id: str
    ami_name: str | None = None
    ami_description: str | None = None
    ami_creation_date: str | None = None


class AwsEc2Client:
    aws_account_credentials: AwsAccountCredentials

    def __init__(self, aws_account_credentials: AwsAccountCredentials):
        self.aws_account_credentials = aws_account_credentials

    async def _run_async(self, func, *args, **kwargs):
        """Run a blocking function in a separate thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    def _parse_aws_error(self, error: ClientError, operation: str) -> Exception:
        """Parse AWS ClientError and return appropriate specific exception.

        Args:
            error: The boto3 ClientError
            operation: Description of the operation that failed

        Returns:
            Specific exception type based on error code
        """
        error_code = error.response.get("Error", {}).get("Code", "")
        error_message = error.response.get("Error", {}).get("Message", str(error))

        # Authentication/Authorization errors
        if error_code in (
            "UnauthorizedOperation",
            "InvalidClientTokenId",
            "SignatureDoesNotMatch",
            "AccessDenied",
        ):
            return EC2AuthenticationException(f"{operation} - Authentication failed: {error_message}")

        # Instance not found
        if error_code in ("InvalidInstanceID.NotFound", "InvalidInstanceId.NotFound"):
            return EC2InstanceNotFoundException(f"{operation} - Instance not found: {error_message}")

        # Quota/Limit errors
        if error_code in (
            "InstanceLimitExceeded",
            "InsufficientInstanceCapacity",
            "RequestLimitExceeded",
        ):
            return EC2QuotaExceededException(f"{operation} - AWS quota exceeded: {error_message}")

        # Invalid parameters
        if error_code in (
            "InvalidParameterValue",
            "InvalidParameter",
            "InvalidAMIID.NotFound",
            "InvalidGroup.NotFound",
        ):
            return EC2InvalidParameterException(f"{operation} - Invalid parameter: {error_message}")

        # Generic AWS error
        return IntegrationException(f"{operation} - AWS error [{error_code}]: {error_message}")

    def _health_sync(self) -> bool:
        """Validates whether the service is available (Synchronous implementation)"""
        try:
            ec2_client = boto3.client(
                "ec2",
                aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
                aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
                region_name=AwsRegion.US_EAST_1.value,
            )
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_regions.html
            response = ec2_client.describe_regions()
            if "Regions" in response:
                return True
            return False
        except (ValueError, ParamValidationError, ClientError) as e:
            log.error(f"Error while verifying access to EC2: {e}")
            raise IntegrationException(f"Error while verifying access to EC2: {e}")

    async def health(self) -> bool:
        """Validates whether the service is available

        Returns:
            bool: True if EC2 Cloud is available.
        """
        return await self._run_async(self._health_sync)

    def _get_ami_ids_by_name_sync(
        self,
        aws_region: AwsRegion,
        ami_name: str,
    ) -> list[str]:
        """Query AWS to find AMI IDs that match the given AMI name (Synchronous)."""
        try:
            ec2_client = boto3.client(
                "ec2",
                aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
                aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
                region_name=aws_region.value,
            )

            # Search for AMIs by name pattern
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_images.html
            response = ec2_client.describe_images(Filters=[{"Name": "name", "Values": [f"*{ami_name}*"]}])  # Wildcard search

            ami_ids = [image["ImageId"] for image in response.get("Images", [])]

            if ami_ids:
                log.info(f"Found {len(ami_ids)} AMI(s) matching name pattern '{ami_name}' in {aws_region.value}: {ami_ids}")
            else:
                log.warning(f"No AMIs found matching name pattern '{ami_name}' in {aws_region.value}")

            return ami_ids

        except ClientError as e:
            error = self._parse_aws_error(e, f"Query AMIs by name '{ami_name}'")
            log.error(f"Failed to query AMIs: {error}")
            raise error
        except (ValueError, ParamValidationError) as e:
            log.error(f"Invalid parameters for AMI query: {e}")
            raise EC2InvalidParameterException(f"Invalid AMI name parameter: {e}")

    async def get_ami_ids_by_name(
        self,
        aws_region: AwsRegion,
        ami_name: str,
    ) -> list[str]:
        """Query AWS to find AMI IDs that match the given AMI name.

        Args:
            aws_region: The AWS region to search in.
            ami_name: The AMI name pattern to search for.

        Returns:
            List of AMI IDs that match the name pattern.

        Raises:
            IntegrationException: If the AMI query fails.
        """
        return await self._run_async(self._get_ami_ids_by_name_sync, aws_region, ami_name)

    def _get_ami_details_sync(self, aws_region: AwsRegion, ami_id: str) -> AmiDetails | None:
        """Get AMI details from AWS by AMI ID (Synchronous)."""
        try:
            ec2_client = boto3.client(
                "ec2",
                aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
                aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
                region_name=aws_region.value,
            )

            # Query AMI by ID
            response = ec2_client.describe_images(ImageIds=[ami_id])

            images = response.get("Images", [])
            if not images:
                log.warning(f"AMI {ami_id} not found in {aws_region.value}")
                return None

            image = images[0]
            ami_details = AmiDetails(
                ami_id=ami_id,
                ami_name=image.get("Name"),
                ami_description=image.get("Description"),
                ami_creation_date=image.get("CreationDate"),
            )

            log.debug(f"Retrieved AMI details for {ami_id}: name={ami_details.ami_name}, " f"created={ami_details.ami_creation_date}")

            return ami_details

        except ClientError as e:
            error = self._parse_aws_error(e, f"Get AMI details for '{ami_id}'")
            log.error(f"Failed to get AMI details: {error}")
            raise error
        except (ValueError, ParamValidationError) as e:
            log.error(f"Invalid parameters for AMI details query: {e}")
            raise EC2InvalidParameterException(f"Invalid AMI ID parameter: {e}")

    async def get_ami_details(self, aws_region: AwsRegion, ami_id: str) -> AmiDetails | None:
        """Get AMI details from AWS by AMI ID.

        Args:
            aws_region: The AWS region where the AMI exists.
            ami_id: The AMI ID to query.

        Returns:
            AmiDetails with name, description, and creation date, or None if not found.

        Raises:
            IntegrationException: If the AMI query fails.
        """
        return await self._run_async(self._get_ami_details_sync, aws_region, ami_id)

    def _create_instance_sync(
        self,
        aws_region: AwsRegion,
        instance_name: str,
        ami_id: str,
        ami_name: str,
        instance_type: str,
        security_group_ids: list[str],
        subnet_id: str,
        key_name: str,
    ) -> CMLWorkerInstanceDto | None:
        """Creates a single EC2 instance for CML Worker (Synchronous)."""
        ec2 = boto3.resource(
            "ec2",
            aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
            aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
            region_name=aws_region.value,
        )

        try:
            # Validate security group IDs when using VPC (subnet_id)
            # AWS requires security group IDs (sg-xxx) not names when using SubnetId
            if subnet_id:
                invalid_sgs = [sg for sg in security_group_ids if not sg.startswith("sg-")]
                if invalid_sgs:
                    raise EC2InvalidParameterException(
                        f"When using a VPC subnet, security groups must be IDs (sg-xxx) not names. "
                        f"Invalid security groups: {invalid_sgs}. "
                        f"Please provide security group IDs that belong to the same VPC as the subnet."
                    )

            tag_specifications = [
                {
                    "ResourceType": "instance",
                    "Tags": [{"Key": "Name", "Value": instance_name}],
                }
            ]
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/service-resource/create_instances.html#create-instances
            instances = ec2.create_instances(  # type: ignore[attr-defined]
                ImageId=ami_id,
                MinCount=1,
                MaxCount=1,
                InstanceType=instance_type,
                SecurityGroupIds=security_group_ids,
                SubnetId=subnet_id,
                KeyName=key_name,
                TagSpecifications=tag_specifications,
                Monitoring={"Enabled": True},  # Enable detailed CloudWatch monitoring
            )
            instance = instances[0]
            log.info(f"New CML Worker EC2 instance created in region {aws_region.value}: id={instance.id}, instance_type={instance.instance_type}")

            # Extract tags from the instance
            tags = {}
            if hasattr(instance, "tags") and instance.tags:
                tags = {tag["Key"]: tag["Value"] for tag in instance.tags}

            return CMLWorkerInstanceDto(
                id=instance.id,
                aws_instance_id=instance.id,
                aws_region=aws_region,
                instance_name=instance_name,
                ami_id=instance.image_id,
                ami_name=ami_name,
                instance_type=instance.instance_type,
                security_group_ids=[sg["GroupId"] for sg in instance.security_groups],
                subnet_id=subnet_id,
                instance_state=(instance.state["Name"] if hasattr(instance, "state") else "pending"),
                key_pair_name=key_name,
                public_ip=instance.public_ip_address,
                private_ip=instance.private_ip_address,
                tags=tags,
            )

        except ParamValidationError as e:
            log.error(f"Error creating CML Worker instance - invalid parameters: {e}")
            raise EC2InvalidParameterException(f"Invalid parameters for instance creation: {e}")
        except ClientError as e:
            log.error(f"Error creating CML Worker instance in region {aws_region.value}: {e}")
            raise self._parse_aws_error(e, "Create CML Worker instance")
        except ValueError as e:
            log.error(f"Error creating CML Worker instance - invalid value: {e}")
            raise EC2InstanceCreationException(f"Invalid value provided: {e}")

    async def create_instance(
        self,
        aws_region: AwsRegion,
        instance_name: str,
        ami_id: str,
        ami_name: str,
        instance_type: str,
        security_group_ids: list[str],
        subnet_id: str,
        key_name: str,
    ) -> CMLWorkerInstanceDto | None:
        """Creates a single EC2 instance for CML Worker.

        Args:
            aws_region: The name of the AWS region where to create the instance.
            instance_name: The name of the EC2 instance to create.
            ami_id: The ID of the AMI to use for the instance.
            ami_name: Human-readable name of the AMI.
            instance_type: The type of instance to create.
            security_group_ids: A list of security group IDs to assign to the instance.
            subnet_id: The VPC subnet ID where the instance will be launched.
            key_name: SSH key pair name for instance access.

        Returns:
            CMLWorkerInstanceDto containing the created instance details.

        Raises:
            IntegrationException: If instance creation fails.
        """
        return await self._run_async(
            self._create_instance_sync,
            aws_region,
            instance_name,
            ami_id,
            ami_name,
            instance_type,
            security_group_ids,
            subnet_id,
            key_name,
        )

    def _start_instance_sync(self, aws_region: AwsRegion, instance_id: str) -> bool:
        """Starts a stopped EC2 instance (Synchronous)."""
        ec2_client = boto3.client(
            "ec2",
            aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
            aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
            region_name=aws_region.value,
        )
        try:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/start_instances.html
            response = ec2_client.start_instances(InstanceIds=[instance_id])
            if response and response.get("StartingInstances"):
                log.info(f"CML Worker EC2 instance {instance_id} start requested in region {aws_region.value}")
                return True
            return False

        except ParamValidationError as e:
            log.error(f"Error starting CML Worker instance - invalid parameters: {e}")
            raise EC2InvalidParameterException(f"Invalid instance ID provided: {e}")
        except ClientError as e:
            log.error(f"Error starting CML Worker instance {instance_id} in region {aws_region.value}: {e}")
            raise self._parse_aws_error(e, f"Start instance {instance_id}")
        except ValueError as e:
            log.error(f"Error starting CML Worker instance - invalid value: {e}")
            raise EC2InstanceOperationException(f"Failed to start instance: {e}")

    async def start_instance(self, aws_region: AwsRegion, instance_id: str) -> bool:
        """Starts a stopped EC2 instance.

        Args:
            aws_region: The AWS region where the instance is located.
            instance_id: The AWS identifier of the EC2 instance to start.

        Returns:
            True if the start request was successful, False otherwise.

        Raises:
            EC2InstanceNotFoundException: If instance not found.
            EC2InstanceOperationException: If the start operation fails.
            EC2AuthenticationException: If credentials are invalid.
        """
        return await self._run_async(self._start_instance_sync, aws_region, instance_id)

    def _stop_instance_sync(self, aws_region: AwsRegion, instance_id: str) -> bool:
        """Stops a running EC2 instance (Synchronous)."""
        ec2_client = boto3.client(
            "ec2",
            aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
            aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
            region_name=aws_region.value,
        )
        try:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/stop_instances.html
            response = ec2_client.stop_instances(InstanceIds=[instance_id])
            if response and response.get("StoppingInstances"):
                log.info(f"CML Worker EC2 instance {instance_id} stop requested in region {aws_region.value}")
                return True
            return False

        except ParamValidationError as e:
            log.error(f"Error stopping CML Worker instance - invalid parameters: {e}")
            raise EC2InvalidParameterException(f"Invalid instance ID provided: {e}")
        except ClientError as e:
            log.error(f"Error stopping CML Worker instance {instance_id} in region {aws_region.value}: {e}")
            raise self._parse_aws_error(e, f"Stop instance {instance_id}")
        except ValueError as e:
            log.error(f"Error stopping CML Worker instance - invalid value: {e}")
            raise EC2InstanceOperationException(f"Failed to stop instance: {e}")

    async def stop_instance(self, aws_region: AwsRegion, instance_id: str) -> bool:
        """Stops a running EC2 instance.

        Args:
            aws_region: The AWS region where the instance is located.
            instance_id: The AWS identifier of the EC2 instance to stop.

        Returns:
            True if the stop request was successful, False otherwise.

        Raises:
            EC2InstanceNotFoundException: If instance not found.
            EC2InstanceOperationException: If the stop operation fails.
            EC2AuthenticationException: If credentials are invalid.
        """
        return await self._run_async(self._stop_instance_sync, aws_region, instance_id)

    def _terminate_instance_sync(self, aws_region: AwsRegion, instance_id: str) -> bool:
        """Terminates a single EC2 instance (Synchronous)."""
        ec2_client = boto3.client(
            "ec2",
            aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
            aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
            region_name=aws_region.value,
        )
        try:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/terminate_instances.html
            response = ec2_client.terminate_instances(InstanceIds=[instance_id])
            if response:
                log.info(f"CML Worker EC2 instance {instance_id} termination requested in region {aws_region.value}")
                return True
            return False

        except ParamValidationError as e:
            log.error(f"Error terminating CML Worker instance - invalid parameters: {e}")
            raise EC2InvalidParameterException(f"Invalid instance ID provided: {e}")
        except ClientError as e:
            log.error(f"Error terminating CML Worker instance {instance_id} in region {aws_region.value}: {e}")
            raise self._parse_aws_error(e, f"Terminate instance {instance_id}")
        except ValueError as e:
            log.error(f"Error terminating CML Worker instance - invalid value: {e}")
            raise EC2InstanceOperationException(f"Failed to terminate instance: {e}")

    async def terminate_instance(self, aws_region: AwsRegion, instance_id: str) -> bool:
        """Terminates a single EC2 instance.

        Args:
            aws_region: The name of the AWS region where to create the instance.
            instance_id: The AWS identifier of the EC2 instance to terminate.

        Returns:
            True if the termination request was successful, False otherwise.

        Raises:
            EC2InstanceNotFoundException: If instance not found.
            EC2InstanceOperationException: If the termination operation fails.
            EC2AuthenticationException: If credentials are invalid.
        """
        return await self._run_async(self._terminate_instance_sync, aws_region, instance_id)

    def _get_instance_status_checks_sync(
        self,
        aws_region: AwsRegion,
        instance_id: str,
    ) -> dict[str, str]:
        """Get instance and system status checks for an EC2 instance (Synchronous)."""
        ec2_client = boto3.client(
            "ec2",
            aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
            aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
            region_name=aws_region.value,
        )
        try:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_instance_status.html
            response = ec2_client.describe_instance_status(
                InstanceIds=[instance_id],
                IncludeAllInstances=True,
            )

            if response.get("InstanceStatuses"):
                status = response["InstanceStatuses"][0]
                monitoring_state = status.get("Monitoring", {}).get("State", "disabled")
                return {
                    "instance_status_check": status["InstanceStatus"]["Status"],
                    "ec2_system_status_check": status["SystemStatus"]["Status"],
                    "instance_state": status["InstanceState"]["Name"],
                    "monitoring_state": monitoring_state,
                }

            # If no status returned, instance might not exist or be in a transitional state
            log.warning(f"No status information available for CML Worker instance {instance_id} in region {aws_region.value}")
            return {
                "instance_status_check": "unknown",
                "ec2_system_status_check": "unknown",
                "instance_state": "unknown",
                "monitoring_state": "disabled",
            }

        except ParamValidationError as e:
            log.error(f"Error getting status checks - invalid parameters: {e}")
            raise EC2InvalidParameterException(f"Invalid instance ID provided: {e}")
        except ClientError as e:
            log.error(f"Error getting status checks for CML Worker instance {instance_id} in region {aws_region.value}: {e}")
            raise self._parse_aws_error(e, f"Get status checks for instance {instance_id}")
        except ValueError as e:
            log.error(f"Error getting status checks - invalid value: {e}")
            raise EC2StatusCheckException(f"Failed to get status checks: {e}")

    async def get_instance_status_checks(
        self,
        aws_region: AwsRegion,
        instance_id: str,
    ) -> dict[str, str]:
        """Get instance and system status checks for an EC2 instance.

        Args:
            aws_region: The AWS region where the instance is located.
            instance_id: The AWS identifier of the EC2 instance.

        Returns:
            Dictionary containing:
                - instance_status_check: Status of instance checks (ok, impaired, insufficient-data, etc.)
                - ec2_system_status_check: Status of AWS system/hardware checks (ok, impaired, insufficient-data, etc.)
                - instance_state: Current state of the instance (pending, running, stopping, stopped, etc.)

        Raises:
            IntegrationException: If the status check retrieval fails.
        """
        return await self._run_async(self._get_instance_status_checks_sync, aws_region, instance_id)

    def _get_tags_sync(self, aws_region: AwsRegion, instance_id: str) -> dict[str, str]:
        """Get all tags for an EC2 instance (Synchronous)."""
        ec2_client = boto3.client(
            "ec2",
            aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
            aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
            region_name=aws_region.value,
        )
        try:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_tags.html
            response = ec2_client.describe_tags(
                Filters=[
                    {"Name": "resource-id", "Values": [instance_id]},
                    {"Name": "resource-type", "Values": ["instance"]},
                ]
            )

            tags = {}
            if response.get("Tags"):
                tags = {tag["Key"]: tag["Value"] for tag in response["Tags"]}

            log.info(f"Retrieved {len(tags)} tags for CML Worker instance {instance_id} in region {aws_region.value}")
            return tags

        except ParamValidationError as e:
            log.error(f"Error getting tags - invalid parameters: {e}")
            raise EC2InvalidParameterException(f"Invalid instance ID provided: {e}")
        except ClientError as e:
            log.error(f"Error getting tags for CML Worker instance {instance_id} in region {aws_region.value}: {e}")
            raise self._parse_aws_error(e, f"Get tags for instance {instance_id}")
        except ValueError as e:
            log.error(f"Error getting tags - invalid value: {e}")
            raise EC2TagOperationException(f"Failed to get tags: {e}")

    async def get_tags(self, aws_region: AwsRegion, instance_id: str) -> dict[str, str]:
        """Get all tags for an EC2 instance.

        Args:
            aws_region: The AWS region where the instance is located.
            instance_id: The AWS identifier of the EC2 instance.

        Returns:
            Dictionary of tag key-value pairs.

        Raises:
            IntegrationException: If the tag retrieval fails.
        """
        return await self._run_async(self._get_tags_sync, aws_region, instance_id)

    def _add_tags_sync(
        self,
        aws_region: AwsRegion,
        instance_id: str,
        tags: dict[str, str],
    ) -> bool:
        """Add or update tags on an EC2 instance (Synchronous)."""
        ec2_client = boto3.client(
            "ec2",
            aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
            aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
            region_name=aws_region.value,
        )
        try:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/create_tags.html
            tag_list = [{"Key": k, "Value": v} for k, v in tags.items()]
            ec2_client.create_tags(Resources=[instance_id], Tags=tag_list)

            log.info(f"Added/updated {len(tags)} tags on CML Worker instance {instance_id} in region {aws_region.value}")
            return True

        except ParamValidationError as e:
            log.error(f"Error adding tags - invalid parameters: {e}")
            raise EC2InvalidParameterException(f"Invalid parameters for tag operation: {e}")
        except ClientError as e:
            log.error(f"Error adding tags to CML Worker instance {instance_id} in region {aws_region.value}: {e}")
            raise self._parse_aws_error(e, f"Add tags to instance {instance_id}")
        except ValueError as e:
            log.error(f"Error adding tags - invalid value: {e}")
            raise EC2TagOperationException(f"Failed to add tags: {e}")

    async def add_tags(
        self,
        aws_region: AwsRegion,
        instance_id: str,
        tags: dict[str, str],
    ) -> bool:
        """Add or update tags on an EC2 instance.

        Args:
            aws_region: The AWS region where the instance is located.
            instance_id: The AWS identifier of the EC2 instance.
            tags: Dictionary of tag key-value pairs to add/update.

        Returns:
            True if the tags were successfully added/updated.

        Raises:
            IntegrationException: If the tag operation fails.
        """
        return await self._run_async(self._add_tags_sync, aws_region, instance_id, tags)

    def _remove_tags_sync(
        self,
        aws_region: AwsRegion,
        instance_id: str,
        tag_keys: list[str],
    ) -> bool:
        """Remove tags from an EC2 instance (Synchronous)."""
        ec2_client = boto3.client(
            "ec2",
            aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
            aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
            region_name=aws_region.value,
        )
        try:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/delete_tags.html
            tag_list = [{"Key": key} for key in tag_keys]
            ec2_client.delete_tags(Resources=[instance_id], Tags=tag_list)

            log.info(f"Removed {len(tag_keys)} tags from CML Worker instance {instance_id} in region {aws_region.value}")
            return True

        except ParamValidationError as e:
            log.error(f"Error removing tags - invalid parameters: {e}")
            raise EC2InvalidParameterException(f"Invalid parameters for tag removal: {e}")
        except ClientError as e:
            log.error(f"Error removing tags from CML Worker instance {instance_id} in region {aws_region.value}: {e}")
            raise self._parse_aws_error(e, f"Remove tags from instance {instance_id}")
        except ValueError as e:
            log.error(f"Error removing tags - invalid value: {e}")
            raise EC2TagOperationException(f"Failed to remove tags: {e}")

    async def remove_tags(
        self,
        aws_region: AwsRegion,
        instance_id: str,
        tag_keys: list[str],
    ) -> bool:
        """Remove tags from an EC2 instance.

        Args:
            aws_region: The AWS region where the instance is located.
            instance_id: The AWS identifier of the EC2 instance.
            tag_keys: List of tag keys to remove.

        Returns:
            True if the tags were successfully removed.

        Raises:
            IntegrationException: If the tag removal fails.
        """
        return await self._run_async(self._remove_tags_sync, aws_region, instance_id, tag_keys)

    def _get_instance_details_sync(self, aws_region: AwsRegion, instance_id: str) -> Ec2InstanceDescriptor | None:
        """Gets the given EC2 instance details from the given AWS Region (Synchronous)."""
        ec2_client = boto3.client(
            "ec2",
            aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
            aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
            region_name=aws_region.value,
        )
        try:
            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_instances.html
            res_dict = ec2_client.describe_instances(InstanceIds=[instance_id])
            if res_dict and "Reservations" in res_dict:
                instance = res_dict["Reservations"][0]["Instances"][0]

                # Extract name from tags
                name = None
                for tag in instance.get("Tags", []):
                    if tag["Key"] == "Name":
                        name = tag["Value"]
                        break

                # Extract IPs (may be None if instance is stopped/stopping)
                public_ip = instance.get("PublicIpAddress")
                private_ip = instance.get("PrivateIpAddress")

                return Ec2InstanceDescriptor(
                    id=instance["InstanceId"],
                    type=instance["InstanceType"],
                    state=instance["State"]["Name"],
                    image_id=instance["ImageId"],
                    name=name or instance["InstanceId"],  # Fallback to instance ID if no Name tag
                    launch_timestamp=instance["LaunchTime"],
                    launch_time_relative=relative_time(instance["LaunchTime"]),
                    public_ip=public_ip,
                    private_ip=private_ip,
                )
            return None

        except (ValueError, ParamValidationError, ClientError) as e:
            log.error(f"Error while getting details of instance {instance_id} in Region {aws_region}: {e}")
            raise IntegrationException(f"{type(e)} Error while getting details of instance {instance_id} in Region {aws_region}: {e}")

    async def get_instance_details(self, aws_region: AwsRegion, instance_id: str) -> Ec2InstanceDescriptor | None:
        """Gets the given EC2 instance details from the given AWS Region.

        Args:
            aws_region: The name of the AWS region where to create the instance.
            instance_id: The AWS identifier of the EC2 CML Worker instance.

        Returns:
            Ec2InstanceDescriptor: An Ec2InstanceDescriptor.
        """
        return await self._run_async(self._get_instance_details_sync, aws_region, instance_id)

    def _list_instances_sync(
        self,
        region_name: AwsRegion,
        instance_ids: list[str] | None = None,
        instance_types: list[str] | None = None,
        instance_states: list[str] | None = None,
        image_ids: list[str] | None = None,
        tag_filters: dict[str, str] | None = None,
    ) -> list[Ec2InstanceDescriptor] | None:
        """List EC2 instances in the AWS Region with optional filters (Synchronous)."""
        ec2_client = boto3.client(
            "ec2",
            aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
            aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
            region_name=region_name.value,
        )

        try:
            # Build AWS EC2 filters for server-side filtering
            filters = []

            if instance_types:
                filters.append({"Name": "instance-type", "Values": instance_types})

            if instance_states:
                filters.append({"Name": "instance-state-name", "Values": instance_states})

            if image_ids:
                filters.append({"Name": "image-id", "Values": image_ids})

            if tag_filters:
                for tag_key, tag_value in tag_filters.items():
                    filters.append({"Name": f"tag:{tag_key}", "Values": [tag_value]})

            # Prepare describe_instances parameters
            describe_params: dict[str, Any] = {}
            if instance_ids:
                describe_params["InstanceIds"] = instance_ids
            if filters:
                describe_params["Filters"] = filters

            # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_instances.html
            res_dict = ec2_client.describe_instances(**describe_params)
            instances = []

            if res_dict and "Reservations" in res_dict:
                for reservation in res_dict["Reservations"]:
                    if "Instances" not in reservation:
                        log.warning(f"Reservation {reservation['ReservationId']} has no Instances.")
                        continue

                    for instance in reservation["Instances"]:
                        if "InstanceId" not in instance:
                            log.warning(f"Instance in Reservation {reservation['ReservationId']} has no InstanceId.")
                            continue
                        if "InstanceType" not in instance:
                            log.warning(f"Instance {instance['InstanceId']} in Reservation {reservation['ReservationId']} has no InstanceType.")
                            continue
                        if "ImageId" not in instance:
                            log.warning(f"Instance {instance['InstanceId']} in Reservation {reservation['ReservationId']} has no ImageId.")
                            continue

                        log.debug(f"Instance ID: {instance['InstanceId']}, Instance Type: {instance['InstanceType']}, Image ID: {instance['ImageId']}, LaunchTime: {instance['LaunchTime']}")

                        # Extract instance name from tags
                        ec2_vm_name = f"{instance['InstanceType']}.{instance['ImageId']}.{instance['InstanceId']}"
                        if "Tags" in instance:
                            for tag in instance["Tags"]:
                                if tag["Key"] == "Name":
                                    ec2_vm_name = tag["Value"]
                                    break

                        ec2_vm = Ec2InstanceDescriptor(
                            id=instance["InstanceId"],
                            type=instance["InstanceType"],
                            state=instance["State"]["Name"],
                            image_id=instance["ImageId"],
                            name=ec2_vm_name,
                            launch_timestamp=instance["LaunchTime"],
                            launch_time_relative=relative_time(instance["LaunchTime"]),
                        )
                        instances.append(ec2_vm)

                log.info(f"{len(instances)} EC2 Instances found in Region {region_name} after applying filters.")
                return instances

            log.info(f"No EC2 Instances found in Region {region_name} matching the specified filters.")
            return []

        except (ValueError, ParamValidationError, ClientError) as e:
            log.error(f"Error while listing CML Worker instances in Region {region_name}: {e}")
            raise IntegrationException(f"Error while listing CML Worker instances in Region {region_name}: {e}")

    async def list_instances(
        self,
        region_name: AwsRegion,
        instance_ids: list[str] | None = None,
        instance_types: list[str] | None = None,
        instance_states: list[str] | None = None,
        image_ids: list[str] | None = None,
        tag_filters: dict[str, str] | None = None,
    ) -> list[Ec2InstanceDescriptor] | None:
        """List EC2 instances in the AWS Region with optional filters.

        Args:
            region_name: The name of the AWS region where to list instances.
            instance_ids: Optional list of specific instance IDs to filter by.
            instance_types: Optional list of instance types to filter by (e.g., ['t2.micro', 't3.small']).
            instance_states: Optional list of instance states to filter by (e.g., ['running', 'stopped']).
            image_ids: Optional list of AMI IDs to filter by.
            tag_filters: Optional dictionary of tag key-value pairs to filter by (e.g., {'Environment': 'prod', 'Team': 'backend'}).

        Returns:
            List[Ec2InstanceDescriptor]: A list of Ec2InstanceDescriptor matching the filters.
        """
        return await self._run_async(
            self._list_instances_sync,
            region_name,
            instance_ids,
            instance_types,
            instance_states,
            image_ids,
            tag_filters,
        )

    def _get_instance_resources_utilization_sync(
        self,
        aws_region: AwsRegion,
        instance_id: str,
        relative_start_time: Ec2InstanceResourcesUtilizationRelativeStartTime,
    ) -> Ec2InstanceResourcesUtilization | None:
        """Retrieves averageCPU utilization and memory utilization (Synchronous)."""
        try:
            # Verify instance exists - raises IntegrationException if not found
            self._get_instance_details_sync(aws_region=aws_region, instance_id=instance_id)

            cloudwatch = boto3.client(
                "cloudwatch",
                aws_access_key_id=self.aws_account_credentials.aws_access_key_id,
                aws_secret_access_key=self.aws_account_credentials.aws_secret_access_key,
                region_name=aws_region.value,
            )

            now = datetime.datetime.now(datetime.timezone.utc)
            start_time = now - Ec2InstanceResourcesUtilizationRelativeStartTime.to_timedelta(relative_start_time.value)

            # CPU Utilization (available by default in AWS/EC2)
            cpu_metric = cloudwatch.get_metric_statistics(
                Namespace="AWS/EC2",
                MetricName="CPUUtilization",
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start_time,
                EndTime=now,
                Period=30,
                Statistics=["Average"],
            )
            if len(cpu_metric["Datapoints"]):
                cpu_utilization = cpu_metric["Datapoints"][0]["Average"]
            else:
                cpu_utilization = None

            # Memory Utilization (requires CloudWatch Agent to be installed and configured)
            # Note: Memory metrics are NOT available in AWS/EC2 namespace by default
            # They require CloudWatch Agent publishing to CWAgent namespace
            memory_metric = cloudwatch.get_metric_statistics(
                Namespace="CWAgent",  # Changed from AWS/EC2
                MetricName="mem_used_percent",  # Standard CWAgent metric name
                Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
                StartTime=start_time,
                EndTime=now,
                Period=30,
                Statistics=["Average"],
            )
            if len(memory_metric["Datapoints"]):
                memory_utilization = memory_metric["Datapoints"][0]["Average"]
            else:
                # Fallback: No memory data means CloudWatch Agent not installed/configured
                memory_utilization = None

            return Ec2InstanceResourcesUtilization(
                region_name=aws_region,
                id=instance_id,
                relative_start_time=relative_start_time,
                start_time=start_time,
                end_time=now,
                avg_cpu_utilization=cpu_utilization,
                avg_memory_utilization=memory_utilization,
            )

        except Exception as e:
            log.error(f"Error while pulling resources utilization for CML Worker instance {instance_id} in Region {aws_region}: {e}")
            raise IntegrationException(f"Error while pulling resources utilization for CML Worker instance {instance_id} in Region {aws_region}: {e}")

    async def get_instance_resources_utilization(
        self,
        aws_region: AwsRegion,
        instance_id: str,
        relative_start_time: Ec2InstanceResourcesUtilizationRelativeStartTime,
    ) -> Ec2InstanceResourcesUtilization | None:
        """
        Retrieves averageCPU utilization and memory utilization for a given EC2 instance, region and for the time period starting `now() - relative_start_time`.

        Args:
            aws_region (str): The AWS region where the instance resides.
            instance_id (str): The ID of the EC2 instance.
            relative_start_time (timedelta): The time period to consider for the utilization compute.

        Returns:
            dict: A dictionary containing CPU utilization and memory utilization.
        """
        return await self._run_async(
            self._get_instance_resources_utilization_sync,
            aws_region,
            instance_id,
            relative_start_time,
        )

    @staticmethod
    def configure(builder: "WebApplicationBuilder") -> None:
        """Configure AWS EC2 client in the application builder.

        This method:
        1. Creates AWS account credentials from application settings
        2. Creates an AwsEc2Client instance with the credentials
        3. Registers the client as a singleton in the DI container

        Args:
            builder: WebApplicationBuilder instance for service registration
        """
        from application.settings import app_settings

        log.info("☁️ Configuring AWS EC2 Client...")

        # Create AWS credentials from settings
        credentials = AwsAccountCredentials(
            aws_access_key_id=app_settings.aws_access_key_id,
            aws_secret_access_key=app_settings.aws_secret_access_key,
        )

        # Create EC2 client instance
        ec2_client = AwsEc2Client(aws_account_credentials=credentials)

        # Test connectivity (optional - can be disabled for faster startup)
        try:
            if ec2_client.health():
                log.info("✅ AWS EC2 connection successful")
        except Exception as e:
            log.warning(f"⚠️ AWS EC2 health check failed: {e}")
            log.warning("⚠️ AWS operations may fail at runtime")

        # Register as singleton in DI container
        builder.services.add_singleton(AwsEc2Client, singleton=ec2_client)
        log.info("✅ AWS EC2 Client registered in DI container")
