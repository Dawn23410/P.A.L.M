#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""COS 上传脚本：使用 ima create_media 返回的临时凭证上传文件。

用法：
    python upload_cos.py <local_file> <cos_key> <bucket> <region> <token> <secret_id> <secret_key> [content_type]
"""
import sys

from qcloud_cos import CosConfig, CosS3Client


def main() -> None:
    local_file, cos_key, bucket, region, token, secret_id, secret_key = sys.argv[1:8]
    content_type = sys.argv[8] if len(sys.argv) > 8 else "text/markdown"

    config = CosConfig(
        Region=region,
        SecretId=secret_id,
        SecretKey=secret_key,
        Token=token,
        Scheme="https",
    )
    client = CosS3Client(config)
    with open(local_file, "rb") as fp:
        resp = client.put_object(
            Bucket=bucket,
            Body=fp,
            Key=cos_key,
            ContentType=content_type,
        )
    print("UPLOAD_OK", resp.get("ETag", ""))


if __name__ == "__main__":
    main()
