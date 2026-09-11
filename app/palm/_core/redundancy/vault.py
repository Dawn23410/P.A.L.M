def resolve_vault_root() -> str:
    import os
    return os.path.join(os.path.expanduser("~"), ".palm", "vault")
