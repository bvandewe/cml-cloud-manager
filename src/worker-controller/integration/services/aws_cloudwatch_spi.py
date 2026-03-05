"""AWS CloudWatch SPI Client for Worker Controller.

Service Provider Interface (SPI) for AWS CloudWatch metrics.
Handles EC2 instance metrics collection.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    boto3 = None  # type: ignore
    ClientError = Exception  # type: ignore

if TYPE_CHECKING:
    from neuroglia.dependency_injection.service_collection import ServiceCollection

logger = logging.getLogger(__name__)


@dataclass
class Ec2Metrics:
    """EC2 CloudWatch metrics."""

    instance_id: str
    cpu_utilization: float | None  # Percentage 0-100
    network_in_bytes: float | None
    network_out_bytes: float | None
    disk_read_ops: float | None
    disk_write_ops: float | None
    timestamp: datetime | None = None


@dataclass
class AwsCredentials:
    """AWS credentials configuration."""

    access_key_id: str
    secret_access_key: str
    region: str = "us-east-1"


class AwsCloudWatchSpiClient:
    """AWS CloudWatch Service Provider Interface.

    Handles CloudWatch metrics collection for EC2 instances.
    """

    def __init__(self, credentials: AwsCredentials):
        """Initialize the CloudWatch SPI client.

        Args:
            credentials: AWS credentials and region.
        """
        if boto3 is None:
            raise RuntimeError("boto3 is required for CloudWatch operations")

        self._credentials = credentials
        self._client = None

    def _get_client(self):
        """Get or create boto3 CloudWatch client."""
        if self._client is None:
            self._client = boto3.client(
                "cloudwatch",
                region_name=self._credentials.region,
                aws_access_key_id=self._credentials.access_key_id,
                aws_secret_access_key=self._credentials.secret_access_key,
            )
        return self._client

    async def _run_async(self, func, *args, **kwargs) -> Any:
        """Run blocking boto3 call in executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def get_ec2_metrics(
        self,
        instance_id: str,
        period_minutes: int = 5,
        lookback_minutes: int = 10,
    ) -> Ec2Metrics:
        """Get EC2 instance metrics from CloudWatch.

        Args:
            instance_id: EC2 instance ID.
            period_minutes: Aggregation period in minutes.
            lookback_minutes: How far back to look for metrics.

        Returns:
            Ec2Metrics with available metrics.
        """
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(minutes=lookback_minutes)
        period = period_minutes * 60

        metrics = Ec2Metrics(
            instance_id=instance_id,
            cpu_utilization=None,
            network_in_bytes=None,
            network_out_bytes=None,
            disk_read_ops=None,
            disk_write_ops=None,
        )

        # Fetch CPU utilization
        metrics.cpu_utilization = await self._get_metric(
            instance_id=instance_id,
            metric_name="CPUUtilization",
            namespace="AWS/EC2",
            start_time=start_time,
            end_time=end_time,
            period=period,
        )

        # Fetch network metrics
        metrics.network_in_bytes = await self._get_metric(
            instance_id=instance_id,
            metric_name="NetworkIn",
            namespace="AWS/EC2",
            start_time=start_time,
            end_time=end_time,
            period=period,
            statistic="Sum",
        )

        metrics.network_out_bytes = await self._get_metric(
            instance_id=instance_id,
            metric_name="NetworkOut",
            namespace="AWS/EC2",
            start_time=start_time,
            end_time=end_time,
            period=period,
            statistic="Sum",
        )

        # Fetch disk metrics
        metrics.disk_read_ops = await self._get_metric(
            instance_id=instance_id,
            metric_name="DiskReadOps",
            namespace="AWS/EC2",
            start_time=start_time,
            end_time=end_time,
            period=period,
            statistic="Sum",
        )

        metrics.disk_write_ops = await self._get_metric(
            instance_id=instance_id,
            metric_name="DiskWriteOps",
            namespace="AWS/EC2",
            start_time=start_time,
            end_time=end_time,
            period=period,
            statistic="Sum",
        )

        metrics.timestamp = end_time
        return metrics

    async def _get_metric(
        self,
        instance_id: str,
        metric_name: str,
        namespace: str,
        start_time: datetime,
        end_time: datetime,
        period: int,
        statistic: str = "Average",
    ) -> float | None:
        """Get a single metric value.

        Args:
            instance_id: EC2 instance ID.
            metric_name: CloudWatch metric name.
            namespace: CloudWatch namespace.
            start_time: Query start time.
            end_time: Query end time.
            period: Aggregation period in seconds.
            statistic: Aggregation statistic (Average, Sum, etc.).

        Returns:
            Metric value or None if not available.
        """
        try:
            response = await self._run_async(
                self._get_client().get_metric_statistics,
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=[
                    {"Name": "InstanceId", "Value": instance_id},
                ],
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=[statistic],
            )

            datapoints = response.get("Datapoints", [])
            if not datapoints:
                return None

            # Return most recent datapoint
            latest = max(datapoints, key=lambda x: x["Timestamp"])
            return latest.get(statistic)

        except ClientError as e:
            logger.warning(f"Error getting CloudWatch metric {metric_name} for {instance_id}: {e}")
            return None

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
