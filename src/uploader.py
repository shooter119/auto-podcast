from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import boto3
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from botocore.exceptions import ClientError, EndpointConnectionError

logger = logging.getLogger(__name__)


def _get_s3_client(config: dict[str, Any]):
    r2_config = config["r2"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{r2_config['account_id']}.r2.cloudflarestorage.com",
        aws_access_key_id=r2_config["access_key_id"],
        aws_secret_access_key=r2_config["secret_access_key"],
        region_name="auto",
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=30),
    retry=retry_if_exception_type((EndpointConnectionError, ClientError)),
    reraise=True,
)
def upload_file(
    file_path: Path, key: str, config: dict[str, Any],
    content_type: str = "audio/mpeg",
) -> str:
    r2_config = config["r2"]
    client = _get_s3_client(config)

    logger.info("上传文件: %s -> %s/%s", file_path.name, r2_config["bucket"], key)
    client.upload_file(
        str(file_path),
        r2_config["bucket"],
        key,
        ExtraArgs={"ContentType": content_type},
    )

    public_url = f"{r2_config['public_url'].rstrip('/')}/{key}"
    logger.info("上传完成: %s", public_url)
    return public_url


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=30),
    retry=retry_if_exception_type((EndpointConnectionError, ClientError)),
    reraise=True,
)
def upload_bytes(
    data: bytes, key: str, config: dict[str, Any],
    content_type: str = "application/xml",
) -> str:
    r2_config = config["r2"]
    client = _get_s3_client(config)

    logger.info("上传数据: %s/%s", r2_config["bucket"], key)
    client.put_object(
        Bucket=r2_config["bucket"],
        Key=key,
        Body=data,
        ContentType=content_type,
    )

    public_url = f"{r2_config['public_url'].rstrip('/')}/{key}"
    logger.info("上传完成: %s", public_url)
    return public_url
