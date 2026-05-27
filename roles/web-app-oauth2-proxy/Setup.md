# Setup

## Cookie Secret

To generate a cookie secret execute:

```bash
ansible-vault encrypt_string "$(openssl rand -hex 16)"
```
