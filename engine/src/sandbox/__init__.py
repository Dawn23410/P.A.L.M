"""AI 沙箱核心包 — 共享错误码与格式化响应。"""

ERROR_CODES = {
    "NET_DENIED":        (403, "network request rejected by user"),
    "NET_BLACKLISTED":   (403, "target is in permanent blacklist"),
    "HONEYPOT_EXFIL":    (403, "sensitive file read followed by network egress"),
    "HONEYPOT_SCAN":     (403, "bulk access to sensitive decoy files"),
    "HONEYPOT_MODIFY":   (403, "modification of protected decoy file"),
    "QUOTA_MEMORY":      (507, "memory limit exceeded"),
    "QUOTA_CPU":         (408, "cpu time limit exceeded"),
    "QUOTA_DISK":        (507, "disk write quota exceeded"),
    "QUOTA_NET":         (429, "network quota exhausted"),
    "SYS_DELETE":        (403, "system file deletion blocked"),
    "SYS_SECURITY":      (403, "security process termination blocked"),
    "ICMP_DISABLED":     (403, "ping command is disabled"),
    "ICMP_FLOOD":        (429, "repeated ping attempts detected"),
    "AST_REJECT":        (403, "static analysis flagged malicious pattern"),
    "SANDBOX_DISABLED":  (403, "sandbox is not enabled"),
    "NOT_FOUND":         (404, "endpoint not found"),
    "BAD_REQUEST":       (400, "invalid request parameters"),
    "INTERNAL_ERROR":    (500, "internal sandbox error"),
}

def err_resp(code, extra_reason=""):
    errno, reason = ERROR_CODES.get(code, (500, "unknown error"))
    reason = "%s: %s" % (reason, extra_reason) if extra_reason else reason
    return {"ok": False, "errno": errno, "code": code, "reason": reason}
