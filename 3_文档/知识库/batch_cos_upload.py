#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批量推 COS：读取 _batch_creds.json，逐个上传，续跑不中断。

creds 文件格式（list）：
  [{"name":..., "path":..., "cos_key":..., "bucket":..., "region":...,
    "token":..., "secret_id":..., "secret_key":..., "content_type":...}, ...]
"""
import json
import os
import sys

from qcloud_cos import CosConfig, CosS3Client

BASE = os.path.dirname(os.path.abspath(__file__))


def main() -> None:
    creds_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "_batch_creds.json")
    entries = json.load(open(creds_path, encoding="utf-8"))
    ok, fail = 0, []
    for e in entries:
        try:
            config = CosConfig(
                Region=e["region"],
                SecretId=e["secret_id"],
                SecretKey=e["secret_key"],
                Token=e["token"],
                Scheme="https",
            )
            client = CosS3Client(config)
            with open(e["path"], "rb") as fp:
                resp = client.put_object(
                    Bucket=e["bucket"],
                    Body=fp,
                    Key=e["cos_key"],
                    ContentType=e.get("content_type", "text/markdown"),
                )
            print("OK", e["name"], resp.get("ETag", ""))
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print("FAIL", e["name"], repr(exc)[:200])
            fail.append(e["name"])
    print("SUMMARY ok=%d fail=%d" % (ok, len(fail)))
    for f in fail:
        print("  FAILED:", f)
    sys.exit(0 if not fail else 1)


if __name__ == "__main__":
    main()
